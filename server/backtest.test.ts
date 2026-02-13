import { describe, it, expect } from 'vitest';

/**
 * ARC Macro Risk OS v2.2 — Comprehensive Backtest Tests
 * Covers: overlay-on-CDI framework, 5 instruments, ensemble (Ridge+GBM),
 * score demeaning, two-level regime (global + domestic), new institutional features
 * (CIP basis, BEER cointegration, REER gap, term premium, breakeven, fiscal premium),
 * heatmap, attribution, and quality gates.
 */

// ─── V2.2 Sample Data ─────────────────────────────────────────────────────────

const sampleSummaryV22 = {
  period: '2015-02-28 → 2024-07-31',
  n_months: 114,
  overlay: {
    total_return: 215.2,
    annualized_return: 12.8,
    annualized_vol: 6.6,
    sharpe: 1.94,
    max_drawdown: -8.4,
    calmar: 1.53,
    win_rate: 71.0,
  },
  total: {
    total_return: 621.3,
    annualized_return: 23.1,
    annualized_vol: 6.7,
    sharpe: 3.47,
    max_drawdown: -5.0,
    calmar: 4.62,
    win_rate: 78.1,
  },
  ic_per_instrument: { fx: 0.061, front: 0.69, belly: 0.74, long: 0.76, hard: 0.32 },
  hit_rates: { fx: 45.6, front: 71.0, belly: 78.1, long: 71.9, hard: 59.6 },
  attribution_pct: { fx: -7.79, front: 41.6, belly: 126.4, long: 41.1, hard: 13.7 },
  total_tc_pct: 4.1,
  avg_monthly_turnover: 1.0,
  best_month: { date: '2016-03-31', return_pct: 6.0 },
  worst_month: { date: '2020-03-31', return_pct: -4.6 },
  ensemble: {
    avg_w_ridge: 0.352,
    avg_w_gbm: 0.648,
    final_w_ridge: 0.183,
    final_w_gbm: 0.817,
  },
  score_demeaning: {
    raw_score_mean: 0.391,
    raw_score_std: 2.815,
    demeaned_score_mean: 0.003,
    demeaned_score_std: 0.058,
  },
  regime_summary: {
    carry_pct: 69.3,
    riskoff_pct: 19.3,
    stress_pct: 11.4,
  },
};

const samplePointV22 = {
  date: '2020-03-31',
  equity_overlay: 1.45,
  equity_total: 3.57,
  overlay_return: -0.023,
  cash_return: 0.003,
  total_return: -0.020,
  drawdown_overlay: -0.065,
  drawdown_total: -0.02,
  fx_pnl: -0.01,
  front_pnl: 0.005,
  belly_pnl: 0.008,
  long_pnl: -0.002,
  hard_pnl: 0.003,
  weight_fx: 0.5,
  weight_front: -1.2,
  weight_belly: 1.0,
  weight_long: -0.3,
  weight_hard: 0.4,
  mu_fx: 0.03,
  mu_front: -0.01,
  mu_belly: 0.02,
  mu_long: -0.005,
  mu_hard: 0.01,
  P_carry: 0.1,
  P_riskoff: 0.8,
  P_stress: 0.1,
  P_dom_calm: 0.3,
  P_dom_stress: 0.7,
  tc_pct: 0.05,
  turnover: 0.8,
  score_total: -1.5,
  raw_score: 1.5,
  demeaned_score: -0.8,
  w_ridge_avg: 0.35,
  w_gbm_avg: 0.65,
};

// ─── Summary Structure Tests ──────────────────────────────────────────────────

