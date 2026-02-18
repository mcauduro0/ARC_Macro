/**
 * Portfolio Engine — Institutional-grade portfolio management for B3/BMF instruments.
 *
 * Translates ARC Macro model weights into:
 *   1. Risk budget allocation (AUM → vol target → risk units)
 *   2. B3 instrument mapping (DOL/WDO, DI1, FRA, DDI, NTN-B)
 *   3. Contract sizing (notional → contracts with rounding)
 *   4. VaR computation (parametric delta-normal, component VaR)
 *   5. Exposure analytics (gross/net, DV01 ladder, FX delta)
 *   6. Rebalancing engine (current vs target, trade list, cost estimation)
 *
 * Best practices from Bridgewater, Brevan Howard, SPX Capital, Verde AM.
 */

// ============================================================
// B3/BMF INSTRUMENT SPECIFICATIONS
// ============================================================

export interface B3InstrumentSpec {
  type: string;           // DOL, WDO, DI1, FRA, DDI, NTNB
  name: string;           // Human-readable name
  contractSize: number;   // Size per contract
  contractUnit: string;   // BRL, USD, PU, etc.
  tickSize: number;       // Minimum price increment
  tickValue: number;      // Value per tick in BRL
  marginPct: number;      // Initial margin as % of notional
  tradingHours: string;   // Trading hours (BRT)
  settlement: string;     // Settlement type
  monthCodes: string;     // Available month codes
}

export const B3_INSTRUMENTS: Record<string, B3InstrumentSpec> = {
  DOL: {
    type: "DOL",
    name: "Dólar Futuro (Cheio)",
    contractSize: 50000,    // USD 50,000 per contract
    contractUnit: "USD",
    tickSize: 0.5,          // R$ 0.50 per USD 1,000
    tickValue: 25,          // R$ 25 per tick
    marginPct: 0.05,        // ~5% margin
    tradingHours: "09:00-18:00 BRT",
    settlement: "Cash (D+1)",
    monthCodes: "FGHJKMNQUVXZ",
  },
  WDO: {
    type: "WDO",
    name: "Mini Dólar Futuro",
    contractSize: 10000,    // USD 10,000 per contract
    contractUnit: "USD",
    tickSize: 0.5,
    tickValue: 5,           // R$ 5 per tick
    marginPct: 0.05,
    tradingHours: "09:00-18:00 BRT",
    settlement: "Cash (D+1)",
    monthCodes: "FGHJKMNQUVXZ",
  },
  DI1: {
    type: "DI1",
    name: "Futuro de DI (Taxa de Juros)",
    contractSize: 100000,   // R$ 100,000 PU at maturity
    contractUnit: "BRL_PU",
    tickSize: 0.005,        // 0.5 bps
    tickValue: 0,           // Depends on DV01
    marginPct: 0.02,        // ~2% margin
    tradingHours: "09:00-18:00 BRT",
    settlement: "Cash (D+1)",
    monthCodes: "FGHJKMNQUVXZ",
  },
  FRA: {
    type: "FRA",
    name: "FRA de DI (Forward Rate Agreement)",
    contractSize: 100000,
    contractUnit: "BRL_PU",
    tickSize: 0.005,
    tickValue: 0,
    marginPct: 0.03,
    tradingHours: "09:00-18:00 BRT",
    settlement: "Cash (D+1)",
    monthCodes: "FGHJKMNQUVXZ",
  },
  DDI: {
    type: "DDI",
    name: "Futuro de Cupom Cambial (DDI)",
    contractSize: 50000,    // USD 50,000
    contractUnit: "USD",
    tickSize: 0.001,
    tickValue: 50,
    marginPct: 0.04,
    tradingHours: "09:00-18:00 BRT",
    settlement: "Cash (D+1)",
    monthCodes: "FGHJKMNQUVXZ",
  },
  NTNB: {
    type: "NTNB",
    name: "NTN-B (Tesouro IPCA+)",
    contractSize: 1000,     // R$ 1,000 face value
    contractUnit: "BRL",
    tickSize: 0.01,
    tickValue: 10,
    marginPct: 0.10,
    tradingHours: "09:00-18:00 BRT",
    settlement: "D+1",
    monthCodes: "FGHJKMNQUVXZ",
  },
};

// Month code mapping
const MONTH_CODES: Record<number, string> = {
  1: "F", 2: "G", 3: "H", 4: "J", 5: "K", 6: "M",
  7: "N", 8: "Q", 9: "U", 10: "V", 11: "X", 12: "Z",
};

// ============================================================
// B3 TICKER GENERATION
// ============================================================

/**
 * Generate B3 ticker for a given instrument and target date.
 * DI1F27 = DI1 Jan/2027, WDOH26 = WDO Mar/2026
 */
export function generateB3Ticker(instrumentType: string, targetYear: number, targetMonth: number): string {
  const monthCode = MONTH_CODES[targetMonth] || "F";
  const yearSuffix = String(targetYear).slice(-2);
  return `${instrumentType}${monthCode}${yearSuffix}`;
}

/**
 * Get the nearest liquid DI1 contract for a given tenor (in years).
 * DI1 contracts expire on the 1st business day of the month.
 * Most liquid: Jan (F), Apr (J), Jul (N), Oct (V)
 */
export function getNearestDI1Ticker(tenorYears: number, referenceDate: Date = new Date()): string {
  const targetDate = new Date(referenceDate);
  targetDate.setFullYear(targetDate.getFullYear() + tenorYears);

  // Snap to nearest liquid month (Jan, Apr, Jul, Oct)
  const liquidMonths = [1, 4, 7, 10];
  const targetMonth = targetDate.getMonth() + 1;
  let bestMonth = liquidMonths[0];
  let bestDist = 12;
  for (const m of liquidMonths) {
    const dist = Math.abs(m - targetMonth);
    if (dist < bestDist) {
      bestDist = dist;
      bestMonth = m;
    }
  }

  let year = targetDate.getFullYear();
  if (bestMonth < targetMonth && bestDist > 1) {
    year += 1;
  }

  return generateB3Ticker("DI1", year, bestMonth);
}

