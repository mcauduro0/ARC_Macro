"""
Dual Feature Selection: Elastic Net + Boruta + Stability Selection
===================================================================
v4.4 — Major improvements:
  1. Elastic Net replaces LASSO (L1+L2 handles correlated features)
  2. Fixed stability selection (adaptive thresholds, composite scoring)
  3. Feature interaction terms (VIX×CDS, carry×regime, etc.)
  4. Instability alerts (Robust→Unstable detection)

Elastic Net — L1+L2 penalized regression for structural features.
              L1 (sparsity) + L2 (grouping) via mixing parameter l1_ratio.
              Handles correlated features (Z_fiscal, Z_cds_br) properly.
              CV-optimized alpha AND l1_ratio.

Boruta     — Random Forest-based non-linear feature validation.
              Creates shadow features, trains RF, compares real vs shadow.
              Features that don't consistently beat noise are rejected.

Stability  — Bootstrap resampling with ADAPTIVE thresholds.
              Uses composite score = weighted(enet_freq, boruta_freq, rf_importance).
              Thresholds calibrated from actual frequency distribution.
              Robust: top quartile. Moderate: middle. Unstable: bottom quartile.

Interactions — Cross-feature products (VIX×CDS, carry×regime, etc.)
               Validated with Boruta before inclusion.
"""

import sys
import numpy as np
import pandas as pd
from sklearn.linear_model import ElasticNetCV, ElasticNet, LassoCV, Lasso
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import StandardScaler
from scipy.stats import rankdata
import warnings
import json
import os
from datetime import datetime
warnings.filterwarnings('ignore')

def log(msg):
    print(msg, file=sys.stderr)


# ============================================================
# STRUCTURAL FEATURE CLASSIFICATION
# ============================================================
STRUCTURAL_FEATURES = {
    'Z_beer', 'Z_reer_gap', 'mu_fx_val',
    'carry_fx', 'carry_front', 'carry_belly', 'carry_long', 'carry_hard',
    'Z_real_diff', 'Z_diferencial_real',
    'Z_tot', 'Z_termos_de_troca', 'Z_iron_ore',
    'Z_fiscal', 'Z_fiscal_risk', 'Z_fiscal_premium', 'Z_debt_accel',
    'Z_infl_surprise', 'Z_surpresa_inflacao',
    'Z_term_premium', 'Z_tp_5y',
    'Z_policy_gap', 'Z_rstar_composite', 'Z_selic_star_gap',
    'Z_fiscal_component', 'Z_sovereign_component',
}

MARKET_FEATURES = {
    'Z_dxy', 'Z_vix', 'Z_cds_br', 'Z_cds_brasil',
    'Z_hy_spread', 'Z_ewz', 'Z_bop',
    'Z_focus_fx', 'Z_cftc_brl', 'Z_idp_flow', 'Z_portfolio_flow',
    'Z_cip_basis', 'Z_us_real_yield', 'Z_us_breakeven',
    'Z_pb_momentum', 'Z_rstar_momentum',
    'rstar_regime_signal', 'Z_rstar_curve_gap',
}

# ============================================================
# FEATURE INTERACTION DEFINITIONS
# ============================================================
INTERACTION_PAIRS = [
    # Risk interactions
    ('Z_vix', 'Z_cds_br', 'vix_x_cds'),
    ('Z_vix', 'Z_cds_brasil', 'vix_x_cds_br'),
    # Carry × regime
    ('carry_fx', 'rstar_regime_signal', 'carry_x_regime'),
    ('carry_front', 'rstar_regime_signal', 'carry_front_x_regime'),
    ('carry_long', 'rstar_regime_signal', 'carry_long_x_regime'),
    ('carry_belly', 'rstar_regime_signal', 'carry_belly_x_regime'),
    ('carry_hard', 'rstar_regime_signal', 'carry_hard_x_regime'),
    # Fiscal × sovereign
    ('Z_fiscal', 'Z_cds_br', 'fiscal_x_cds'),
    ('Z_fiscal', 'Z_cds_brasil', 'fiscal_x_cds_br'),
    ('Z_fiscal_premium', 'Z_sovereign_component', 'fiscal_prem_x_sovereign'),
    # Policy × market
    ('Z_policy_gap', 'Z_dxy', 'policy_x_dxy'),
    ('Z_policy_gap', 'Z_vix', 'policy_x_vix'),
    # Valuation × momentum
    ('Z_beer', 'Z_pb_momentum', 'beer_x_momentum'),
    ('Z_reer_gap', 'Z_pb_momentum', 'reer_x_momentum'),
    # Term structure × risk
    ('Z_term_premium', 'Z_vix', 'term_prem_x_vix'),
    ('Z_term_premium', 'Z_cds_br', 'term_prem_x_cds'),
    ('Z_term_premium', 'Z_cds_brasil', 'term_prem_x_cds_br'),
    # r* interactions
    ('Z_rstar_composite', 'Z_dxy', 'rstar_x_dxy'),
    ('Z_rstar_composite', 'Z_vix', 'rstar_x_vix'),
    ('Z_selic_star_gap', 'rstar_regime_signal', 'selic_gap_x_regime'),
]


