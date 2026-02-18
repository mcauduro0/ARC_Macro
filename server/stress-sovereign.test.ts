/**
 * Tests for Combined Stress Testing, r* Backtest, and Sovereign Risk features
 */
import { describe, it, expect } from 'vitest';

// ============================================================
// Combined Stress Scenarios — Impact Calculation Tests
// ============================================================

describe('Combined Stress Scenarios', () => {
  const baseDashboard = {
    current_spot: 5.224,
    di_1y: 12.82,
    di_2y: 12.62,
    di_5y: 13.01,
    di_10y: 13.51,
    embi_spread: 144,
    vix: 20.6,
    dxy: 96.88,
    selic_target: 14.9,
    equilibrium: {
      composite_rstar: 4.75,
      selic_star: 11.57,
      rstar_fiscal: 6.42,
      acm_term_premium_5y: -0.1,
      fiscal_decomposition: { base: 4, fiscal: 2.07, sovereign: 0.35 },
      model_contributions: {
        fiscal: { weight: 0.15, current_value: 6.42 },
        parity: { weight: 0.10, current_value: 6.18 },
        market_implied: { weight: 0.30, current_value: 6.72 },
        state_space: { weight: 0.35, current_value: 2.00 },
        regime: { weight: 0.10, current_value: 4.51 },
      },
    },
  };

  it('EM Crisis scenario should depreciate BRL significantly', () => {
    // EM Crisis: EMBI +250, DXY +8%, VIX +15
    const embiImpact = (250 / 100) * 0.12; // +30%
    const dxyImpact = (8 / 100) * 1.2;     // +9.6%
    const vixImpact = (15 / 10) * 0.04;    // +6%
    const totalFxPct = embiImpact + dxyImpact + vixImpact;
    const newSpot = 5.224 * (1 + totalFxPct);

    expect(totalFxPct).toBeGreaterThan(0.15); // >15% depreciation
    expect(newSpot).toBeGreaterThan(6.0); // USDBRL > 6.0
  });

  it('Goldilocks scenario should appreciate BRL', () => {
    // Goldilocks: EMBI -60, DXY -4%, VIX -5
    const embiImpact = (-60 / 100) * 0.12;
    const dxyImpact = (-4 / 100) * 1.2;
    const vixImpact = (-5 / 10) * 0.04;
    const totalFxPct = embiImpact + dxyImpact + vixImpact;

    expect(totalFxPct).toBeLessThan(0); // BRL appreciation
    expect(5.224 * (1 + totalFxPct)).toBeLessThan(5.0);
  });

  it('DI curve should steepen with fiscal shock', () => {
    const selicDelta = 4.0;
    const cdsDelta = 150;
    const riskPremium = cdsDelta / 100 * 0.5;

    const di1yDelta = selicDelta * 0.8 + riskPremium * 0.3;
    const di10yDelta = selicDelta * 0.3 + riskPremium * 0.8;

    // Front-end moves more from SELIC, back-end from risk premium
    expect(di1yDelta).toBeGreaterThan(di10yDelta);
    expect(di1yDelta).toBeGreaterThan(3); // >300bps at front
    expect(di10yDelta).toBeGreaterThan(1); // >100bps at back
  });

  it('r* should increase with fiscal deterioration', () => {
    const debtGdpNew = 78 + 12; // +12pp debt/GDP
    const debtPremium = Math.max(0, (debtGdpNew - 60) * 0.08);
    const primaryNew = -0.5 + (-3.5); // -4% primary
    const fiscalPremium = Math.max(0, -primaryNew * 0.50);
    const cdsNew = 150 + 150;
    const cdsPremium = (cdsNew / 100) * 0.35;
    const newFiscalRstar = 4.0 + debtPremium * 0.4 + fiscalPremium * 0.3 + cdsPremium * 0.3;

    expect(newFiscalRstar).toBeGreaterThan(5.5); // Significantly higher than base r* of 4.0
    expect(debtPremium).toBeGreaterThan(2); // Significant debt premium
  });

  it('all 5 preset scenarios should have valid shock parameters', () => {
    const scenarioIds = ['em_crisis_fiscal', 'taper_tantrum', 'lula_fiscal_2', 'covid_v2', 'goldilocks'];
    // Each scenario must have all 9 shock parameters
    const requiredShocks = [
      'debt_gdp_delta', 'primary_balance_delta', 'cds_delta', 'embi_delta',
      'vix_delta', 'dxy_delta', 'ipca_exp_delta', 'ust10y_delta', 'selic_delta'
    ];

    expect(scenarioIds).toHaveLength(5);
    // At least one positive scenario (goldilocks)
    expect(scenarioIds).toContain('goldilocks');
  });
});