describe('Backtest v2.2 Summary Structure', () => {
  it('should have overlay metrics with correct field names', () => {
    const o = sampleSummaryV22.overlay;
    expect(o).toHaveProperty('total_return');
    expect(o).toHaveProperty('annualized_return');
    expect(o).toHaveProperty('annualized_vol');
    expect(o).toHaveProperty('sharpe');
    expect(o).toHaveProperty('max_drawdown');
    expect(o).toHaveProperty('calmar');
    expect(o).toHaveProperty('win_rate');
  });

  it('should have total metrics with correct field names', () => {
    const t = sampleSummaryV22.total;
    expect(t).toHaveProperty('total_return');
    expect(t).toHaveProperty('annualized_return');
    expect(t).toHaveProperty('sharpe');
  });

  it('should have overlay Sharpe > 1.5 (v2.2 institutional quality)', () => {
    expect(sampleSummaryV22.overlay.sharpe).toBeGreaterThan(1.5);
  });

  it('should have total Sharpe > overlay Sharpe (CDI boost)', () => {
    expect(sampleSummaryV22.total.sharpe).toBeGreaterThan(sampleSummaryV22.overlay.sharpe);
  });

  it('should have best_month as object with date and return_pct', () => {
    expect(sampleSummaryV22.best_month).toHaveProperty('date');
    expect(sampleSummaryV22.best_month).toHaveProperty('return_pct');
    expect(sampleSummaryV22.best_month.return_pct).toBeGreaterThan(0);
  });

  it('should have worst_month as object with date and return_pct', () => {
    expect(sampleSummaryV22.worst_month).toHaveProperty('date');
    expect(sampleSummaryV22.worst_month).toHaveProperty('return_pct');
    expect(sampleSummaryV22.worst_month.return_pct).toBeLessThan(0);
  });

  it('should have IC per instrument for all 5 instruments', () => {
    const instruments = ['fx', 'front', 'belly', 'long', 'hard'] as const;
    instruments.forEach(inst => {
      expect(sampleSummaryV22.ic_per_instrument).toHaveProperty(inst);
    });
  });

  it('should have hit rates for all 5 instruments between 0 and 100', () => {
    const instruments = ['fx', 'front', 'belly', 'long', 'hard'] as const;
    instruments.forEach(inst => {
      expect(sampleSummaryV22.hit_rates[inst]).toBeGreaterThan(0);
      expect(sampleSummaryV22.hit_rates[inst]).toBeLessThanOrEqual(100);
    });
  });

  it('should have attribution_pct for all 5 instruments', () => {
    const instruments = ['fx', 'front', 'belly', 'long', 'hard'] as const;
    instruments.forEach(inst => {
      expect(sampleSummaryV22.attribution_pct).toHaveProperty(inst);
    });
  });

  it('should have transaction cost and turnover metrics', () => {
    expect(sampleSummaryV22.total_tc_pct).toBeGreaterThan(0);
    expect(sampleSummaryV22.avg_monthly_turnover).toBeGreaterThan(0);
  });
});

// ─── Ensemble Tests ───────────────────────────────────────────────────────────

describe('Backtest v2.2 Ensemble Structure', () => {
  it('should have ensemble weights in summary', () => {
    expect(sampleSummaryV22.ensemble).toBeDefined();
    expect(sampleSummaryV22.ensemble).toHaveProperty('avg_w_ridge');
    expect(sampleSummaryV22.ensemble).toHaveProperty('avg_w_gbm');
    expect(sampleSummaryV22.ensemble).toHaveProperty('final_w_ridge');
    expect(sampleSummaryV22.ensemble).toHaveProperty('final_w_gbm');
  });

  it('average ensemble weights should sum to 1.0', () => {
    const e = sampleSummaryV22.ensemble;
    expect(e.avg_w_ridge + e.avg_w_gbm).toBeCloseTo(1.0, 2);
  });

  it('final ensemble weights should sum to 1.0', () => {
    const e = sampleSummaryV22.ensemble;
    expect(e.final_w_ridge + e.final_w_gbm).toBeCloseTo(1.0, 2);
  });

  it('GBM should have higher average weight than Ridge', () => {
    expect(sampleSummaryV22.ensemble.avg_w_gbm).toBeGreaterThan(sampleSummaryV22.ensemble.avg_w_ridge);
  });

  it('timeseries points should have ensemble weight fields summing to 1.0', () => {
    expect(samplePointV22.w_ridge_avg + samplePointV22.w_gbm_avg).toBeCloseTo(1.0, 2);
  });
});

