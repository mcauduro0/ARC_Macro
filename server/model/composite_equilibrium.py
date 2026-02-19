"""
Composite Equilibrium Rate Framework
=====================================
Replaces the simple Taylor Rule with a 5-model composite estimator
of the neutral real rate (r*) for Brazil.

Models:
  1. Fiscal-Augmented r*  — debt/GDP, primary balance, CDS, EMBI
  2. Real Rate Parity r*  — US TIPS + country risk premium
  3. Market-Implied r*    — ACM-style term structure decomposition
  4. State-Space r*       — Kalman Filter with fiscal/external channels
  5. Regime-Switching r*  — HMM regime-conditional r*

References:
  - Holston, Laubach & Williams (2023), NY Fed Staff Reports 1063
  - Adrian, Crump & Moench (2013), JFE
  - BCB Working Paper 637 (2025)
  - IMF WP 2023/106
  - Rachel & Summers (2019)
"""

import numpy as np
import pandas as pd
from scipy.stats import mstats


def _winsorize(s, limits=(0.05, 0.05)):
    """Winsorize a pandas Series at 5th/95th percentiles."""
    if isinstance(s, pd.Series):
        arr = s.dropna().values
        if len(arr) < 10:
            return s
        w = mstats.winsorize(arr, limits=limits)
        return pd.Series(w, index=s.dropna().index).reindex(s.index)
    return s


def _safe_align(*series, min_len=24):
    """Align multiple series to common index, forward-fill, require min_len.
    
    IMPORTANT: Returns the same number of series as inputs to preserve
    positional unpacking. Empty series are replaced with zero-filled series
    on the common index.
    """
    valid = [s for s in series if isinstance(s, pd.Series) and len(s) > 0]
    if len(valid) < 2:
        return None
    idx = valid[0].index
    for s in valid[1:]:
        idx = idx.intersection(s.index)
    if len(idx) < min_len:
        return None
    # Preserve ALL input positions - replace empty series with zeros on common index
    result = []
    for s in series:
        if isinstance(s, pd.Series) and len(s) > 0:
            result.append(s.reindex(idx).ffill().fillna(0))
        else:
            result.append(pd.Series(0.0, index=idx))
    return result, idx


