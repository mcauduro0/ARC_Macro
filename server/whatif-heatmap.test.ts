/**
 * Tests for RegimeWeightHeatmap and WhatIfPanel data logic
 * Tests the r* recalculation engine and regime weight matrix validation
 */
import { describe, it, expect } from 'vitest';

// ============================================================
// r* Recalculation Engine (mirrors WhatIfPanel logic)
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
// Regime Weight Matrix Validation
// ============================================================

const REGIME_WEIGHTS: Record<string, Record<string, number>> = {
  carry: { fiscal: 0.15, parity: 0.10, market_implied: 0.30, state_space: 0.35, regime: 0.10 },
  riskoff: { fiscal: 0.15, parity: 0.30, market_implied: 0.20, state_space: 0.20, regime: 0.15 },
  domestic_stress: { fiscal: 0.40, parity: 0.10, market_implied: 0.15, state_space: 0.15, regime: 0.20 },
};

describe('Regime Weight Matrix', () => {
  it('should have weights summing to 1.0 for each regime', () => {
    for (const [regime, weights] of Object.entries(REGIME_WEIGHTS)) {
      const sum = Object.values(weights).reduce((s, w) => s + w, 0);
      expect(sum).toBeCloseTo(1.0, 2);
    }
  });

  it('should have all 5 models in each regime', () => {
    const expectedModels = ['fiscal', 'parity', 'market_implied', 'state_space', 'regime'];
    for (const [regime, weights] of Object.entries(REGIME_WEIGHTS)) {
      for (const model of expectedModels) {
        expect(weights).toHaveProperty(model);
        expect(weights[model]).toBeGreaterThan(0);
      }
    }
  });

  it('should have fiscal model dominant in domestic_stress regime', () => {
    const stressWeights = REGIME_WEIGHTS.domestic_stress;
    const maxModel = Object.entries(stressWeights).reduce((a, b) => a[1] > b[1] ? a : b);
    expect(maxModel[0]).toBe('fiscal');
    expect(maxModel[1]).toBeGreaterThanOrEqual(0.35);
  });

  it('should have state_space dominant in carry regime', () => {
    const carryWeights = REGIME_WEIGHTS.carry;
    const maxModel = Object.entries(carryWeights).reduce((a, b) => a[1] > b[1] ? a : b);
    expect(maxModel[0]).toBe('state_space');
  });

  it('should have parity dominant in riskoff regime', () => {
    const riskoffWeights = REGIME_WEIGHTS.riskoff;
    const maxModel = Object.entries(riskoffWeights).reduce((a, b) => a[1] > b[1] ? a : b);
    expect(maxModel[0]).toBe('parity');
  });

  it('should have all weights between 0 and 1', () => {
    for (const weights of Object.values(REGIME_WEIGHTS)) {
      for (const w of Object.values(weights)) {
        expect(w).toBeGreaterThanOrEqual(0);
        expect(w).toBeLessThanOrEqual(1);
      }
    }
  });
});

describe('What-If r* Recalculation Engine', () => {
  const currentVars = {
    debt_gdp: 78,
    primary_balance: -0.5,
    cds_5y: 160,
    embi: 144,
    ipca_exp: 5.8,
  };

  it('should return a positive r* for current values', () => {
    const rstar = recalcFiscalRstar(currentVars);
    expect(rstar).toBeGreaterThan(3);
    expect(rstar).toBeLessThan(10);
  });

  it('should increase r* when debt/GDP increases', () => {
    const base = recalcFiscalRstar(currentVars);
    const higher = recalcFiscalRstar({ ...currentVars, debt_gdp: 90 });
    expect(higher).toBeGreaterThan(base);
  });

  it('should decrease r* when primary balance improves (surplus)', () => {
    const base = recalcFiscalRstar(currentVars);
    const better = recalcFiscalRstar({ ...currentVars, primary_balance: 2.0 });
    expect(better).toBeLessThan(base);
  });

  it('should increase r* when CDS rises', () => {
    const base = recalcFiscalRstar(currentVars);
    const higher = recalcFiscalRstar({ ...currentVars, cds_5y: 300 });
    expect(higher).toBeGreaterThan(base);
  });

  it('should produce much higher r* in stress scenario', () => {
    const base = recalcFiscalRstar(currentVars);
    const stress = recalcFiscalRstar({
      debt_gdp: 100,
      primary_balance: -4,
      cds_5y: 400,
      embi: 500,
      ipca_exp: 9.0,
    });
    expect(stress).toBeGreaterThan(base + 1); // At least 100bps higher
  });

  it('should produce lower r* in consolidation scenario', () => {
    const base = recalcFiscalRstar(currentVars);
    const consolidation = recalcFiscalRstar({
      debt_gdp: 75,
      primary_balance: 1.5,
      cds_5y: 120,
      embi: 110,
      ipca_exp: 4.5,
    });
    expect(consolidation).toBeLessThan(base);
  });

  it('should correctly propagate fiscal r* delta to composite', () => {
    const currentComposite = 4.75;
    const currentFiscalRstar = 6.42;
    const fiscalWeight = 0.15;

    // Fiscal r* increases by 1pp
    const newFiscalRstar = 7.42;
    const newComposite = recalcCompositeRstar(currentComposite, currentFiscalRstar, newFiscalRstar, fiscalWeight);

    // Delta should be 1.0 * 0.15 = 0.15pp
    expect(newComposite - currentComposite).toBeCloseTo(0.15, 2);
  });

  it('should not change composite when fiscal r* unchanged', () => {
    const currentComposite = 4.75;
    const currentFiscalRstar = 6.42;
    const fiscalWeight = 0.15;

    const newComposite = recalcCompositeRstar(currentComposite, currentFiscalRstar, currentFiscalRstar, fiscalWeight);
    expect(newComposite).toBeCloseTo(currentComposite, 4);
  });

  it('should calculate SELIC* correctly from r* + IPCA + term premium', () => {
    const rstar = 4.75;
    const ipcaExp = 5.8;
    const termPremium = -0.1;
    const selicStar = rstar + ipcaExp + termPremium;
    expect(selicStar).toBeCloseTo(10.45, 1);
  });

  it('should not produce negative r* for reasonable inputs', () => {
    const bestCase = recalcFiscalRstar({
      debt_gdp: 50,
      primary_balance: 4,
      cds_5y: 50,
      embi: 50,
      ipca_exp: 3,
    });
    expect(bestCase).toBeGreaterThanOrEqual(0);
  });
});
