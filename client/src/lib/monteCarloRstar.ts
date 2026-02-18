/**
 * Monte Carlo Simulation Engine for r* What-If Scenarios
 *
 * Varies the 5 fiscal variables simultaneously using correlated random draws,
 * recalculates r* for each simulation, and returns the probability distribution.
 */

// ============================================================
// Correlation Matrix for Fiscal Variables
// ============================================================
// debt_gdp, primary_balance, cds_5y, embi, ipca_exp
// Based on historical Brazilian macro correlations
const CORR_MATRIX = [
  [1.00, -0.65,  0.70,  0.72,  0.45], // debt_gdp
  [-0.65,  1.00, -0.55, -0.50, -0.30], // primary_balance
  [0.70, -0.55,  1.00,  0.85,  0.40],  // cds_5y
  [0.72, -0.50,  0.85,  1.00,  0.35],  // embi
  [0.45, -0.30,  0.40,  0.35,  1.00],  // ipca_exp
];

// Variable volatilities (1-year standard deviations)
const VOLATILITIES: Record<string, number> = {
  debt_gdp: 5.0,        // 5pp std dev
  primary_balance: 1.2,  // 1.2pp std dev
  cds_5y: 60,           // 60bps std dev
  embi: 70,             // 70bps std dev
  ipca_exp: 1.5,        // 1.5pp std dev
};

const VAR_KEYS = ['debt_gdp', 'primary_balance', 'cds_5y', 'embi', 'ipca_exp'];

// ============================================================
// Cholesky Decomposition (for correlated random draws)
// ============================================================
function choleskyDecomposition(matrix: number[][]): number[][] {
  const n = matrix.length;
  const L: number[][] = Array.from({ length: n }, () => Array(n).fill(0));

  for (let i = 0; i < n; i++) {
    for (let j = 0; j <= i; j++) {
      let sum = 0;
      for (let k = 0; k < j; k++) {
        sum += L[i][k] * L[j][k];
      }
      if (i === j) {
        L[i][j] = Math.sqrt(Math.max(0, matrix[i][i] - sum));
      } else {
        L[i][j] = (matrix[i][j] - sum) / (L[j][j] || 1e-10);
      }
    }
  }
  return L;
}

// ============================================================
// Box-Muller Transform (standard normal random)
// ============================================================
function randn(): number {
  let u1 = 0, u2 = 0;
  while (u1 === 0) u1 = Math.random();
  while (u2 === 0) u2 = Math.random();
  return Math.sqrt(-2.0 * Math.log(u1)) * Math.cos(2.0 * Math.PI * u2);
}

// ============================================================
// Generate Correlated Random Variables
// ============================================================
function generateCorrelatedShocks(L: number[][], n: number): number[][] {
  const dim = L.length;
  const results: number[][] = [];

  for (let i = 0; i < n; i++) {
    const z = Array.from({ length: dim }, () => randn());
    const correlated = Array(dim).fill(0);
    for (let j = 0; j < dim; j++) {
      for (let k = 0; k <= j; k++) {
        correlated[j] += L[j][k] * z[k];
      }
    }
    results.push(correlated);
  }
  return results;
}

// ============================================================
// r* Recalculation (same as WhatIfPanel)
// ============================================================
function recalcFiscalRstar(vars: Record<string, number>): number {
  const base = 4.0;
  const debtPremium = Math.max(0, (vars.debt_gdp - 60) * 0.08);
  const fiscalPremium = Math.max(0, -vars.primary_balance * 0.50);
  const cdsPremium = (vars.cds_5y / 100) * 0.35;
  return base + debtPremium * 0.4 + fiscalPremium * 0.3 + cdsPremium * 0.3;
}

function recalcCompositeRstar(
  currentComposite: number,
  currentFiscalRstar: number,
  newFiscalRstar: number,
  fiscalWeight: number
): number {
  const fiscalDelta = (newFiscalRstar - currentFiscalRstar) * fiscalWeight;
  return currentComposite + fiscalDelta;
}

// ============================================================
// Monte Carlo Simulation
// ============================================================
export interface MonteCarloParams {
  /** Number of simulations */
  numSims: number;
  /** Current variable values (center of distribution) */
  centerValues: Record<string, number>;
  /** Variable bounds */
  bounds: Record<string, { min: number; max: number }>;
  /** Current composite r* from the model */
  currentComposite: number;
  /** Current fiscal r* from the model */
  currentFiscalRstar: number;
  /** Fiscal model weight in the composite */
  fiscalWeight: number;
  /** Current IPCA expectation (for SELIC* calc) */
  ipcaExp: number;
  /** ACM term premium */
  termPremium: number;
}