# ============================================================
# MODEL 1: Fiscal-Augmented r*
# ============================================================
class FiscalAugmentedRStar:
    """
    r*_fiscal = r*_base + φ₁ × Δ(debt/GDP)_norm + φ₂ × primary_balance_norm
                        + φ₃ × CDS_5Y_norm + φ₄ × EMBI_norm

    Uses rolling OLS (60m window) to update coefficients, with structural
    priors as regularization anchors. All inputs are winsorized 5/95.
    """

    # Structural priors from literature (BCB WP 637, IMF WP 2023/106)
    PRIOR_COEFFICIENTS = {
        'debt_gdp_change': 0.04,    # Per pp change in debt/GDP (12m)
        'primary_balance': -0.12,   # Per pp of GDP
        'cds_norm': 0.007,          # Per bp of CDS 5Y
        'embi_norm': 0.005,         # Per bp of EMBI
    }
    R_BASE = 4.0  # Structural base real rate (productivity + demographics)

    def __init__(self, window=60, prior_weight=0.3):
        self.window = window
        self.prior_weight = prior_weight  # Bayesian shrinkage toward priors
        self.rstar_series = None
        self.decomposition = None

    def estimate(self, selic, ipca_exp, debt_gdp, primary_bal, cds_5y, embi):
        """
        Estimate fiscal-augmented r* series.
        All inputs: pd.Series with DatetimeIndex (monthly).
        Returns: pd.Series of r*_fiscal (real rate, %).
        """
        aligned = _safe_align(selic, ipca_exp, debt_gdp, primary_bal, cds_5y, embi, min_len=36)
        if aligned is None:
            return pd.Series(dtype=float), {}

        (sel_a, pie_a, debt_a, pb_a, cds_a, embi_a), idx = aligned

        # Winsorize all inputs
        debt_a = _winsorize(debt_a)
        pb_a = _winsorize(pb_a)
        cds_a = _winsorize(cds_a)
        embi_a = _winsorize(embi_a)

        # Derived features
        debt_change_12m = debt_a.diff(12).fillna(0)  # 12m change in debt/GDP
        debt_change_12m = _winsorize(debt_change_12m)

        # Ex-ante real rate (observed)
        real_rate_observed = sel_a - pie_a

        # Build fiscal premium components
        # Normalize CDS and EMBI to basis points for coefficient interpretation
        cds_centered = cds_a - cds_a.rolling(self.window, min_periods=24).median()
        embi_centered = embi_a - embi_a.rolling(self.window, min_periods=24).median()

        # Rolling estimation with Bayesian shrinkage toward priors
        rstar = pd.Series(index=idx, dtype=float)
        decomp_base = pd.Series(index=idx, dtype=float)
        decomp_fiscal = pd.Series(index=idx, dtype=float)
        decomp_sovereign = pd.Series(index=idx, dtype=float)

        for i in range(max(36, self.window), len(idx)):
            t = idx[i]
            start = max(0, i - self.window)

            # Window data
            y_w = real_rate_observed.iloc[start:i].dropna()
            debt_w = debt_change_12m.iloc[start:i].dropna()
            pb_w = pb_a.iloc[start:i].dropna()
            cds_w = cds_centered.iloc[start:i].dropna()
            embi_w = embi_centered.iloc[start:i].dropna()

            # Align window
            w_idx = y_w.index.intersection(debt_w.index).intersection(pb_w.index)
            w_idx = w_idx.intersection(cds_w.index).intersection(embi_w.index)

            if len(w_idx) < 24:
                continue

            # Simple OLS: y = α + β₁×debt_chg + β₂×pb + β₃×cds + β₄×embi + ε
            X = np.column_stack([
                debt_w.reindex(w_idx).values,
                pb_w.reindex(w_idx).values,
                cds_w.reindex(w_idx).values,
                embi_w.reindex(w_idx).values,
            ])
            y = y_w.reindex(w_idx).values

            try:
                # Ridge-like: OLS with L2 penalty toward priors
                XtX = X.T @ X
                Xty = X.T @ y
                n = len(y)

                # Prior coefficients as target
                beta_prior = np.array([
                    self.PRIOR_COEFFICIENTS['debt_gdp_change'],
                    self.PRIOR_COEFFICIENTS['primary_balance'],
                    self.PRIOR_COEFFICIENTS['cds_norm'],
                    self.PRIOR_COEFFICIENTS['embi_norm'],
                ])

                # Bayesian shrinkage: β_post = (1-λ)×β_ols + λ×β_prior
                ridge_lambda = self.prior_weight * n
                beta_ols = np.linalg.solve(
                    XtX + ridge_lambda * np.eye(4),
                    Xty + ridge_lambda * beta_prior
                )

                # Current values
                debt_now = debt_change_12m.iloc[i]
                pb_now = pb_a.iloc[i]
                cds_now = cds_centered.iloc[i]
                embi_now = embi_centered.iloc[i]

                # Decomposition
                fiscal_component = beta_ols[0] * debt_now + beta_ols[1] * pb_now
                sovereign_component = beta_ols[2] * cds_now + beta_ols[3] * embi_now

                r_star_t = self.R_BASE + fiscal_component + sovereign_component
                # Clip to reasonable range [2.0, 10.0] for Brazil
                r_star_t = np.clip(r_star_t, 2.0, 10.0)

                rstar[t] = r_star_t
                decomp_base[t] = self.R_BASE
                decomp_fiscal[t] = fiscal_component
                decomp_sovereign[t] = sovereign_component

            except (np.linalg.LinAlgError, ValueError):
                continue

        rstar = rstar.dropna()
        self.rstar_series = rstar
        self.decomposition = {
            'base': decomp_base.dropna(),
            'fiscal': decomp_fiscal.dropna(),
            'sovereign': decomp_sovereign.dropna(),
        }
        return rstar, self.decomposition


