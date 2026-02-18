"""Quick test to check if equilibrium data is produced correctly."""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings('ignore')

from macro_risk_os_v2 import DataLayer, FeatureEngine, DEFAULT_CONFIG

print("Loading data...")
dl = DataLayer(DEFAULT_CONFIG)
dl.load_all()
dl.build_monthly()
dl.compute_instrument_returns()

print(f"Monthly series: {len(dl.monthly)}")

print("\nBuilding features (including composite equilibrium)...")
fe = FeatureEngine(dl, DEFAULT_CONFIG)
fe.build_all()

print(f"\nHas _compositor: {hasattr(fe, '_compositor')}")
print(f"_compositor value: {fe._compositor if hasattr(fe, '_compositor') else 'N/A'}")
print(f"Has _composite_rstar: {hasattr(fe, '_composite_rstar')}")
print(f"Has _eq_model_results: {hasattr(fe, '_eq_model_results')}")
print(f"Has _taylor_selic_star: {hasattr(fe, '_taylor_selic_star')}")
print(f"Has _front_fair: {hasattr(fe, '_front_fair')}")
print(f"Has _belly_fair: {hasattr(fe, '_belly_fair')}")
print(f"Has _long_fair: {hasattr(fe, '_long_fair')}")

if hasattr(fe, '_compositor') and fe._compositor is not None:
    print(f"\nCompositor model_contributions: {json.dumps(fe._compositor.model_contributions, indent=2, default=str)}")
    if hasattr(fe, '_composite_rstar') and len(fe._composite_rstar) > 0:
        print(f"Composite r*: {fe._composite_rstar.iloc[-1]:.2f}%")
else:
    print("\n*** _compositor is None or not set! ***")
    
if hasattr(fe, '_eq_model_results'):
    print(f"\nModel results ({len(fe._eq_model_results)} models):")
    for name, series in fe._eq_model_results.items():
        if len(series) > 0:
            print(f"  {name}: {series.iloc[-1]:.2f}% ({len(series)} months)")
        else:
            print(f"  {name}: empty series")

if hasattr(fe, '_taylor_selic_star') and len(fe._taylor_selic_star) > 0:
    print(f"\nSELIC*: {fe._taylor_selic_star.iloc[-1]:.2f}%")

if hasattr(fe, '_front_fair'):
    print(f"Front fair: {fe._front_fair}%")
if hasattr(fe, '_belly_fair'):
    print(f"Belly fair: {fe._belly_fair}%")
if hasattr(fe, '_long_fair'):
    print(f"Long fair: {fe._long_fair}%")

# Now simulate the output block
print("\n=== Simulating output block ===")
if hasattr(fe, '_compositor') and fe._compositor is not None:
    compositor = fe._compositor
    eq_data = {
        'composite_rstar': round(float(fe._composite_rstar.iloc[-1]), 2) if hasattr(fe, '_composite_rstar') and len(fe._composite_rstar) > 0 else None,
        'model_contributions': compositor.model_contributions,
        'method': 'composite_5model',
    }
    if hasattr(fe, '_eq_model_results'):
        for name, series in fe._eq_model_results.items():
            if len(series) > 0:
                eq_data[f'rstar_{name}'] = round(float(series.iloc[-1]), 2)
    if hasattr(fe, '_fiscal_decomposition') and fe._fiscal_decomposition:
        eq_data['fiscal_decomposition'] = fe._fiscal_decomposition
    if hasattr(fe, '_acm_term_premium') and fe._acm_term_premium is not None and len(fe._acm_term_premium) > 0:
        eq_data['acm_term_premium_5y'] = round(float(fe._acm_term_premium.iloc[-1]), 2)
    print(f"\neq_data: {json.dumps(eq_data, indent=2, default=str)}")
    print("\n*** SUCCESS: equilibrium data would be set ***")
else:
    print("\n*** FAILURE: _compositor not available ***")

print("\nDone.")
