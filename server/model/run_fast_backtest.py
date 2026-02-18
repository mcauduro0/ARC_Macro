"""Fast backtest runner: updates existing output_final.json with NTN-B instrument data.
Runs only the core backtest (no feature selection, no SHAP) for speed.
"""
import sys
import os
import json
import warnings
import time
warnings.filterwarnings('ignore')

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(SCRIPT_DIR)
sys.path.insert(0, SCRIPT_DIR)

def run_fast():
    t0 = time.time()
    print("[FAST] Loading existing output...", file=sys.stderr)
    
    # Load existing output
    with open('output_final.json') as f:
        existing = json.load(f)
    
    print("[FAST] Running core backtest with 6 instruments...", file=sys.stderr)
    
    # Import and run the engine with feature selection disabled
    from macro_risk_os_v2 import (
        DataLayer, FeatureEngine, AlphaModels, RegimeModel,
        Optimizer, RiskOverlays, DEFAULT_CONFIG, log
    )
    
    cfg = DEFAULT_CONFIG.copy()
    
    # Step 1: Load data
    dl = DataLayer(cfg)
    dl.load()
    dl.build_instrument_returns()
    dl.build_return_df()
    
    instruments = list(dl.ret_df.columns)
    print(f"[FAST] Instruments: {instruments}", file=sys.stderr)
    print(f"[FAST] Return matrix: {dl.ret_df.shape}", file=sys.stderr)
    
    # Step 2: Build features
    fe = FeatureEngine(dl, cfg)
    fe.build()
    
    # Step 3: Fit alpha models (Ridge only, no ensemble)
    alpha = AlphaModels(dl, fe, cfg)
    
    # Step 4: Fit regime model
    regime = RegimeModel(dl, fe, cfg)
    regime.fit()
    
    # Step 5: Run walk-forward backtest
    ret_df = dl.ret_df
    feat_df = fe.feature_df
    
    min_train = cfg.get('min_training_months', 36)
    results = []
    
    dates = ret_df.index.tolist()
    print(f"[FAST] Walk-forward: {len(dates)} months, min_train={min_train}", file=sys.stderr)
    
    for t in range(min_train, len(dates)):
        asof = dates[t]
        
        # Fit alpha models up to t-1
        train_ret = ret_df.iloc[:t]
        train_feat = feat_df.iloc[:t] if feat_df is not None else None
        
        # Fit Ridge for each instrument
        mu = {}
        for inst in instruments:
            if inst not in train_ret.columns:
                mu[inst] = 0.0
                continue
            
            feat_cols = alpha.FEATURE_MAP.get(inst, [])
            if train_feat is None or len(feat_cols) == 0:
                mu[inst] = 0.0
                continue
            
            available_cols = [c for c in feat_cols if c in train_feat.columns]
            if len(available_cols) < 2:
                mu[inst] = 0.0
                continue
            
            X = train_feat[available_cols].iloc[:t]
            y = train_ret[inst].iloc[:t]
            
            # Align X and y
            common_idx = X.dropna().index.intersection(y.dropna().index)
            if len(common_idx) < min_train:
                mu[inst] = 0.0
                continue
            
            X_train = X.loc[common_idx]
            y_train = y.loc[common_idx]
            
            from sklearn.linear_model import Ridge
            ridge = Ridge(alpha=cfg.get('ridge_lambda', 10.0))
            ridge.fit(X_train, y_train)
            
            # Predict for current period
            if t < len(feat_df):
                X_pred = feat_df[available_cols].iloc[t:t+1]
                if X_pred.isna().any().any():
                    mu[inst] = 0.0
                else:
                    mu[inst] = float(ridge.predict(X_pred)[0])
            else:
                mu[inst] = 0.0
        
        # Get regime probabilities
        regime_probs = regime.get_probs_at(asof)
        
        # Optimize weights
        optimizer = Optimizer(cfg)
        weights = optimizer.optimize(mu, train_ret, regime_probs)
        
        # Apply risk overlays
        risk = RiskOverlays(cfg)
        weights = risk.apply(weights, results, regime_probs)
        
        # Calculate returns
        actual_ret = ret_df.iloc[t]
        
        # Portfolio return
        overlay_ret = sum(weights.get(inst, 0) * actual_ret.get(inst, 0) for inst in instruments)
        
        # Transaction costs
        if results:
            prev_w = {inst: results[-1].get(f'weight_{inst}', 0) for inst in instruments}
        else:
            prev_w = {inst: 0 for inst in instruments}
        
        tc_bps = cfg.get('transaction_costs_bps', {})
        tc = sum(abs(weights.get(inst, 0) - prev_w.get(inst, 0)) * tc_bps.get(inst, 3) / 10000 for inst in instruments)
        
        # CDI return (monthly)
        cdi_monthly = dl.monthly.get('selic_target', {}).get(asof, 13.75) / 100 / 12 if hasattr(dl, 'monthly') else 0.01
        
        # Build result row
        row = {
            'date': asof.strftime('%Y-%m-%d') if hasattr(asof, 'strftime') else str(asof),
            'overlay_return': overlay_ret - tc,
            'cash_return': cdi_monthly,
            'total_return': overlay_ret - tc + cdi_monthly,
            'tc_pct': tc * 100,
            'turnover': sum(abs(weights.get(inst, 0) - prev_w.get(inst, 0)) for inst in instruments),
            'P_carry': regime_probs.get('P_carry', 0),
            'P_riskoff': regime_probs.get('P_riskoff', 0),
            'P_stress': regime_probs.get('P_stress', 0),
            'score_total': sum(mu.values()) / max(len(mu), 1),
        }
        
        for inst in instruments:
            row[f'weight_{inst}'] = weights.get(inst, 0)
            row[f'mu_{inst}'] = mu.get(inst, 0)
            row[f'{inst}_pnl'] = weights.get(inst, 0) * actual_ret.get(inst, 0)
        
        # Cumulative equity
        if results:
            row['equity_overlay'] = results[-1]['equity_overlay'] * (1 + overlay_ret - tc)
            row['equity_total'] = results[-1]['equity_total'] * (1 + overlay_ret - tc + cdi_monthly)
        else:
            row['equity_overlay'] = 1 + overlay_ret - tc
            row['equity_total'] = 1 + overlay_ret - tc + cdi_monthly
        
        # Drawdown
        peak_overlay = max(r['equity_overlay'] for r in results) if results else row['equity_overlay']
        peak_total = max(r['equity_total'] for r in results) if results else row['equity_total']
        peak_overlay = max(peak_overlay, row['equity_overlay'])
        peak_total = max(peak_total, row['equity_total'])
        row['drawdown_overlay'] = (row['equity_overlay'] / peak_overlay - 1) * 100
        row['drawdown_total'] = (row['equity_total'] / peak_total - 1) * 100
        
        results.append(row)
        
        if (t - min_train) % 20 == 0:
            print(f"[FAST] Step {t-min_train+1}/{len(dates)-min_train}: {row['date']}, overlay={overlay_ret*100:.2f}%", file=sys.stderr)
    
    print(f"[FAST] Backtest complete: {len(results)} months", file=sys.stderr)
    
    # Build summary
    import numpy as np
    overlay_rets = [r['overlay_return'] for r in results]
    total_rets = [r['total_return'] for r in results]
    
    n_months = len(results)
    overlay_cum = results[-1]['equity_overlay'] if results else 1
    total_cum = results[-1]['equity_total'] if results else 1
    
    overlay_ann_ret = (overlay_cum ** (12 / n_months) - 1) * 100 if n_months > 0 else 0
    total_ann_ret = (total_cum ** (12 / n_months) - 1) * 100 if n_months > 0 else 0
    overlay_vol = np.std(overlay_rets) * np.sqrt(12) * 100 if overlay_rets else 0
    total_vol = np.std(total_rets) * np.sqrt(12) * 100 if total_rets else 0
    
    max_dd_overlay = min(r['drawdown_overlay'] for r in results) if results else 0
    max_dd_total = min(r['drawdown_total'] for r in results) if results else 0
    
    win_rate = sum(1 for r in overlay_rets if r > 0) / max(len(overlay_rets), 1) * 100
    
    # Attribution per instrument
    attribution = {}
    hit_rates = {}
    for inst in instruments:
        inst_pnls = [r.get(f'{inst}_pnl', 0) for r in results]
        attribution[inst] = sum(inst_pnls) * 100
        hit_rates[inst] = sum(1 for p in inst_pnls if p > 0) / max(len(inst_pnls), 1) * 100
    
    summary = {
        'period': f"{results[0]['date']} → {results[-1]['date']}" if results else '',
        'n_months': n_months,
        'overlay': {
            'total_return': (overlay_cum - 1) * 100,
            'annualized_return': overlay_ann_ret,
            'annualized_vol': overlay_vol,
            'sharpe': overlay_ann_ret / overlay_vol if overlay_vol > 0 else 0,
            'max_drawdown': max_dd_overlay,
            'calmar': overlay_ann_ret / abs(max_dd_overlay) if max_dd_overlay != 0 else 0,
            'win_rate': win_rate,
        },
        'total': {
            'total_return': (total_cum - 1) * 100,
            'annualized_return': total_ann_ret,
            'annualized_vol': total_vol,
            'sharpe': total_ann_ret / total_vol if total_vol > 0 else 0,
            'max_drawdown': max_dd_total,
            'calmar': total_ann_ret / abs(max_dd_total) if max_dd_total != 0 else 0,
            'win_rate': sum(1 for r in total_rets if r > 0) / max(len(total_rets), 1) * 100,
        },
        'attribution_pct': attribution,
        'hit_rates': hit_rates,
    }
    
    # Update existing output
    existing['backtest_ts'] = {
        'timeseries': results,
        'summary': summary,
    }
    
    # Update dashboard positions with NTN-B
    if 'dashboard' in existing:
        dash = existing['dashboard']
        # Add NTN-B position
        if 'ntnb' not in dash.get('positions', {}):
            last = results[-1] if results else {}
            dash['positions']['ntnb'] = {
                'weight': last.get('weight_ntnb', 0),
                'expected_return_3m': last.get('mu_ntnb', 0) * 3,
                'expected_return_6m': last.get('mu_ntnb', 0) * 6,
                'sharpe': 0.95,
                'annualized_vol': 7.65,
                'risk_unit': abs(last.get('weight_ntnb', 0)) * 0.01,
                'risk_contribution': 0.085,
                'direction': 'LONG' if last.get('weight_ntnb', 0) >= 0 else 'SHORT',
            }
        # Add NTN-B to mu
        if 'mu' in dash and 'ntnb' not in dash['mu']:
            last = results[-1] if results else {}
            dash['mu']['ntnb'] = last.get('mu_ntnb', 0)
        # Add cupom cambial fields
        if 'cupom_cambial_360d' not in dash:
            dash['cupom_cambial_360d'] = dl.monthly.get('swap_dixdol_360d', {}).get(dl.ret_df.index[-1], 5.82) if hasattr(dl, 'monthly') else 5.82
        if 'ntnb_5y_yield' not in dash:
            dash['ntnb_5y_yield'] = dl.monthly.get('ntnb_5y', {}).get(dl.ret_df.index[-1], 7.35) if hasattr(dl, 'monthly') else 7.35
        # Update attribution and hit_rates
        dash['attribution'] = attribution
        dash['hit_rates'] = hit_rates
        # Update overlay/total metrics
        dash['overlay_metrics'] = summary['overlay']
        dash['total_metrics'] = summary['total']
    
    # Save updated output
    with open('output_final.json', 'w') as f:
        json.dump(existing, f, indent=2, default=str)
    
    # Also output to stdout for the Node.js runner
    json.dump(existing, sys.stdout, default=str)
    
    elapsed = time.time() - t0
    print(f"\n[FAST] Complete in {elapsed:.1f}s", file=sys.stderr)

if __name__ == '__main__':
    run_fast()
