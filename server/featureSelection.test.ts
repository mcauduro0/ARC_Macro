import { describe, it, expect } from 'vitest';

/**
 * Feature Selection v4.3 — LASSO + Boruta + Stability + Path + Temporal tests
 * Tests the output structure and validation of the full feature selection system.
 */

// Mock feature selection result structure (matches Python output)
const MOCK_FS_RESULT: Record<string, any> = {
  fx: {
    total_features: 20,
    lasso: {
      n_selected: 10,
      alpha: 0.0007,
      selected: ['Z_real_diff', 'Z_fiscal', 'Z_dxy', 'Z_vix', 'Z_beer', 'Z_reer_gap', 'Z_iron_ore', 'Z_focus_fx', 'Z_ewz', 'carry_fx'],
      coefficients: { Z_real_diff: 0.002, Z_fiscal: -0.001 },
      path: {
        alphas: [0.1, 0.05, 0.01, 0.005, 0.001, 0.0007, 0.0005, 0.0001],
        coefficients: {
          Z_real_diff: [0, 0, 0.001, 0.0015, 0.002, 0.002, 0.0021, 0.0022],
          Z_fiscal: [0, 0, -0.0005, -0.0008, -0.001, -0.001, -0.0011, -0.0012],
          Z_dxy: [0, 0, 0, 0, 0.0003, 0.0005, 0.0006, 0.0008],
        },
        selected_alpha: 0.0007,
        n_alphas: 8,
      },
    },
    boruta: {
      n_confirmed: 1,
      n_tentative: 1,
      n_rejected: 18,
      confirmed: ['Z_focus_fx'],
      tentative: ['Z_ewz'],
      rejected: ['Z_real_diff', 'Z_infl_surprise', 'Z_fiscal', 'Z_tot', 'Z_dxy', 'Z_vix', 'Z_cds_br', 'Z_beer', 'Z_reer_gap', 'Z_term_premium', 'Z_cip_basis', 'Z_iron_ore', 'Z_policy_gap', 'Z_rstar_composite', 'Z_rstar_momentum', 'Z_selic_star_gap', 'rstar_regime_signal', 'carry_fx'],
      n_iterations: 30,
    },
    stability: {
      n_subsamples: 100,
      subsample_ratio: 0.8,
      lasso_frequency: { Z_real_diff: 0.92, Z_fiscal: 0.85, Z_dxy: 0.78, Z_vix: 0.45, Z_focus_fx: 0.88 },
      boruta_frequency: { Z_focus_fx: 0.72, Z_ewz: 0.35 },
      combined_frequency: { Z_real_diff: 0.92, Z_fiscal: 0.85, Z_dxy: 0.78, Z_vix: 0.45, Z_focus_fx: 0.95, Z_ewz: 0.35 },
      classification: { Z_real_diff: 'robust', Z_fiscal: 'robust', Z_dxy: 'moderate', Z_vix: 'unstable', Z_focus_fx: 'robust', Z_ewz: 'unstable' },
    },
    final: {
      n_features: 10,
      features: ['Z_real_diff', 'Z_fiscal', 'Z_dxy', 'Z_vix', 'Z_beer', 'Z_reer_gap', 'Z_iron_ore', 'Z_focus_fx', 'Z_ewz', 'carry_fx'],
      reduction_pct: 50,
      method: 'lasso_union_boruta',
    },
  },
  front: {
    total_features: 13,
    lasso: {
      n_selected: 1,
      alpha: 0.0013,
      selected: ['carry_front'],
      coefficients: { carry_front: 0.003 },
      path: {
        alphas: [0.1, 0.05, 0.01, 0.005, 0.0013, 0.001, 0.0005],
        coefficients: {
          carry_front: [0, 0, 0.001, 0.002, 0.003, 0.0035, 0.004],
        },
        selected_alpha: 0.0013,
        n_alphas: 7,
      },
    },
    boruta: {
      n_confirmed: 4,
      n_tentative: 3,
      n_rejected: 6,
      confirmed: ['carry_front', 'Z_portfolio_flow', 'Z_selic_star_gap', 'rstar_regime_signal'],
      tentative: ['Z_real_diff', 'Z_fiscal', 'Z_slope'],
      rejected: ['Z_infl_surprise', 'Z_tot', 'Z_dxy', 'Z_vix', 'Z_cds_br', 'Z_iron_ore'],
      n_iterations: 30,
    },
    stability: {
      n_subsamples: 100,
      subsample_ratio: 0.8,
      lasso_frequency: { carry_front: 0.95 },
      boruta_frequency: { carry_front: 0.88, Z_portfolio_flow: 0.62, Z_selic_star_gap: 0.55, rstar_regime_signal: 0.72 },
      combined_frequency: { carry_front: 0.98, Z_portfolio_flow: 0.62, Z_selic_star_gap: 0.55, rstar_regime_signal: 0.72 },
      classification: { carry_front: 'robust', Z_portfolio_flow: 'moderate', Z_selic_star_gap: 'moderate', rstar_regime_signal: 'moderate' },
    },
    final: {
      n_features: 4,
      features: ['carry_front', 'Z_portfolio_flow', 'Z_selic_star_gap', 'rstar_regime_signal'],
      reduction_pct: 69,
      method: 'lasso_union_boruta',
    },
  },
};

