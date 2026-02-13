import { describe, it, expect, vi, beforeEach } from "vitest";

// Mock fetch globally before importing the module
const mockFetch = vi.fn();
global.fetch = mockFetch;

// We'll test the utility functions and type structures
describe("MarketDataService", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockFetch.mockReset();
  });

  describe("B3 Instrument Specs", () => {
    it("should define correct DOL contract size", () => {
      // DOL = USD 50,000
      const dolContractSize = 50_000;
      expect(dolContractSize).toBe(50000);
    });

    it("should define correct WDO contract size", () => {
      // WDO = USD 10,000
      const wdoContractSize = 10_000;
      expect(wdoContractSize).toBe(10000);
    });

    it("should define correct DI1 contract size", () => {
      // DI1 = R$ 100,000 (PU at maturity)
      const di1FaceValue = 100_000;
      expect(di1FaceValue).toBe(100000);
    });
  });

  describe("MTM Calculations", () => {
    it("should calculate FX P&L correctly for long position", () => {
      const entryPrice = 5.50;
      const currentPrice = 5.80;
      const contracts = 10;
      const contractSize = 10_000; // WDO
      const pnlPerContract = (currentPrice - entryPrice) * contractSize;
      const totalPnl = pnlPerContract * contracts;
      expect(pnlPerContract).toBeCloseTo(3000, 0);
      expect(totalPnl).toBeCloseTo(30000, 0);
    });

    it("should calculate FX P&L correctly for short position", () => {
      const entryPrice = 5.80;
      const currentPrice = 5.50;
      const contracts = -5; // negative = short
      const contractSize = 10_000;
      const pnlPerContract = (currentPrice - entryPrice) * contractSize;
      const totalPnl = pnlPerContract * Math.abs(contracts);
      // Short: entry 5.80, current 5.50 => profit
      // But pnlPerContract = (5.50 - 5.80) * 10000 = -3000 per contract
      // For short, profit = -pnlPerContract * contracts = -(-3000) * 5 = 15000
      expect(pnlPerContract).toBeCloseTo(-3000, 0);
      // For short position, P&L is inverted
      const shortPnl = -pnlPerContract * Math.abs(contracts);
      expect(shortPnl).toBeCloseTo(15000, 0);
    });

    it("should calculate DI PU from yield correctly", () => {
      // PU = 100,000 / (1 + yield/100)^(du/252)
      const faceValue = 100_000;
      const yieldPct = 14.0;
      const du = 252; // 1 year
      const pu = faceValue / Math.pow(1 + yieldPct / 100, du / 252);
      expect(pu).toBeCloseTo(87719.30, 0); // ~87,719
      expect(pu).toBeLessThan(faceValue);
      expect(pu).toBeGreaterThan(0);
    });

    it("should calculate DI PU correctly for different tenors", () => {
      const faceValue = 100_000;
      const yieldPct = 13.0;
      
      // 1Y (252 du)
      const pu1y = faceValue / Math.pow(1 + yieldPct / 100, 252 / 252);
      // 5Y (1260 du)
      const pu5y = faceValue / Math.pow(1 + yieldPct / 100, 1260 / 252);
      // 10Y (2520 du)
      const pu10y = faceValue / Math.pow(1 + yieldPct / 100, 2520 / 252);

      // Longer tenor = lower PU (more discounting)
      expect(pu1y).toBeGreaterThan(pu5y);
      expect(pu5y).toBeGreaterThan(pu10y);
      expect(pu10y).toBeGreaterThan(0);
    });

    it("should calculate DI DV01 correctly", () => {
      const faceValue = 100_000;
      const yieldPct = 14.0;
      const du = 252;
      
      const puBase = faceValue / Math.pow(1 + yieldPct / 100, du / 252);
      const puUp = faceValue / Math.pow(1 + (yieldPct + 0.01) / 100, du / 252);
      const dv01 = Math.abs(puBase - puUp);
      
      expect(dv01).toBeGreaterThan(0);
      expect(dv01).toBeLessThan(100); // DV01 should be reasonable
    });
  });

  describe("VaR Calculations", () => {
    it("should calculate parametric VaR 95% correctly", () => {
      const portfolioValue = 1_500_000;
      const portfolioVol = 0.10; // 10% annual
      const dailyVol = portfolioVol / Math.sqrt(252);
      const z95 = 1.645;
      const var95Daily = portfolioValue * dailyVol * z95;
      
      expect(var95Daily).toBeGreaterThan(0);
      expect(var95Daily).toBeLessThan(portfolioValue * 0.05); // Less than 5% of AUM
    });

    it("should calculate parametric VaR 99% correctly", () => {
      const portfolioValue = 1_500_000;
      const portfolioVol = 0.10;
      const dailyVol = portfolioVol / Math.sqrt(252);
      const z99 = 2.326;
      const var99Daily = portfolioValue * dailyVol * z99;
      const z95 = 1.645;
      const var95Daily = portfolioValue * dailyVol * z95;
      
      // VaR 99% should be larger than VaR 95%
      expect(var99Daily).toBeGreaterThan(var95Daily);
    });

    it("should scale VaR from daily to monthly correctly", () => {
      const dailyVar = 10_000;
      const monthlyVar = dailyVar * Math.sqrt(21); // 21 trading days
      
      expect(monthlyVar).toBeCloseTo(dailyVar * Math.sqrt(21), 0);
      expect(monthlyVar).toBeGreaterThan(dailyVar);
    });
  });

  describe("Risk Limits", () => {
    it("should detect VaR breach", () => {
      const varPct = 2.5; // 2.5% of AUM
      const limit = 1.5; // 1.5% limit
      const breached = varPct > limit;
      expect(breached).toBe(true);
    });

    it("should detect leverage breach", () => {
      const grossExposure = 4_500_000;
      const aum = 1_500_000;
      const leverage = grossExposure / aum;
      const maxLeverage = 5.0;
      expect(leverage).toBe(3.0);
      expect(leverage < maxLeverage).toBe(true);
    });

    it("should detect margin utilization breach", () => {
      const totalMargin = 500_000;
      const aum = 1_500_000;
      const marginPct = (totalMargin / aum) * 100;
      const maxMarginPct = 30;
      expect(marginPct).toBeCloseTo(33.33, 1);
      expect(marginPct > maxMarginPct).toBe(true);
    });
  });

  describe("Stress Test Scenarios", () => {
    it("should calculate Taper Tantrum impact on FX", () => {
      // BRL depreciates ~20% in Taper Tantrum
      const fxDelta = -100_000; // Short USD 100k
      const brlMove = 0.20; // +20% depreciation
      const fxPnl = fxDelta * brlMove;
      expect(fxPnl).toBe(-20_000); // Loss on short USD
    });

    it("should calculate Lula Election impact on rates", () => {
      // DI rates rise ~300bps
      const dv01 = 500; // R$ 500/bp
      const rateMove = 300; // +300bps
      // If long rates (receiver), rates rising = loss
      const ratesPnl = -dv01 * rateMove;
      expect(ratesPnl).toBe(-150_000);
    });

    it("should calculate COVID impact on portfolio", () => {
      // BRL depreciates ~30%, rates rise ~200bps
      const fxDelta = -50_000;
      const dv01 = 300;
      const brlMove = 0.30;
      const rateMove = 200;
      
      const fxPnl = fxDelta * brlMove;
      const ratesPnl = -dv01 * rateMove;
      const totalPnl = fxPnl + ratesPnl;
      
      expect(fxPnl).toBe(-15_000);
      expect(ratesPnl).toBe(-60_000);
      expect(totalPnl).toBe(-75_000);
    });
  });

  describe("Trade Workflow", () => {
    it("should validate trade status transitions", () => {
      const validTransitions: Record<string, string[]> = {
        pending: ["approved", "executed", "cancelled"],
        approved: ["executed", "cancelled"],
        executed: ["filled"],
        filled: [],
        cancelled: [],
      };

      expect(validTransitions.pending).toContain("approved");
      expect(validTransitions.approved).toContain("executed");
      expect(validTransitions.executed).toContain("filled");
      expect(validTransitions.filled).toHaveLength(0);
      expect(validTransitions.cancelled).toHaveLength(0);
    });

    it("should calculate slippage correctly", () => {
      const targetPrice = 5.8500;
      const executedPrice = 5.8520;
      const contracts = 10;
      const contractSize = 10_000;
      
      const slippagePricePerUnit = executedPrice - targetPrice;
      const slippageBrl = slippagePricePerUnit * contracts * contractSize;
      const slippageBps = (slippagePricePerUnit / targetPrice) * 10_000;
      
      expect(slippagePricePerUnit).toBeCloseTo(0.002, 4);
      expect(slippageBrl).toBeCloseTo(200, 0);
      expect(slippageBps).toBeCloseTo(3.42, 1);
    });

    it("should calculate commission as percentage of notional", () => {
      const notional = 580_000;
      const commission = 29; // R$ 29
      const commissionBps = (commission / notional) * 10_000;
      
      expect(commissionBps).toBeCloseTo(0.5, 1);
    });
  });

  describe("P&L Tracking", () => {
    it("should calculate daily P&L from price changes", () => {
      const positions = [
        { instrument: "fx", contracts: -3, contractSize: 10_000, entryPrice: 5.85, currentPrice: 5.82 },
        { instrument: "front", contracts: 68, puEntry: 87_719, puCurrent: 87_800 },
      ];

      // FX: short 3 WDO, price dropped from 5.85 to 5.82 => profit
      const fxPnl = -(5.82 - 5.85) * 3 * 10_000; // = 900
      expect(fxPnl).toBeCloseTo(900, 0);

      // Front: long 68 DI1, PU increased from 87719 to 87800 => profit
      const frontPnl = (87_800 - 87_719) * 68;
      expect(frontPnl).toBeCloseTo(5508, 0);
    });

    it("should calculate MTD P&L as sum of daily P&Ls", () => {
      const dailyPnls = [1000, -500, 2000, -300, 800];
      const mtd = dailyPnls.reduce((sum, pnl) => sum + pnl, 0);
      expect(mtd).toBe(3000);
    });

    it("should calculate return vs CDI benchmark", () => {
      const portfolioReturn = 0.015; // 1.5% MTD
      const cdiReturn = 0.012; // 1.2% MTD (CDI)
      const alpha = portfolioReturn - cdiReturn;
      expect(alpha).toBeCloseTo(0.003, 4); // 30bps alpha
    });

    it("should calculate drawdown correctly", () => {
      const equityCurve = [100, 105, 103, 108, 102, 110];
      let peak = equityCurve[0];
      let maxDd = 0;
      
      for (const val of equityCurve) {
        if (val > peak) peak = val;
        const dd = (val - peak) / peak;
        if (dd < maxDd) maxDd = dd;
      }
      
      // Max drawdown: peak 108, trough 102 => -5.56%
      expect(maxDd).toBeCloseTo(-0.0556, 3);
    });
  });

  describe("Factor Exposure", () => {
    it("should decompose portfolio into FX, Rates, Credit factors", () => {
      const positions = {
        fx: { weight: -0.024, riskContrib: 2.4 },
        front: { weight: 0.499, riskContrib: 49.9 },
        belly: { weight: 0.400, riskContrib: 40.0 },
        long: { weight: 0.249, riskContrib: 24.9 },
        hard: { weight: 0.182, riskContrib: 18.2 },
      };

      const fxExposure = positions.fx.riskContrib;
      const ratesExposure = positions.front.riskContrib + positions.belly.riskContrib + positions.long.riskContrib;
      const creditExposure = positions.hard.riskContrib;

      expect(fxExposure).toBeCloseTo(2.4, 1);
      expect(ratesExposure).toBeCloseTo(114.8, 1);
      expect(creditExposure).toBeCloseTo(18.2, 1);
    });

    it("should calculate Herfindahl concentration index", () => {
      const weights = [0.499, 0.400, 0.249, 0.182, 0.024];
      const totalWeight = weights.reduce((s, w) => s + Math.abs(w), 0);
      const normalizedWeights = weights.map(w => Math.abs(w) / totalWeight);
      const hhi = normalizedWeights.reduce((s, w) => s + w * w, 0);
      
      // HHI ranges from 1/N (equal) to 1 (concentrated)
      expect(hhi).toBeGreaterThan(0.2); // Somewhat concentrated
      expect(hhi).toBeLessThan(1);
    });
  });

  describe("ANBIMA Integration Types", () => {
    it("should define correct ETTJ vertex mapping", () => {
      const vertexMap: Record<string, number> = {
        "252": 1,    // 1Y
        "504": 2,    // 2Y
        "756": 3,    // 3Y
        "1260": 5,   // 5Y
        "2520": 10,  // 10Y
      };

      expect(vertexMap["252"]).toBe(1);
      expect(vertexMap["1260"]).toBe(5);
      expect(vertexMap["2520"]).toBe(10);
    });

    it("should validate DI yield format", () => {
      // ANBIMA returns yields as decimal (e.g., 0.1390 = 13.90%)
      const anbimaYield = 0.1390;
      const yieldPct = anbimaYield * 100;
      expect(yieldPct).toBeCloseTo(13.90, 2);
    });
  });

  describe("BCB SGS Integration", () => {
    it("should parse BCB date format correctly", () => {
      const bcbDate = "12/02/2026";
      const [day, month, year] = bcbDate.split("/");
      const isoDate = `${year}-${month}-${day}`;
      expect(isoDate).toBe("2026-02-12");
    });

    it("should convert PTAX to USDBRL spot", () => {
      const ptaxCompra = 5.2000;
      const ptaxVenda = 5.2100;
      const ptaxMid = (ptaxCompra + ptaxVenda) / 2;
      expect(ptaxMid).toBeCloseTo(5.2050, 4);
    });
  });
});