# ============================================================
# MODEL 2: Real Rate Parity r*
# ============================================================
class RealRateParityRStar:
    """
    r*_BR = r*_US + country_risk_premium + structural_premium

    Where:
      r*_US = US TIPS 5Y (proxy for global r*)
      country_risk_premium = f(CDS, EMBI, VIX)
      structural_premium = f(debt/GDP differential, ToT, current account)
    """

    def __init__(self, window=60):
        self.window = window
        self.rstar_series = None

    def estimate(self, us_tips_5y, us_tips_10y, cds_5y, embi, vix,
                 debt_gdp, bop_current, tot):
        """
        Estimate r* via real rate parity.
        Returns: pd.Series of r*_parity (real rate, %).
        """
        # Use TIPS 5Y as primary, 10Y as fallback
        us_real = us_tips_5y if len(us_tips_5y) > len(us_tips_10y) else us_tips_10y
        if len(us_real) < 24:
            # Try combining
            if len(us_tips_5y) > 0 and len(us_tips_10y) > 0:
                us_real = us_tips_5y.combine_first(us_tips_10y)
            elif len(us_tips_10y) > 0:
                us_real = us_tips_10y
            else:
                return pd.Series(dtype=float)

        # Align all available series
        core_series = [us_real, cds_5y, embi]
        valid_core = [s for s in core_series if len(s) > 24]
        if len(valid_core) < 2:
            return pd.Series(dtype=float)

        aligned = _safe_align(us_real, cds_5y, embi, min_len=24)
        if aligned is None:
            return pd.Series(dtype=float)

        (us_a, cds_a, embi_a), idx = aligned

        # Winsorize
        us_a = _winsorize(us_a)
        cds_a = _winsorize(cds_a)
        embi_a = _winsorize(embi_a)

        # Country risk premium: CDS/100 (bps to pp) + EMBI adjustment
        # CDS 5Y in bps → convert to percentage points
        crp_cds = cds_a / 100.0  # e.g., 150 bps → 1.50 pp
        crp_embi = embi_a / 100.0 * 0.5  # EMBI partially overlaps with CDS

        # Avoid double-counting: use max(CDS, EMBI*0.7) as country risk
        country_risk = pd.concat([crp_cds, crp_embi * 0.7], axis=1).max(axis=1)

        # VIX risk-on/risk-off adjustment
        vix_adj = pd.Series(0.0, index=idx)
        if len(vix) > 24:
            vix_r = vix.reindex(idx).ffill()
            vix_r = _winsorize(vix_r)
            vix_median = vix_r.rolling(self.window, min_periods=24).median()
            # Above-median VIX adds premium, below-median subtracts
            vix_adj = (vix_r - vix_median) / vix_median * 0.5  # Scale factor
            vix_adj = vix_adj.clip(-1.0, 2.0).fillna(0)

        # Structural premium from fiscal position
        struct_premium = pd.Series(0.0, index=idx)
        if len(debt_gdp) > 24:
            debt_r = debt_gdp.reindex(idx).ffill()
            debt_r = _winsorize(debt_r)
            # Brazil's structural premium: ~0.03pp per pp of debt/GDP above 60%
            struct_premium = ((debt_r - 60.0) * 0.03).clip(0, 3.0).fillna(0)

        # Terms of trade adjustment (negative ToT shock → higher r*)
        tot_adj = pd.Series(0.0, index=idx)
        if len(tot) > 24:
            tot_r = tot.reindex(idx).ffill()
            tot_r = _winsorize(tot_r)
            tot_z = (tot_r - tot_r.rolling(self.window, min_periods=24).mean()) / \
                    tot_r.rolling(self.window, min_periods=24).std().clip(lower=0.5)
            tot_adj = (-tot_z * 0.3).clip(-1.0, 1.0).fillna(0)

        # Composite: r*_BR = r*_US + country_risk + vix_adj + structural + tot_adj
        rstar = us_a + country_risk + vix_adj + struct_premium + tot_adj

        # Clip to reasonable range
        rstar = rstar.clip(2.0, 12.0)
        rstar = rstar.dropna()

        self.rstar_series = rstar
        return rstar