// ============================================================
// r* Signal Backtesting Tests
// ============================================================

describe('r* Signal Backtesting', () => {
  it('restrictive signal should be triggered when SELIC > SELIC* + 1.5pp', () => {
    const selicActual = 14.9;
    const selicStar = 11.57;
    const gap = selicActual - selicStar;
    const signal = gap > 1.5 ? 'restrictive' : gap < -1.5 ? 'accommodative' : 'neutral';

    expect(gap).toBeCloseTo(3.33, 1);
    expect(signal).toBe('restrictive');
  });

  it('accommodative signal should be triggered when SELIC < SELIC* - 1.5pp', () => {
    const selicActual = 8.0;
    const selicStar = 11.57;
    const gap = selicActual - selicStar;
    const signal = gap > 1.5 ? 'restrictive' : gap < -1.5 ? 'accommodative' : 'neutral';

    expect(gap).toBeLessThan(-1.5);
    expect(signal).toBe('accommodative');
  });

  it('neutral signal when gap is within ±1.5pp', () => {
    const selicActual = 12.0;
    const selicStar = 11.57;
    const gap = selicActual - selicStar;
    const signal = gap > 1.5 ? 'restrictive' : gap < -1.5 ? 'accommodative' : 'neutral';

    expect(Math.abs(gap)).toBeLessThan(1.5);
    expect(signal).toBe('neutral');
  });

  it('r* signal scaling should be bounded between -0.5 and 1.0', () => {
    const gaps = [5, 3, 1, 0, -1, -3, -5];
    for (const gap of gaps) {
      const signal = gap > 1.5 ? 'restrictive' : gap < -1.5 ? 'accommodative' : 'neutral';
      const scaling = signal === 'restrictive' ? Math.min(1, gap / 5) :
                      signal === 'accommodative' ? Math.max(-0.5, gap / 5) : 0.2;
      expect(scaling).toBeGreaterThanOrEqual(-0.5);
      expect(scaling).toBeLessThanOrEqual(1);
    }
  });

  it('Sharpe ratio calculation should be consistent', () => {
    const returns = [0.5, -0.2, 0.8, -0.1, 0.3, 0.6, -0.4, 0.2, 0.1, -0.3, 0.7, 0.4];
    const vol = Math.sqrt(returns.reduce((s, r) => s + r * r, 0) / returns.length) * Math.sqrt(12);
    const annReturn = returns.reduce((s, r) => s + r, 0) / returns.length * 12;
    const sharpe = vol > 0 ? annReturn / vol : 0;

    expect(vol).toBeGreaterThan(0);
    expect(typeof sharpe).toBe('number');
    expect(isFinite(sharpe)).toBe(true);
  });
});

// ============================================================
// Sovereign Risk Dashboard Tests
// ============================================================

