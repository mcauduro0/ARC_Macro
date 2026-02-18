import { describe, it, expect } from "vitest";
import {
  generateB3Ticker,
  getNearestDI1Ticker,
  getNearestFXTicker,
  mapModelToB3,
  computeRiskBudget,
  sizeContracts,
  computeVaR,
  computeExposure,
  generateRebalancingPlan,
  computeFullPortfolio,
  B3_INSTRUMENTS,
  type MarketData,
  type ContractSizing,
} from "./portfolioEngine";

// Standard market data for testing
const MARKET_DATA: MarketData = {
  spotUsdbrl: 5.18,
  di1y: 13.90,
  di5y: 13.90,
  di10y: 14.40,
  embiSpread: 228,
  vol30d: 12.5,
  cdiDaily: 0.0545,
};

// Standard model weights (from actual model output)
const MODEL_WEIGHTS: Record<string, number> = {
  fx: -0.024,
  front: 0.499,
  belly: 0.0,
  long: 0.249,
  hard: 0.182,
  ntnb: 0.0,
};

const EXPECTED_RETURNS: Record<string, number> = {
  fx: 0.0963,
  front: 0.00404,
  belly: 0.0,
  long: 0.04379,
  hard: -0.0025,
  ntnb: 0.0,
};

describe("B3 Ticker Generation", () => {
  it("generates correct DI1 ticker", () => {
    expect(generateB3Ticker("DI1", 2027, 1)).toBe("DI1F27");
    expect(generateB3Ticker("DI1", 2026, 4)).toBe("DI1J26");
    expect(generateB3Ticker("DI1", 2030, 7)).toBe("DI1N30");
  });

  it("generates correct WDO ticker", () => {
    expect(generateB3Ticker("WDO", 2026, 3)).toBe("WDOH26");
    expect(generateB3Ticker("WDO", 2026, 12)).toBe("WDOZ26");
  });

  it("generates correct DOL ticker", () => {
    expect(generateB3Ticker("DOL", 2026, 6)).toBe("DOLM26");
  });

  it("getNearestDI1Ticker returns a valid DI1 ticker", () => {
    const ticker = getNearestDI1Ticker(1, new Date("2026-02-12"));
    expect(ticker).toMatch(/^DI1[FJNV]\d{2}$/);
  });

  it("getNearestDI1Ticker for 5Y returns ~5 years out", () => {
    const ticker = getNearestDI1Ticker(5, new Date("2026-02-12"));
    expect(ticker).toMatch(/^DI1[FJNV]3[01]$/);
  });

  it("getNearestDI1Ticker for 10Y returns ~10 years out", () => {
    const ticker = getNearestDI1Ticker(10, new Date("2026-02-12"));
    expect(ticker).toMatch(/^DI1[FJNV]3[56]$/);
  });

  it("getNearestFXTicker returns next month contract", () => {
    const ticker = getNearestFXTicker("WDO", new Date("2026-02-12"));
    expect(ticker).toBe("WDOH26"); // March 2026
  });

  it("getNearestFXTicker DOL returns next month contract", () => {
    const ticker = getNearestFXTicker("DOL", new Date("2026-02-12"));
    expect(ticker).toBe("DOLH26"); // March 2026
  });
});

describe("B3 Instrument Specifications", () => {
  it("has all required instruments", () => {
    expect(B3_INSTRUMENTS).toHaveProperty("DOL");
    expect(B3_INSTRUMENTS).toHaveProperty("WDO");
    expect(B3_INSTRUMENTS).toHaveProperty("DI1");
    expect(B3_INSTRUMENTS).toHaveProperty("FRA");
    expect(B3_INSTRUMENTS).toHaveProperty("DDI");
    expect(B3_INSTRUMENTS).toHaveProperty("NTNB");
  });

  it("DOL contract size is USD 50,000", () => {
    expect(B3_INSTRUMENTS.DOL.contractSize).toBe(50000);
  });

  it("WDO contract size is USD 10,000", () => {
    expect(B3_INSTRUMENTS.WDO.contractSize).toBe(10000);
  });

  it("DI1 contract size is R$ 100,000 PU", () => {
    expect(B3_INSTRUMENTS.DI1.contractSize).toBe(100000);
  });
});