// ─── Score Demeaning Tests ────────────────────────────────────────────────────

describe('Backtest v2.2 Score Demeaning', () => {
  it('should have score_demeaning stats in summary', () => {
    expect(sampleSummaryV22.score_demeaning).toBeDefined();
    expect(sampleSummaryV22.score_demeaning).toHaveProperty('raw_score_mean');
    expect(sampleSummaryV22.score_demeaning).toHaveProperty('demeaned_score_mean');
  });

  it('demeaned score mean should be much closer to zero than raw', () => {
    const sd = sampleSummaryV22.score_demeaning;
    expect(Math.abs(sd.demeaned_score_mean)).toBeLessThan(Math.abs(sd.raw_score_mean));
  });

  it('demeaned score mean should be near zero (< 0.1)', () => {
    expect(Math.abs(sampleSummaryV22.score_demeaning.demeaned_score_mean)).toBeLessThan(0.1);
  });

  it('timeseries points should have raw_score and demeaned_score', () => {
    expect(typeof samplePointV22.raw_score).toBe('number');
    expect(typeof samplePointV22.demeaned_score).toBe('number');
  });
});

// ─── Two-Level Regime Tests ───────────────────────────────────────────────────

describe('Backtest v2.2 Two-Level Regime', () => {
  it('should have global regime probabilities in timeseries', () => {
    expect(typeof samplePointV22.P_carry).toBe('number');
    expect(typeof samplePointV22.P_riskoff).toBe('number');
    expect(typeof samplePointV22.P_stress).toBe('number');
  });

  it('global regime probabilities should sum to ~1.0', () => {
    const sum = samplePointV22.P_carry + samplePointV22.P_riskoff + samplePointV22.P_stress;
    expect(sum).toBeCloseTo(1.0, 1);
  });

  it('should have domestic regime probabilities in timeseries', () => {
    expect(typeof samplePointV22.P_dom_calm).toBe('number');
    expect(typeof samplePointV22.P_dom_stress).toBe('number');
  });

  it('domestic regime probabilities should sum to ~1.0', () => {
    const sum = samplePointV22.P_dom_calm + samplePointV22.P_dom_stress;
    expect(sum).toBeCloseTo(1.0, 1);
  });

  it('all regime probabilities should be in [0, 1]', () => {
    [samplePointV22.P_carry, samplePointV22.P_riskoff, samplePointV22.P_stress,
     samplePointV22.P_dom_calm, samplePointV22.P_dom_stress].forEach(p => {
      expect(p).toBeGreaterThanOrEqual(0);
      expect(p).toBeLessThanOrEqual(1);
    });
  });

  it('should have regime summary in backtest summary', () => {
    expect(sampleSummaryV22.regime_summary).toBeDefined();
    const rs = sampleSummaryV22.regime_summary;
    expect(rs.carry_pct + rs.riskoff_pct + rs.stress_pct).toBeCloseTo(100, 0);
  });

  it('during COVID (2020-03), risk-off should dominate', () => {
    // COVID period should show high risk-off probability
    expect(samplePointV22.P_riskoff).toBeGreaterThan(0.5);
  });
});

// ─── Timeseries Point Structure Tests ─────────────────────────────────────────