/**
 * Get the nearest liquid FX contract (DOL or WDO).
 * FX futures expire on the 1st business day of the month.
 * Front month is always the most liquid.
 */
export function getNearestFXTicker(type: "DOL" | "WDO", referenceDate: Date = new Date()): string {
  const nextMonth = new Date(referenceDate);
  nextMonth.setMonth(nextMonth.getMonth() + 1);
  return generateB3Ticker(type, nextMonth.getFullYear(), nextMonth.getMonth() + 1);
}

// ============================================================
// INSTRUMENT MAPPING: Model → B3
// ============================================================

export interface InstrumentMapping {
  modelInstrument: string;   // fx, front, belly, long, hard
  b3Type: string;            // DOL, WDO, DI1, FRA, DDI, NTNB
  b3Ticker: string;          // e.g. WDOH26, DI1F27
  tenorYears: number;        // approximate tenor
  duration: number;          // modified duration
  contractSpec: B3InstrumentSpec;
}

/**
 * Map model instruments to B3 contracts.
 * Returns the optimal B3 instrument for each model position.
 */
export function mapModelToB3(
  fxPreference: "DOL" | "WDO" = "WDO",
  referenceDate: Date = new Date()
): InstrumentMapping[] {
  return [
    {
      modelInstrument: "fx",
      b3Type: fxPreference,
      b3Ticker: getNearestFXTicker(fxPreference, referenceDate),
      tenorYears: 1 / 12,  // 1 month
      duration: 0,
      contractSpec: B3_INSTRUMENTS[fxPreference],
    },
    {
      modelInstrument: "front",
      b3Type: "DI1",
      b3Ticker: getNearestDI1Ticker(1, referenceDate),
      tenorYears: 1,
      duration: 0.95,  // ~1Y duration
      contractSpec: B3_INSTRUMENTS.DI1,
    },
    {
      modelInstrument: "belly",
      b3Type: "DI1",
      b3Ticker: getNearestDI1Ticker(5, referenceDate),
      tenorYears: 5,
      duration: 4.2,  // ~5Y duration
      contractSpec: B3_INSTRUMENTS.DI1,
    },
    {
      modelInstrument: "long",
      b3Type: "DI1",
      b3Ticker: getNearestDI1Ticker(10, referenceDate),
      tenorYears: 10,
      duration: 7.5,  // ~10Y duration
      contractSpec: B3_INSTRUMENTS.DI1,
    },
    {
      modelInstrument: "hard",
      b3Type: "DDI",
      b3Ticker: getNearestDI1Ticker(5, referenceDate).replace("DI1", "DDI"),
      tenorYears: 5,
      duration: 4.5,
      contractSpec: B3_INSTRUMENTS.DDI,
    },
    {
      modelInstrument: "ntnb",
      b3Type: "NTNB",
      b3Ticker: `NTNB${referenceDate.getFullYear() + 5}`,
      tenorYears: 5,
      duration: 4.5,
      contractSpec: B3_INSTRUMENTS.NTNB,
    },
  ];
}

// ============================================================
// RISK BUDGET CALCULATOR
// ============================================================

export interface RiskBudget {
  aumBrl: number;
  volTargetAnnual: number;
  riskBudgetBrl: number;          // AUM * volTarget
  riskBudgetDaily: number;        // riskBudgetBrl / sqrt(252)
  instruments: InstrumentRiskBudget[];
  totalWeightAbs: number;
  grossLeverage: number;
}

export interface InstrumentRiskBudget {
  instrument: string;
  modelWeight: number;
  direction: "long" | "short" | "flat";
  riskAllocationBrl: number;      // |weight| * riskBudget
  riskAllocationPct: number;      // % of total risk
  expectedReturnAnnual: number;   // E[r] from model
  sharpeContribution: number;     // weight * E[r] / vol
}

/**
 * Compute risk budget allocation from model weights.
 */
export function computeRiskBudget(
  aumBrl: number,
  volTargetAnnual: number,
  modelWeights: Record<string, number>,
  expectedReturns: Record<string, number> = {}
): RiskBudget {
  const riskBudgetBrl = aumBrl * volTargetAnnual;
  const riskBudgetDaily = riskBudgetBrl / Math.sqrt(252);

  const totalWeightAbs = Object.values(modelWeights).reduce((sum, w) => sum + Math.abs(w), 0);

  const instruments: InstrumentRiskBudget[] = Object.entries(modelWeights).map(([inst, weight]) => {
    const absWeight = Math.abs(weight);
    const direction: "long" | "short" | "flat" = weight > 0.001 ? "long" : weight < -0.001 ? "short" : "flat";

    return {
      instrument: inst,
      modelWeight: weight,
      direction,
      riskAllocationBrl: absWeight * riskBudgetBrl,
      riskAllocationPct: totalWeightAbs > 0 ? (absWeight / totalWeightAbs) * 100 : 0,
      expectedReturnAnnual: (expectedReturns[inst] || 0) * 12,  // monthly → annual
      sharpeContribution: weight * (expectedReturns[inst] || 0),
    };
  });

  return {
    aumBrl,
    volTargetAnnual,
    riskBudgetBrl,
    riskBudgetDaily,
    instruments,
    totalWeightAbs,
    grossLeverage: totalWeightAbs,
  };
}

// ============================================================
// CONTRACT SIZING ENGINE
// ============================================================

