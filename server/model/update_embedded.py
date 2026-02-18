"""
Update the embedded model data in the frontend with the latest v4.3 model output.
This ensures the dashboard shows v4.3 features (stability, LASSO path, temporal) even without a DB run.
"""
import json
import os
import sys

def main():
    # Try v4.5 first, then v4.4, v4.3, then fall back to v4.0
    for candidate in ["/tmp/model_v45_output.json", "/tmp/model_v44_output.json", "/tmp/model_v43_output.json", "/tmp/model_output_full.json"]:
        if os.path.exists(candidate) and os.path.getsize(candidate) > 100:
            model_output_path = candidate
            break
    else:
        model_output_path = "/tmp/model_output_full.json"
    
    embedded_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 
                                  "..", "..", "client", "src", "data", "modelData.ts")
    
    if not os.path.exists(model_output_path):
        print("ERROR: Model output not found", file=sys.stderr)
        sys.exit(1)
    
    with open(model_output_path, 'r') as f:
        data = json.load(f)
    
    dashboard = data.get('dashboard', {})
    timeseries = data.get('timeseries', [])
    regime = data.get('regime', [])
    cyclical = data.get('cyclical_factors_ts', [])
    state_vars = data.get('state_variables_ts', [])
    score = data.get('score_ts', [])
    rstar_ts = dashboard.get('rstar_ts', [])
    backtest = data.get('backtest_ts', {})
    shap_importance = data.get('shap_importance', {})
    shap_history = data.get('shap_history', [])
    
    # v4.3: Feature selection with stability + LASSO path
    feature_selection = dashboard.get('feature_selection', {})
    feature_selection_temporal = data.get('feature_selection_temporal', {})
    
    # Downsample LASSO path to 50 points to reduce embedded file size
    for inst_key, inst_val in feature_selection.items():
        if isinstance(inst_val, dict):
            lasso = inst_val.get('lasso', {})
            if isinstance(lasso, dict):
                path = lasso.get('path', [])
                if isinstance(path, list) and len(path) > 50:
                    step = len(path) / 50
                    indices = [int(i * step) for i in range(50)]
                    # Always include last point
                    if indices[-1] != len(path) - 1:
                        indices[-1] = len(path) - 1
                    lasso['path'] = [path[i] for i in indices]
    
    # Build the TypeScript file
    ts_content = f"""/**
 * Embedded model data — auto-generated from v4.3 model output.
 * This serves as fallback when no database run exists.
 * Generated: {dashboard.get('run_date', 'unknown')}
 */

// Dashboard snapshot
export const dashboardData = {json.dumps(dashboard, indent=2)};

// Timeseries (last 60 points for performance)
export const timeseriesData = {json.dumps(timeseries[-60:] if len(timeseries) > 60 else timeseries, indent=2)};

// Regime probabilities (last 60 points)
export const regimeData = {json.dumps(regime[-60:] if len(regime) > 60 else regime, indent=2)};

// Cyclical factors (last 60 points)
export const cyclicalData = {json.dumps(cyclical[-60:] if len(cyclical) > 60 else cyclical, indent=2)};

// State variables Z-scores (last 60 points)
export const stateVariablesData = {json.dumps(state_vars[-60:] if len(state_vars) > 60 else state_vars, indent=2)};

// Composite score (last 60 points)
export const scoreData = {json.dumps(score[-60:] if len(score) > 60 else score, indent=2)};

// r* timeseries (last 60 points)
export const rstarTsData = {json.dumps(rstar_ts[-60:] if len(rstar_ts) > 60 else rstar_ts, indent=2)};

// Backtest results
export const backtestData = {json.dumps(backtest, indent=2)};

// SHAP feature importance
export const shapImportanceData = {json.dumps(shap_importance, indent=2)};

// SHAP temporal evolution (last 200 entries)
export const shapHistoryData = {json.dumps(shap_history[-200:] if len(shap_history) > 200 else shap_history, indent=2)};

// v4.3: Feature selection results (per instrument with stability + LASSO path)
export const featureSelectionData = {json.dumps(feature_selection, indent=2)};

// v4.3: Feature selection temporal tracking
export const featureSelectionTemporalData = {json.dumps(feature_selection_temporal, indent=2)};
"""
    
    with open(embedded_path, 'w') as f:
        f.write(ts_content)
    
    print(f"Updated embedded data at {embedded_path}", file=sys.stderr)
    print(f"Dashboard run_date: {dashboard.get('run_date')}", file=sys.stderr)
    print(f"Version: {dashboard.get('version')}", file=sys.stderr)
    print(f"State variables: {list(dashboard.get('state_variables', {}).keys())}", file=sys.stderr)
    print(f"Feature selection instruments: {list(feature_selection.keys())}", file=sys.stderr)
    has_stability = any(isinstance(v, dict) and 'stability' in v for v in feature_selection.values())
    has_path = any(isinstance(v, dict) and isinstance(v.get('lasso', {}).get('path'), list) for v in feature_selection.values())
    print(f"Has stability: {has_stability}, Has LASSO path: {has_path}", file=sys.stderr)
    print(f"Temporal tracking: {'present' if feature_selection_temporal else 'missing'}", file=sys.stderr)
    print(f"Timeseries: {len(timeseries)} points", file=sys.stderr)
    print("OK")

if __name__ == '__main__':
    main()
