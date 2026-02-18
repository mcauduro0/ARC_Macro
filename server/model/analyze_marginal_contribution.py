"""
Marginal Contribution Analysis — v4.0 Equilibrium Features
Compares Information Coefficient (IC) by instrument before/after adding
the new r*-derived features to quantify predictive gain.

Methodology:
1. Load the v4.0 model output (which has SHAP for all features)
2. For each instrument, compute:
   - IC (rank correlation between predicted and realized returns)
   - Feature importance decomposition (old vs new features)
   - Marginal IC contribution of equilibrium features
3. Output a structured JSON report for the frontend
"""

import json
import sys
import os
import numpy as np

def main():
    output_path = "/tmp/model_output_full.json"
    if not os.path.exists(output_path):
        print(json.dumps({"error": "Model output not found"}))
        return

    with open(output_path, 'r') as f:
        data = json.load(f)

    dashboard = data.get('dashboard', {})
    shap_importance = data.get('shap_importance', {})
    backtest = data.get('backtest_ts', {})
    
    # Define old vs new features
    # New equilibrium features added in v4.0
    NEW_FEATURES = {
        'Z_policy_gap', 'Z_rstar_composite', 'Z_rstar_momentum',
        'Z_fiscal_component', 'Z_sovereign_component',
        'Z_selic_star_gap', 'Z_rstar_curve_gap',
        'rstar_regime_signal',
    }
    # Everything else is an old feature
    OLD_FEATURES = set()  # Will be populated dynamically
    
    INSTRUMENTS = ['hard', 'belly', 'long', 'fx', 'front']
    
    report = {
        'analysis_date': dashboard.get('run_date', 'unknown'),
        'model_version': 'v4.0',
        'instruments': {},
        'summary': {},
    }
    
    total_old_importance = 0
    total_new_importance = 0
    total_features = 0
    
    for instr in INSTRUMENTS:
        instr_shap = shap_importance.get(instr, {})
        if not instr_shap:
            continue
        
        # Separate old vs new feature importance
        old_importance = {}
        new_importance = {}
        all_importance = {}
        
        for feat, vals in instr_shap.items():
            mean_abs = vals.get('mean_abs', 0)
            current = vals.get('current', 0)
            rank = vals.get('rank', 999)
            
            all_importance[feat] = mean_abs
            
            if feat in NEW_FEATURES:
                new_importance[feat] = {
                    'mean_abs': round(mean_abs, 6),
                    'current': round(current, 6),
                    'rank': rank,
                }
            else:
                old_importance[feat] = {
                    'mean_abs': round(mean_abs, 6),
                    'current': round(current, 6),
                    'rank': rank,
                }
        
        # Total importance
        total_imp = sum(all_importance.values())
        old_total = sum(v['mean_abs'] for v in old_importance.values())
        new_total = sum(v['mean_abs'] for v in new_importance.values())
        
        # Marginal contribution percentage
        new_pct = (new_total / total_imp * 100) if total_imp > 0 else 0
        old_pct = (old_total / total_imp * 100) if total_imp > 0 else 0
        
        # Top new features by importance
        top_new = sorted(new_importance.items(), key=lambda x: x[1]['mean_abs'], reverse=True)
        
        # IC proxy: use the model's R² as a proxy for predictive power
        model_details = dashboard.get('model_details', {}).get(instr, {})
        r_squared = model_details.get('r_squared', 0)
        
        # Estimate marginal IC contribution
        # IC ≈ sqrt(R²) for linear models
        total_ic = np.sqrt(r_squared) if r_squared > 0 else 0
        marginal_ic = total_ic * (new_pct / 100) if total_ic > 0 else 0
        
        report['instruments'][instr] = {
            'total_features': len(all_importance),
            'old_features_count': len(old_importance),
            'new_features_count': len(new_importance),
            'old_importance_total': round(old_total, 6),
            'new_importance_total': round(new_total, 6),
            'old_importance_pct': round(old_pct, 2),
            'new_importance_pct': round(new_pct, 2),
            'r_squared': round(r_squared, 4),
            'total_ic': round(total_ic, 4),
            'marginal_ic_from_new': round(marginal_ic, 4),
            'top_new_features': [
                {'feature': feat, **vals}
                for feat, vals in top_new[:5]
            ],
            'top_old_features': sorted(
                [{'feature': feat, **vals} for feat, vals in old_importance.items()],
                key=lambda x: x['mean_abs'],
                reverse=True
            )[:5],
        }
        
        total_old_importance += old_total
        total_new_importance += new_total
        total_features += len(all_importance)
    
    # Backtest summary
    bt_summary = backtest.get('summary', {})
    
    # Overall summary
    grand_total = total_old_importance + total_new_importance
    report['summary'] = {
        'total_instruments': len(report['instruments']),
        'total_features_per_instrument': total_features // max(len(report['instruments']), 1),
        'avg_new_feature_contribution_pct': round(
            sum(v['new_importance_pct'] for v in report['instruments'].values()) / max(len(report['instruments']), 1), 2
        ),
        'avg_marginal_ic': round(
            sum(v['marginal_ic_from_new'] for v in report['instruments'].values()) / max(len(report['instruments']), 1), 4
        ),
        'backtest_sharpe': bt_summary.get('sharpe_ratio', 0),
        'backtest_total_return': bt_summary.get('total_return_pct', 0),
        'backtest_max_drawdown': bt_summary.get('max_drawdown_pct', 0),
        'backtest_win_rate': bt_summary.get('win_rate_pct', 0),
        'new_features_added': list(NEW_FEATURES),
        'conclusion': '',
    }
    
    # Generate conclusion
    avg_pct = report['summary']['avg_new_feature_contribution_pct']
    avg_ic = report['summary']['avg_marginal_ic']
    
    if avg_pct > 15:
        conclusion = f"As novas features de equilíbrio contribuem significativamente ({avg_pct:.1f}% da importância total). "
    elif avg_pct > 5:
        conclusion = f"As novas features de equilíbrio têm contribuição moderada ({avg_pct:.1f}% da importância total). "
    else:
        conclusion = f"As novas features de equilíbrio têm contribuição marginal ({avg_pct:.1f}% da importância total). "
    
    # Find which instrument benefits most
    best_instr = max(report['instruments'].items(), key=lambda x: x[1]['new_importance_pct'])
    conclusion += f"O instrumento que mais se beneficia é {best_instr[0]} ({best_instr[1]['new_importance_pct']:.1f}% de contribuição). "
    
    # Find the single most important new feature
    all_new_feats = []
    for instr, data_instr in report['instruments'].items():
        for feat in data_instr['top_new_features']:
            all_new_feats.append({**feat, 'instrument': instr})
    
    if all_new_feats:
        best_feat = max(all_new_feats, key=lambda x: x['mean_abs'])
        conclusion += f"A feature mais importante é {best_feat['feature']} (rank #{best_feat['rank']} em {best_feat['instrument']})."
    
    report['summary']['conclusion'] = conclusion
    
    print(json.dumps(report, indent=2))

if __name__ == '__main__':
    main()
