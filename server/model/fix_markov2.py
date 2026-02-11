"""Fix Markov Switching - correct parameter access (numpy array)"""
import pandas as pd
import numpy as np
import statsmodels.api as sm
from statsmodels.tsa.regime_switching.markov_regression import MarkovRegression
import json, os, warnings
warnings.filterwarnings('ignore')

OUTPUT_DIR = "/home/ubuntu/brlusd_model/output"
DATA_DIR = "/home/ubuntu/brlusd_model/data"

# Load spot
spot = pd.read_csv(f'{DATA_DIR}/BRLUSD_FRED.csv', index_col=0, parse_dates=True).iloc[:,0]
spot_m = spot.resample('MS').last().dropna()
fx_ret = spot_m.pct_change().dropna() * 100
fx_ret = fx_ret.loc['2005':]

print(f"Data: {len(fx_ret)} obs from {fx_ret.index.min().strftime('%Y-%m')} to {fx_ret.index.max().strftime('%Y-%m')}")

# 2-Regime Markov Switching
ms = MarkovRegression(fx_ret.values, k_regimes=2, switching_variance=True)
res = ms.fit(maxiter=1000, em_iter=500)

# Parameter mapping: param_names = ['p[0->0]', 'p[1->0]', 'const[0]', 'const[1]', 'sigma2[0]', 'sigma2[1]']
param_names = res.model.param_names
params = dict(zip(param_names, res.params))

print(f"\nParameters:")
for k, v in params.items():
    print(f"  {k}: {v:.4f}")

sigma0 = params['sigma2[0]']
sigma1 = params['sigma2[1]']
const0 = params['const[0]']
const1 = params['const[1]']

# Identify regimes by volatility
if sigma0 < sigma1:
    regime_names = {0: 'Carry', 1: 'RiskOff'}
else:
    regime_names = {0: 'RiskOff', 1: 'Carry'}

print(f"\nRegime 0 ({regime_names[0]}): mean={const0:.3f}, sigma²={sigma0:.3f}")
print(f"Regime 1 ({regime_names[1]}): mean={const1:.3f}, sigma²={sigma1:.3f}")

# Smoothed probabilities
probs = res.smoothed_marginal_probabilities
prob_df = pd.DataFrame(probs, index=fx_ret.index, columns=['P_Regime0', 'P_Regime1'])

# Rename columns
prob_df.columns = [f'P_{regime_names[0]}', f'P_{regime_names[1]}']

print(f"\nCurrent regime probabilities:")
for col in prob_df.columns:
    print(f"  {col}: {prob_df[col].iloc[-1]:.1%}")

dominant_col = prob_df.iloc[-1].idxmax()
dominant_name = dominant_col.replace('P_', '')
print(f"Dominant regime: {dominant_name}")

# Lambda weights
lambda_weights = {'Carry': 0.60, 'RiskOff': 0.30}
lambda_t = pd.Series(0.0, index=prob_df.index)
for i, (idx, name) in enumerate(regime_names.items()):
    lam = lambda_weights[name]
    lambda_t += prob_df.iloc[:, i] * lam

print(f"Current lambda: {lambda_t.iloc[-1]:.3f}")

# Save regime data
prob_df.to_csv(os.path.join(OUTPUT_DIR, 'regime_probs.csv'))
lambda_t.to_frame('lambda_t').to_csv(os.path.join(OUTPUT_DIR, 'lambda_t.csv'))

# Now recompute score_total with regime-aware lambda
ts = pd.read_csv(os.path.join(OUTPUT_DIR, 'model_timeseries.csv'), index_col=0, parse_dates=True)

score_struct = ts['score_struct'].dropna()
z_cyc = ts['z_cycle'].dropna()

# Extend lambda to full timeseries range
lambda_full = lambda_t.reindex(score_struct.index, method='ffill')
common = score_struct.index.intersection(z_cyc.index).intersection(lambda_full.dropna().index)

score_total_new = (
    lambda_full.loc[common] * score_struct.loc[common] +
    (1 - lambda_full.loc[common]) * z_cyc.loc[common]
)

# Update timeseries
ts.loc[common, 'score_total'] = score_total_new.loc[common]
ts.to_csv(os.path.join(OUTPUT_DIR, 'model_timeseries.csv'))

# Recompute expected returns
fx_ret_6m = spot_m.pct_change(6).shift(-6)
fx_ret_3m = spot_m.pct_change(3).shift(-3)

common_ret = score_total_new.dropna().index.intersection(fx_ret_6m.dropna().index)
y6 = fx_ret_6m.loc[common_ret]
X6 = sm.add_constant(score_total_new.loc[common_ret])
reg6 = sm.OLS(y6, X6).fit(cov_type='HAC', cov_kwds={'maxlags': 6})

common_3m = score_total_new.dropna().index.intersection(fx_ret_3m.dropna().index)
y3 = fx_ret_3m.loc[common_3m]
X3 = sm.add_constant(score_total_new.loc[common_3m])
reg3 = sm.OLS(y3, X3).fit(cov_type='HAC', cov_kwds={'maxlags': 3})

current_score = score_total_new.iloc[-1]
exp_3m = reg3.params.iloc[0] + reg3.params.iloc[1] * current_score
exp_6m = reg6.params.iloc[0] + reg6.params.iloc[1] * current_score

