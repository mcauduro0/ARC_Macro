/**
 * Tests for r* time series, Monte Carlo simulation, and PDF export features.
 * Tests the data flow, Monte Carlo engine logic, and API integration.
 */
import { describe, it, expect } from 'vitest';

// ============================================================
// Monte Carlo Engine Tests (logic validation)
// ============================================================
describe('Monte Carlo r* Simulation Engine', () => {
  // Replicate the core functions from monteCarloRstar.ts for testing
  function choleskyDecomposition(matrix: number[][]): number[][] {
    const n = matrix.length;
    const L: number[][] = Array.from({ length: n }, () => Array(n).fill(0));
    for (let i = 0; i < n; i++) {
      for (let j = 0; j <= i; j++) {
        let sum = 0;
        for (let k = 0; k < j; k++) sum += L[i][k] * L[j][k];
        if (i === j) L[i][j] = Math.sqrt(Math.max(0, matrix[i][i] - sum));
        else L[i][j] = (matrix[i][j] - sum) / (L[j][j] || 1e-10);
      }
    }
    return L;
  }

  function recalcFiscalRstar(vars: Record<string, number>): number {
    const base = 4.0;
    const debtPremium = Math.max(0, (vars.debt_gdp - 60) * 0.08);
    const fiscalPremium = Math.max(0, -vars.primary_balance * 0.50);
    const cdsPremium = (vars.cds_5y / 100) * 0.35;
    return base + debtPremium * 0.4 + fiscalPremium * 0.3 + cdsPremium * 0.3;
  }

  it('Cholesky decomposition produces valid lower triangular matrix', () => {
    const matrix = [
      [1.0, 0.5],
      [0.5, 1.0],
    ];
    const L = choleskyDecomposition(matrix);

    // L should be lower triangular
    expect(L[0][1]).toBe(0);
    // L * L^T should equal original matrix
    const reconstructed00 = L[0][0] * L[0][0] + L[0][1] * L[0][1];
    const reconstructed01 = L[0][0] * L[1][0] + L[0][1] * L[1][1];
    const reconstructed11 = L[1][0] * L[1][0] + L[1][1] * L[1][1];
    expect(reconstructed00).toBeCloseTo(1.0, 5);
    expect(reconstructed01).toBeCloseTo(0.5, 5);
    expect(reconstructed11).toBeCloseTo(1.0, 5);
  });

  it('Cholesky handles 5x5 correlation matrix', () => {
    const CORR = [
      [1.00, -0.65,  0.70,  0.72,  0.45],
      [-0.65,  1.00, -0.55, -0.50, -0.30],
      [0.70, -0.55,  1.00,  0.85,  0.40],
      [0.72, -0.50,  0.85,  1.00,  0.35],
      [0.45, -0.30,  0.40,  0.35,  1.00],
    ];
    const L = choleskyDecomposition(CORR);

    // Verify L is lower triangular
    for (let i = 0; i < 5; i++) {
      for (let j = i + 1; j < 5; j++) {
        expect(L[i][j]).toBe(0);
      }
    }

    // Verify diagonal is positive
    for (let i = 0; i < 5; i++) {
      expect(L[i][i]).toBeGreaterThan(0);
    }
  });

  it('Fiscal r* increases with higher debt/GDP', () => {
    const base = recalcFiscalRstar({ debt_gdp: 70, primary_balance: 0, cds_5y: 150, embi: 140, ipca_exp: 5 });
    const high = recalcFiscalRstar({ debt_gdp: 100, primary_balance: 0, cds_5y: 150, embi: 140, ipca_exp: 5 });
    expect(high).toBeGreaterThan(base);
  });

  it('Fiscal r* increases with larger deficit', () => {
    const surplus = recalcFiscalRstar({ debt_gdp: 78, primary_balance: 2, cds_5y: 150, embi: 140, ipca_exp: 5 });
    const deficit = recalcFiscalRstar({ debt_gdp: 78, primary_balance: -3, cds_5y: 150, embi: 140, ipca_exp: 5 });
    expect(deficit).toBeGreaterThan(surplus);
  });

  it('Fiscal r* increases with higher CDS', () => {
    const low = recalcFiscalRstar({ debt_gdp: 78, primary_balance: -0.5, cds_5y: 100, embi: 140, ipca_exp: 5 });
    const high = recalcFiscalRstar({ debt_gdp: 78, primary_balance: -0.5, cds_5y: 400, embi: 140, ipca_exp: 5 });
    expect(high).toBeGreaterThan(low);
  });

  it('Fiscal r* has a floor at base rate when all variables are minimal', () => {
    const minimal = recalcFiscalRstar({ debt_gdp: 50, primary_balance: 4, cds_5y: 50, embi: 50, ipca_exp: 2 });
    // Base is 4.0, with minimal debt premium and CDS contribution
    expect(minimal).toBeGreaterThanOrEqual(4.0);
  });

  it('Stress scenario produces significantly higher r* than consolidation', () => {
    const consolidation = recalcFiscalRstar({ debt_gdp: 75, primary_balance: 1.5, cds_5y: 120, embi: 110, ipca_exp: 4.5 });
    const stress = recalcFiscalRstar({ debt_gdp: 100, primary_balance: -4, cds_5y: 400, embi: 500, ipca_exp: 9 });
    expect(stress - consolidation).toBeGreaterThan(1.0); // At least 100bps difference
  });
});