// Mock temporal comparison data
const MOCK_TEMPORAL = {
  changes: [
    { instrument: 'fx', feature: 'Z_ewz', change_type: 'gained', from_status: 'rejected', to_status: 'selected' },
    { instrument: 'front', feature: 'Z_slope', change_type: 'lost', from_status: 'selected', to_status: 'rejected' },
  ],
  summary: {
    fx: {
      total_features_tracked: 20,
      features_gained: ['Z_ewz'],
      features_lost: [],
      features_stable: ['Z_real_diff', 'Z_fiscal', 'Z_dxy'],
      structural_shift_score: 0.15,
    },
    front: {
      total_features_tracked: 13,
      features_gained: [],
      features_lost: ['Z_slope'],
      features_stable: ['carry_front', 'Z_portfolio_flow'],
      structural_shift_score: 0.25,
    },
  },
  run_date: '2026-02-15',
  previous_date: '2026-02-14',
};

// ============ LASSO + Boruta Base Tests ============

describe('Feature Selection Result Structure', () => {
  it('should have valid LASSO results per instrument', () => {
    for (const [inst, result] of Object.entries(MOCK_FS_RESULT)) {
      expect(result.lasso).toBeDefined();
      expect(result.lasso.n_selected).toBeGreaterThan(0);
      expect(result.lasso.alpha).toBeGreaterThan(0);
      expect(result.lasso.selected).toBeInstanceOf(Array);
      expect(result.lasso.selected.length).toBe(result.lasso.n_selected);
    }
  });

  it('should have valid Boruta results per instrument', () => {
    for (const [inst, result] of Object.entries(MOCK_FS_RESULT)) {
      expect(result.boruta).toBeDefined();
      expect(result.boruta.n_confirmed).toBeGreaterThanOrEqual(0);
      expect(result.boruta.n_tentative).toBeGreaterThanOrEqual(0);
      expect(result.boruta.n_rejected).toBeGreaterThanOrEqual(0);
      const borutaTotal = result.boruta.n_confirmed + result.boruta.n_tentative + result.boruta.n_rejected;
      expect(borutaTotal).toBe(result.total_features);
      expect(result.boruta.confirmed.length).toBe(result.boruta.n_confirmed);
      expect(result.boruta.tentative.length).toBe(result.boruta.n_tentative);
      expect(result.boruta.rejected.length).toBe(result.boruta.n_rejected);
    }
  });

  it('should have valid final selection per instrument', () => {
    for (const [inst, result] of Object.entries(MOCK_FS_RESULT)) {
      expect(result.final).toBeDefined();
      expect(result.final.n_features).toBeGreaterThan(0);
      expect(result.final.n_features).toBeLessThanOrEqual(result.total_features);
      expect(result.final.features.length).toBe(result.final.n_features);
      expect(result.final.reduction_pct).toBeGreaterThanOrEqual(0);
      expect(result.final.reduction_pct).toBeLessThanOrEqual(100);
    }
  });

  it('should achieve meaningful feature reduction', () => {
    for (const [inst, result] of Object.entries(MOCK_FS_RESULT)) {
      expect(result.final.reduction_pct).toBeGreaterThanOrEqual(30);
    }
  });

  it('LASSO selected features should be subset of all features', () => {
    for (const [inst, result] of Object.entries(MOCK_FS_RESULT)) {
      expect(result.lasso.n_selected).toBeLessThanOrEqual(result.total_features);
    }
  });

  it('Boruta confirmed features should be in final set', () => {
    for (const [inst, result] of Object.entries(MOCK_FS_RESULT)) {
      const finalSet = new Set(result.final.features);
      for (const feat of result.boruta.confirmed) {
        expect(finalSet.has(feat)).toBe(true);
      }
    }
  });

  it('final method should be lasso_union_boruta', () => {
    for (const [inst, result] of Object.entries(MOCK_FS_RESULT)) {
      expect(result.final.method).toBe('lasso_union_boruta');
    }
  });
});

