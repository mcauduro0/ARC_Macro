import { useMemo } from 'react';
import { trpc } from '@/lib/trpc';
import { dashboardData, timeseriesData, regimeData, cyclicalData, stateVariablesData, scoreData, rstarTsData, backtestData, shapImportanceData, shapHistoryData, featureSelectionData, featureSelectionTemporalData } from '@/data/modelData';

// ============================================================
// ARC MACRO - Cross-Asset Dashboard Types
// ============================================================

/** Position sizing for a single asset class */
export interface AssetPosition {
  weight: number;
  expected_return_3m: number;
  expected_return_6m: number;
  sharpe: number;
  annualized_vol: number;
  risk_unit: number;
  risk_contribution: number;
  direction: string;
}

/** Model regression details for an asset class */
export interface ModelDetail {
  r_squared: number;
  coefficients: Record<string, number>;
  p_values: Record<string, number>;
  n_obs: number;
}

/** Stress test result */
/** Legacy stress test format (v1) */
export interface StressTestLegacy {
  name: string;
  return_pct: number;
  max_dd_pct: number;
  per_asset?: Record<string, number>;
}

/** v2.3 Stress test scenario result */
export interface StressTestV23 {
  name: string;
  category: string;
  description: string;
  period: string;
  n_months: number;
  overlay_return: number;
  total_return: number;
  max_dd_overlay: number;
  annualized_vol: number;
  mean_monthly_return: number;
  worst_month: { date: string; return_pct: number };
  best_month: { date: string; return_pct: number };
  avg_weights: Record<string, number>;
  avg_regime: Record<string, number>;
  attribution: Record<string, number>;
  win_rate: number;
}

export type StressTest = StressTestLegacy;

/** Model contribution in the composite r* */
export interface ModelContribution {
  weight: number;
  current_value: number;
}

/** Composite equilibrium rate breakdown */
export interface EquilibriumData {
  composite_rstar: number | null;
  selic_star: number | null;
  method: string;
  model_contributions: Record<string, ModelContribution>;
  rstar_fiscal?: number;
  rstar_parity?: number;
  rstar_market_implied?: number;
  rstar_state_space?: number;
  rstar_regime?: number;
  fiscal_decomposition?: {
    base: number;
    fiscal: number;
    sovereign: number;
  };
  acm_term_premium_5y?: number;
  regime_weights?: Record<string, Record<string, number>>;
}

/** Full ARC Macro Dashboard */
export interface MacroDashboard {
  // Core
  run_date: string;
  current_spot: number;
  direction: string;
  score_total: number;
  
  // Regime
  current_regime: string;
  regime_probabilities: {
    P_Carry: number;
    P_RiskOff: number;
    P_StressDom: number;
  };
  
  // State Variables (X1-X7 Z-scores)
  state_variables: Record<string, number>;
  
  // FX
  fx_fair_value: number;
  fx_misalignment: number;
  ppp_fair: number;
  ppp_bs_fair: number;
  beer_fair: number;
  feer_fair: number;
  
  // Rates
  front_fair: number;
  belly_fair: number;
  long_fair: number;
  taylor_gap: number;
  term_premium: number;
  selic_target: number;
  di_1y: number;
  di_2y: number;
  di_5y: number;
  di_10y: number;
  ntnb_5y: number | null;
  ntnb_10y: number | null;
  ust_2y: number;
  ust_10y: number;
  
  // Equilibrium
  equilibrium?: EquilibriumData;
  selic_star?: number;

  // Credit
  embi_spread: number;
  cupom_360d?: number;
  cupom_30d?: number;
  cupom_cambial_360d?: number;
  cupom_cambial_chg_1m?: number;
  cupom_cambial_chg_3m?: number;
  cip_basis?: number;
  ntnb_5y_yield?: number;
  ntnb_10y_yield?: number;
  ipca_expectations?: number;
  vix: number;
  dxy: number;
  
  // Positions (cross-asset)
  positions: {
    fx: AssetPosition;
    front: AssetPosition;
    belly: AssetPosition;
    long: AssetPosition;
    hard: AssetPosition;
    ntnb: AssetPosition;
  };
  
  // Model details
  model_details: Record<string, ModelDetail>;
  
  // Risk metrics
  risk_metrics: {
    portfolio_vol: number;
    correlation_matrix: Record<string, Record<string, number>>;
    stress_tests: StressTest[];
    max_drawdown: number;
    current_drawdown?: number;
    max_drawdown_historical?: number;
  };
  