export interface MonteCarloResult {
  /** Number of simulations run */
  simulations: number;
  /** Mean r* across simulations */
  mean: number;
  /** Median r* */
  median: number;
  /** Standard deviation */
  std: number;
  /** Percentiles */
  p5: number;
  p10: number;
  p25: number;
  p75: number;
  p90: number;
  p95: number;
  /** Probability of r* > 6% (restrictive) */
  probAbove6: number;
  /** Probability of r* < 3% (accommodative) */
  probBelow3: number;
  /** Mean SELIC* */
  meanSelicStar: number;
  /** Histogram bins for visualization */
  histogram: Array<{ binStart: number; binEnd: number; count: number; frequency: number }>;
  /** Raw simulation results (for detailed analysis) */
  rawResults: number[];
}

export function runMonteCarloSimulation(params: MonteCarloParams): MonteCarloResult {
  const { numSims, centerValues, bounds, currentComposite, currentFiscalRstar, fiscalWeight, ipcaExp, termPremium } = params;

  // Cholesky decomposition of correlation matrix
  const L = choleskyDecomposition(CORR_MATRIX);

  // Generate correlated shocks
  const shocks = generateCorrelatedShocks(L, numSims);

  // Run simulations
  const rstarResults: number[] = [];
  const selicStarResults: number[] = [];

  for (let i = 0; i < numSims; i++) {
    // Apply shocks to variables
    const simVars: Record<string, number> = {};
    VAR_KEYS.forEach((key, j) => {
      const vol = VOLATILITIES[key];
      let value = centerValues[key] + shocks[i][j] * vol;
      // Clamp to bounds
      value = Math.max(bounds[key]?.min ?? -Infinity, Math.min(bounds[key]?.max ?? Infinity, value));
      simVars[key] = value;
    });

    // Recalculate r*
    const newFiscalRstar = recalcFiscalRstar(simVars);
    const newComposite = recalcCompositeRstar(currentComposite, currentFiscalRstar, newFiscalRstar, fiscalWeight);

    // SELIC* = r* + IPCA + term premium (use simulated IPCA)
    const simIpca = simVars.ipca_exp;
    const newSelicStar = newComposite + simIpca + termPremium;

    rstarResults.push(newComposite);
    selicStarResults.push(newSelicStar);
  }

  // Sort for percentile calculation
  const sorted = [...rstarResults].sort((a, b) => a - b);
  const n = sorted.length;

  const percentile = (p: number) => {
    const idx = Math.floor(p * n);
    return sorted[Math.min(idx, n - 1)];
  };

  // Statistics
  const mean = rstarResults.reduce((s, v) => s + v, 0) / n;
  const median = percentile(0.5);
  const variance = rstarResults.reduce((s, v) => s + (v - mean) ** 2, 0) / n;
  const std = Math.sqrt(variance);

  const meanSelicStar = selicStarResults.reduce((s, v) => s + v, 0) / n;

  // Probabilities
  const probAbove6 = rstarResults.filter(r => r > 6).length / n;
  const probBelow3 = rstarResults.filter(r => r < 3).length / n;

  // Histogram (20 bins)
  const minR = sorted[0];
  const maxR = sorted[n - 1];
  const binWidth = (maxR - minR) / 20 || 0.1;
  const histogram: MonteCarloResult['histogram'] = [];

  for (let b = 0; b < 20; b++) {
    const binStart = minR + b * binWidth;
    const binEnd = binStart + binWidth;
    const count = rstarResults.filter(r => r >= binStart && (b === 19 ? r <= binEnd : r < binEnd)).length;
    histogram.push({
      binStart: Math.round(binStart * 100) / 100,
      binEnd: Math.round(binEnd * 100) / 100,
      count,
      frequency: count / n,
    });
  }

  return {
    simulations: numSims,
    mean: Math.round(mean * 100) / 100,
    median: Math.round(median * 100) / 100,
    std: Math.round(std * 100) / 100,
    p5: Math.round(percentile(0.05) * 100) / 100,
    p10: Math.round(percentile(0.10) * 100) / 100,
    p25: Math.round(percentile(0.25) * 100) / 100,
    p75: Math.round(percentile(0.75) * 100) / 100,
    p90: Math.round(percentile(0.90) * 100) / 100,
    p95: Math.round(percentile(0.95) * 100) / 100,
    probAbove6,
    probBelow3,
    meanSelicStar: Math.round(meanSelicStar * 100) / 100,
    histogram,
    rawResults: rstarResults,
  };
}