export interface ContractSizing {
  instrument: string;
  b3Ticker: string;
  b3Type: string;
  direction: "long" | "short" | "flat";
  // Risk metrics
  modelWeight: number;
  riskAllocationBrl: number;
  // Notional
  notionalBrl: number;
  notionalUsd: number;
  // Contracts
  contractsExact: number;        // exact (fractional)
  contracts: number;             // rounded to nearest integer
  contractSize: number;
  contractUnit: string;
  // DV01 / Delta
  dv01Brl: number | null;       // for rates instruments
  fxDeltaBrl: number | null;    // for FX instruments
  spreadDv01Usd: number | null; // for hard currency
  // Margin
  marginRequiredBrl: number;
  marginPct: number;
  // Entry reference
  entryPrice: number;           // spot/yield at entry
}

export interface MarketData {
  spotUsdbrl: number;
  di1y: number;        // DI 1Y yield (%)
  di5y: number;        // DI 5Y yield (%)
  di10y: number;       // DI 10Y yield (%)
  embiSpread: number;  // EMBI spread (bps)
  vol30d: number;      // USDBRL 30d vol (%)
  cdiDaily: number;    // CDI daily rate (%)
}

/**
 * Size contracts for each instrument based on risk budget and market data.
 * This is the core function that translates model weights into tradeable positions.
 */
export function sizeContracts(
  riskBudget: RiskBudget,
  mappings: InstrumentMapping[],
  marketData: MarketData
): ContractSizing[] {
  const results: ContractSizing[] = [];

  for (const instBudget of riskBudget.instruments) {
    const mapping = mappings.find(m => m.modelInstrument === instBudget.instrument);
    if (!mapping) continue;

    const weight = instBudget.modelWeight;
    const absRisk = instBudget.riskAllocationBrl;
    const direction = instBudget.direction;
    const spec = mapping.contractSpec;

    let notionalBrl = 0;
    let notionalUsd = 0;
    let contractsExact = 0;
    let dv01Brl: number | null = null;
    let fxDeltaBrl: number | null = null;
    let spreadDv01Usd: number | null = null;
    let entryPrice = 0;

    switch (instBudget.instrument) {
      case "fx": {
        // FX: Notional = Risk / Vol30d
        const vol = marketData.vol30d / 100;
        notionalBrl = absRisk / (vol > 0 ? vol : 0.15);
        notionalUsd = notionalBrl / marketData.spotUsdbrl;
        contractsExact = notionalUsd / spec.contractSize;
        fxDeltaBrl = notionalBrl * (weight > 0 ? -1 : 1); // short USD = negative delta
        entryPrice = marketData.spotUsdbrl;
        break;
      }
      case "front": {
        // Front-End DI 1Y: DV01 = Risk / (Yield * Duration)
        const yield1y = marketData.di1y / 100;
        const duration = mapping.duration;
        dv01Brl = absRisk / (yield1y * duration * 10000);  // DV01 per bp
        // DI1 PU = 100000 / (1 + yield)^(du/252)
        // DV01 per contract ≈ PU * duration / 10000
        const du252 = duration * 252;
        const pu = 100000 / Math.pow(1 + yield1y, du252 / 252);
        const dv01PerContract = pu * duration / 10000;
        contractsExact = dv01PerContract > 0 ? (dv01Brl / dv01PerContract) : 0;
        notionalBrl = contractsExact * pu;
        entryPrice = marketData.di1y;
        break;
      }
      case "belly": {
        // Belly DI 5Y
        const yield5y = marketData.di5y / 100;
        const duration = mapping.duration;
        dv01Brl = absRisk / (yield5y * duration * 10000);
        const du252 = duration * 252;
        const pu = 100000 / Math.pow(1 + yield5y, du252 / 252);
        const dv01PerContract = pu * duration / 10000;
        contractsExact = dv01PerContract > 0 ? (dv01Brl / dv01PerContract) : 0;
        notionalBrl = contractsExact * pu;
        entryPrice = marketData.di5y;
        break;
      }
      case "long": {
        // Long-End DI 10Y
        const yield10y = marketData.di10y / 100;
        const duration = mapping.duration;
        dv01Brl = absRisk / (yield10y * duration * 10000);
        const du252 = duration * 252;
        const pu = 100000 / Math.pow(1 + yield10y, du252 / 252);
        const dv01PerContract = pu * duration / 10000;
        contractsExact = dv01PerContract > 0 ? (dv01Brl / dv01PerContract) : 0;
        notionalBrl = contractsExact * pu;
        entryPrice = marketData.di10y;
        break;
      }
      case "hard": {
        // Hard Currency via DDI (cupom cambial)
        // DDI represents the USD interest rate in Brazil
        // Use DV01-based sizing similar to DI contracts
        // DDI DV01 per contract ≈ USD 50k * duration / 10000
        const hardDuration = mapping.duration; // ~5 years for DDI
        const spreadBps = marketData.embiSpread > 0 ? marketData.embiSpread : 200;
        // Spread DV01 target in USD
        spreadDv01Usd = absRisk / (marketData.spotUsdbrl * spreadBps);
        // DV01 per DDI contract in USD
        const dv01PerDdiContract = spec.contractSize * hardDuration / 10000;
        contractsExact = dv01PerDdiContract > 0 ? (spreadDv01Usd / dv01PerDdiContract) : 0;
        // Cap notional at 2x AUM to prevent excessive leverage
        const maxContractsFromAum = (riskBudget.aumBrl * 2) / (spec.contractSize * marketData.spotUsdbrl);
        if (Math.abs(contractsExact) > maxContractsFromAum) {
          contractsExact = maxContractsFromAum * Math.sign(contractsExact || 1);
        }
        notionalUsd = Math.abs(contractsExact) * spec.contractSize;
        notionalBrl = notionalUsd * marketData.spotUsdbrl;
        entryPrice = marketData.embiSpread;
        break;
      }
      case "ntnb": {
        // NTN-B (Tesouro IPCA+): Duration-based sizing similar to DI
        // Real yield ≈ DI5Y - IPCA expectations
        const realYield = (marketData.di5y - 4.5) / 100; // proxy: DI5Y minus ~4.5% IPCA exp
        const ntnbDuration = mapping.duration;
        dv01Brl = absRisk / (Math.max(realYield, 0.03) * ntnbDuration * 10000);
        // NTN-B PU based on real yield
        const ntnbPu = spec.contractSize / Math.pow(1 + Math.max(realYield, 0.03), ntnbDuration);
        const dv01PerNtnb = ntnbPu * ntnbDuration / 10000;
        contractsExact = dv01PerNtnb > 0 ? (dv01Brl / dv01PerNtnb) : 0;
        notionalBrl = Math.abs(contractsExact) * ntnbPu;
        entryPrice = marketData.di5y - 4.5; // proxy real yield
        break;
      }
    }

    const contracts = Math.round(contractsExact);
    const marginRequiredBrl = Math.abs(contracts) * spec.contractSize *
      (spec.contractUnit === "USD" ? marketData.spotUsdbrl : 1) * spec.marginPct;

    results.push({
      instrument: instBudget.instrument,
      b3Ticker: mapping.b3Ticker,
      b3Type: mapping.b3Type,
      direction,
      modelWeight: weight,
      riskAllocationBrl: absRisk,
      notionalBrl: Math.abs(notionalBrl),
      notionalUsd: Math.abs(notionalUsd),
      contractsExact,
      contracts: Math.abs(contracts),
      contractSize: spec.contractSize,
      contractUnit: spec.contractUnit,
      dv01Brl,
      fxDeltaBrl,
      spreadDv01Usd,
      marginRequiredBrl,
      marginPct: spec.marginPct,
      entryPrice,
    });
  }

  return results;
}