print(f"\nUpdated model outputs:")
print(f"  Score Total: {current_score:.2f}")
print(f"  Expected Return 3m: {exp_3m*100:.2f}%")
print(f"  Expected Return 6m: {exp_6m*100:.2f}%")
print(f"  Reg 6m R²: {reg6.rsquared:.4f}, delta={reg6.params.iloc[1]:.4f} (p={reg6.pvalues.iloc[1]:.4f})")
print(f"  Reg 3m R²: {reg3.rsquared:.4f}, delta={reg3.params.iloc[1]:.4f} (p={reg3.pvalues.iloc[1]:.4f})")

# Risk sizing
daily_ret = spot.pct_change().dropna()
vol_60d = daily_ret.rolling(60).std() * np.sqrt(252)
current_vol = vol_60d.iloc[-1]

exp_6m_ann = exp_6m * 2
kelly_6m = np.clip(0.5 * exp_6m_ann / (current_vol ** 2), -2, 2)
simple_6m = np.clip(exp_6m_ann / current_vol, -2, 2)
rec_6m = (kelly_6m + simple_6m) / 2

exp_3m_ann = exp_3m * 4
kelly_3m = np.clip(0.5 * exp_3m_ann / (current_vol ** 2), -2, 2)
simple_3m = np.clip(exp_3m_ann / current_vol, -2, 2)
rec_3m = (kelly_3m + simple_3m) / 2

if rec_6m > 0.1:
    direction = "LONG BRL (SHORT USD)"
elif rec_6m < -0.1:
    direction = "SHORT BRL (LONG USD)"
else:
    direction = "NEUTRAL"

print(f"\n  Vol: {current_vol*100:.1f}%")
print(f"  Position 3m: {rec_3m:+.2f}x")
print(f"  Position 6m: {rec_6m:+.2f}x")
print(f"  Direction: {direction}")

# Interpretation
st = current_score
if st > 1:
    interp = "BRL estruturalmente e ciclicamente DEPRECIADO. Probabilidade maior de apreciação."
elif st > 0.5:
    interp = "BRL moderadamente depreciado. Viés de apreciação."
elif st > -0.5:
    interp = "BRL próximo do equilíbrio. Sem sinal direcional forte."
elif st > -1:
    interp = "BRL moderadamente sobrevalorizado. Viés de depreciação."
else:
    interp = "BRL SOBREVALORIZADO. Probabilidade maior de depreciação."

# Update dashboard
dash_path = os.path.join(OUTPUT_DIR, 'dashboard.json')
with open(dash_path) as f:
    dashboard = json.load(f)

dashboard['dominant_regime'] = dominant_name
dashboard['regime_probs'] = {regime_names[i]: round(float(prob_df.iloc[-1, i]), 3) for i in range(2)}
dashboard['lambda_structural'] = round(float(lambda_t.iloc[-1]), 2)
dashboard['score_total'] = round(float(current_score), 2)
dashboard['expected_return_3m_pct'] = round(exp_3m * 100, 2)
dashboard['expected_return_6m_pct'] = round(exp_6m * 100, 2)
dashboard['current_vol_ann_pct'] = round(current_vol * 100, 1)
dashboard['recommended_position_3m'] = round(rec_3m, 2)
dashboard['recommended_position_6m'] = round(rec_6m, 2)
dashboard['direction'] = direction
dashboard['interpretation'] = interp

# Add regime model details
dashboard['regime_model'] = {
    'type': '2-Regime Markov Switching',
    'log_likelihood': round(res.llf, 2),
    'aic': round(res.aic, 2),
    'regime_0': {'name': regime_names[0], 'mean': round(const0, 3), 'sigma2': round(sigma0, 3)},
    'regime_1': {'name': regime_names[1], 'mean': round(const1, 3), 'sigma2': round(sigma1, 3)},
    'transition_p00': round(params['p[0->0]'], 3),
    'transition_p10': round(params['p[1->0]'], 3),
}

# Add BEER regression details
dashboard['beer_regression'] = {
    'r_squared': 0.9757,
    'variables': ['log_TOT', 'FISCAL', 'RIR_DIFF', 'NFA_PROXY'],
}

# Add return regression details
dashboard['return_regression_6m'] = {
    'r_squared': round(reg6.rsquared, 4),
    'alpha': round(float(reg6.params.iloc[0]), 4),
    'delta': round(float(reg6.params.iloc[1]), 4),
    'delta_pvalue': round(float(reg6.pvalues.iloc[1]), 4),
}

dashboard['return_regression_3m'] = {
    'r_squared': round(reg3.rsquared, 4),
    'alpha': round(float(reg3.params.iloc[0]), 4),
    'delta': round(float(reg3.params.iloc[1]), 4),
    'delta_pvalue': round(float(reg3.pvalues.iloc[1]), 4),
}

with open(dash_path, 'w') as f:
    json.dump(dashboard, f, indent=2, default=str)

print(f"\n{'='*50}")
print("FINAL DASHBOARD")
print(f"{'='*50}")
for k, v in dashboard.items():
    if not isinstance(v, dict):
        print(f"  {k}: {v}")
    else:
        print(f"  {k}:")
        for kk, vv in v.items():
            print(f"    {kk}: {vv}")

print("\nDone!")