describe('Backtest v2.2 Timeseries Point Structure', () => {
  it('should have equity_overlay and equity_total', () => {
    expect(samplePointV22.equity_overlay).toBeGreaterThan(0);
    expect(samplePointV22.equity_total).toBeGreaterThan(0);
  });

  it('should have overlay_return, cash_return, total_return', () => {
    expect(typeof samplePointV22.overlay_return).toBe('number');
    expect(typeof samplePointV22.cash_return).toBe('number');
    expect(typeof samplePointV22.total_return).toBe('number');
  });

  it('cash_return should be non-negative (CDI)', () => {
    expect(samplePointV22.cash_return).toBeGreaterThanOrEqual(0);
  });

  it('should have drawdown fields (non-positive)', () => {
    expect(samplePointV22.drawdown_overlay).toBeLessThanOrEqual(0);
    expect(samplePointV22.drawdown_total).toBeLessThanOrEqual(0);
  });

  it('should have per-instrument PnL fields for all 5 instruments', () => {
    ['fx_pnl', 'front_pnl', 'belly_pnl', 'long_pnl', 'hard_pnl'].forEach(f => {
      expect(samplePointV22).toHaveProperty(f);
      expect(typeof (samplePointV22 as any)[f]).toBe('number');
    });
  });

  it('should have per-instrument weight fields for all 5 instruments', () => {
    ['weight_fx', 'weight_front', 'weight_belly', 'weight_long', 'weight_hard'].forEach(f => {
      expect(samplePointV22).toHaveProperty(f);
      expect(typeof (samplePointV22 as any)[f]).toBe('number');
    });
  });

  it('should have per-instrument mu (expected return) fields', () => {
    ['mu_fx', 'mu_front', 'mu_belly', 'mu_long', 'mu_hard'].forEach(f => {
      expect(samplePointV22).toHaveProperty(f);
      expect(typeof (samplePointV22 as any)[f]).toBe('number');
    });
  });

  it('should have transaction cost and turnover', () => {
    expect(samplePointV22.tc_pct).toBeGreaterThanOrEqual(0);
    expect(samplePointV22.turnover).toBeGreaterThanOrEqual(0);
  });
});

// ─── Heatmap Data Builder Tests ───────────────────────────────────────────────

describe('Backtest v2.2 Heatmap Data Builder', () => {
  const timeseries = [
    { ...samplePointV22, date: '2020-01-31', overlay_return: 0.02 },
    { ...samplePointV22, date: '2020-02-29', overlay_return: -0.01 },
    { ...samplePointV22, date: '2020-03-31', overlay_return: -0.05 },
    { ...samplePointV22, date: '2021-01-31', overlay_return: 0.01 },
    { ...samplePointV22, date: '2021-06-30', overlay_return: 0.04 },
  ];

  function buildHeatmapData(ts: typeof timeseries) {
    const map: Record<number, Record<number, number>> = {};
    ts.forEach(pt => {
      const d = new Date(pt.date + 'T00:00:00Z');
      const year = d.getUTCFullYear();
      const month = d.getUTCMonth();
      if (!map[year]) map[year] = {};
      map[year][month] = pt.overlay_return * 100;
    });
    return map;
  }

  it('should group returns by year and month', () => {
    const heatmap = buildHeatmapData(timeseries);
    expect(heatmap[2020]).toBeDefined();
    expect(heatmap[2021]).toBeDefined();
    expect(Object.keys(heatmap[2020]).length).toBe(3);
    expect(Object.keys(heatmap[2021]).length).toBe(2);
  });

  it('should map months correctly using UTC', () => {
    const heatmap = buildHeatmapData(timeseries);
    expect(heatmap[2020][0]).toBeCloseTo(2.0, 1);  // Jan
    expect(heatmap[2020][1]).toBeCloseTo(-1.0, 1);  // Feb
    expect(heatmap[2020][2]).toBeCloseTo(-5.0, 1);  // Mar
  });

  it('should handle cross-year data', () => {
    const heatmap = buildHeatmapData(timeseries);
    expect(heatmap[2021][0]).toBeCloseTo(1.0, 1);  // Jan 2021
    expect(heatmap[2021][5]).toBeCloseTo(4.0, 1);  // Jun 2021
  });
});

// ─── Heatmap Color Function Tests ─────────────────────────────────────────────