// ============================================================
// VaR ENGINE (Parametric Delta-Normal)
// ============================================================

export interface VaRResult {
  // Portfolio-level VaR
  varDaily95Brl: number;      // 1-day 95% VaR
  varDaily99Brl: number;      // 1-day 99% VaR
  varMonthly95Brl: number;    // 1-month 95% VaR
  varMonthly99Brl: number;    // 1-month 99% VaR
  // As % of AUM
  varDaily95Pct: number;
  varDaily99Pct: number;
  // Component VaR (contribution by instrument)
  componentVar: ComponentVaR[];
  // Stress scenarios
  stressTests: StressTest[];
}

export interface ComponentVaR {
  instrument: string;
  varContributionBrl: number;
  varContributionPct: number;   // % of total VaR
  marginalVarBrl: number;       // marginal VaR (add 1 unit)
}

export interface StressTest {
  name: string;
  description: string;
  shocks: Record<string, number>;  // instrument → shock (%)
  portfolioPnlBrl: number;
  portfolioPnlPct: number;
}

// Correlation matrix for BRL macro instruments (historical estimates)
const CORRELATION_MATRIX: Record<string, Record<string, number>> = {
  fx:    { fx: 1.00, front: -0.45, belly: -0.50, long: -0.55, hard: -0.30, ntnb: -0.40 },
  front: { fx: -0.45, front: 1.00, belly: 0.92, long: 0.85, hard: 0.40, ntnb: 0.75 },
  belly: { fx: -0.50, front: 0.92, belly: 1.00, long: 0.95, hard: 0.45, ntnb: 0.85 },
  long:  { fx: -0.55, front: 0.85, belly: 0.95, long: 1.00, hard: 0.50, ntnb: 0.88 },
  hard:  { fx: -0.30, front: 0.40, belly: 0.45, long: 0.50, hard: 1.00, ntnb: 0.35 },
  ntnb:  { fx: -0.40, front: 0.75, belly: 0.85, long: 0.88, hard: 0.35, ntnb: 1.00 },
};

// Daily volatility estimates (annualized → daily)
const DAILY_VOL_ESTIMATES: Record<string, number> = {
  fx: 0.15 / Math.sqrt(252),     // ~15% annual → ~0.95% daily
  front: 0.08 / Math.sqrt(252),  // ~8% annual → ~0.50% daily
  belly: 0.12 / Math.sqrt(252),  // ~12% annual → ~0.76% daily
  long: 0.18 / Math.sqrt(252),   // ~18% annual → ~1.13% daily
  hard: 0.10 / Math.sqrt(252),   // ~10% annual → ~0.63% daily
  ntnb: 0.14 / Math.sqrt(252),   // ~14% annual → ~0.88% daily
};

/**
 * Compute parametric (delta-normal) VaR.
 * Uses correlation matrix and daily vol estimates.
 */