describe("Model to B3 Mapping", () => {
  it("maps all 6 model instruments", () => {
    const mappings = mapModelToB3("WDO");
    expect(mappings).toHaveLength(6);
    const instruments = mappings.map(m => m.modelInstrument);
    expect(instruments).toContain("fx");
    expect(instruments).toContain("front");
    expect(instruments).toContain("belly");
    expect(instruments).toContain("long");
    expect(instruments).toContain("hard");
  });

  it("maps FX to WDO when preferred", () => {
    const mappings = mapModelToB3("WDO");
    const fx = mappings.find(m => m.modelInstrument === "fx");
    expect(fx?.b3Type).toBe("WDO");
  });

  it("maps FX to DOL when preferred", () => {
    const mappings = mapModelToB3("DOL");
    const fx = mappings.find(m => m.modelInstrument === "fx");
    expect(fx?.b3Type).toBe("DOL");
  });

  it("maps front to DI1 with ~1Y tenor", () => {
    const mappings = mapModelToB3("WDO");
    const front = mappings.find(m => m.modelInstrument === "front");
    expect(front?.b3Type).toBe("DI1");
    expect(front?.tenorYears).toBe(1);
  });

  it("maps long to DI1 with ~10Y tenor", () => {
    const mappings = mapModelToB3("WDO");
    const long = mappings.find(m => m.modelInstrument === "long");
    expect(long?.b3Type).toBe("DI1");
    expect(long?.tenorYears).toBe(10);
  });

  it("maps hard to DDI", () => {
    const mappings = mapModelToB3("WDO");
    const hard = mappings.find(m => m.modelInstrument === "hard");
    expect(hard?.b3Type).toBe("DDI");
  });
});

describe("Risk Budget Computation", () => {
  it("computes correct risk budget for R$ 100M AUM, 10% vol target", () => {
    const budget = computeRiskBudget(100_000_000, 0.10, MODEL_WEIGHTS, EXPECTED_RETURNS);
    expect(budget.aumBrl).toBe(100_000_000);
    expect(budget.volTargetAnnual).toBe(0.10);
    expect(budget.riskBudgetBrl).toBe(10_000_000); // 100M * 10%
    expect(budget.riskBudgetDaily).toBeCloseTo(10_000_000 / Math.sqrt(252), 0);
  });

  it("allocates risk proportionally to absolute weights", () => {
    const budget = computeRiskBudget(100_000_000, 0.10, MODEL_WEIGHTS, EXPECTED_RETURNS);
    const totalAbsWeight = Object.values(MODEL_WEIGHTS).reduce((s, w) => s + Math.abs(w), 0);
    expect(budget.totalWeightAbs).toBeCloseTo(totalAbsWeight, 4);
    expect(budget.grossLeverage).toBeCloseTo(totalAbsWeight, 4);
  });

  it("identifies correct directions", () => {
    const budget = computeRiskBudget(100_000_000, 0.10, MODEL_WEIGHTS, EXPECTED_RETURNS);
    const fxBudget = budget.instruments.find(i => i.instrument === "fx");
    expect(fxBudget?.direction).toBe("short");

    const frontBudget = budget.instruments.find(i => i.instrument === "front");
    expect(frontBudget?.direction).toBe("long");

    const bellyBudget = budget.instruments.find(i => i.instrument === "belly");
    expect(bellyBudget?.direction).toBe("flat");
  });

  it("risk allocations sum to risk budget", () => {
    const budget = computeRiskBudget(100_000_000, 0.10, MODEL_WEIGHTS, EXPECTED_RETURNS);
    const totalRisk = budget.instruments.reduce((s, i) => s + i.riskAllocationBrl, 0);
    expect(totalRisk).toBeCloseTo(budget.riskBudgetBrl * budget.totalWeightAbs, 0);
  });

  it("handles zero AUM gracefully", () => {
    const budget = computeRiskBudget(0, 0.10, MODEL_WEIGHTS);
    expect(budget.riskBudgetBrl).toBe(0);
    expect(budget.riskBudgetDaily).toBe(0);
  });
});