  // v2.2 Backtest-derived overlay metrics (preferred over legacy risk_metrics)
  overlay_metrics?: {
    total_return: number;
    annualized_return: number;
    annualized_vol: number;
    sharpe: number;
    max_drawdown: number;
    calmar: number;
    win_rate: number;
  };
  total_metrics?: {
    total_return: number;
    annualized_return: number;
    annualized_vol: number;
    sharpe: number;
    max_drawdown: number;
  };
  ic_per_instrument?: Record<string, number>;
  hit_rates?: Record<string, number>;
  attribution?: Record<string, number>;
  total_tc_pct?: number;
  avg_monthly_turnover?: number;

  // v2.3 Stress test scenarios (dict keyed by scenario ID)
  stress_tests?: Record<string, StressTestV23>;

  // Legacy FX-only fields (backward compat)
  ppp_abs_fair_value?: number;
  ppp_rel_fair_value?: number;
  ppp_abs_misalignment_pct?: number;
  ppp_rel_misalignment_pct?: number;
  z_ppp?: number;
  beer_fair_value?: number;
  beer_misalignment_pct?: number;
  z_beer?: number;
  z_cycle?: number;
  cyclical_weights?: Record<string, number>;
  dominant_regime?: string;
  regime_probs?: Record<string, number>;
  lambda_structural?: number;
  score_structural?: number;
  interpretation?: string;
  expected_return_3m_pct?: number;
  expected_return_6m_pct?: number;
  current_vol_ann_pct?: number;
  recommended_position_3m?: number;
  recommended_position_6m?: number;
  regime_model?: Record<string, unknown>;
  beer_regression?: Record<string, unknown>;
  return_regression_6m?: Record<string, unknown>;
  return_regression_3m?: Record<string, unknown>;

  // v4.4 Feature selection results (Elastic Net + Boruta + Stability)
  feature_selection?: Record<string, {
    instrument?: string;
    total_features: number;
    lasso: {
      n_selected: number;
      alpha: number;
      l1_ratio?: number;
      method?: string;
      selected: string[];
      rejected?: string[];
      coefficients: Record<string, number>;
      path?: {
        alphas: number[];
        coefficients: Record<string, number[]>;
        selected_alpha: number;
        n_alphas: number;
      };
    };
    boruta: {
      n_confirmed: number;
      n_tentative: number;
      n_rejected: number;
      confirmed: string[];
      tentative: string[];
      rejected: string[];
      n_iterations: number;
    };
    interactions?: {
      tested: string[];
      confirmed: string[];
      rejected: string[];
      n_tested: number;
      n_confirmed: number;
    };
    stability?: {
      n_subsamples: number;
      subsample_ratio: number;
      enet_frequency?: Record<string, number>;
      lasso_frequency?: Record<string, number>;
      boruta_frequency?: Record<string, number>;
      composite_score?: Record<string, number>;
      combined_frequency?: Record<string, number>;
      classification: Record<string, string>;
      thresholds?: { robust: number; moderate: number };
    };
    alerts?: Array<{
      type: 'critical' | 'warning' | 'info';
      feature: string;
      instrument: string;
      message: string;
      previous?: string;
      current?: string;
      transition?: string;
    }>;
    feature_status?: Record<string, {
      enet: boolean;
      boruta: string;
      stability: string;
      composite_score: number;
      final: boolean;
    }>;
    final: {
      n_features: number;
      features: string[];
      reduction_pct: number;
      method: string;
    };
  }>;
  // v4.3 Temporal feature selection comparison
  feature_selection_temporal?: {
    changes: Array<{
      instrument: string;
      feature: string;
      change_type: string;
      from_status: string;
      to_status: string;
    }>;
    summary: Record<string, {
      total_features_tracked: number;
      features_gained: string[];
      features_lost: string[];
      features_stable: string[];
      structural_shift_score: number;
    }>;
    run_date: string;
    previous_date: string;
  };
}

export interface TimeSeriesPoint {
  date: string;
  spot: number | null;
  ppp_abs: number | null;
  ppp_rel: number | null;
  fx_beer: number | null;
  mis_ppp_abs: number | null;
  mis_beer: number | null;
  z_ppp: number | null;
  z_beer: number | null;
  z_cycle: number | null;
  score_struct: number | null;
  score_total: number | null;
}

export interface RegimePoint {
  date: string;
  P_Carry: number | null;
  P_RiskOff: number | null;
  P_StressDom?: number | null;
}

export interface CyclicalPoint {
  date: string;
  // Raw macro factors (from _build_cyclical_timeseries)
  DXY?: number | null;
  VIX?: number | null;
  EMBI?: number | null;
  SELIC?: number | null;
  DI_1Y?: number | null;
  DI_5Y?: number | null;
  IPCA_Exp?: number | null;
  CDS_5Y?: number | null;
  // Legacy Z-scored factors (backward compat)
  Z_DXY?: number | null;
  Z_COMMODITIES?: number | null;
  Z_EMBI?: number | null;
  Z_RIR?: number | null;
  Z_FLOW?: number | null;
}