export function computeVaR(
  positions: ContractSizing[],
  aumBrl: number,
  marketData?: MarketData
): VaRResult {
  const instruments = ["fx", "front", "belly", "long", "hard", "ntnb"];
  const z95 = 1.645;
  const z99 = 2.326;

  // Build exposure vector (risk allocation with sign)
  const exposures: Record<string, number> = {};
  for (const inst of instruments) {
    const pos = positions.find(p => p.instrument === inst);
    if (pos) {
      const sign = pos.direction === "short" ? -1 : pos.direction === "long" ? 1 : 0;
      exposures[inst] = sign * pos.riskAllocationBrl;
    } else {
      exposures[inst] = 0;
    }
  }

  // Update daily vols with market data if available
  const dailyVols = { ...DAILY_VOL_ESTIMATES };
  if (marketData) {
    dailyVols.fx = (marketData.vol30d / 100) / Math.sqrt(252);
  }

  // Compute individual VaRs
  const individualVars: Record<string, number> = {};
  for (const inst of instruments) {
    individualVars[inst] = Math.abs(exposures[inst]) * dailyVols[inst];
  }

  // Compute portfolio variance using correlation matrix
  let portfolioVariance = 0;
  for (const i of instruments) {
    for (const j of instruments) {
      const corr = CORRELATION_MATRIX[i]?.[j] ?? 0;
      portfolioVariance += individualVars[i] * individualVars[j] * corr;
    }
  }
  const portfolioStdDaily = Math.sqrt(Math.max(0, portfolioVariance));

  // VaR calculations
  const varDaily95 = portfolioStdDaily * z95;
  const varDaily99 = portfolioStdDaily * z99;
  const varMonthly95 = varDaily95 * Math.sqrt(21);  // 21 trading days
  const varMonthly99 = varDaily99 * Math.sqrt(21);

  // Component VaR (Euler decomposition)
  const componentVar: ComponentVaR[] = instruments.map(inst => {
    // Marginal VaR = d(VaR)/d(w_i) ≈ sum_j(w_j * sigma_j * rho_ij) * z / portfolioStd
    let marginalContrib = 0;
    for (const j of instruments) {
      const corr = CORRELATION_MATRIX[inst]?.[j] ?? 0;
      marginalContrib += individualVars[j] * corr;
    }
    const varContribution = portfolioStdDaily > 0
      ? (individualVars[inst] * marginalContrib / portfolioStdDaily) * z95
      : 0;

    return {
      instrument: inst,
      varContributionBrl: Math.abs(varContribution),
      varContributionPct: varDaily95 > 0 ? (Math.abs(varContribution) / varDaily95) * 100 : 0,
      marginalVarBrl: portfolioStdDaily > 0 ? (marginalContrib / portfolioStdDaily) * z95 : 0,
    };
  });

  // Stress tests
  const stressTests = computeStressTests(positions, aumBrl);

  return {
    varDaily95Brl: varDaily95,
    varDaily99Brl: varDaily99,
    varMonthly95Brl: varMonthly95,
    varMonthly99Brl: varMonthly99,
    varDaily95Pct: aumBrl > 0 ? (varDaily95 / aumBrl) * 100 : 0,
    varDaily99Pct: aumBrl > 0 ? (varDaily99 / aumBrl) * 100 : 0,
    componentVar,
    stressTests,
  };
}

/**
 * Compute stress test scenarios.
 */
function computeStressTests(positions: ContractSizing[], aumBrl: number): StressTest[] {
  const scenarios: StressTest[] = [
    {
      name: "2008 Lehman Crisis",
      description: "Global financial crisis: BRL -30%, DI +300bps, EMBI +400bps",
      shocks: { fx: -0.30, front: 0.03, belly: 0.03, long: 0.03, hard: -0.04, ntnb: 0.025 },
      portfolioPnlBrl: 0,
      portfolioPnlPct: 0,
    },
    {
      name: "2013 Taper Tantrum",
      description: "Fed tapering: BRL -15%, DI +150bps, EMBI +100bps",
      shocks: { fx: -0.15, front: 0.015, belly: 0.015, long: 0.015, hard: -0.01, ntnb: 0.012 },
      portfolioPnlBrl: 0,
      portfolioPnlPct: 0,
    },
    {
      name: "2015 Dilma Crisis",
      description: "Fiscal/political crisis: BRL -25%, DI +400bps, EMBI +200bps",
      shocks: { fx: -0.25, front: 0.04, belly: 0.04, long: 0.04, hard: -0.02, ntnb: 0.035 },
      portfolioPnlBrl: 0,
      portfolioPnlPct: 0,
    },
    {
      name: "2020 COVID Crash",
      description: "Pandemic: BRL -20%, DI -200bps (front), +100bps (long), EMBI +300bps",
      shocks: { fx: -0.20, front: -0.02, belly: 0.005, long: 0.01, hard: -0.03, ntnb: 0.008 },
      portfolioPnlBrl: 0,
      portfolioPnlPct: 0,
    },
    {
      name: "2022 Lula Election",
      description: "Political uncertainty: BRL -10%, DI +200bps, EMBI +100bps",
      shocks: { fx: -0.10, front: 0.02, belly: 0.02, long: 0.02, hard: -0.01, ntnb: 0.015 },
      portfolioPnlBrl: 0,
      portfolioPnlPct: 0,
    },
    {
      name: "Bull Scenario: EM Rally",
      description: "Risk-on: BRL +15%, DI -200bps, EMBI -100bps",
      shocks: { fx: 0.15, front: -0.02, belly: -0.02, long: -0.02, hard: 0.01, ntnb: -0.015 },
      portfolioPnlBrl: 0,
      portfolioPnlPct: 0,
    },
  ];

  for (const scenario of scenarios) {
    let totalPnl = 0;
    for (const pos of positions) {
      const shock = scenario.shocks[pos.instrument] || 0;
      const sign = pos.direction === "long" ? 1 : pos.direction === "short" ? -1 : 0;

      if (pos.instrument === "fx") {
        // FX: P&L = notional * shock * direction
        // Short USD gains when BRL appreciates (shock > 0)
        totalPnl += pos.notionalBrl * shock * sign * -1; // invert because short USD
      } else if (["front", "belly", "long"].includes(pos.instrument)) {
        // Rates: P&L = DV01 * shock_bps * direction
        // Receiver (long) gains when yield falls (shock < 0)
        const shockBps = shock * 10000; // convert to bps
        totalPnl += (pos.dv01Brl || 0) * shockBps * sign * -1; // receiver gains on yield drop
      } else if (pos.instrument === "hard") {
        // Hard: P&L = spreadDV01 * shock_bps * direction * spot
        const shockBps = shock * 10000;
        totalPnl += (pos.spreadDv01Usd || 0) * shockBps * sign * -1;
      } else if (pos.instrument === "ntnb") {
        // NTN-B: P&L = DV01 * shock_bps * direction (real yield shock)
        const shockBps = shock * 10000;
        totalPnl += (pos.dv01Brl || 0) * shockBps * sign * -1;
      }
    }

    scenario.portfolioPnlBrl = totalPnl;
    scenario.portfolioPnlPct = aumBrl > 0 ? (totalPnl / aumBrl) * 100 : 0;
  }

  return scenarios;
}

