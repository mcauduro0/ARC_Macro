"""Standalone runner: collects fresh data, runs the Macro Risk OS v2.3, and outputs JSON to stdout.
This script is designed to be called from Node.js via child_process.
It outputs a single JSON object with the full Macro Risk OS v2.3 results.
v2.3: Removed legacy v1 model execution. All output is from the modern engine.
"""

import sys
import os
import json
import warnings
warnings.filterwarnings('ignore')

# Set paths relative to this script
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

def run_and_output():
    """Run the full Macro Risk OS v2 and output JSON to stdout"""
    
    # Step 1: Collect fresh data
    print("[RUNNER] Starting data collection...", file=sys.stderr)
    try:
        from data_collector import collect_all
        collect_all()
    except Exception as e:
        print(f"[WARN] Data collection had errors: {e}", file=sys.stderr)
    
    # Step 2: Run Macro Risk OS v2.3
    print("[RUNNER] Running Macro Risk OS v2.3 engine...", file=sys.stderr)
    
    from macro_risk_os_v2 import run_v2
    v2_result = run_v2()
    
    # Step 3: Build output compatible with modelRunner.ts
    bt = v2_result.get('backtest', {})
    bt_ts = bt.get('timeseries', [])
    bt_summary = bt.get('summary', {})
    current = v2_result.get('current', {})
    config = v2_result.get('config', {})
    
    # Build dashboard object (current state) — enriched from v2.3 engine
    dashboard = {
        'version': 'v2.3',
        'framework': 'overlay_on_cdi',
        'run_date': current.get('date', ''),
        'current_spot': current.get('current_spot', 0),
        'current_regime': current.get('current_regime', 'carry'),
        'dominant_regime': current.get('current_regime', 'carry'),
        'score_total': current.get('score_total', 0),
        'direction': current.get('direction', 'NEUTRAL'),
        'interpretation': f"Score total: {current.get('score_total', 0):.2f}" if current.get('score_total') else 'N/A',
        'mu': current.get('mu', {}),
        'regime_probs': current.get('regime', {}),
        'regime_probabilities': current.get('regime', {}),
        'config': config,
        # State variables (Z-scores)
        'state_variables': current.get('state_variables', {}),
        # Cross-asset positions
        'positions': current.get('positions', {}),
        # FX
        'fx_fair_value': current.get('fx_fair_value', 0),
        'fx_misalignment': current.get('fx_misalignment', 0),
        'ppp_fair': current.get('ppp_fair', 0),
        'beer_fair': current.get('beer_fair', 0),
        # Rates
        'selic_target': current.get('selic_target', 0),
        'di_1y': current.get('di_1y', 0),
        'di_5y': current.get('di_5y', 0),
        'di_10y': current.get('di_10y', 0),
        'front_fair': current.get('front_fair', 0),
        'belly_fair': current.get('belly_fair', 0),
        'long_fair': current.get('long_fair', 0),
        'taylor_gap': current.get('taylor_gap', 0),
        'term_premium': current.get('term_premium', 0),
        # Credit / Global
        'embi_spread': current.get('embi_spread', 0),
        'ust_2y': current.get('ust_2y', 0),
        'ust_10y': current.get('ust_10y', 0),
        'vix': current.get('vix', 0),
        'dxy': current.get('dxy', 0),
        # Risk
        'risk_metrics': {
            'portfolio_vol': current.get('portfolio_vol', 0),
            'correlation_matrix': {},
            'stress_tests': [],
            'max_drawdown': 0,
        },
    }
    
    # Build overlay summary for dashboard
    overlay = bt_summary.get('overlay', {})
    total = bt_summary.get('total', {})
    dashboard['overlay_metrics'] = overlay
    dashboard['total_metrics'] = total
    dashboard['ic_per_instrument'] = bt_summary.get('ic_per_instrument', {})
    dashboard['hit_rates'] = bt_summary.get('hit_rates', {})
    dashboard['attribution'] = bt_summary.get('attribution_pct', {})
    dashboard['total_tc_pct'] = bt_summary.get('total_tc_pct', 0)
    dashboard['avg_monthly_turnover'] = bt_summary.get('avg_monthly_turnover', 0)
    
    # Add stress tests to dashboard so frontend can read them
    stress_tests = v2_result.get('stress_tests', {})
    dashboard['stress_tests'] = stress_tests
    
    # Build timeseries (for backward compat with v1 dashboard)
    timeseries = []
    for r in bt_ts:
        timeseries.append({
            'date': r['date'],
            'equity_overlay': r['equity_overlay'],
            'equity_total': r['equity_total'],
            'overlay_return': r['overlay_return'],
            'cash_return': r['cash_return'],
            'total_return': r['total_return'],
            'drawdown_overlay': r['drawdown_overlay'],
            'drawdown_total': r['drawdown_total'],
            'score_total': r.get('score_total', 0),
            # Weights
            'weight_fx': r.get('weight_fx', 0),
            'weight_front': r.get('weight_front', 0),
            'weight_belly': r.get('weight_belly', 0),
            'weight_long': r.get('weight_long', 0),
            'weight_hard': r.get('weight_hard', 0),
            # Mu predictions
            'mu_fx': r.get('mu_fx', 0),
            'mu_front': r.get('mu_front', 0),
            'mu_belly': r.get('mu_belly', 0),
            'mu_long': r.get('mu_long', 0),
            'mu_hard': r.get('mu_hard', 0),
            # PnL attribution
            'fx_pnl': r.get('fx_pnl', 0),
            'front_pnl': r.get('front_pnl', 0),
            'belly_pnl': r.get('belly_pnl', 0),
            'long_pnl': r.get('long_pnl', 0),
            'hard_pnl': r.get('hard_pnl', 0),
            # Regime
            'P_carry': r.get('P_carry', 0),
            'P_riskoff': r.get('P_riskoff', 0),
            'P_stress': r.get('P_stress', 0),
            # Costs
            'tc_pct': r.get('tc_pct', 0),
            'turnover': r.get('turnover', 0),
            # v2.3: Two-level regime
            'P_domestic_calm': r.get('P_domestic_calm', 0),
            'P_domestic_stress': r.get('P_domestic_stress', 0),
            # v2.3: Ensemble & score demeaning
            'w_ridge_avg': r.get('w_ridge_avg', 0.5),
            'w_gbm_avg': r.get('w_gbm_avg', 0.5),
            'raw_score': r.get('raw_score', 0),
            'demeaned_score': r.get('demeaned_score', 0),
            # v2.3: Rolling Sharpe 12m
            'rolling_sharpe_12m': r.get('rolling_sharpe_12m', None),
        })
    
    # Build regime timeseries (v2.3: includes domestic regime)
    # Frontend ChartsSection expects P_Carry, P_RiskOff, P_StressDom (capitalized)
    regime_ts = []
    for r in bt_ts:
        regime_ts.append({
            'date': r['date'],
            'P_Carry': r.get('P_carry', 0),
            'P_RiskOff': r.get('P_riskoff', 0),
            'P_StressDom': r.get('P_stress', 0),
            'P_domestic_calm': r.get('P_domestic_calm', 0),
            'P_domestic_stress': r.get('P_domestic_stress', 0),
        })
    
    # Build state variables (Z-scores over time) — from v2.3 engine
    state_vars_ts = v2_result.get('state_variables_ts', [])
    
    # Build cyclical factors — from v2.3 engine
    cyclical_ts = v2_result.get('cyclical_ts', [])
    
    # Build fair value timeseries — from v2.3 engine
    fair_value_ts = v2_result.get('fair_value_ts', [])
    
    # Merge fair_value_ts into main timeseries by date (for ChartsSection Fair Value tab)
    fv_by_date = {fv['date']: fv for fv in fair_value_ts}
    for ts_point in timeseries:
        fv = fv_by_date.get(ts_point['date'])
        if fv:
            ts_point['spot'] = fv.get('spot')
            ts_point['ppp_fair'] = fv.get('ppp_fair')
            ts_point['beer_fair'] = fv.get('beer_fair')
            ts_point['fx_fair'] = fv.get('fx_fair')
    
    # Also add fair_value_ts points that are outside the backtest period (pre-backtest history)
    bt_dates = {ts['date'] for ts in timeseries}
    for fv in fair_value_ts:
        if fv['date'] not in bt_dates:
            timeseries.append({
                'date': fv['date'],
                'spot': fv.get('spot'),
                'ppp_fair': fv.get('ppp_fair'),
                'beer_fair': fv.get('beer_fair'),
                'fx_fair': fv.get('fx_fair'),
                'equity_overlay': None,
                'equity_total': None,
            })
    # Sort timeseries by date
    timeseries.sort(key=lambda x: x['date'])
    
    # Build score timeseries — prefer v2.3 engine output, fallback to backtest records
    score_ts = v2_result.get('score_ts', [])
    if not score_ts:
        for r in bt_ts:
            score_ts.append({
                'date': r['date'],
                'score_total': r.get('score_total', 0),
                'mu_fx': r.get('mu_fx', 0),
                'mu_front': r.get('mu_front', 0),
                'mu_belly': r.get('mu_belly', 0),
                'mu_long': r.get('mu_long', 0),
                'mu_hard': r.get('mu_hard', 0),
            })
    
    # Build backtest_ts (for BacktestPanel)
    backtest_ts = {
        'timeseries': bt_ts,
        'summary': bt_summary,
    }
    
    # Stress test results
    stress_tests = v2_result.get('stress_tests', {})
    
    # Final output
    result = {
        'dashboard': dashboard,
        'timeseries': timeseries,
        'regime': regime_ts,
        'state_variables_ts': state_vars_ts,
        'cyclical_factors_ts': cyclical_ts,
        'score_ts': score_ts,
        'backtest_ts': backtest_ts,
        'stress_tests': stress_tests,
        'fair_value_ts': fair_value_ts,
    }
    
    # v2.3: Legacy v1 model (macro_risk_os.py) has been deprecated.
    # All output is now exclusively from the v2.3 engine.
    # The legacy file is preserved for reference but no longer executed.
    
    # Output final JSON to stdout
    sys.stdout.write(json.dumps(result, default=str))
    sys.stdout.write('\n')
    sys.stdout.flush()
    
    print(f"[RUNNER] Complete. v2.3 overlay={overlay.get('total_return', 0):.1f}%, Sharpe={overlay.get('sharpe', 0):.2f}", file=sys.stderr)


def _sanitize(obj):
    """Sanitize object for JSON serialization"""
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [_sanitize(v) for v in obj]
    elif isinstance(obj, float):
        if obj != obj:  # NaN
            return None
        return round(obj, 6)
    elif hasattr(obj, 'item'):  # numpy scalar
        return round(float(obj), 6)
    return obj


if __name__ == '__main__':
    # Redirect model prints to stderr
    import builtins
    old_print = builtins.print
    def model_print(*args, **kwargs):
        if 'file' not in kwargs:
            kwargs['file'] = sys.stderr
        old_print(*args, **kwargs)
    builtins.print = model_print
    
    try:
        run_and_output()
    finally:
        builtins.print = old_print