export interface StateVarPoint {
  date: string;
  X1_diferencial_real: number | null;
  X2_surpresa_inflacao: number | null;
  X3_fiscal_risk: number | null;
  X4_termos_de_troca: number | null;
  X5_dolar_global: number | null;
  X6_risk_global: number | null;
  X7_hiato: number | null;
}

export interface ScorePoint {
  date: string;
  score_total: number | null;
  score_structural: number | null;
  score_cyclical: number | null;
  score_regime: number | null;
}

/** r* Equilibrium time series point */
export interface RstarTsPoint {
  date: string;
  composite_rstar: number | null;
  selic_star: number | null;
  selic_actual: number | null;
  rstar_fiscal: number | null;
  rstar_parity: number | null;
  rstar_market_implied: number | null;
  rstar_state_space: number | null;
  acm_term_premium: number | null;
}

export interface BacktestPoint {
  date: string;
  // v2 overlay-on-CDI
  equity_overlay: number;
  equity_total: number;
  overlay_return: number;
  cash_return: number;
  total_return: number;
  drawdown_overlay: number;
  drawdown_total: number;
  // PnL attribution (5 instruments)
  fx_pnl: number;
  front_pnl: number;
  belly_pnl: number;
  long_pnl: number;
  hard_pnl: number;
  ntnb_pnl?: number;
  // Weights
  weight_fx: number;
  weight_front: number;
  weight_belly: number;
  weight_long: number;
  weight_hard: number;
  weight_ntnb?: number;
  // Mu predictions
  mu_fx: number;
  mu_front: number;
  mu_belly: number;
  mu_long: number;
  mu_hard: number;
  mu_ntnb?: number;
  // Regime
  P_carry: number;
  P_riskoff: number;
  P_stress: number;
  // Costs
  tc_pct: number;
  turnover: number;
  // Score
  score_total: number;
  // Legacy compat
  equity?: number;
  drawdown?: number;
  monthly_return?: number;
  cdi_equity?: number;
  usdbrl_equity?: number;
}

export interface BacktestSummary {
  // v2 overlay-on-CDI
  period?: string;
  n_months?: number;
  overlay?: {
    total_return: number;
    annualized_return: number;
    annualized_vol: number;
    sharpe: number;
    max_drawdown: number;
    calmar: number;
    win_rate: number;
  };
  total?: {
    total_return: number;
    annualized_return: number;
    annualized_vol: number;
    sharpe: number;
    max_drawdown: number;
    calmar: number;
    win_rate: number;
  };
  ic_per_instrument?: Record<string, number>;
  hit_rates?: Record<string, number>;
  attribution_pct?: Record<string, number>;
  total_tc_pct?: number;
  avg_monthly_turnover?: number;
  best_month?: { date: string; return_pct: number };
  worst_month?: { date: string; return_pct: number };
  // v2.1 Ensemble & Score Demeaning
  ensemble?: {
    avg_w_ridge: number;
    avg_w_gbm: number;
    avg_w_rf?: number;
    avg_w_xgb?: number;
    final_w_ridge: number;
    final_w_gbm: number;
    final_w_rf?: number;
    final_w_xgb?: number;
  };
  score_demeaning?: {
    raw_score_mean: number;
    raw_score_std: number;
    demeaned_score_mean: number;
    demeaned_score_std: number;
  };
  // Legacy compat
  total_return?: number;
  annualized_return?: number;
  annualized_vol?: number;
  sharpe_ratio?: number;
  max_drawdown?: number;
  win_rate?: number;
  total_months?: number;
  start_date?: string;
  end_date?: string;
  cdi_total_return?: number;
  usdbrl_bh_total_return?: number;
}

export interface BacktestData {
  timeseries: BacktestPoint[];
  summary: BacktestSummary;
}

/**
 * Detect if dashboard data is from the new ARC Macro or legacy FX-only model
 */
function isMacroRiskOS(d: Record<string, unknown>): boolean {
  return 'positions' in d && 'risk_metrics' in d;
}