// ============================================================
// EXPOSURE ANALYTICS
// ============================================================

export interface ExposureAnalytics {
  // Aggregate
  grossExposureBrl: number;
  netExposureBrl: number;
  grossLeverage: number;        // gross / AUM
  netLeverage: number;          // net / AUM
  // By instrument
  fxDeltaTotalBrl: number;
  dv01TotalBrl: number;
  spreadDv01TotalUsd: number;
  // DV01 Ladder
  dv01Ladder: DV01LadderEntry[];
  // Margin
  totalMarginBrl: number;
  marginUtilizationPct: number; // margin / AUM
  // Concentration
  largestPositionPct: number;
  herfindahlIndex: number;      // concentration measure (0-1)
}

export interface DV01LadderEntry {
  tenor: string;
  instrument: string;
  b3Ticker: string;
  dv01Brl: number;
  direction: string;
}

/**
 * Compute exposure analytics for the portfolio.
 */
export function computeExposure(
  positions: ContractSizing[],
  aumBrl: number
): ExposureAnalytics {
  let grossExposure = 0;
  let netExposure = 0;
  let fxDeltaTotal = 0;
  let dv01Total = 0;
  let spreadDv01Total = 0;
  let totalMargin = 0;
  const dv01Ladder: DV01LadderEntry[] = [];

  for (const pos of positions) {
    const sign = pos.direction === "long" ? 1 : pos.direction === "short" ? -1 : 0;
    grossExposure += pos.notionalBrl;
    netExposure += pos.notionalBrl * sign;

    if (pos.fxDeltaBrl) fxDeltaTotal += pos.fxDeltaBrl;
    if (pos.dv01Brl) {
      dv01Total += pos.dv01Brl * sign;
      dv01Ladder.push({
        tenor: pos.instrument === "front" ? "1Y" : pos.instrument === "belly" ? "5Y" : "10Y",
        instrument: pos.instrument,
        b3Ticker: pos.b3Ticker,
        dv01Brl: pos.dv01Brl * sign,
        direction: pos.direction,
      });
    }
    if (pos.spreadDv01Usd) spreadDv01Total += pos.spreadDv01Usd * sign;
    totalMargin += pos.marginRequiredBrl;
  }

  // Concentration metrics
  const riskAllocations = positions.map(p => p.riskAllocationBrl);
  const totalRisk = riskAllocations.reduce((s, r) => s + r, 0);
  const largestPct = totalRisk > 0 ? (Math.max(...riskAllocations) / totalRisk) * 100 : 0;
  const herfindahl = totalRisk > 0
    ? riskAllocations.reduce((s, r) => s + Math.pow(r / totalRisk, 2), 0)
    : 0;

  return {
    grossExposureBrl: grossExposure,
    netExposureBrl: netExposure,
    grossLeverage: aumBrl > 0 ? grossExposure / aumBrl : 0,
    netLeverage: aumBrl > 0 ? netExposure / aumBrl : 0,
    fxDeltaTotalBrl: fxDeltaTotal,
    dv01TotalBrl: dv01Total,
    spreadDv01TotalUsd: spreadDv01Total,
    dv01Ladder,
    totalMarginBrl: totalMargin,
    marginUtilizationPct: aumBrl > 0 ? (totalMargin / aumBrl) * 100 : 0,
    largestPositionPct: largestPct,
    herfindahlIndex: herfindahl,
  };
}

// ============================================================
// REBALANCING ENGINE
// ============================================================

export interface RebalancingPlan {
  date: string;
  // Current vs Target
  currentPositions: ContractSizing[];
  targetPositions: ContractSizing[];
  // Trades to execute
  trades: TradeOrder[];
  // Cost estimation
  estimatedCostBrl: number;
  estimatedCostBps: number;
  turnoverPct: number;
  // Summary
  summary: string;
}

export interface TradeOrder {
  instrument: string;
  b3Ticker: string;
  b3Type: string;
  action: "BUY" | "SELL" | "HOLD";
  contractsDelta: number;       // positive = buy, negative = sell
  notionalDeltaBrl: number;
  estimatedCostBrl: number;
  // Context
  currentContracts: number;
  targetContracts: number;
  reason: string;
}

// Transaction cost estimates (bps of notional)
const TC_ESTIMATES_BPS: Record<string, number> = {
  DOL: 2,
  WDO: 3,
  DI1: 1.5,
  FRA: 2,
  DDI: 3,
  NTNB: 5,
};

/**
 * Generate rebalancing plan: current → target positions.
 */