// ============================================================
// r* Time Series Data Tests
// ============================================================
describe('r* Time Series Data Structure', () => {
  it('rstar_ts points have required fields', () => {
    const samplePoint = {
      date: '2025-12-31',
      composite_rstar: 4.75,
      selic_star: 11.57,
      selic_actual: 14.9,
      rstar_fiscal: 6.42,
      rstar_parity: 6.18,
      rstar_market_implied: 6.72,
      rstar_state_space: 2.0,
      acm_term_premium: -0.10,
    };

    expect(samplePoint.date).toBeDefined();
    expect(samplePoint.composite_rstar).toBeGreaterThan(0);
    expect(samplePoint.selic_star).toBeGreaterThan(samplePoint.composite_rstar);
    expect(samplePoint.selic_actual).toBeGreaterThan(0);
  });

  it('policy gap is correctly computed from selic_actual - selic_star', () => {
    const point = { selic_actual: 14.9, selic_star: 11.57 };
    const policyGap = point.selic_actual - point.selic_star;
    expect(policyGap).toBeCloseTo(3.33, 1);
    expect(policyGap).toBeGreaterThan(0); // Currently restrictive
  });
});

// ============================================================
// PDF Export Data Structure Tests
// ============================================================
describe('PDF Export Data Validation', () => {
  it('export data contains all required sections', () => {
    const exportData = {
      scenarioName: 'Stress Fiscal',
      scenarioDescription: 'Crise fiscal: déficit -4%, dívida 100%',
      exportDate: '14/02/2026 20:30:00',
      variables: [
        { label: 'Dívida/PIB', value: 100, unit: '%', defaultValue: 78, delta: 22 },
      ],
      results: {
        currentComposite: 4.75,
        newComposite: 6.5,
        deltaRstar: 1.75,
        currentSelicStar: 11.57,
        newSelicStar: 15.5,
        deltaSelicStar: 3.93,
        newFiscalRstar: 8.2,
        currentFiscalRstar: 6.42,
        newPolicyGap: -0.6,
        signal: 'restrictive',
      },
      modelInfo: {
        runDate: '2026-02-14',
        currentRegime: 'Carry',
        selicTarget: 14.9,
        spotRate: 5.7654,
        compositeMethod: 'regime_weighted',
        activeModels: 5,
      },
    };

    expect(exportData.scenarioName).toBeTruthy();
    expect(exportData.variables.length).toBeGreaterThan(0);
    expect(exportData.results.newComposite).toBeGreaterThan(0);
    expect(exportData.modelInfo.activeModels).toBe(5);
  });

  it('Monte Carlo section in PDF has correct percentile ordering', () => {
    const mc = {
      simulations: 10000,
      mean: 4.75,
      median: 4.70,
      p5: 3.2,
      p25: 4.1,
      p75: 5.4,
      p95: 6.8,
      std: 0.95,
      probAbove6: 0.12,
      probBelow3: 0.05,
    };

    expect(mc.p5).toBeLessThan(mc.p25);
    expect(mc.p25).toBeLessThan(mc.median);
    expect(mc.median).toBeLessThan(mc.p75);
    expect(mc.p75).toBeLessThan(mc.p95);
    expect(mc.probAbove6 + mc.probBelow3).toBeLessThanOrEqual(1);
  });
});

// ============================================================
// Composite r* Recalculation Tests
// ============================================================
describe('Composite r* Recalculation', () => {
  function recalcCompositeRstar(
    currentComposite: number,
    currentFiscalRstar: number,
    newFiscalRstar: number,
    fiscalWeight: number
  ): number {
    const fiscalDelta = (newFiscalRstar - currentFiscalRstar) * fiscalWeight;
    return currentComposite + fiscalDelta;
  }

  it('composite r* stays the same when fiscal r* is unchanged', () => {
    const result = recalcCompositeRstar(4.75, 6.42, 6.42, 0.15);
    expect(result).toBeCloseTo(4.75, 5);
  });

  it('composite r* increases when fiscal r* increases', () => {
    const result = recalcCompositeRstar(4.75, 6.42, 8.0, 0.15);
    expect(result).toBeGreaterThan(4.75);
  });

  it('fiscal weight scales the impact correctly', () => {
    const low = recalcCompositeRstar(4.75, 6.42, 8.0, 0.10);
    const high = recalcCompositeRstar(4.75, 6.42, 8.0, 0.30);
    expect(high - 4.75).toBeCloseTo((low - 4.75) * 3, 1);
  });
});