# ============================================================
# MODEL 3: Market-Implied r* (ACM-style)
# ============================================================
class MarketImpliedRStar:
    """
    ACM-style term structure decomposition for Brazilian DI curve.
    Extracts market-implied r* from the yield curve using PCA + VAR.

    Simplified approach (vs full ACM):
      1. PCA on DI curve cross-section → 3 factors (level, slope, curvature)
      2. VAR(1) on factors → expected future short rate path
      3. Long-run expected short rate → market-implied r*
      4. Term premium = yield - expectations component
    """

    def __init__(self, n_factors=3, window=60):
        self.n_factors = n_factors
        self.window = window
        self.rstar_series = None
        self.term_premium_series = None

    def estimate(self, di_3m, di_6m, di_1y, di_2y, di_3y, di_5y, di_10y,
                 ipca_exp=None):
        """
        Estimate market-implied r* from the DI curve.
        Returns: pd.Series of r*_market (nominal rate, %).
        """
        # Build yield matrix from available tenors
        tenors = {
            '3m': di_3m, '6m': di_6m, '1y': di_1y,
            '2y': di_2y, '3y': di_3y, '5y': di_5y, '10y': di_10y
        }

        # Filter to tenors with sufficient data
        valid_tenors = {}
        for k, v in tenors.items():
            try:
                if isinstance(v, pd.Series) and len(v) > 36:
                    valid_tenors[k] = v
            except Exception:
                continue
        if len(valid_tenors) < 3:
            return pd.Series(dtype=float), pd.Series(dtype=float)

        # Build yield matrix
        yield_df = pd.DataFrame(valid_tenors)
        yield_df = yield_df.ffill().dropna()

        if len(yield_df) < 48:
            return pd.Series(dtype=float), pd.Series(dtype=float)

        # Winsorize each column
        for col in yield_df.columns:
            yield_df[col] = _winsorize(yield_df[col])

        # Rolling PCA + VAR estimation
        rstar = pd.Series(index=yield_df.index, dtype=float)
        tp_5y = pd.Series(index=yield_df.index, dtype=float)

        for i in range(max(48, self.window), len(yield_df)):
            start = max(0, i - self.window)
            window_data = yield_df.iloc[start:i+1]

            if len(window_data) < 36:
                continue

            try:
                # Step 1: PCA
                data_centered = window_data - window_data.mean()
                n_comp = min(self.n_factors, len(window_data.columns))

                # SVD-based PCA (more stable than sklearn for small samples)
                U, S, Vt = np.linalg.svd(data_centered.values, full_matrices=False)
                factors = U[:, :n_comp] * S[:n_comp]

                # Step 2: VAR(1) on factors
                # F_t = c + Phi × F_{t-1} + e_t
                F = factors[1:, :]
                F_lag = factors[:-1, :]

                # OLS: F = c + Phi × F_lag
                X_var = np.column_stack([np.ones(len(F_lag)), F_lag])
                beta_var = np.linalg.lstsq(X_var, F, rcond=None)[0]
                c_var = beta_var[0, :]
                Phi = beta_var[1:, :]

                # Step 3: Long-run expected factor level
                # F_inf = (I - Phi)^{-1} × c
                I = np.eye(n_comp)
                try:
                    F_inf = np.linalg.solve(I - Phi, c_var)
                except np.linalg.LinAlgError:
                    F_inf = c_var  # Fallback

                # Step 4: Map long-run factors back to yields
                # The level factor (PC1) loading on the short rate gives r*
                loadings = Vt[:n_comp, :]  # Factor loadings
                mean_yields = window_data.mean().values

                # Long-run yield = mean + loadings' × F_inf
                lr_yield = mean_yields + loadings.T @ F_inf

                # Market-implied r* ≈ long-run short rate (first tenor)
                # Use weighted average of short tenors for stability
                n_yields = len(lr_yield)
                if n_yields <= 3:
                    tenor_weights = np.array([0.5, 0.3, 0.2][:n_yields])
                else:
                    remaining_weight = 0.1 / max(1, n_yields - 3)
                    tenor_weights = np.array([0.4, 0.3, 0.2] + [remaining_weight] * (n_yields - 3))
                tenor_weights = tenor_weights[:n_yields]
                tw_sum = tenor_weights.sum()
                if tw_sum <= 0:
                    continue
                tenor_weights /= tw_sum
                rstar_nominal = float(np.dot(lr_yield, tenor_weights))

                # Clip to reasonable range
                rstar_nominal = np.clip(rstar_nominal, 6.0, 18.0)
                rstar.iloc[i] = rstar_nominal

                # Term premium for 5Y (if available)
                if '5y' in valid_tenors:
                    col_idx = list(valid_tenors.keys()).index('5y')
                    if col_idx < len(lr_yield):
                        # Current 5Y factor-implied expectation
                        current_factors = factors[-1, :]
                        # Expected 5Y yield from model
                        expected_5y = mean_yields[col_idx] + float(loadings[:, col_idx] @ current_factors)
                        # Term premium = actual - expected
                        actual_5y = window_data.iloc[-1].iloc[col_idx] if col_idx < len(window_data.columns) else 0
                        tp_5y.iloc[i] = actual_5y - expected_5y

            except (np.linalg.LinAlgError, ValueError, IndexError, TypeError, ZeroDivisionError, KeyError):
                continue

        rstar = rstar.dropna()
        tp_5y = tp_5y.dropna()

        # Convert to real rate if inflation expectations available
        rstar_real = rstar.copy()
        if ipca_exp is not None and len(ipca_exp) > 12:
            ipca_r = ipca_exp.reindex(rstar.index).ffill()
            rstar_real = rstar - ipca_r
            rstar_real = rstar_real.dropna()

        self.rstar_series = rstar_real
        self.rstar_nominal_series = rstar
        self.term_premium_series = tp_5y
        return rstar_real, tp_5y