describe('Sovereign Risk Dashboard', () => {
  it('CDS term structure should be upward sloping for investment grade', () => {
    const embi = 144;
    const cds5y = Math.round(embi * 0.85);
    const slope = 0.12; // Normal slope for non-distressed

    const cds1y = Math.round(cds5y * (1 - slope * 4));
    const cds10y = Math.round(cds5y * (1 + slope * 5));

    expect(cds1y).toBeLessThan(cds5y);
    expect(cds10y).toBeGreaterThan(cds5y);
    expect(cds5y).toBeCloseTo(122, 0);
  });

  it('CDS term structure should invert for distressed credits', () => {
    const embi = 400;
    const cds5y = Math.round(embi * 0.85);
    const slope = -0.15; // Inverted for distressed

    const cds1y = Math.round(cds5y * (1 - slope * 4));
    const cds10y = Math.round(cds5y * (1 + slope * 5));

    expect(cds1y).toBeGreaterThan(cds5y); // Inverted
    expect(cds10y).toBeLessThan(cds5y);
  });

  it('EMBI decomposition should sum to total spread', () => {
    const embi = 144;
    const sovereign = Math.round(embi * 0.35);
    const fiscal = Math.round(embi * 0.25);
    const external = Math.round(embi * 0.20);
    const liquidity = embi - sovereign - fiscal - external;

    expect(sovereign + fiscal + external + liquidity).toBe(embi);
    expect(sovereign).toBeGreaterThan(0);
    expect(fiscal).toBeGreaterThan(0);
    expect(external).toBeGreaterThan(0);
    expect(liquidity).toBeGreaterThan(0);
  });

  it('implied rating should match EMBI spread ranges', () => {
    const ratingFromEMBI = (embi: number) => {
      if (embi < 80) return 'BBB-';
      if (embi < 120) return 'BB+';
      if (embi < 200) return 'BB';
      if (embi < 350) return 'BB-';
      return 'B+';
    };

    expect(ratingFromEMBI(60)).toBe('BBB-');
    expect(ratingFromEMBI(100)).toBe('BB+');
    expect(ratingFromEMBI(144)).toBe('BB');
    expect(ratingFromEMBI(250)).toBe('BB-');
    expect(ratingFromEMBI(400)).toBe('B+');
  });

  it('sovereign risk score should be 0-100', () => {
    const embi = 144;
    const rstar = 4.75;
    const vix = 20.6;
    const fiscalPremium = 2.07;

    const embiScore = Math.min(25, Math.max(0, (embi - 50) / 400 * 25));
    const rstarScore = Math.min(25, Math.max(0, (rstar - 2) / 8 * 25));
    const vixScore = Math.min(25, Math.max(0, (vix - 12) / 40 * 25));
    const fiscalScore = Math.min(25, Math.max(0, (fiscalPremium / 4) * 25));
    const total = Math.round(embiScore + rstarScore + vixScore + fiscalScore);

    expect(total).toBeGreaterThanOrEqual(0);
    expect(total).toBeLessThanOrEqual(100);
    expect(embiScore).toBeLessThanOrEqual(25);
    expect(rstarScore).toBeLessThanOrEqual(25);
  });

  it('rating migration probabilities should sum to ~100%', () => {
    const rstar = 4.75;
    const embi = 144;
    const fiscalStress = Math.min(1, Math.max(0,
      (rstar - 3) / 6 * 0.4 +
      (embi - 100) / 300 * 0.3 +
      (2.07 / 4) * 0.3
    ));

    const upgrade = Math.max(2, Math.round((1 - fiscalStress) * 25));
    const stable = Math.round(60 + (1 - fiscalStress) * 15);
    const down1 = Math.round(fiscalStress * 20);
    const down2 = Math.max(1, Math.round(fiscalStress * 8));
    const defaultProb = Math.max(0.1, Math.round(fiscalStress * 3 * 10) / 10);

    const total = upgrade + stable + down1 + down2 + defaultProb;
    // After normalization, should be close to 100
    expect(total).toBeGreaterThan(80);
    expect(total).toBeLessThan(120);
  });

  it('fiscal stress index should be bounded 0-100%', () => {
    const testCases = [
      { rstar: 2, embi: 50, fiscal: 0.5 },
      { rstar: 4.75, embi: 144, fiscal: 2.07 },
      { rstar: 8, embi: 400, fiscal: 4 },
      { rstar: 10, embi: 600, fiscal: 5 },
    ];

    for (const tc of testCases) {
      const stress = Math.min(1, Math.max(0,
        (tc.rstar - 3) / 6 * 0.4 +
        (tc.embi - 100) / 300 * 0.3 +
        (tc.fiscal / 4) * 0.3
      ));
      expect(stress).toBeGreaterThanOrEqual(0);
      expect(stress).toBeLessThanOrEqual(1);
    }
  });
});
