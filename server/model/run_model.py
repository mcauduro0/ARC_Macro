"""
Standalone runner: collects fresh data, runs the Macro Risk OS, and outputs JSON to stdout.
This script is designed to be called from Node.js via child_process.
It outputs a single JSON object with the full Macro Risk OS results.
"""

import sys
import os
import json
import warnings
warnings.filterwarnings('ignore')

# Set paths relative to this script
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

def run_and_output():
    """Run the full Macro Risk OS and output JSON to stdout"""
    
    # Step 1: Collect fresh data
    print("[RUNNER] Starting data collection...", file=sys.stderr)
    try:
        from data_collector import collect_all
        collect_all()
    except Exception as e:
        print(f"[WARN] Data collection had errors: {e}", file=sys.stderr)
    
    # Step 2: Run Macro Risk OS
    print("[RUNNER] Running Macro Risk OS engine...", file=sys.stderr)
    
    from macro_risk_os import run_macro_risk_os
    result = run_macro_risk_os()
    
    # Step 3: Also run legacy FX model for backward compatibility
    print("[RUNNER] Running legacy FX model...", file=sys.stderr)
    try:
        from model_engine import run_full_model
        legacy_dashboard, legacy_results = run_full_model()
        
        # Merge legacy data into result
        result['legacy_fx'] = {
            'dashboard': _sanitize(legacy_dashboard),
        }
        
        # Read legacy CSV outputs for backward-compatible timeseries
        import csv
        output_dir = os.path.join(SCRIPT_DIR, "output")
        
        # Legacy timeseries
        ts_path = os.path.join(output_dir, 'model_timeseries.csv')
        if os.path.exists(ts_path):
            legacy_ts = []
            with open(ts_path) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    date = row.get('', row.get('date', ''))[:10]
                    if len(date) != 10:
                        continue
                    obj = {'date': date}
                    for k in ['spot','ppp_abs','ppp_rel','fx_beer','mis_ppp_abs','mis_beer','z_ppp','z_beer','z_cycle','score_struct','score_total']:
                        v = row.get(k, '')
                        obj[k] = float(v) if v else None
                    legacy_ts.append(obj)
            result['legacy_timeseries'] = legacy_ts
        
        # Legacy regime
        reg_path = os.path.join(output_dir, 'regime_probs.csv')
        if os.path.exists(reg_path):
            legacy_regime = []
            with open(reg_path) as f:
                reader = csv.DictReader(f)
                cols = reader.fieldnames or []
                for row in reader:
                    date = ''
                    for c in ['observation_date', 'date', '']:
                        if c in row:
                            date = row[c][:10]
                            break
                    if len(date) != 10:
                        continue
                    obj = {'date': date}
                    for k in cols:
                        if k.startswith('P_'):
                            v = row.get(k, '')
                            obj[k] = float(v) if v else None
                    legacy_regime.append(obj)
            result['legacy_regime'] = legacy_regime
        
        # Legacy cyclical
        cyc_path = os.path.join(output_dir, 'cyclical_factors.csv')
        if os.path.exists(cyc_path):
            legacy_cyc = []
            with open(cyc_path) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    date = row.get('', row.get('date', ''))[:10]
                    if len(date) != 10:
                        continue
                    obj = {'date': date}
                    for k in ['Z_DXY','Z_COMMODITIES','Z_EMBI','Z_RIR','Z_FLOW']:
                        v = row.get(k, '')
                        obj[k] = float(v) if v else None
                    legacy_cyc.append(obj)
            result['legacy_cyclical'] = legacy_cyc
        
    except Exception as e:
        print(f"[WARN] Legacy model had errors: {e}", file=sys.stderr)
        result['legacy_fx'] = None
    
    # Output final JSON to stdout
    print(json.dumps(result, default=str))
    
    dashboard = result.get('dashboard', {})
    print(f"[RUNNER] Complete. spot={dashboard.get('current_spot')}, regime={dashboard.get('current_regime')}", file=sys.stderr)


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