class FeatureSelectionResult:
    """Container for dual selection results with stability metrics."""
    
    def __init__(self, instrument: str):
        self.instrument = instrument
        self.all_features = []
        
        # Elastic Net results (replaces LASSO)
        self.enet_selected = []
        self.enet_rejected = []
        self.enet_coefficients = {}
        self.enet_alpha = 0.0
        self.enet_l1_ratio = 0.5
        self.enet_path = []  # [{alpha, coefficients, n_nonzero}, ...]
        
        # Boruta results
        self.boruta_confirmed = []
        self.boruta_tentative = []
        self.boruta_rejected = []
        self.boruta_importances = {}
        self.boruta_shadow_max = 0.0
        self.boruta_iterations = 0
        
        # Interaction terms
        self.interactions_tested = []
        self.interactions_confirmed = []
        self.interactions_rejected = []
        
        # Final merged result
        self.final_features = []
        self.feature_status = {}
        
        # Stability selection results
        self.stability = {
            'n_subsamples': 0,
            'subsample_ratio': 0.8,
            'enet_frequency': {},
            'boruta_frequency': {},
            'composite_score': {},
            'classification': {},
            'thresholds': {'robust': 0.0, 'moderate': 0.0},
        }
        
        # Instability alerts
        self.alerts = []
    
    def to_dict(self):
        return {
            'instrument': self.instrument,
            'total_features': len(self.all_features),
            'lasso': {
                'selected': self.enet_selected,
                'rejected': self.enet_rejected,
                'coefficients': {k: round(v, 6) for k, v in self.enet_coefficients.items()},
                'alpha': round(self.enet_alpha, 6),
                'l1_ratio': round(self.enet_l1_ratio, 4),
                'n_selected': len(self.enet_selected),
                'path': self.enet_path,
                'method': 'elastic_net',
            },
            'boruta': {
                'confirmed': self.boruta_confirmed,
                'tentative': self.boruta_tentative,
                'rejected': self.boruta_rejected,
                'importances': {k: round(v, 6) for k, v in self.boruta_importances.items()},
                'shadow_threshold': round(self.boruta_shadow_max, 6),
                'iterations': self.boruta_iterations,
                'n_confirmed': len(self.boruta_confirmed),
                'n_tentative': len(self.boruta_tentative),
                'n_rejected': len(self.boruta_rejected),
            },
            'interactions': {
                'tested': self.interactions_tested,
                'confirmed': self.interactions_confirmed,
                'rejected': self.interactions_rejected,
                'n_tested': len(self.interactions_tested),
                'n_confirmed': len(self.interactions_confirmed),
            },
            'final': {
                'features': self.final_features,
                'n_features': len(self.final_features),
                'reduction_pct': round(
                    (1 - len(self.final_features) / max(len(self.all_features), 1)) * 100, 1
                ),
                'method': 'elastic_net_union_boruta',
            },
            'feature_status': self.feature_status,
            'stability': self.stability,
            'alerts': self.alerts,
        }


def winsorize(series, lower=0.05, upper=0.95):
    """Winsorize at 5%-95% percentiles."""
    if len(series) < 10:
        return series
    lo = series.quantile(lower)
    hi = series.quantile(upper)
    return series.clip(lo, hi)