describe("Contract Sizing", () => {
  it("sizes FX contracts correctly", () => {
    const budget = computeRiskBudget(100_000_000, 0.10, MODEL_WEIGHTS, EXPECTED_RETURNS);
    const mappings = mapModelToB3("WDO");
    const positions = sizeContracts(budget, mappings, MARKET_DATA);

    const fx = positions.find(p => p.instrument === "fx");
    expect(fx).toBeDefined();
    expect(fx!.b3Type).toBe("WDO");
    expect(fx!.direction).toBe("short");
    expect(fx!.contracts).toBeGreaterThan(0);
    expect(fx!.notionalBrl).toBeGreaterThan(0);
    expect(fx!.fxDeltaBrl).not.toBeNull();
    expect(fx!.marginRequiredBrl).toBeGreaterThan(0);
  });

  it("sizes DI1 front contracts correctly", () => {
    const budget = computeRiskBudget(100_000_000, 0.10, MODEL_WEIGHTS, EXPECTED_RETURNS);
    const mappings = mapModelToB3("WDO");
    const positions = sizeContracts(budget, mappings, MARKET_DATA);

    const front = positions.find(p => p.instrument === "front");
    expect(front).toBeDefined();
    expect(front!.b3Type).toBe("DI1");
    expect(front!.direction).toBe("long");
    expect(front!.contracts).toBeGreaterThan(0);
    expect(front!.dv01Brl).not.toBeNull();
    expect(front!.dv01Brl!).toBeGreaterThan(0);
    expect(front!.entryPrice).toBe(13.90);
  });

  it("sizes DI1 long contracts correctly", () => {
    const budget = computeRiskBudget(100_000_000, 0.10, MODEL_WEIGHTS, EXPECTED_RETURNS);
    const mappings = mapModelToB3("WDO");
    const positions = sizeContracts(budget, mappings, MARKET_DATA);

    const long = positions.find(p => p.instrument === "long");
    expect(long).toBeDefined();
    expect(long!.b3Type).toBe("DI1");
    expect(long!.direction).toBe("long");
    expect(long!.contracts).toBeGreaterThan(0);
    expect(long!.dv01Brl).not.toBeNull();
  });

  it("flat belly has zero contracts", () => {
    const budget = computeRiskBudget(100_000_000, 0.10, MODEL_WEIGHTS, EXPECTED_RETURNS);
    const mappings = mapModelToB3("WDO");
    const positions = sizeContracts(budget, mappings, MARKET_DATA);

    const belly = positions.find(p => p.instrument === "belly");
    expect(belly).toBeDefined();
    expect(belly!.direction).toBe("flat");
    expect(belly!.contracts).toBe(0);
  });

  it("sizes DDI hard contracts correctly", () => {
    const budget = computeRiskBudget(100_000_000, 0.10, MODEL_WEIGHTS, EXPECTED_RETURNS);
    const mappings = mapModelToB3("WDO");
    const positions = sizeContracts(budget, mappings, MARKET_DATA);

    const hard = positions.find(p => p.instrument === "hard");
    expect(hard).toBeDefined();
    expect(hard!.b3Type).toBe("DDI");
    expect(hard!.direction).toBe("long");
    expect(hard!.contracts).toBeGreaterThan(0);
    expect(hard!.spreadDv01Usd).not.toBeNull();
  });

  it("all positions have positive margin requirements", () => {
    const budget = computeRiskBudget(100_000_000, 0.10, MODEL_WEIGHTS, EXPECTED_RETURNS);
    const mappings = mapModelToB3("WDO");
    const positions = sizeContracts(budget, mappings, MARKET_DATA);

    for (const pos of positions) {
      if (pos.contracts > 0) {
        expect(pos.marginRequiredBrl).toBeGreaterThan(0);
      }
    }
  });
});

describe("VaR Computation", () => {
  it("computes positive VaR values", () => {
    const budget = computeRiskBudget(100_000_000, 0.10, MODEL_WEIGHTS, EXPECTED_RETURNS);
    const mappings = mapModelToB3("WDO");
    const positions = sizeContracts(budget, mappings, MARKET_DATA);
    const varResult = computeVaR(positions, 100_000_000, MARKET_DATA);

    expect(varResult.varDaily95Brl).toBeGreaterThan(0);
    expect(varResult.varDaily99Brl).toBeGreaterThan(0);
    expect(varResult.varDaily99Brl).toBeGreaterThan(varResult.varDaily95Brl);
  });

  it("monthly VaR is larger than daily VaR", () => {
    const budget = computeRiskBudget(100_000_000, 0.10, MODEL_WEIGHTS, EXPECTED_RETURNS);
    const mappings = mapModelToB3("WDO");
    const positions = sizeContracts(budget, mappings, MARKET_DATA);
    const varResult = computeVaR(positions, 100_000_000, MARKET_DATA);

    expect(varResult.varMonthly95Brl).toBeGreaterThan(varResult.varDaily95Brl);
    expect(varResult.varMonthly99Brl).toBeGreaterThan(varResult.varDaily99Brl);
  });

  it("VaR as % of AUM is reasonable (< 5% daily)", () => {
    const budget = computeRiskBudget(100_000_000, 0.10, MODEL_WEIGHTS, EXPECTED_RETURNS);
    const mappings = mapModelToB3("WDO");
    const positions = sizeContracts(budget, mappings, MARKET_DATA);
    const varResult = computeVaR(positions, 100_000_000, MARKET_DATA);

    expect(varResult.varDaily95Pct).toBeLessThan(5);
    expect(varResult.varDaily95Pct).toBeGreaterThan(0);
  });

  it("has component VaR for all instruments", () => {
    const budget = computeRiskBudget(100_000_000, 0.10, MODEL_WEIGHTS, EXPECTED_RETURNS);
    const mappings = mapModelToB3("WDO");
    const positions = sizeContracts(budget, mappings, MARKET_DATA);
    const varResult = computeVaR(positions, 100_000_000, MARKET_DATA);

    expect(varResult.componentVar).toHaveLength(6);
  });

  it("has stress test scenarios", () => {
    const budget = computeRiskBudget(100_000_000, 0.10, MODEL_WEIGHTS, EXPECTED_RETURNS);
    const mappings = mapModelToB3("WDO");
    const positions = sizeContracts(budget, mappings, MARKET_DATA);
    const varResult = computeVaR(positions, 100_000_000, MARKET_DATA);

    expect(varResult.stressTests.length).toBeGreaterThan(0);
    for (const st of varResult.stressTests) {
      expect(st.name).toBeDefined();
      expect(typeof st.portfolioPnlBrl).toBe("number");
    }
  });
});