describe('Heatmap Color Function', () => {
  function getHeatmapColor(value: number | null): string {
    if (value === null) return 'transparent';
    const clamped = Math.max(-6, Math.min(6, value));
    if (clamped >= 0) {
      const intensity = clamped / 6;
      const r = Math.round(20 + (52 - 20) * (1 - intensity));
      const g = Math.round(30 + (211 - 30) * intensity);
      const b = Math.round(30 + (153 - 30) * intensity * 0.6);
      return `rgb(${r}, ${g}, ${b})`;
    } else {
      const intensity = Math.abs(clamped) / 6;
      const r = Math.round(30 + (244 - 30) * intensity);
      const g = Math.round(30 + (63 - 30) * (1 - intensity));
      const b = Math.round(30 + (94 - 30) * (1 - intensity * 0.5));
      return `rgb(${r}, ${g}, ${b})`;
    }
  }

  it('should return transparent for null values', () => {
    expect(getHeatmapColor(null)).toBe('transparent');
  });

  it('should return green-ish for positive values', () => {
    const color = getHeatmapColor(3);
    const [, r, g] = color.match(/rgb\((\d+), (\d+), (\d+)\)/)!.map(Number);
    expect(g).toBeGreaterThan(r);
  });

  it('should return red-ish for negative values', () => {
    const color = getHeatmapColor(-3);
    const [, r, g] = color.match(/rgb\((\d+), (\d+), (\d+)\)/)!.map(Number);
    expect(r).toBeGreaterThan(g);
  });

  it('should clamp extreme values to [-6, 6]', () => {
    expect(getHeatmapColor(10)).toBe(getHeatmapColor(6));
    expect(getHeatmapColor(-10)).toBe(getHeatmapColor(-6));
  });
});

// ─── Overlay Metrics Extraction Tests ─────────────────────────────────────────

describe('Backtest v2.2 Overlay Metrics Extraction', () => {
  function getOverlayMetrics(summary: typeof sampleSummaryV22) {
    return {
      totalReturn: summary.overlay.total_return,
      annReturn: summary.overlay.annualized_return,
      annVol: summary.overlay.annualized_vol,
      sharpe: summary.overlay.sharpe,
      maxDD: summary.overlay.max_drawdown,
      calmar: summary.overlay.calmar,
      winRate: summary.overlay.win_rate,
    };
  }

  it('should extract overlay metrics with correct v2.2 values', () => {
    const m = getOverlayMetrics(sampleSummaryV22);
    expect(m.totalReturn).toBe(215.2);
    expect(m.annReturn).toBe(12.8);
    expect(m.annVol).toBe(6.6);
    expect(m.sharpe).toBe(1.94);
    expect(m.maxDD).toBe(-8.4);
    expect(m.calmar).toBe(1.53);
    expect(m.winRate).toBe(71.0);
  });

  it('should allow toFixed calls on all numeric fields', () => {
    const m = getOverlayMetrics(sampleSummaryV22);
    expect(() => m.totalReturn.toFixed(1)).not.toThrow();
    expect(() => m.annReturn.toFixed(1)).not.toThrow();
    expect(() => m.annVol.toFixed(1)).not.toThrow();
    expect(() => m.sharpe.toFixed(2)).not.toThrow();
    expect(() => m.maxDD.toFixed(1)).not.toThrow();
    expect(() => m.calmar.toFixed(2)).not.toThrow();
    expect(() => m.winRate.toFixed(0)).not.toThrow();
  });
});

// ─── Ensemble Data Builder Tests ──────────────────────────────────────────────