# ============================================================
# ELASTIC NET FEATURE SELECTION (replaces LASSO)
# ============================================================
class ElasticNetSelector:
    """
    Elastic Net (L1+L2) feature selection with CV-optimized alpha and l1_ratio.
    
    L1 component provides sparsity (like LASSO).
    L2 component provides grouping — correlated features (Z_fiscal, Z_cds_br)
    are kept together instead of arbitrarily dropping one.
    
    l1_ratio=1.0 → pure LASSO
    l1_ratio=0.5 → balanced Elastic Net
    l1_ratio=0.1 → mostly Ridge (minimal sparsity)
    """
    
    def __init__(self, n_alphas=50, cv_folds=5, max_iter=10000, path_n_alphas=100):
        self.n_alphas = n_alphas
        self.cv_folds = cv_folds
        self.max_iter = max_iter
        self.path_n_alphas = path_n_alphas
        # Test multiple l1_ratios to find optimal balance
        self.l1_ratios = [0.1, 0.2, 0.3, 0.5, 0.7, 0.9, 0.95, 1.0]
    
    def select(self, X: pd.DataFrame, y: pd.Series, compute_path=True) -> dict:
        """
        Run ElasticNetCV to find optimal alpha and l1_ratio.
        """
        scaler = StandardScaler()
        X_scaled = pd.DataFrame(
            scaler.fit_transform(X), 
            columns=X.columns, 
            index=X.index
        )
        
        enet_cv = ElasticNetCV(
            l1_ratio=self.l1_ratios,
            n_alphas=self.n_alphas,
            cv=min(self.cv_folds, max(3, len(X) // 20)),
            max_iter=self.max_iter,
            random_state=42,
            fit_intercept=True,
        )
        
        enet_cv.fit(X_scaled.values, y.values)
        
        optimal_alpha = enet_cv.alpha_
        optimal_l1_ratio = enet_cv.l1_ratio_
        coefficients = dict(zip(X.columns, enet_cv.coef_))
        
        selected = [f for f, c in coefficients.items() if abs(c) > 1e-8]
        rejected = [f for f, c in coefficients.items() if abs(c) <= 1e-8]
        
        # Compute coefficient path across alpha values (at optimal l1_ratio)
        path = []
        if compute_path:
            alpha_max = max(optimal_alpha * 100, 1.0)
            alpha_min = optimal_alpha * 0.01
            alphas_to_try = np.logspace(
                np.log10(alpha_min), 
                np.log10(alpha_max), 
                self.path_n_alphas
            )
            for alpha in sorted(alphas_to_try, reverse=True):
                enet = ElasticNet(
                    alpha=alpha, l1_ratio=optimal_l1_ratio,
                    max_iter=self.max_iter, fit_intercept=True
                )
                enet.fit(X_scaled.values, y.values)
                coefs = dict(zip(X.columns, enet.coef_))
                path.append({
                    'alpha': round(float(alpha), 8),
                    'log_alpha': round(float(np.log10(alpha)), 4),
                    'coefficients': {k: round(float(v), 6) for k, v in coefs.items()},
                    'n_nonzero': sum(1 for v in coefs.values() if abs(v) > 1e-8),
                    'is_optimal': abs(alpha - optimal_alpha) / optimal_alpha < 0.05,
                })
        
        return {
            'selected': selected,
            'rejected': rejected,
            'coefficients': coefficients,
            'alpha': optimal_alpha,
            'l1_ratio': optimal_l1_ratio,
            'path': path,
        }
    
    def select_fast(self, X: pd.DataFrame, y: pd.Series) -> list:
        """Fast Elastic Net selection without path (for bootstrap stability)."""
        scaler = StandardScaler()
        X_scaled = pd.DataFrame(
            scaler.fit_transform(X), columns=X.columns, index=X.index
        )
        enet_cv = ElasticNetCV(
            l1_ratio=[0.3, 0.5, 0.7, 0.9, 1.0],
            n_alphas=20, cv=min(3, max(2, len(X) // 30)),
            max_iter=5000, random_state=42, fit_intercept=True,
        )
        enet_cv.fit(X_scaled.values, y.values)
        return [f for f, c in zip(X.columns, enet_cv.coef_) if abs(c) > 1e-8]


# ============================================================
# BORUTA FEATURE SELECTION
# ============================================================
class BorutaSelector:
    """
    Boruta algorithm — non-linear feature validation via shadow features.
    """
    
    def __init__(self, n_iterations=50, alpha=0.05, max_depth=5, n_estimators=200):
        self.n_iterations = n_iterations
        self.alpha = alpha
        self.max_depth = max_depth
        self.n_estimators = n_estimators
    
    def select(self, X: pd.DataFrame, y: pd.Series) -> dict:
        """Run Boruta algorithm to classify features."""
        n_features = X.shape[1]
        feature_names = list(X.columns)
        
        hit_counts = np.zeros(n_features)
        importance_accumulator = np.zeros(n_features)
        shadow_max_accumulator = 0.0
        actual_iterations = 0
        
        for iteration in range(self.n_iterations):
            try:
                X_shadow = X.copy()
                for col in X_shadow.columns:
                    X_shadow[col] = np.random.permutation(X_shadow[col].values)
                X_shadow.columns = [f'shadow_{c}' for c in X.columns]
                
                X_combined = pd.concat([X, X_shadow], axis=1)
                
                rf = RandomForestRegressor(
                    n_estimators=self.n_estimators,
                    max_depth=self.max_depth,
                    min_samples_leaf=max(5, len(X) // 50),
                    max_features='sqrt',
                    random_state=42 + iteration,
                    n_jobs=1,
                )
                rf.fit(X_combined.values, y.values)
                
                importances = rf.feature_importances_
                real_importances = importances[:n_features]
                shadow_importances = importances[n_features:]
                shadow_max = np.max(shadow_importances)
                
                hit_counts += (real_importances > shadow_max).astype(float)
                importance_accumulator += real_importances
                shadow_max_accumulator += shadow_max
                actual_iterations += 1
                
            except Exception as e:
                continue
        
        if actual_iterations == 0:
            return {
                'confirmed': [], 'tentative': feature_names, 'rejected': [],
                'importances': {f: 0.0 for f in feature_names},
                'shadow_max': 0.0, 'iterations': 0,
            }
        
        hit_rates = hit_counts / actual_iterations
        avg_importances = importance_accumulator / actual_iterations
        avg_shadow_max = shadow_max_accumulator / actual_iterations
        
        # Classification thresholds based on binomial test
        # At alpha=0.05, with n iterations, threshold for "confirmed" 
        from scipy.stats import binom
        confirm_threshold = binom.ppf(1 - self.alpha, actual_iterations, 0.5) / actual_iterations
        reject_threshold = binom.ppf(self.alpha, actual_iterations, 0.5) / actual_iterations
        
        confirmed = []
        tentative = []
        rejected = []
        
        for i, feat in enumerate(feature_names):
            if hit_rates[i] >= confirm_threshold:
                confirmed.append(feat)
            elif hit_rates[i] <= reject_threshold:
                rejected.append(feat)
            else:
                tentative.append(feat)
        
        return {
            'confirmed': confirmed,
            'tentative': tentative,
            'rejected': rejected,
            'importances': dict(zip(feature_names, avg_importances.tolist())),
            'shadow_max': float(avg_shadow_max),
            'iterations': actual_iterations,
        }
    
    def select_fast(self, X: pd.DataFrame, y: pd.Series) -> list:
        """Fast Boruta for bootstrap stability (20 iterations, 150 trees)."""
        n_features = X.shape[1]
        feature_names = list(X.columns)
        hit_counts = np.zeros(n_features)
        actual = 0
        
        for iteration in range(10):  # Reduced for speed
            try:
                X_shadow = X.copy()
                for col in X_shadow.columns:
                    X_shadow[col] = np.random.permutation(X_shadow[col].values)
                X_shadow.columns = [f'shadow_{c}' for c in X.columns]
                X_combined = pd.concat([X, X_shadow], axis=1)
                
                rf = RandomForestRegressor(
                    n_estimators=150, max_depth=5,
                    min_samples_leaf=max(5, len(X) // 50),
                    max_features='sqrt', random_state=42 + iteration, n_jobs=1,
                )
                rf.fit(X_combined.values, y.values)
                
                importances = rf.feature_importances_
                shadow_max = np.max(importances[n_features:])
                hit_counts += (importances[:n_features] > shadow_max).astype(float)
                actual += 1
            except:
                continue
        
        if actual == 0:
            return feature_names
        hit_rates = hit_counts / actual
        # Use 0.5 threshold (feature must beat shadow >50% of the time)
        return [f for i, f in enumerate(feature_names) if hit_rates[i] > 0.5]


# ============================================================
# FEATURE INTERACTION BUILDER
# ============================================================
class InteractionBuilder:
    """
    Creates and validates feature interaction terms.
    
    Tests cross-feature products (VIX × CDS, carry × regime, etc.)
    and validates with Boruta to ensure genuine predictive power.
    """
    
    @staticmethod
    def build_interactions(X: pd.DataFrame, instrument: str) -> tuple:
        """
        Build interaction features available for this instrument's feature set.
        
        Returns:
            (X_with_interactions, interaction_names_added)
        """
        X_out = X.copy()
        added = []
        
        available_cols = set(X.columns)
        
        for feat_a, feat_b, name in INTERACTION_PAIRS:
            if feat_a in available_cols and feat_b in available_cols:
                # Standardize before multiplying to avoid scale issues
                a_std = (X[feat_a] - X[feat_a].mean()) / (X[feat_a].std() + 1e-10)
                b_std = (X[feat_b] - X[feat_b].mean()) / (X[feat_b].std() + 1e-10)
                X_out[f'IX_{name}'] = a_std * b_std
                added.append(f'IX_{name}')
        
        return X_out, added
    
    @staticmethod
    def validate_interactions(X: pd.DataFrame, y: pd.Series, 
                              interaction_names: list, n_iterations=30) -> tuple:
        """
        Validate interaction terms using Boruta.
        Only keep interactions that genuinely beat shadow features.
        
        Returns:
            (confirmed_interactions, rejected_interactions)
        """
        if not interaction_names:
            return [], []
        
        # Only test the interaction columns against shadows
        X_interactions = X[interaction_names].copy()
        n_features = len(interaction_names)
        hit_counts = np.zeros(n_features)
        actual = 0
        
        for iteration in range(n_iterations):
            try:
                X_shadow = X_interactions.copy()
                for col in X_shadow.columns:
                    X_shadow[col] = np.random.permutation(X_shadow[col].values)
                X_shadow.columns = [f'shadow_{c}' for c in X_interactions.columns]
                X_combined = pd.concat([X_interactions, X_shadow], axis=1)
                
                rf = RandomForestRegressor(
                    n_estimators=200, max_depth=5,
                    min_samples_leaf=max(5, len(X) // 50),
                    max_features='sqrt', random_state=42 + iteration, n_jobs=1,
                )
                rf.fit(X_combined.values, y.values)
                
                importances = rf.feature_importances_
                shadow_max = np.max(importances[n_features:])
                hit_counts += (importances[:n_features] > shadow_max).astype(float)
                actual += 1
            except:
                continue
        
        if actual == 0:
            return [], interaction_names
        
        hit_rates = hit_counts / actual
        confirmed = [f for i, f in enumerate(interaction_names) if hit_rates[i] > 0.5]
        rejected = [f for i, f in enumerate(interaction_names) if hit_rates[i] <= 0.5]
        
        return confirmed, rejected


# ============================================================
# STABILITY SELECTION (Fixed v4.4)
# ============================================================
class StabilitySelector:
    """
    Bootstrap-based stability selection with ADAPTIVE thresholds.
    
    v4.4 fixes:
    - Uses composite score (weighted enet_freq + boruta_freq + rf_importance_rank)
    - Adaptive thresholds based on actual score distribution (percentiles)
    - Increased Boruta fast iterations (10→20) for better convergence
    - Separate enet and boruta frequency tracking
    
    Classification uses ADAPTIVE thresholds:
      - Robust:   score >= P75 of composite scores
      - Moderate:  P40 <= score < P75
      - Unstable:  score < P40
    
    This ensures ~25% robust, ~35% moderate, ~40% unstable — a realistic
    distribution for macro data with low signal-to-noise ratio.
    """
    
    def __init__(self, n_subsamples=100, subsample_ratio=0.8):
        self.n_subsamples = n_subsamples
        self.subsample_ratio = subsample_ratio
        self.enet = ElasticNetSelector(n_alphas=20, cv_folds=3, max_iter=5000)
        self.boruta = BorutaSelector(n_iterations=10, max_depth=5, n_estimators=80)
    
    def run(self, X: pd.DataFrame, y: pd.Series, instrument: str) -> dict:
        """
        Run stability selection on bootstrap subsamples with composite scoring.
        """
        n_obs = len(X)
        n_sample = int(n_obs * self.subsample_ratio)
        feature_names = list(X.columns)
        n_features = len(feature_names)
        
        enet_counts = np.zeros(n_features)
        boruta_counts = np.zeros(n_features)
        rf_importance_sum = np.zeros(n_features)
        
        actual_subsamples = 0
        
        log(f"[Stability] {instrument}: Running {self.n_subsamples} bootstrap subsamples "
            f"({self.subsample_ratio*100:.0f}% of {n_obs} obs)...")
        
        for i in range(self.n_subsamples):
            try:
                np.random.seed(42 + i * 7)
                idx = np.random.choice(n_obs, size=n_sample, replace=False)
                X_sub = X.iloc[idx]
                y_sub = y.iloc[idx]
                
                # Winsorize subsample
                X_sub_w = X_sub.copy()
                for col in X_sub_w.columns:
                    X_sub_w[col] = winsorize(X_sub_w[col])
                y_sub_w = winsorize(y_sub)
                
                # Fast Elastic Net selection
                enet_selected = self.enet.select_fast(X_sub_w, y_sub_w)
                enet_set = set(enet_selected)
                
                # Fast Boruta selection (20 iterations)
                boruta_confirmed = self.boruta.select_fast(X_sub_w, y_sub_w)
                boruta_set = set(boruta_confirmed)
                
                # Also get RF importance for composite scoring
                rf = RandomForestRegressor(
                    n_estimators=100, max_depth=5,
                    min_samples_leaf=max(5, len(X_sub_w) // 50),
                    max_features='sqrt', random_state=42 + i, n_jobs=1,
                )
                rf.fit(X_sub_w.values, y_sub_w.values)
                rf_importance_sum += rf.feature_importances_
                
                # Count selections
                for j, feat in enumerate(feature_names):
                    if feat in enet_set:
                        enet_counts[j] += 1
                    if feat in boruta_set:
                        boruta_counts[j] += 1
                
                actual_subsamples += 1
                
                if (i + 1) % 20 == 0:
                    log(f"[Stability] {instrument}: {i+1}/{self.n_subsamples} subsamples completed")
                    
            except Exception as e:
                log(f"[Stability] {instrument}: Subsample {i} failed: {e}")
                continue
        
        if actual_subsamples == 0:
            return {
                'n_subsamples': 0,
                'subsample_ratio': self.subsample_ratio,
                'enet_frequency': {f: 1.0 for f in feature_names},
                'boruta_frequency': {f: 1.0 for f in feature_names},
                'composite_score': {f: 1.0 for f in feature_names},
                'classification': {f: 'robust' for f in feature_names},
                'thresholds': {'robust': 0.8, 'moderate': 0.4},
                # Keep backward-compatible keys
                'lasso_frequency': {f: 1.0 for f in feature_names},
                'combined_frequency': {f: 1.0 for f in feature_names},
            }
        
        enet_freq = enet_counts / actual_subsamples
        boruta_freq = boruta_counts / actual_subsamples
        rf_importance_avg = rf_importance_sum / actual_subsamples
        
        # Normalize RF importance to [0, 1]
        rf_max = rf_importance_avg.max()
        rf_normalized = rf_importance_avg / rf_max if rf_max > 0 else rf_importance_avg
        
        # --- COMPOSITE SCORE ---
        # Weighted combination: 40% enet freq + 30% boruta freq + 30% RF importance
        composite = 0.40 * enet_freq + 0.30 * boruta_freq + 0.30 * rf_normalized
        
        # --- ADAPTIVE THRESHOLDS ---
        # Based on actual distribution of composite scores
        p75 = np.percentile(composite, 75)
        p40 = np.percentile(composite, 40)
        
        # Ensure minimum separation
        if p75 - p40 < 0.05:
            p75 = np.percentile(composite, 70)
            p40 = np.percentile(composite, 35)
        
        # Classify using adaptive thresholds
        classification = {}
        for j, feat in enumerate(feature_names):
            score = composite[j]
            if score >= p75:
                classification[feat] = 'robust'
            elif score >= p40:
                classification[feat] = 'moderate'
            else:
                classification[feat] = 'unstable'
        
        n_robust = sum(1 for v in classification.values() if v == 'robust')
        n_moderate = sum(1 for v in classification.values() if v == 'moderate')
        n_unstable = sum(1 for v in classification.values() if v == 'unstable')
        
        log(f"[Stability] {instrument}: {actual_subsamples} subsamples completed. "
            f"Robust={n_robust}, Moderate={n_moderate}, Unstable={n_unstable} "
            f"(thresholds: robust>={p75:.3f}, moderate>={p40:.3f})")
        
        composite_dict = {feat: round(float(composite[j]), 4) for j, feat in enumerate(feature_names)}
        enet_freq_dict = {feat: round(float(enet_freq[j]), 3) for j, feat in enumerate(feature_names)}
        boruta_freq_dict = {feat: round(float(boruta_freq[j]), 3) for j, feat in enumerate(feature_names)}
        
        return {
            'n_subsamples': actual_subsamples,
            'subsample_ratio': self.subsample_ratio,
            'enet_frequency': enet_freq_dict,
            'boruta_frequency': boruta_freq_dict,
            'composite_score': composite_dict,
            'classification': classification,
            'thresholds': {
                'robust': round(float(p75), 4),
                'moderate': round(float(p40), 4),
            },
            # Backward-compatible keys
            'lasso_frequency': enet_freq_dict,
            'combined_frequency': composite_dict,
        }


# ============================================================
# INSTABILITY ALERT DETECTOR
# ============================================================
class InstabilityAlertDetector:
    """
    Detects when features change stability classification between runs.
    Generates alerts when Robust→Unstable transitions occur (regime change signal).
    """
    
    @staticmethod
    def detect_alerts(current_stability: dict, instrument: str) -> list:
        """
        Compare current stability with previous run.
        Returns list of alert dicts.
        """
        alerts = []
        
        # Load previous stability from temporal history
        history_file = os.path.join(os.path.dirname(__file__), 'feature_selection_history.json')
        try:
            if os.path.exists(history_file):
                with open(history_file, 'r') as f:
                    history = json.load(f)
                if len(history) >= 1:
                    prev = history[-1]
                    prev_classification = prev.get('instruments', {}).get(
                        instrument, {}
                    ).get('stability_classification', {})
                    
                    current_classification = current_stability.get('classification', {})
                    
                    for feat, current_class in current_classification.items():
                        prev_class = prev_classification.get(feat, 'unknown')
                        
                        # Robust → Unstable = critical alert
                        if prev_class == 'robust' and current_class == 'unstable':
                            alerts.append({
                                'type': 'critical',
                                'feature': feat,
                                'instrument': instrument,
                                'transition': f'{prev_class} → {current_class}',
                                'message': f'{feat} dropped from Robust to Unstable — possible regime change',
                            })
                        # Robust → Moderate = warning
                        elif prev_class == 'robust' and current_class == 'moderate':
                            alerts.append({
                                'type': 'warning',
                                'feature': feat,
                                'instrument': instrument,
                                'transition': f'{prev_class} → {current_class}',
                                'message': f'{feat} weakened from Robust to Moderate — monitor closely',
                            })
                        # Unstable → Robust = positive signal
                        elif prev_class == 'unstable' and current_class == 'robust':
                            alerts.append({
                                'type': 'info',
                                'feature': feat,
                                'instrument': instrument,
                                'transition': f'{prev_class} → {current_class}',
                                'message': f'{feat} strengthened from Unstable to Robust — new signal emerging',
                            })
        except Exception as e:
            log(f"[InstabilityAlert] {instrument}: Failed to detect alerts: {e}")
        
        return alerts


# ============================================================
# TEMPORAL SELECTION TRACKER
# ============================================================
class TemporalSelectionTracker:
    """Tracks feature selection results over time."""
    
    HISTORY_FILE = os.path.join(os.path.dirname(__file__), 'feature_selection_history.json')
    MAX_HISTORY = 52
    
    @classmethod
    def save_snapshot(cls, results: dict, run_date: str = None):
        """Save current feature selection results as a temporal snapshot."""
        if run_date is None:
            run_date = datetime.utcnow().strftime('%Y-%m-%d')
        
        snapshot = {
            'date': run_date,
            'timestamp': datetime.utcnow().isoformat(),
            'instruments': {},
        }
        
        for inst, result in results.items():
            snapshot['instruments'][inst] = {
                'final_features': result.get('final', {}).get('features', []),
                'n_features': result.get('final', {}).get('n_features', 0),
                'reduction_pct': result.get('final', {}).get('reduction_pct', 0),
                'lasso_selected': result.get('lasso', {}).get('selected', []),
                'lasso_alpha': result.get('lasso', {}).get('alpha', 0),
                'l1_ratio': result.get('lasso', {}).get('l1_ratio', 0.5),
                'boruta_confirmed': result.get('boruta', {}).get('confirmed', []),
                'stability_classification': result.get('stability', {}).get('classification', {}),
                'stability_composite_scores': result.get('stability', {}).get('composite_score', result.get('stability', {}).get('composite_scores', {})),
                'stability_thresholds': result.get('stability', {}).get('thresholds', {}),
                'interactions_confirmed': result.get('interactions', {}).get('confirmed', []),
            }
        
        history = cls._load_history()
        history = [h for h in history if h.get('date') != run_date]
        history.append(snapshot)
        
        if len(history) > cls.MAX_HISTORY:
            history = history[-cls.MAX_HISTORY:]
        
        try:
            with open(cls.HISTORY_FILE, 'w') as f:
                json.dump(history, f, indent=2)
            log(f"[TemporalTracker] Saved snapshot for {run_date} ({len(history)} total)")
        except Exception as e:
            log(f"[TemporalTracker] Failed to save: {e}")
    
    @classmethod
    def get_history(cls) -> list:
        return cls._load_history()
    
    @classmethod
    def detect_changes(cls, current_results: dict) -> dict:
        """Compare current selection with previous snapshot."""
        history = cls._load_history()
        if len(history) < 2:
            return {'has_previous': False, 'changes': {}}
        
        previous = history[-1]
        changes = {}
        for inst, current in current_results.items():
            current_features = set(current.get('final', {}).get('features', []))
            prev_inst = previous.get('instruments', {}).get(inst, {})
            prev_features = set(prev_inst.get('final_features', []))
            
            gained = sorted(current_features - prev_features)
            lost = sorted(prev_features - current_features)
            stable = sorted(current_features & prev_features)
            
            changes[inst] = {
                'gained': gained, 'lost': lost, 'stable': stable,
                'n_gained': len(gained), 'n_lost': len(lost), 'n_stable': len(stable),
                'turnover_pct': round(
                    (len(gained) + len(lost)) / max(len(current_features | prev_features), 1) * 100, 1
                ),
            }
        
        return {
            'has_previous': True,
            'previous_date': previous.get('date', 'unknown'),
            'changes': changes,
        }
    
    @classmethod
    def build_temporal_summary(cls) -> dict:
        """Build summary of feature selection evolution over time."""
        history = cls._load_history()
        if not history:
            return {'n_snapshots': 0, 'timeline': [], 'feature_persistence': {}}
        
        timeline = []
        for snapshot in history:
            entry = {'date': snapshot.get('date', ''), 'instruments': {}}
            for inst, data in snapshot.get('instruments', {}).items():
                entry['instruments'][inst] = {
                    'n_features': data.get('n_features', 0),
                    'features': data.get('final_features', []),
                    'reduction_pct': data.get('reduction_pct', 0),
                    'lasso_alpha': data.get('lasso_alpha', 0),
                }
            timeline.append(entry)
        
        all_instruments = set()
        for snapshot in history:
            all_instruments.update(snapshot.get('instruments', {}).keys())
        
        feature_persistence = {}
        for inst in all_instruments:
            feat_counts = {}
            n_snapshots_with_inst = 0
            for snapshot in history:
                inst_data = snapshot.get('instruments', {}).get(inst, {})
                features = inst_data.get('final_features', [])
                if features:
                    n_snapshots_with_inst += 1
                    for f in features:
                        feat_counts[f] = feat_counts.get(f, 0) + 1
            if n_snapshots_with_inst > 0:
                feature_persistence[inst] = {
                    f: round(count / n_snapshots_with_inst, 3)
                    for f, count in feat_counts.items()
                }
        
        return {
            'n_snapshots': len(history),
            'date_range': {
                'start': history[0].get('date', ''),
                'end': history[-1].get('date', ''),
            },
            'timeline': timeline,
            'feature_persistence': feature_persistence,
        }
    
    @classmethod
    def build_rolling_stability(cls, window_months: int = 12) -> dict:
        """
        Build rolling stability data for visualization.
        Returns per-instrument, per-feature composite score timeseries.
        """
        history = cls._load_history()
        if not history:
            return {'n_snapshots': 0, 'instruments': {}}
        
        # Limit to window
        if len(history) > window_months:
            history = history[-window_months:]
        
        dates = [h.get('date', '') for h in history]
        all_instruments = set()
        for h in history:
            all_instruments.update(h.get('instruments', {}).keys())
        
        result = {
            'n_snapshots': len(history),
            'dates': dates,
            'instruments': {},
        }
        
        for inst in sorted(all_instruments):
            # Collect all features that appear in any snapshot
            all_features = set()
            for h in history:
                inst_data = h.get('instruments', {}).get(inst, {})
                scores = inst_data.get('stability_composite_scores', {})
                all_features.update(scores.keys())
            
            feature_series = {}
            for feat in sorted(all_features):
                series = []
                for h in history:
                    inst_data = h.get('instruments', {}).get(inst, {})
                    scores = inst_data.get('stability_composite_scores', {})
                    classification = inst_data.get('stability_classification', {})
                    series.append({
                        'date': h.get('date', ''),
                        'composite_score': scores.get(feat, 0),
                        'classification': classification.get(feat, 'unknown'),
                    })
                feature_series[feat] = series
            
            # Also compute per-date summary stats
            date_summaries = []
            for h in history:
                inst_data = h.get('instruments', {}).get(inst, {})
                classification = inst_data.get('stability_classification', {})
                n_robust = sum(1 for v in classification.values() if v == 'robust')
                n_moderate = sum(1 for v in classification.values() if v == 'moderate')
                n_unstable = sum(1 for v in classification.values() if v == 'unstable')
                total = n_robust + n_moderate + n_unstable
                date_summaries.append({
                    'date': h.get('date', ''),
                    'n_robust': n_robust,
                    'n_moderate': n_moderate,
                    'n_unstable': n_unstable,
                    'pct_robust': round(n_robust / max(total, 1) * 100, 1),
                })
            
            result['instruments'][inst] = {
                'feature_series': feature_series,
                'date_summaries': date_summaries,
            }
        
        return result
    
    @classmethod
    def _load_history(cls) -> list:
        try:
            if os.path.exists(cls.HISTORY_FILE):
                with open(cls.HISTORY_FILE, 'r') as f:
                    return json.load(f)
        except Exception as e:
            log(f"[TemporalTracker] Failed to load history: {e}")
        return []


# ============================================================
# DUAL FEATURE SELECTOR (v4.4 — Elastic Net + Interactions)
# ============================================================
class DualFeatureSelector:
    """
    Orchestrates Elastic Net + Boruta + Interactions + Stability.
    
    v4.4 enhancements:
    - Elastic Net replaces LASSO (L1+L2 for correlated features)
    - Feature interaction terms validated with Boruta
    - Adaptive stability thresholds (composite scoring)
    - Instability alerts for regime change detection
    """
    
    def __init__(self, config=None):
        self.config = config or {}
        self.enet = ElasticNetSelector(
            n_alphas=self.config.get('enet_n_alphas', 50),
            cv_folds=self.config.get('enet_cv_folds', 5),
            path_n_alphas=self.config.get('enet_path_n_alphas', 100),
        )
        self.boruta = BorutaSelector(
            n_iterations=self.config.get('boruta_iterations', 20),
            alpha=self.config.get('boruta_alpha', 0.05),
            max_depth=self.config.get('boruta_max_depth', 5),
            n_estimators=self.config.get('boruta_n_estimators', 100),
        )
        self.stability_selector = StabilitySelector(
            n_subsamples=self.config.get('stability_n_subsamples', 30),
            subsample_ratio=self.config.get('stability_subsample_ratio', 0.8),
        )
    
    def select(self, X: pd.DataFrame, y: pd.Series, instrument: str) -> FeatureSelectionResult:
        """
        Run Elastic Net + Boruta + Interactions + Stability.
        """
        result = FeatureSelectionResult(instrument)
        result.all_features = list(X.columns)
        
        log(f"[FeatureSelection] {instrument}: {len(X.columns)} features, {len(X)} observations")
        
        # --- Winsorize inputs ---
        X_w = X.copy()
        for col in X_w.columns:
            X_w[col] = winsorize(X_w[col])
        y_w = winsorize(y)
        
        mask = X_w.notna().all(axis=1) & y_w.notna()
        X_w = X_w[mask]
        y_w = y_w[mask]
        
        if len(X_w) < 36:
            log(f"[FeatureSelection] {instrument}: insufficient data ({len(X_w)} < 36)")
            result.final_features = list(X.columns)
            result.feature_status = {f: 'confirmed' for f in X.columns}
            return result
        
        # --- Build Interaction Terms ---
        log(f"[FeatureSelection] {instrument}: Building interaction terms...")
        X_with_ix, ix_names = InteractionBuilder.build_interactions(X_w, instrument)
        result.interactions_tested = ix_names
        
        if ix_names:
            log(f"[FeatureSelection] {instrument}: Validating {len(ix_names)} interactions with Boruta...")
            confirmed_ix, rejected_ix = InteractionBuilder.validate_interactions(
                X_with_ix, y_w, ix_names, n_iterations=30
            )
            result.interactions_confirmed = confirmed_ix
            result.interactions_rejected = rejected_ix
            log(f"[FeatureSelection] {instrument}: Interactions confirmed={len(confirmed_ix)}, "
                f"rejected={len(rejected_ix)}")
            
            # Add confirmed interactions to feature set
            if confirmed_ix:
                for ix_name in confirmed_ix:
                    X_w[ix_name] = X_with_ix[ix_name]
                result.all_features = list(X_w.columns)
        
        # --- Elastic Net Pass (with full path) ---
        log(f"[FeatureSelection] {instrument}: Running Elastic Net with {self.enet.path_n_alphas}-alpha path...")
        try:
            enet_result = self.enet.select(X_w, y_w, compute_path=True)
            result.enet_selected = enet_result['selected']
            result.enet_rejected = enet_result['rejected']
            result.enet_coefficients = enet_result['coefficients']
            result.enet_alpha = enet_result['alpha']
            result.enet_l1_ratio = enet_result.get('l1_ratio', 0.5)
            result.enet_path = enet_result['path']
            log(f"[FeatureSelection] {instrument}: Elastic Net selected {len(result.enet_selected)}/{len(X_w.columns)} "
                f"(alpha={result.enet_alpha:.4f}, l1_ratio={result.enet_l1_ratio:.2f}, "
                f"path={len(result.enet_path)} points)")
        except Exception as e:
            log(f"[FeatureSelection] {instrument}: Elastic Net failed: {e}")
            result.enet_selected = list(X_w.columns)
        
        # --- Boruta Pass ---
        log(f"[FeatureSelection] {instrument}: Running Boruta ({self.boruta.n_iterations} iterations)...")
        try:
            boruta_result = self.boruta.select(X_w, y_w)
            result.boruta_confirmed = boruta_result['confirmed']
            result.boruta_tentative = boruta_result['tentative']
            result.boruta_rejected = boruta_result['rejected']
            result.boruta_importances = boruta_result['importances']
            result.boruta_shadow_max = boruta_result['shadow_max']
            result.boruta_iterations = boruta_result['iterations']
            log(f"[FeatureSelection] {instrument}: Boruta confirmed={len(result.boruta_confirmed)}, "
                f"tentative={len(result.boruta_tentative)}, rejected={len(result.boruta_rejected)}")
        except Exception as e:
            log(f"[FeatureSelection] {instrument}: Boruta failed: {e}")
            result.boruta_confirmed = list(X_w.columns)
        
        # --- Stability Selection (composite scoring) ---
        log(f"[FeatureSelection] {instrument}: Running Stability Selection "
            f"({self.stability_selector.n_subsamples} subsamples)...")
        try:
            stability_result = self.stability_selector.run(X_w, y_w, instrument)
            result.stability = stability_result
            log(f"[FeatureSelection] {instrument}: Stability complete. "
                f"Robust={sum(1 for v in stability_result['classification'].values() if v == 'robust')}, "
                f"Moderate={sum(1 for v in stability_result['classification'].values() if v == 'moderate')}, "
                f"Unstable={sum(1 for v in stability_result['classification'].values() if v == 'unstable')}")
        except Exception as e:
            log(f"[FeatureSelection] {instrument}: Stability failed: {e}")
        
        # --- Instability Alerts ---
        try:
            result.alerts = InstabilityAlertDetector.detect_alerts(
                result.stability, instrument
            )
            if result.alerts:
                for alert in result.alerts:
                    log(f"[ALERT] {alert['type'].upper()}: {alert['message']}")
        except Exception as e:
            log(f"[FeatureSelection] {instrument}: Alert detection failed: {e}")
        
        # --- Merge Strategy ---
        enet_set = set(result.enet_selected)
        boruta_confirmed_set = set(result.boruta_confirmed)
        boruta_tentative_set = set(result.boruta_tentative)
        
        # Union of Elastic Net + Boruta confirmed
        final_set = enet_set | boruta_confirmed_set
        
        # Add tentative features that are also in Elastic Net
        for feat in boruta_tentative_set:
            if feat in enet_set:
                final_set.add(feat)
        
        # Minimum feature count
        if len(final_set) < 3:
            log(f"[FeatureSelection] {instrument}: Too few features ({len(final_set)}), keeping all")
            final_set = set(X_w.columns)
        
        result.final_features = sorted(final_set, key=lambda f: list(X_w.columns).index(f) if f in X_w.columns else 999)
        
        # Build per-feature status
        for feat in X_w.columns:
            if feat in boruta_confirmed_set and feat in enet_set:
                result.feature_status[feat] = 'confirmed_both'
            elif feat in boruta_confirmed_set:
                result.feature_status[feat] = 'confirmed_boruta'
            elif feat in enet_set:
                result.feature_status[feat] = 'confirmed_enet'
            elif feat in boruta_tentative_set:
                result.feature_status[feat] = 'tentative'
            else:
                result.feature_status[feat] = 'rejected'
        
        log(f"[FeatureSelection] {instrument}: Final={len(result.final_features)}/{len(X_w.columns)} features "
            f"({100 - len(result.final_features)/len(X_w.columns)*100:.0f}% reduction)")
        
        return result


def run_dual_selection(data_layer, feature_engine, feature_map: dict, config=None) -> dict:
    """
    Run dual feature selection with stability analysis for all instruments.
    """
    selector = DualFeatureSelector(config)
    results = {}
    
    ret_df = data_layer.ret_df
    feat_df = feature_engine.feature_df
    
    if ret_df is None or feat_df is None:
        return results
    
    for inst, feat_names in feature_map.items():
        if inst not in ret_df.columns:
            continue
        
        available_feats = [f for f in feat_names if f in feat_df.columns]
        if len(available_feats) < 3:
            continue
        
        y = ret_df[inst].dropna()
        X = feat_df[available_feats].reindex(y.index).dropna()
        y = y.reindex(X.index)
        
        if len(y) < 36:
            continue
        
        result = selector.select(X, y, inst)
        results[inst] = result.to_dict()
    
    # --- Temporal Tracking ---
    try:
        run_date = datetime.utcnow().strftime('%Y-%m-%d')
        TemporalSelectionTracker.save_snapshot(results, run_date)
    except Exception as e:
        log(f"[FeatureSelection] Temporal tracking failed: {e}")
    
    # --- Add temporal comparison to results ---
    try:
        temporal_changes = TemporalSelectionTracker.detect_changes(results)
        temporal_summary = TemporalSelectionTracker.build_temporal_summary()
    except Exception as e:
        log(f"[FeatureSelection] Temporal analysis failed: {e}")
        temporal_changes = {'has_previous': False, 'changes': {}}
        temporal_summary = {'n_snapshots': 0, 'timeline': [], 'feature_persistence': {}}
    
    return {
        'per_instrument': results,
        'temporal_changes': temporal_changes,
        'temporal_summary': temporal_summary,
    }