describe("Exposure Analytics", () => {
  it("computes gross and net exposure", () => {
    const budget = computeRiskBudget(100_000_000, 0.10, MODEL_WEIGHTS, EXPECTED_RETURNS);
    const mappings = mapModelToB3("WDO");
    const positions = sizeContracts(budget, mappings, MARKET_DATA);
    const exposure = computeExposure(positions, 100_000_000);

    expect(exposure.grossExposureBrl).toBeGreaterThan(0);
    expect(exposure.grossLeverage).toBeGreaterThan(0);
  });

  it("computes DV01 ladder", () => {
    const budget = computeRiskBudget(100_000_000, 0.10, MODEL_WEIGHTS, EXPECTED_RETURNS);
    const mappings = mapModelToB3("WDO");
    const positions = sizeContracts(budget, mappings, MARKET_DATA);
    const exposure = computeExposure(positions, 100_000_000);

    expect(exposure.dv01Ladder.length).toBeGreaterThan(0);
    expect(exposure.dv01TotalBrl).not.toBe(0);
  });

  it("margin utilization is reasonable (< 50%)", () => {
    const budget = computeRiskBudget(100_000_000, 0.10, MODEL_WEIGHTS, EXPECTED_RETURNS);
    const mappings = mapModelToB3("WDO");
    const positions = sizeContracts(budget, mappings, MARKET_DATA);
    const exposure = computeExposure(positions, 100_000_000);

    expect(exposure.marginUtilizationPct).toBeLessThan(50);
    expect(exposure.totalMarginBrl).toBeGreaterThan(0);
  });

  it("Herfindahl index is between 0 and 1", () => {
    const budget = computeRiskBudget(100_000_000, 0.10, MODEL_WEIGHTS, EXPECTED_RETURNS);
    const mappings = mapModelToB3("WDO");
    const positions = sizeContracts(budget, mappings, MARKET_DATA);
    const exposure = computeExposure(positions, 100_000_000);

    expect(exposure.herfindahlIndex).toBeGreaterThanOrEqual(0);
    expect(exposure.herfindahlIndex).toBeLessThanOrEqual(1);
  });
});

describe("Rebalancing Plan", () => {
  it("generates initial setup trades when no current positions", () => {
    const budget = computeRiskBudget(100_000_000, 0.10, MODEL_WEIGHTS, EXPECTED_RETURNS);
    const mappings = mapModelToB3("WDO");
    const targetPositions = sizeContracts(budget, mappings, MARKET_DATA);
    const plan = generateRebalancingPlan([], targetPositions, 100_000_000);

    expect(plan.trades.length).toBeGreaterThan(0);
    const activeTrades = plan.trades.filter(t => t.action !== "HOLD");
    expect(activeTrades.length).toBeGreaterThan(0);
    expect(plan.estimatedCostBrl).toBeGreaterThan(0);
  });

  it("generates HOLD when positions match target", () => {
    const budget = computeRiskBudget(100_000_000, 0.10, MODEL_WEIGHTS, EXPECTED_RETURNS);
    const mappings = mapModelToB3("WDO");
    const positions = sizeContracts(budget, mappings, MARKET_DATA);
    const plan = generateRebalancingPlan(positions, positions, 100_000_000);

    for (const trade of plan.trades) {
      expect(trade.action).toBe("HOLD");
    }
    expect(plan.estimatedCostBrl).toBe(0);
  });

  it("has reasonable turnover percentage", () => {
    const budget = computeRiskBudget(100_000_000, 0.10, MODEL_WEIGHTS, EXPECTED_RETURNS);
    const mappings = mapModelToB3("WDO");
    const targetPositions = sizeContracts(budget, mappings, MARKET_DATA);
    const plan = generateRebalancingPlan([], targetPositions, 100_000_000);

    expect(plan.turnoverPct).toBeGreaterThan(0);
  });

  it("has summary text", () => {
    const budget = computeRiskBudget(100_000_000, 0.10, MODEL_WEIGHTS, EXPECTED_RETURNS);
    const mappings = mapModelToB3("WDO");
    const targetPositions = sizeContracts(budget, mappings, MARKET_DATA);
    const plan = generateRebalancingPlan([], targetPositions, 100_000_000);

    expect(plan.summary.length).toBeGreaterThan(0);
  });
});