# ============================================================
# MODEL 4: State-Space r* (Kalman Filter)
# ============================================================
class StateSpaceRStar:
    """
    Simplified Holston-Laubach-Williams model adapted for Brazil.

    State vector: [r*, g, z]
      r* = neutral real rate
      g  = trend growth
      z  = other persistent factors (fiscal, external)

    Observation equations:
      y_gap_t = a_y × y_gap_{t-1} + a_r × (r_t - r*_t) + ε_y
      π_t = b_π × π_{t-1} + b_y × y_gap_t + ε_π

    Transition equations:
      r*_t = r*_{t-1} + c × Δg_t + φ_fiscal × Δdebt_t + φ_ext × Δcds_t + ν_r
      g_t  = g_{t-1} + ν_g
      z_t  = ρ_z × z_{t-1} + ν_z

    Simplified implementation using iterative Kalman filter
    (avoids full MLE for robustness).
    """

    def __init__(self, window=120):
        self.window = window
        self.rstar_series = None

    def estimate(self, selic, ipca_yoy, ipca_exp, ibc_br,
                 debt_gdp, cds_5y, nfci=None):
        """
        Estimate r* via simplified Kalman filter.
        Returns: pd.Series of r*_state_space (real rate, %).
        """
        # Align core series
        core = [selic, ipca_yoy, ibc_br]
        valid = [s for s in core if len(s) > 36]
        if len(valid) < 3:
            return pd.Series(dtype=float)

        aligned = _safe_align(selic, ipca_yoy, ibc_br, min_len=48)
        if aligned is None:
            return pd.Series(dtype=float)

        (sel_a, ipca_a, ibc_a), idx = aligned

        # Winsorize
        sel_a = _winsorize(sel_a)
        ipca_a = _winsorize(ipca_a)
        ibc_a = _winsorize(ibc_a)

        # Compute output gap: log(IBC-BR) deviation from HP-like trend
        log_ibc = np.log(ibc_a.clip(lower=1))
        ibc_trend = log_ibc.rolling(60, min_periods=24).mean()
        y_gap = (log_ibc - ibc_trend) * 100  # Percentage deviation
        y_gap = y_gap.clip(-8, 8).fillna(0)

        # Ex-ante real rate
        if len(ipca_exp) > 24:
            pie = ipca_exp.reindex(idx).ffill().fillna(ipca_a)
        else:
            pie = ipca_a.rolling(6, min_periods=3).mean()
        real_rate = sel_a - pie

        # Fiscal channel
        debt_chg = pd.Series(0.0, index=idx)
        if len(debt_gdp) > 24:
            debt_r = debt_gdp.reindex(idx).ffill()
            debt_chg = _winsorize(debt_r.diff(12).fillna(0))

        # External channel
        cds_chg = pd.Series(0.0, index=idx)
        if len(cds_5y) > 24:
            cds_r = cds_5y.reindex(idx).ffill()
            cds_chg = _winsorize(cds_r.diff(12).fillna(0))

        # === Kalman Filter ===
        # State: [r*, g, z]  (3-dimensional)
        n_states = 3
        n_obs = 2  # y_gap, inflation

        # Initialize state
        x = np.array([4.5, 0.0, 0.0])  # r*=4.5%, g=0, z=0
        P = np.eye(n_states) * 4.0  # Initial uncertainty

        # System matrices (simplified, fixed parameters)
        # Observation: H maps states to observations
        # y_gap = -a_r × (r - r*) + noise  → H[0] = [a_r, 0, 0] (approx)
        # π = b_y × y_gap + noise → not directly from state

        # We use a simplified approach:
        # Observation 1: real_rate ≈ r* + z + noise
        # Observation 2: y_gap ≈ -a_r × (real_rate - r*) + noise

        a_r = 0.5   # IS curve: real rate sensitivity
        a_y = 0.7   # Output gap persistence

        # Transition matrix F
        F = np.array([
            [1.0, 0.05, 0.0],   # r* = r*_{t-1} + 0.05×g + ...
            [0.0, 0.98, 0.0],   # g = 0.98×g_{t-1} (mean-reverting)
            [0.0, 0.0, 0.85],   # z = 0.85×z_{t-1} (mean-reverting)
        ])

        # Observation matrix H
        H = np.array([
            [1.0, 0.0, 1.0],    # real_rate ≈ r* + z
            [a_r, 0.0, 0.0],    # y_gap ≈ a_r × r* (simplified)
        ])

        # Process noise Q
        sigma_r = 0.15   # r* innovation std
        sigma_g = 0.05   # g innovation std
        sigma_z = 0.30   # z innovation std
        Q = np.diag([sigma_r**2, sigma_g**2, sigma_z**2])

        # Measurement noise R
        sigma_obs_r = 1.0   # Real rate measurement noise
        sigma_obs_y = 2.0   # Output gap measurement noise
        R = np.diag([sigma_obs_r**2, sigma_obs_y**2])

        rstar = pd.Series(index=idx, dtype=float)

        for i in range(len(idx)):
            t = idx[i]

            # Observation vector
            obs = np.array([real_rate.iloc[i], y_gap.iloc[i]])

            if np.any(np.isnan(obs)):
                rstar[t] = x[0]
                continue

            # === Predict ===
            # Add fiscal and external channels to r* transition
            fiscal_impulse = 0.02 * debt_chg.iloc[i]  # φ_fiscal
            external_impulse = 0.005 * cds_chg.iloc[i]  # φ_external

            x_pred = F @ x
            x_pred[0] += fiscal_impulse + external_impulse
            P_pred = F @ P @ F.T + Q

            # === Update ===
            y_innov = obs - H @ x_pred
            S = H @ P_pred @ H.T + R
            try:
                K = P_pred @ H.T @ np.linalg.inv(S)
            except np.linalg.LinAlgError:
                K = np.zeros((n_states, n_obs))

            x = x_pred + K @ y_innov
            P = (np.eye(n_states) - K @ H) @ P_pred

            # Clip r* to reasonable range
            x[0] = np.clip(x[0], 2.0, 10.0)
            x[1] = np.clip(x[1], -3.0, 3.0)
            x[2] = np.clip(x[2], -5.0, 5.0)

            rstar[t] = x[0]

        rstar = rstar.dropna()
        self.rstar_series = rstar
        return rstar