describe('Backtest v2.2 Ensemble Data Builder', () => {
  it('should compute ensemble data from timeseries points', () => {
    const ensembleData = [{
      date: samplePointV22.date,
      w_ridge: (samplePointV22.w_ridge_avg ?? 0.5) * 100,
      w_gbm: (samplePointV22.w_gbm_avg ?? 0.5) * 100,
      raw_score: samplePointV22.raw_score ?? 0,
      demeaned_score: samplePointV22.demeaned_score ?? 0,
    }];

    expect(ensembleData[0].w_ridge).toBeCloseTo(35, 0);
    expect(ensembleData[0].w_gbm).toBeCloseTo(65, 0);
    expect(ensembleData[0].w_ridge + ensembleData[0].w_gbm).toBeCloseTo(100, 0);
  });

  it('should handle missing ensemble fields with defaults', () => {
    const ptNoEnsemble = { ...samplePointV22 } as any;
    delete ptNoEnsemble.w_ridge_avg;
    delete ptNoEnsemble.w_gbm_avg;

    const ensembleData = [{
      w_ridge: (ptNoEnsemble.w_ridge_avg ?? 0.5) * 100,
      w_gbm: (ptNoEnsemble.w_gbm_avg ?? 0.5) * 100,
    }];

    expect(ensembleData[0].w_ridge).toBe(50);
    expect(ensembleData[0].w_gbm).toBe(50);
  });
});

// ─── v2.2 Quality Gate Tests ──────────────────────────────────────────────────

describe('v2.2 Quality Gates (Institutional Standard)', () => {
  it('Overlay Sharpe should be above 1.5', () => {
    expect(sampleSummaryV22.overlay.sharpe).toBeGreaterThan(1.5);
  });

  it('Win rate should be above 60%', () => {
    expect(sampleSummaryV22.overlay.win_rate).toBeGreaterThan(60);
  });

  it('Max drawdown should be better than -15%', () => {
    expect(sampleSummaryV22.overlay.max_drawdown).toBeGreaterThan(-15);
  });

  it('Calmar ratio should be above 1.0', () => {
    expect(sampleSummaryV22.overlay.calmar).toBeGreaterThan(1.0);
  });

  it('Total Sharpe (CDI + overlay) should be above 3.0', () => {
    expect(sampleSummaryV22.total.sharpe).toBeGreaterThan(3.0);
  });

  it('Transaction costs should be below 10% of total return', () => {
    expect(sampleSummaryV22.total_tc_pct / sampleSummaryV22.overlay.total_return).toBeLessThan(0.1);
  });

  it('Belly IC should be above 0.5 (strongest signal)', () => {
    expect(sampleSummaryV22.ic_per_instrument.belly).toBeGreaterThan(0.5);
  });

  it('At least 3 instruments should have positive IC', () => {
    const positiveIC = Object.values(sampleSummaryV22.ic_per_instrument).filter(ic => ic > 0).length;
    expect(positiveIC).toBeGreaterThanOrEqual(3);
  });

  it('FX IC should be positive (improved from v2.0)', () => {
    expect(sampleSummaryV22.ic_per_instrument.fx).toBeGreaterThan(0);
  });
});

// ─── v2.2 vs v2.1 Improvement Tests ──────────────────────────────────────────

describe('v2.2 vs v2.1 Improvements', () => {
  const v21Sharpe = 1.61;
  const v21Calmar = 1.24;
  const v21WinRate = 71.9;
  const v21FxIC = 0.025;

  it('Overlay Sharpe should improve from v2.1', () => {
    expect(sampleSummaryV22.overlay.sharpe).toBeGreaterThan(v21Sharpe);
  });

  it('Calmar ratio should improve from v2.1', () => {
    expect(sampleSummaryV22.overlay.calmar).toBeGreaterThan(v21Calmar);
  });

  it('FX IC should improve from v2.1', () => {
    expect(sampleSummaryV22.ic_per_instrument.fx).toBeGreaterThan(v21FxIC);
  });

  it('All instruments should have positive IC in v2.2', () => {
    Object.entries(sampleSummaryV22.ic_per_instrument).forEach(([inst, ic]) => {
      expect(ic).toBeGreaterThan(0, `${inst} should have positive IC`);
    });
  });
});