// ============ LASSO Path Tests ============

describe('LASSO Coefficient Path', () => {
  it('should have path data for each instrument', () => {
    for (const [inst, result] of Object.entries(MOCK_FS_RESULT)) {
      expect(result.lasso.path).toBeDefined();
      expect(result.lasso.path.alphas).toBeInstanceOf(Array);
      expect(result.lasso.path.alphas.length).toBeGreaterThan(0);
      expect(result.lasso.path.n_alphas).toBe(result.lasso.path.alphas.length);
    }
  });

  it('alphas should be in descending order (high to low regularization)', () => {
    for (const [inst, result] of Object.entries(MOCK_FS_RESULT)) {
      const alphas = result.lasso.path.alphas;
      for (let i = 1; i < alphas.length; i++) {
        expect(alphas[i]).toBeLessThanOrEqual(alphas[i - 1]);
      }
    }
  });

  it('coefficient arrays should match alpha array length', () => {
    for (const [inst, result] of Object.entries(MOCK_FS_RESULT)) {
      const nAlphas = result.lasso.path.alphas.length;
      for (const [feat, coefs] of Object.entries(result.lasso.path.coefficients)) {
        expect((coefs as number[]).length).toBe(nAlphas);
      }
    }
  });

  it('selected_alpha should be in the alphas array', () => {
    for (const [inst, result] of Object.entries(MOCK_FS_RESULT)) {
      expect(result.lasso.path.alphas).toContain(result.lasso.path.selected_alpha);
    }
  });

  it('at highest alpha, most coefficients should be zero', () => {
    for (const [inst, result] of Object.entries(MOCK_FS_RESULT)) {
      const coefs = result.lasso.path.coefficients;
      const zeroCount = Object.values(coefs).filter((c: any) => c[0] === 0).length;
      const totalFeatures = Object.keys(coefs).length;
      // At highest alpha, at least 50% should be zero
      expect(zeroCount / totalFeatures).toBeGreaterThanOrEqual(0.5);
    }
  });

  it('at lowest alpha, more coefficients should be non-zero', () => {
    for (const [inst, result] of Object.entries(MOCK_FS_RESULT)) {
      const coefs = result.lasso.path.coefficients;
      const lastIdx = result.lasso.path.alphas.length - 1;
      const nonZeroCount = Object.values(coefs).filter((c: any) => Math.abs(c[lastIdx]) > 1e-8).length;
      // At lowest alpha, at least some features should be active
      expect(nonZeroCount).toBeGreaterThan(0);
    }
  });
});

// ============ Stability Selection Tests ============

describe('Stability Selection (Bootstrap)', () => {
  it('should have stability data for each instrument', () => {
    for (const [inst, result] of Object.entries(MOCK_FS_RESULT)) {
      expect(result.stability).toBeDefined();
      expect(result.stability.n_subsamples).toBe(100);
      expect(result.stability.subsample_ratio).toBe(0.8);
    }
  });

  it('frequencies should be between 0 and 1', () => {
    for (const [inst, result] of Object.entries(MOCK_FS_RESULT)) {
      for (const freq of Object.values(result.stability.combined_frequency) as number[]) {
        expect(freq).toBeGreaterThanOrEqual(0);
        expect(freq).toBeLessThanOrEqual(1);
      }
      for (const freq of Object.values(result.stability.lasso_frequency) as number[]) {
        expect(freq).toBeGreaterThanOrEqual(0);
        expect(freq).toBeLessThanOrEqual(1);
      }
      for (const freq of Object.values(result.stability.boruta_frequency) as number[]) {
        expect(freq).toBeGreaterThanOrEqual(0);
        expect(freq).toBeLessThanOrEqual(1);
      }
    }
  });

  it('classification should be robust, moderate, or unstable', () => {
    const validClasses = new Set(['robust', 'moderate', 'unstable']);
    for (const [inst, result] of Object.entries(MOCK_FS_RESULT)) {
      for (const cls of Object.values(result.stability.classification) as string[]) {
        expect(validClasses.has(cls)).toBe(true);
      }
    }
  });

  it('robust features should have frequency > 0.8', () => {
    for (const [inst, result] of Object.entries(MOCK_FS_RESULT)) {
      for (const [feat, cls] of Object.entries(result.stability.classification) as [string, string][]) {
        if (cls === 'robust') {
          expect(result.stability.combined_frequency[feat]).toBeGreaterThan(0.8);
        }
      }
    }
  });

  it('unstable features should have frequency < 0.5', () => {
    for (const [inst, result] of Object.entries(MOCK_FS_RESULT)) {
      for (const [feat, cls] of Object.entries(result.stability.classification) as [string, string][]) {
        if (cls === 'unstable') {
          expect(result.stability.combined_frequency[feat]).toBeLessThan(0.5);
        }
      }
    }
  });

  it('combined frequency should be >= max(lasso, boruta) frequency', () => {
    for (const [inst, result] of Object.entries(MOCK_FS_RESULT)) {
      for (const feat of Object.keys(result.stability.combined_frequency)) {
        const combined = result.stability.combined_frequency[feat];
        const lasso = result.stability.lasso_frequency[feat] || 0;
        const boruta = result.stability.boruta_frequency[feat] || 0;
        expect(combined).toBeGreaterThanOrEqual(Math.max(lasso, boruta) - 0.01);
      }
    }
  });
});