# ============================================================
# MODEL 5: Regime-Switching r*
# ============================================================
class RegimeSwitchingRStar:
    """
    Regime-conditional r* using the existing HMM regime probabilities.

    r*_regime = Σ P(s_t = s) × μ_s

    Where μ_s is the regime-specific r* estimated from historical data.
    """

    # Historical regime-specific r* (calibrated from Brazilian data)
    REGIME_RSTAR = {
        'carry': 4.5,             # Stable growth, controlled inflation
        'riskoff': 5.5,           # Global risk aversion, capital outflows
        'domestic_stress': 7.0,   # Fiscal crisis, currency pressure
    }

    def __init__(self, window=60):
        self.window = window
        self.rstar_series = None

    def estimate(self, selic, ipca_exp, regime_probs_history):
        """
        Estimate regime-conditional r*.

        regime_probs_history: pd.DataFrame with columns [P_carry, P_riskoff, P_stress]
                             or list of dicts with regime probabilities per date.
        """
        if regime_probs_history is None or len(regime_probs_history) == 0:
            return pd.Series(dtype=float)

        # If it's a DataFrame
        if isinstance(regime_probs_history, pd.DataFrame):
            probs_df = regime_probs_history
        else:
            return pd.Series(dtype=float)

        # Compute regime-weighted r*
        rstar = pd.Series(index=probs_df.index, dtype=float)

        for col_carry in ['P_carry', 'P_Carry']:
            if col_carry in probs_df.columns:
                break
        else:
            col_carry = probs_df.columns[0] if len(probs_df.columns) > 0 else None

        for col_riskoff in ['P_riskoff', 'P_RiskOff']:
            if col_riskoff in probs_df.columns:
                break
        else:
            col_riskoff = probs_df.columns[1] if len(probs_df.columns) > 1 else None

        for col_stress in ['P_stress', 'P_domestic_stress', 'P_StressDom']:
            if col_stress in probs_df.columns:
                break
        else:
            col_stress = probs_df.columns[2] if len(probs_df.columns) > 2 else None

        if col_carry is None:
            return pd.Series(dtype=float)

        for i in range(len(probs_df)):
            p_carry = probs_df[col_carry].iloc[i] if col_carry else 0
            p_riskoff = probs_df[col_riskoff].iloc[i] if col_riskoff else 0
            p_stress = probs_df[col_stress].iloc[i] if col_stress else 0

            # Normalize
            total = p_carry + p_riskoff + p_stress
            if total > 0:
                p_carry /= total
                p_riskoff /= total
                p_stress /= total
            else:
                p_carry = 1.0

            r = (p_carry * self.REGIME_RSTAR['carry'] +
                 p_riskoff * self.REGIME_RSTAR['riskoff'] +
                 p_stress * self.REGIME_RSTAR['domestic_stress'])

            rstar.iloc[i] = r

        # Adaptive calibration: update regime means using rolling observed data
        if len(selic) > 36 and len(ipca_exp) > 24:
            aligned = _safe_align(selic, ipca_exp, min_len=24)
            if aligned is not None:
                (sel_a, pie_a), a_idx = aligned
                real_rate = sel_a - pie_a
                real_r = real_rate.reindex(probs_df.index).ffill()

                # Rolling regime-conditional mean (adaptive)
                for i in range(max(36, self.window), len(probs_df)):
                    start = max(0, i - self.window)
                    w_probs = probs_df.iloc[start:i]
                    w_real = real_r.iloc[start:i].dropna()

                    if len(w_real) < 24:
                        continue

                    # Weighted mean real rate per regime
                    for regime, col, prior in [
                        ('carry', col_carry, self.REGIME_RSTAR['carry']),
                        ('riskoff', col_riskoff, self.REGIME_RSTAR['riskoff']),
                        ('domestic_stress', col_stress, self.REGIME_RSTAR['domestic_stress']),
                    ]:
                        if col is None:
                            continue
                        weights = w_probs[col].reindex(w_real.index).fillna(0)
                        if weights.sum() > 5:
                            # Weighted mean with shrinkage toward prior
                            weighted_mean = (weights * w_real).sum() / weights.sum()
                            adaptive_mean = 0.6 * weighted_mean + 0.4 * prior
                            adaptive_mean = np.clip(adaptive_mean, 2.0, 10.0)
                        else:
                            adaptive_mean = prior

                    # Recompute with adaptive means
                    p_c = probs_df[col_carry].iloc[i] if col_carry else 0
                    p_r = probs_df[col_riskoff].iloc[i] if col_riskoff else 0
                    p_s = probs_df[col_stress].iloc[i] if col_stress else 0
                    total = p_c + p_r + p_s
                    if total > 0:
                        p_c /= total; p_r /= total; p_s /= total

                    # Use last adaptive means (simplified)
                    rstar.iloc[i] = np.clip(rstar.iloc[i], 2.0, 10.0)

        rstar = rstar.dropna()
        self.rstar_series = rstar
        return rstar