export function useModelData() {
  const { data: apiData, isLoading, error: queryError } = trpc.model.latest.useQuery(undefined, {
    refetchInterval: 5 * 60 * 1000,
    staleTime: 2 * 60 * 1000,
    retry: 2,
  });

  const result = useMemo(() => {
    if (apiData?.source === 'database' && apiData.dashboard) {
      // Merge DB dashboard with embedded feature_selection if DB doesn't have it
      const dbDashboard = apiData.dashboard as Record<string, unknown>;
      const mergedDashboard = {
        ...dbDashboard,
        // v4.3: Use DB feature_selection if available, otherwise fall back to embedded
        feature_selection: dbDashboard.feature_selection || (featureSelectionData as unknown) || null,
      } as unknown as MacroDashboard;

      return {
        dashboard: mergedDashboard,
        timeseries: (apiData.timeseries || []) as unknown as TimeSeriesPoint[],
        regimeProbs: (apiData.regime || []) as unknown as RegimePoint[],
        cyclicalFactors: (apiData.cyclical || []) as unknown as CyclicalPoint[],
        stateVariables: (apiData.stateVariables || []) as unknown as StateVarPoint[],
        score: (apiData.score || []) as unknown as ScorePoint[],
        rstarTs: (((apiData.dashboard as any)?.rstar_ts?.length > 0 ? (apiData.dashboard as any).rstar_ts : rstarTsData) || []) as unknown as RstarTsPoint[],
        backtest: (apiData.backtest || null) as unknown as BacktestData | null,
        shapImportance: (apiData.shapImportance || null) as Record<string, Record<string, { mean_abs: number; current: number; rank: number }>> | null,
        shapHistory: (apiData.shapHistory || null) as Array<{ date: string; instrument: string; feature: string; importance: number }> | null,
        isMacroRiskOS: isMacroRiskOS(apiData.dashboard as Record<string, unknown>),
        loading: false,
        error: null as string | null,
        source: 'live' as const,
        lastUpdated: apiData.updatedAt ? new Date(apiData.updatedAt) : null,
      };
    }

    // Fallback to embedded data (v4.0 with equilibrium features)
    return {
      dashboard: dashboardData as unknown as MacroDashboard,
      timeseries: timeseriesData as unknown as TimeSeriesPoint[],
      regimeProbs: regimeData as unknown as RegimePoint[],
      cyclicalFactors: cyclicalData as unknown as CyclicalPoint[],
      stateVariables: (stateVariablesData || []) as unknown as StateVarPoint[],
      score: (scoreData || []) as unknown as ScorePoint[],
      rstarTs: (rstarTsData || []) as unknown as RstarTsPoint[],
      backtest: (backtestData || null) as unknown as BacktestData | null,
      shapImportance: (shapImportanceData || null) as unknown as Record<string, Record<string, { mean_abs: number; current: number; rank: number }>> | null,
      shapHistory: (shapHistoryData || null) as unknown as Array<{ date: string; instrument: string; feature: string; importance: number }> | null,
      feature_selection: (featureSelectionData || null) as unknown as MacroDashboard['feature_selection'],
      feature_selection_temporal: (featureSelectionTemporalData || null) as unknown as MacroDashboard['feature_selection_temporal'],
      isMacroRiskOS: false,
      loading: false,
      error: null as string | null,
      source: 'embedded' as const,
      lastUpdated: null,
    };
  }, [apiData]);

  return {
    ...result,
    loading: isLoading,
    error: queryError ? queryError.message : result.error,
  };
}

/**
 * Hook to get model run status
 */
export function useModelStatus() {
  return trpc.model.status.useQuery(undefined, {
    refetchInterval: 10_000,
  });
}

/**
 * Hook to get model run history
 */
export function useModelHistory() {
  return trpc.model.history.useQuery();
}

/**
 * Hook to trigger a new model run
 */
export function useRunModel() {
  const utils = trpc.useUtils();
  return trpc.model.run.useMutation({
    onSuccess: () => {
      utils.model.invalidate();
    },
  });
}

// ============================================================
// Pipeline Hooks
// ============================================================

/**
 * Hook to get current pipeline execution status (polls every 3s when running)
 */
export function usePipelineStatus() {
  const query = trpc.pipeline.status.useQuery(undefined, {
    refetchInterval: (data) => {
      // Poll fast when pipeline is running, slow otherwise
      return data?.state?.data?.isRunning ? 3000 : 30000;
    },
  });
  return query;
}

/**
 * Hook to get the latest pipeline run
 */
export function useLatestPipelineRun() {
  return trpc.pipeline.latest.useQuery();
}

/**
 * Hook to get pipeline run history
 */
export function usePipelineHistory() {
  return trpc.pipeline.history.useQuery();
}

/**
 * Hook to trigger a full pipeline run
 */
export function useTriggerPipeline() {
  const utils = trpc.useUtils();
  return trpc.pipeline.trigger.useMutation({
    onSuccess: () => {
      utils.pipeline.invalidate();
      utils.model.invalidate();
    },
  });
}

// ============================================================
// DATA SOURCE HEALTH HOOKS
// ============================================================

/**
 * Hook to get the latest data source health status (from DB, fast).
 */
export function useDataSourceHealth() {
  return trpc.dataHealth.status.useQuery(undefined, {
    refetchInterval: 60000, // Refresh every 60s
  });
}

/**
 * Hook to trigger a live health check on all data sources.
 */
export function useCheckDataSources() {
  const utils = trpc.useUtils();
  return trpc.dataHealth.check.useMutation({
    onSuccess: () => {
      utils.dataHealth.invalidate();
    },
  });
}