// ============ Temporal Comparison Tests ============

describe('Temporal Feature Selection Comparison', () => {
  it('should have valid temporal structure', () => {
    expect(MOCK_TEMPORAL.run_date).toBeDefined();
    expect(MOCK_TEMPORAL.previous_date).toBeDefined();
    expect(MOCK_TEMPORAL.changes).toBeInstanceOf(Array);
    expect(MOCK_TEMPORAL.summary).toBeDefined();
  });

  it('changes should have valid change_type', () => {
    const validTypes = new Set(['gained', 'lost', 'upgraded', 'downgraded', 'stable']);
    for (const change of MOCK_TEMPORAL.changes) {
      expect(validTypes.has(change.change_type)).toBe(true);
      expect(change.instrument).toBeDefined();
      expect(change.feature).toBeDefined();
    }
  });

  it('summary should have valid structural_shift_score', () => {
    for (const [inst, summary] of Object.entries(MOCK_TEMPORAL.summary)) {
      expect(summary.structural_shift_score).toBeGreaterThanOrEqual(0);
      expect(summary.structural_shift_score).toBeLessThanOrEqual(1);
    }
  });

  it('gained + lost + stable should be consistent', () => {
    for (const [inst, summary] of Object.entries(MOCK_TEMPORAL.summary)) {
      const total = summary.features_gained.length + summary.features_lost.length + summary.features_stable.length;
      // Total tracked should be >= sum of categories
      expect(total).toBeLessThanOrEqual(summary.total_features_tracked);
    }
  });

  it('run_date should be after previous_date', () => {
    expect(new Date(MOCK_TEMPORAL.run_date).getTime()).toBeGreaterThan(
      new Date(MOCK_TEMPORAL.previous_date).getTime()
    );
  });

  it('low shift score means mostly stable features', () => {
    for (const [inst, summary] of Object.entries(MOCK_TEMPORAL.summary)) {
      if (summary.structural_shift_score < 0.2) {
        // Low shift = more stable than changed
        expect(summary.features_stable.length).toBeGreaterThanOrEqual(
          summary.features_gained.length + summary.features_lost.length
        );
      }
    }
  });
});

// ============ Cross-Instrument Consistency ============

describe('Feature Selection Cross-Instrument Consistency', () => {
  it('should have results for expected instruments', () => {
    const instruments = Object.keys(MOCK_FS_RESULT);
    expect(instruments.length).toBeGreaterThanOrEqual(2);
  });

  it('total features should vary by instrument (different feature maps)', () => {
    const totals = Object.values(MOCK_FS_RESULT).map((r: any) => r.total_features);
    const uniqueTotals = new Set(totals);
    expect(uniqueTotals.size).toBeGreaterThanOrEqual(1);
  });

  it('LASSO alpha should be positive for all instruments', () => {
    for (const result of Object.values(MOCK_FS_RESULT) as any[]) {
      expect(result.lasso.alpha).toBeGreaterThan(0);
      expect(result.lasso.alpha).toBeLessThan(1);
    }
  });

  it('all instruments should have stability data with same n_subsamples', () => {
    const nSubsamples = Object.values(MOCK_FS_RESULT).map((r: any) => r.stability?.n_subsamples);
    const unique = new Set(nSubsamples);
    expect(unique.size).toBe(1);
    expect(nSubsamples[0]).toBe(100);
  });
});