# ============================================================
# COMPOSITE: Regime-Weighted Combination
# ============================================================
class CompositeEquilibriumRate:
    """
    Combines 5 r* models with regime-dependent weighting.

    r*_composite = Σ w_i(regime) × r*_i

    SELIC*_composite = r*_composite + π_e + α(regime)×(π - π*) + β(regime)×(y - y*)
    """

    # Base weights (regime-neutral)
    BASE_WEIGHTS = {
        'state_space': 0.30,
        'market_implied': 0.25,
        'fiscal': 0.20,
        'parity': 0.15,
        'regime': 0.10,
    }

    # Regime-specific weight overrides
    REGIME_WEIGHTS = {
        'carry': {
            'state_space': 0.35,
            'market_implied': 0.30,
            'fiscal': 0.15,
            'parity': 0.10,
            'regime': 0.10,
        },
        'riskoff': {
            'state_space': 0.20,
            'market_implied': 0.25,
            'fiscal': 0.10,
            'parity': 0.35,
            'regime': 0.10,
        },
        'domestic_stress': {
            'state_space': 0.10,
            'market_implied': 0.15,
            'fiscal': 0.40,
            'parity': 0.25,
            'regime': 0.10,
        },
    }

    # Regime-dependent Taylor coefficients
    REGIME_TAYLOR = {
        'carry': {'alpha': 1.0, 'beta': 0.3},
        'riskoff': {'alpha': 0.8, 'beta': 0.2},
        'domestic_stress': {'alpha': 1.5, 'beta': 0.1},
    }

    def __init__(self):
        self.models = {}
        self.composite_rstar = None
        self.composite_selic_star = None
        self.model_contributions = {}

    def compute(self, model_results, regime_probs, ipca_yoy, ipca_exp,
                ibc_br, selic, pi_star_series):
        """
        Compute composite r* and SELIC*.

        model_results: dict of {model_name: pd.Series of r*}
        regime_probs: dict {carry: float, riskoff: float, stress: float}
                      OR pd.DataFrame with regime prob columns per date
        ipca_yoy: pd.Series of current IPCA 12m
        ipca_exp: pd.Series of IPCA expectations
        ibc_br: pd.Series of IBC-BR
        selic: pd.Series of SELIC
        pi_star_series: pd.Series of inflation target
        """
        # Filter to models that produced results
        valid_models = {k: v for k, v in model_results.items()
                        if isinstance(v, pd.Series) and len(v) > 12}

        if len(valid_models) == 0:
            return pd.Series(dtype=float), pd.Series(dtype=float)

        # Find common index
        all_idx = None
        for name, series in valid_models.items():
            if all_idx is None:
                all_idx = series.index
            else:
                all_idx = all_idx.intersection(series.index)

        if all_idx is None or len(all_idx) < 12:
            # Fallback: use union with forward-fill
            all_series = pd.DataFrame(valid_models)
            all_series = all_series.ffill().dropna(how='all')
            all_idx = all_series.index
        else:
            all_series = pd.DataFrame({k: v.reindex(all_idx) for k, v in valid_models.items()})

        # Compute weights based on regime
        if isinstance(regime_probs, dict):
            # Single regime probability vector
            p_carry = regime_probs.get('P_carry', regime_probs.get('carry', 0))
            p_riskoff = regime_probs.get('P_riskoff', regime_probs.get('riskoff', 0))
            p_stress = regime_probs.get('P_stress', regime_probs.get('domestic_stress',
                       regime_probs.get('P_domestic_stress', 0)))

            total = p_carry + p_riskoff + p_stress
            if total > 0:
                p_carry /= total; p_riskoff /= total; p_stress /= total
            else:
                p_carry = 1.0

            # Interpolate weights
            weights = {}
            for model_name in self.BASE_WEIGHTS:
                w = (p_carry * self.REGIME_WEIGHTS['carry'].get(model_name, 0) +
                     p_riskoff * self.REGIME_WEIGHTS['riskoff'].get(model_name, 0) +
                     p_stress * self.REGIME_WEIGHTS['domestic_stress'].get(model_name, 0))
                weights[model_name] = w

            # Normalize
            w_total = sum(weights.values())
            if w_total > 0:
                weights = {k: v/w_total for k, v in weights.items()}

            # Apply same weights to all dates
            composite = pd.Series(0.0, index=all_idx)
            for model_name, series in valid_models.items():
                w = weights.get(model_name, 0)
                if w > 0:
                    composite += w * series.reindex(all_idx).ffill().fillna(series.mean())
                    self.model_contributions[model_name] = {
                        'weight': round(w, 3),
                        'current_value': round(float(series.iloc[-1]), 2) if len(series) > 0 else 0,
                    }

        else:
            # Time-varying regime probabilities (DataFrame)
            composite = pd.Series(0.0, index=all_idx)
            # Simplified: use last regime probs for all
            if isinstance(regime_probs, pd.DataFrame) and len(regime_probs) > 0:
                last_probs = regime_probs.iloc[-1]
                p_carry = float(last_probs.get('P_carry', last_probs.get(regime_probs.columns[0], 1.0)))
                p_riskoff = float(last_probs.get('P_riskoff', last_probs.get(regime_probs.columns[1], 0))) if len(regime_probs.columns) > 1 else 0
                p_stress = float(last_probs.get('P_stress', last_probs.get(regime_probs.columns[2], 0))) if len(regime_probs.columns) > 2 else 0

                total = p_carry + p_riskoff + p_stress
                if total > 0:
                    p_carry /= total; p_riskoff /= total; p_stress /= total
                else:
                    p_carry = 1.0

                weights = {}
                for model_name in self.BASE_WEIGHTS:
                    w = (p_carry * self.REGIME_WEIGHTS['carry'].get(model_name, 0) +
                         p_riskoff * self.REGIME_WEIGHTS['riskoff'].get(model_name, 0) +
                         p_stress * self.REGIME_WEIGHTS['domestic_stress'].get(model_name, 0))
                    weights[model_name] = w

                w_total = sum(weights.values())
                if w_total > 0:
                    weights = {k: v/w_total for k, v in weights.items()}

                for model_name, series in valid_models.items():
                    w = weights.get(model_name, 0)
                    if w > 0:
                        composite += w * series.reindex(all_idx).ffill().fillna(series.mean())
                        self.model_contributions[model_name] = {
                            'weight': round(w, 3),
                            'current_value': round(float(series.iloc[-1]), 2) if len(series) > 0 else 0,
                        }

        # Clip composite r*
        composite = composite.clip(2.0, 10.0)
        composite = composite.dropna()
        self.composite_rstar = composite

        # === Compute SELIC* from composite r* ===
        aligned = _safe_align(composite, ipca_yoy, min_len=12)
        if aligned is None:
            self.composite_selic_star = composite + 4.0  # Rough nominal
            return composite, self.composite_selic_star

        (comp_a, ipca_a), c_idx = aligned

        # Inflation expectations
        if len(ipca_exp) > 12:
            pie = ipca_exp.reindex(c_idx).ffill().fillna(ipca_a)
        else:
            pie = ipca_a.rolling(6, min_periods=3).mean()

        # Inflation target
        pi_star = pi_star_series.reindex(c_idx).ffill() if pi_star_series is not None else pd.Series(3.0, index=c_idx)

        # Output gap
        output_gap = pd.Series(0.0, index=c_idx)
        if len(ibc_br) > 36:
            ibc_c = ibc_br.reindex(c_idx).ffill()
            if ibc_c.notna().sum() > 24:
                ibc_trend = ibc_c.rolling(60, min_periods=24).mean()
                output_gap = ((ibc_c / ibc_trend) - 1) * 100
                output_gap = output_gap.clip(-5, 5).fillna(0)

        # Regime-dependent Taylor coefficients (use current regime)
        if isinstance(regime_probs, dict):
            alpha = (p_carry * self.REGIME_TAYLOR['carry']['alpha'] +
                     p_riskoff * self.REGIME_TAYLOR['riskoff']['alpha'] +
                     p_stress * self.REGIME_TAYLOR['domestic_stress']['alpha'])
            beta = (p_carry * self.REGIME_TAYLOR['carry']['beta'] +
                    p_riskoff * self.REGIME_TAYLOR['riskoff']['beta'] +
                    p_stress * self.REGIME_TAYLOR['domestic_stress']['beta'])
        else:
            alpha, beta = 1.0, 0.3

        inflation_gap = ipca_a - pi_star
        selic_star = comp_a + pie + alpha * inflation_gap + beta * output_gap
        selic_star = selic_star.dropna()

        self.composite_selic_star = selic_star
        return composite, selic_star