export function generateRebalancingPlan(
  currentPositions: ContractSizing[],
  targetPositions: ContractSizing[],
  aumBrl: number,
  date: string = new Date().toISOString().slice(0, 10)
): RebalancingPlan {
  const trades: TradeOrder[] = [];
  let totalCost = 0;
  let totalTurnover = 0;

  for (const target of targetPositions) {
    const current = currentPositions.find(p => p.instrument === target.instrument);
    const currentContracts = current
      ? (current.direction === "short" ? -current.contracts : current.contracts)
      : 0;
    const targetContracts = target.direction === "short" ? -target.contracts : target.contracts;
    const delta = targetContracts - currentContracts;

    if (Math.abs(delta) === 0) {
      trades.push({
        instrument: target.instrument,
        b3Ticker: target.b3Ticker,
        b3Type: target.b3Type,
        action: "HOLD",
        contractsDelta: 0,
        notionalDeltaBrl: 0,
        estimatedCostBrl: 0,
        currentContracts: Math.abs(currentContracts),
        targetContracts: Math.abs(targetContracts),
        reason: "No change required",
      });
      continue;
    }

    const action: "BUY" | "SELL" = delta > 0 ? "BUY" : "SELL";
    const notionalDelta = Math.abs(delta) * target.contractSize *
      (target.contractUnit === "USD" ? (target.entryPrice || 5.0) : 1);
    const tcBps = TC_ESTIMATES_BPS[target.b3Type] || 3;
    const cost = notionalDelta * (tcBps / 10000);

    totalCost += cost;
    totalTurnover += Math.abs(notionalDelta);

    let reason = "";
    if (!current || current.contracts === 0) {
      reason = `New position: ${target.direction} ${Math.abs(targetContracts)} contracts`;
    } else if (target.contracts === 0) {
      reason = `Close position: was ${current.direction} ${current.contracts} contracts`;
    } else {
      reason = `Adjust: ${current.direction} ${current.contracts} → ${target.direction} ${target.contracts} contracts`;
    }

    trades.push({
      instrument: target.instrument,
      b3Ticker: target.b3Ticker,
      b3Type: target.b3Type,
      action,
      contractsDelta: delta,
      notionalDeltaBrl: notionalDelta,
      estimatedCostBrl: cost,
      currentContracts: Math.abs(currentContracts),
      targetContracts: Math.abs(targetContracts),
      reason,
    });
  }

  const turnoverPct = aumBrl > 0 ? (totalTurnover / aumBrl) * 100 : 0;
  const costBps = aumBrl > 0 ? (totalCost / aumBrl) * 10000 : 0;

  const activeTrades = trades.filter(t => t.action !== "HOLD");
  const summary = activeTrades.length === 0
    ? "No rebalancing needed — all positions are on target."
    : `${activeTrades.length} trades to execute. Estimated cost: ${costBps.toFixed(1)} bps (R$ ${totalCost.toFixed(0)}). Turnover: ${turnoverPct.toFixed(1)}%.`;

  return {
    date,
    currentPositions,
    targetPositions,
    trades,
    estimatedCostBrl: totalCost,
    estimatedCostBps: costBps,
    turnoverPct,
    summary,
  };
}

// ============================================================
// FULL PORTFOLIO COMPUTATION
// ============================================================

export interface FullPortfolioResult {
  config: {
    aumBrl: number;
    volTargetAnnual: number;
    riskBudgetBrl: number;
    fxInstrument: "DOL" | "WDO";
  };
  riskBudget: RiskBudget;
  positions: ContractSizing[];
  var: VaRResult;
  exposure: ExposureAnalytics;
  rebalancingPlan: RebalancingPlan | null;
  marketData: MarketData;
  instrumentMappings: InstrumentMapping[];
  // Interpretation
  interpretation: PortfolioInterpretation;
}

export interface PortfolioInterpretation {
  macroView: string;
  positionRationale: Record<string, string>;
  riskAssessment: string;
  actionItems: string[];
}

/**
 * Compute full portfolio from model output and config.
 * This is the main entry point for the portfolio management feature.
 */
export function computeFullPortfolio(
  aumBrl: number,
  volTargetAnnual: number,
  fxInstrument: "DOL" | "WDO",
  modelWeights: Record<string, number>,
  expectedReturns: Record<string, number>,
  marketData: MarketData,
  currentPositions: ContractSizing[] = [],
  dashboardData?: Record<string, unknown>
): FullPortfolioResult {
  // 1. Compute risk budget
  const riskBudget = computeRiskBudget(aumBrl, volTargetAnnual, modelWeights, expectedReturns);

  // 2. Map to B3 instruments
  const mappings = mapModelToB3(fxInstrument);

  // 3. Size contracts
  const positions = sizeContracts(riskBudget, mappings, marketData);

  // 4. Compute VaR
  const varResult = computeVaR(positions, aumBrl, marketData);

  // 5. Compute exposure
  const exposure = computeExposure(positions, aumBrl);

  // 6. Generate rebalancing plan (if current positions exist)
  const rebalancingPlan = currentPositions.length > 0
    ? generateRebalancingPlan(currentPositions, positions, aumBrl)
    : generateRebalancingPlan([], positions, aumBrl);

  // 7. Generate interpretation
  const interpretation = generateInterpretation(
    riskBudget, positions, varResult, exposure, marketData, dashboardData
  );

  return {
    config: { aumBrl, volTargetAnnual, riskBudgetBrl: riskBudget.riskBudgetBrl, fxInstrument },
    riskBudget,
    positions,
    var: varResult,
    exposure,
    rebalancingPlan,
    marketData,
    instrumentMappings: mappings,
    interpretation,
  };
}

/**
 * Generate human-readable interpretation of the portfolio.
 */