describe("Full Portfolio Computation", () => {
  it("computes full portfolio end-to-end", () => {
    const result = computeFullPortfolio(
      100_000_000,
      0.10,
      "WDO",
      MODEL_WEIGHTS,
      EXPECTED_RETURNS,
      MARKET_DATA,
      [],
      { regime_dominant: "carry", score_total: 4.01, taylor_gap: 2.86, fx_misalignment: 44.3 }
    );

    expect(result.config.aumBrl).toBe(100_000_000);
    expect(result.config.volTargetAnnual).toBe(0.10);
    expect(result.riskBudget).toBeDefined();
    expect(result.positions.length).toBeGreaterThan(0);
    expect(result.var).toBeDefined();
    expect(result.exposure).toBeDefined();
    expect(result.rebalancingPlan).toBeDefined();
    expect(result.interpretation).toBeDefined();
  });

  it("interpretation has macro view", () => {
    const result = computeFullPortfolio(
      100_000_000,
      0.10,
      "WDO",
      MODEL_WEIGHTS,
      EXPECTED_RETURNS,
      MARKET_DATA,
      [],
      { regime_dominant: "carry", score_total: 4.01, taylor_gap: 2.86, fx_misalignment: 44.3 }
    );

    expect(result.interpretation.macroView.length).toBeGreaterThan(0);
    expect(result.interpretation.positionRationale).toBeDefined();
    expect(result.interpretation.riskAssessment.length).toBeGreaterThan(0);
    expect(result.interpretation.actionItems.length).toBeGreaterThan(0);
  });

  it("interpretation mentions Taylor gap when positive", () => {
    const result = computeFullPortfolio(
      100_000_000,
      0.10,
      "WDO",
      MODEL_WEIGHTS,
      EXPECTED_RETURNS,
      MARKET_DATA,
      [],
      { regime_dominant: "carry", score_total: 4.01, taylor_gap: 2.86, fx_misalignment: 44.3 }
    );

    expect(result.interpretation.macroView).toContain("acima do equilíbrio Taylor");
  });

  it("interpretation mentions FX misalignment when large", () => {
    const result = computeFullPortfolio(
      100_000_000,
      0.10,
      "WDO",
      MODEL_WEIGHTS,
      EXPECTED_RETURNS,
      MARKET_DATA,
      [],
      { regime_dominant: "carry", score_total: 4.01, taylor_gap: 2.86, fx_misalignment: 44.3 }
    );

    expect(result.interpretation.macroView).toContain("desvalorizado");
  });

  it("works with DOL preference", () => {
    const result = computeFullPortfolio(
      100_000_000,
      0.10,
      "DOL",
      MODEL_WEIGHTS,
      EXPECTED_RETURNS,
      MARKET_DATA
    );

    const fx = result.positions.find(p => p.instrument === "fx");
    expect(fx?.b3Type).toBe("DOL");
  });

  it("scales linearly with AUM", () => {
    const result100M = computeFullPortfolio(
      100_000_000, 0.10, "WDO", MODEL_WEIGHTS, EXPECTED_RETURNS, MARKET_DATA
    );
    const result200M = computeFullPortfolio(
      200_000_000, 0.10, "WDO", MODEL_WEIGHTS, EXPECTED_RETURNS, MARKET_DATA
    );

    expect(result200M.riskBudget.riskBudgetBrl).toBe(2 * result100M.riskBudget.riskBudgetBrl);

    // Contracts should roughly double (with rounding)
    const fxContracts100 = result100M.positions.find(p => p.instrument === "fx")?.contracts || 0;
    const fxContracts200 = result200M.positions.find(p => p.instrument === "fx")?.contracts || 0;
    if (fxContracts100 > 0) {
      expect(fxContracts200 / fxContracts100).toBeCloseTo(2, 0);
    }
  });
});