function generateInterpretation(
  riskBudget: RiskBudget,
  positions: ContractSizing[],
  varResult: VaRResult,
  exposure: ExposureAnalytics,
  marketData: MarketData,
  dashboardData?: Record<string, unknown>
): PortfolioInterpretation {
  const dash = dashboardData || {};
  const regime = (dash as any)?.dominant_regime || (dash as any)?.current_regime || (dash as any)?.regime_dominant || "unknown";
  const score = (dash as any)?.score_total || 0;
  const taylorGap = (dash as any)?.taylor_gap || 0;
  const fxMisalignment = (dash as any)?.fx_misalignment || 0;

  // Macro view
  let macroView = "";
  if (score > 3) {
    macroView = `O modelo está CONSTRUTIVO (score ${score.toFixed(1)}) com viés comprado em BRL e receiver em juros. `;
  } else if (score < -3) {
    macroView = `O modelo está DEFENSIVO (score ${score.toFixed(1)}) com viés vendido em BRL e payer em juros. `;
  } else {
    macroView = `O modelo está NEUTRO (score ${score.toFixed(1)}) sem convicção direcional forte. `;
  }

  if (taylorGap > 0) {
    macroView += `A SELIC está ${taylorGap.toFixed(1)}pp acima do equilíbrio Taylor, sugerindo espaço para corte de juros. `;
  } else if (taylorGap < 0) {
    macroView += `A SELIC está ${Math.abs(taylorGap).toFixed(1)}pp abaixo do equilíbrio Taylor, sugerindo pressão para alta de juros. `;
  }

  if (Math.abs(fxMisalignment) > 20) {
    macroView += `O BRL está ${fxMisalignment > 0 ? "desvalorizado" : "sobrevalorizado"} em ${Math.abs(fxMisalignment).toFixed(0)}% vs fair value.`;
  }

  macroView += ` Regime dominante: ${regime}.`;

  // Position rationale
  const positionRationale: Record<string, string> = {};
  for (const pos of positions) {
    const inst = pos.instrument;
    const dir = pos.direction === "long" ? "comprado" : pos.direction === "short" ? "vendido" : "flat";
    const contracts = pos.contracts;
    const ticker = pos.b3Ticker;

    switch (inst) {
      case "fx":
        positionRationale[inst] = pos.direction === "flat"
          ? "Sem posição em câmbio."
          : `${dir.toUpperCase()} ${contracts} contratos ${ticker} (${pos.direction === "short" ? "short USD / long BRL" : "long USD / short BRL"}). ` +
            `Notional: R$ ${(pos.notionalBrl / 1e6).toFixed(1)}M. ` +
            `FX Delta: R$ ${((pos.fxDeltaBrl || 0) / 1e3).toFixed(0)}k. ` +
            `Risco: ${((pos.riskAllocationBrl / riskBudget.riskBudgetBrl) * 100).toFixed(1)}% do orçamento.`;
        break;
      case "front":
      case "belly":
      case "long":
        const tenor = inst === "front" ? "1Y" : inst === "belly" ? "5Y" : "10Y";
        positionRationale[inst] = pos.direction === "flat"
          ? `Sem posição em DI ${tenor}.`
          : `${dir === "comprado" ? "RECEIVER" : "PAYER"} ${contracts} contratos ${ticker} (DI ${tenor}). ` +
            `DV01: R$ ${((pos.dv01Brl || 0)).toFixed(0)}/bp. ` +
            `Notional: R$ ${(pos.notionalBrl / 1e6).toFixed(1)}M. ` +
            `Risco: ${((pos.riskAllocationBrl / riskBudget.riskBudgetBrl) * 100).toFixed(1)}% do orçamento.`;
        break;
      case "hard":
        positionRationale[inst] = pos.direction === "flat"
          ? "Sem posição em cupom cambial."
          : `${dir.toUpperCase()} ${contracts} contratos ${ticker} (DDI/cupom cambial). ` +
            `Spread DV01: USD ${((pos.spreadDv01Usd || 0)).toFixed(0)}/bp. ` +
            `Notional: USD ${(pos.notionalUsd / 1e6).toFixed(1)}M. ` +
            `Risco: ${((pos.riskAllocationBrl / riskBudget.riskBudgetBrl) * 100).toFixed(1)}% do orçamento.`;
        break;
      case "ntnb":
        positionRationale[inst] = pos.direction === "flat"
          ? "Sem posição em NTN-B."
          : `${dir.toUpperCase()} ${contracts} NTN-B ${ticker} (Tesouro IPCA+). ` +
            `DV01: R$ ${((pos.dv01Brl || 0)).toFixed(0)}/bp. ` +
            `Notional: R$ ${(pos.notionalBrl / 1e6).toFixed(1)}M. ` +
            `Risco: ${((pos.riskAllocationBrl / riskBudget.riskBudgetBrl) * 100).toFixed(1)}% do orçamento.`;
        break;
    }
  }

  // Risk assessment
  const varPct = varResult.varDaily95Pct;
  let riskAssessment = `VaR diário (95%): R$ ${(varResult.varDaily95Brl / 1e3).toFixed(0)}k (${varPct.toFixed(2)}% do AUM). `;
  riskAssessment += `Alavancagem bruta: ${exposure.grossLeverage.toFixed(1)}x. `;
  riskAssessment += `Margem utilizada: ${exposure.marginUtilizationPct.toFixed(1)}% do AUM. `;

  if (varPct > 1.0) {
    riskAssessment += "ALERTA: VaR diário acima de 1% do AUM — considere reduzir posições. ";
  }
  if (exposure.marginUtilizationPct > 30) {
    riskAssessment += "ALERTA: Margem utilizada acima de 30% — risco de chamada de margem em stress. ";
  }

  // Action items
  const actionItems: string[] = [];
  if (positions.some(p => p.contracts > 0 && p.direction !== "flat")) {
    actionItems.push("Executar as ordens de rebalanceamento conforme o trade blotter.");
  }
  if (exposure.marginUtilizationPct > 20) {
    actionItems.push(`Garantir margem disponível de R$ ${(exposure.totalMarginBrl / 1e3).toFixed(0)}k na B3.`);
  }
  actionItems.push("Monitorar VaR diário e drawdown intraday.");
  actionItems.push("Verificar liquidez dos contratos antes de executar.");

  return {
    macroView,
    positionRationale,
    riskAssessment,
    actionItems,
  };
}
