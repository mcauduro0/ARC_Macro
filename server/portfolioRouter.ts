/**
 * Portfolio Management tRPC Router — Enhanced v2
 *
 * Procedures:
 *   portfolio.config.get         — Get active portfolio config
 *   portfolio.config.save        — Create/update portfolio config
 *   portfolio.compute            — Compute full portfolio from latest model + config
 *   portfolio.rebalance          — Execute rebalancing (save positions + snapshot + pending trades)
 *   portfolio.positions          — Get current positions
 *   portfolio.snapshots          — Get snapshot history
 *   portfolio.risk               — Get risk analytics
 *   portfolio.trades.pending     — Get pending (model-recommended) trades
 *   portfolio.trades.history     — Get trade history
 *   portfolio.trades.execute     — Mark a trade as executed (user input)
 *   portfolio.trades.record      — Record a manual trade
 *   portfolio.trades.cancel      — Cancel a pending trade
 *   portfolio.pnl.summary        — Get P&L summary (daily/MTD/YTD)
 *   portfolio.pnl.history        — Get daily P&L history
 *   portfolio.pnl.record         — Record daily MTM P&L
 *   portfolio.alerts.active      — Get active alerts
 *   portfolio.alerts.dismiss     — Dismiss an alert
 *   portfolio.alerts.check       — Run alert checks against current portfolio
 */

import { z } from "zod";
import { protectedProcedure, router } from "./_core/trpc";
import {
  getActivePortfolioConfig,
  upsertPortfolioConfig,
  getActivePositions,
  replacePositions,
  insertPortfolioSnapshot,
  getPortfolioSnapshots,
  getLatestPortfolioSnapshot,
  getLatestModelRun,
  insertTrade,
  getTrades,
  getPendingTrades,
  updateTradeExecution,
  cancelTrade,
  insertAlert,
  getActiveAlerts,
  dismissAlert,
  getDailyPnlHistory,
  upsertDailyPnl,
  getDailyPnlRange,
} from "./db";
import {
  computeFullPortfolio,
  computeVaR,
  computeExposure,
  type MarketData,
  type ContractSizing,
} from "./portfolioEngine";
import { notifyOwner } from "./_core/notification";
import {
  fetchMarketPrices,
  computeMtm,
  computeSlippage,
  computeFactorExposure,
  checkRiskLimits,
  DEFAULT_RISK_LIMITS,
  type MtmPosition,
} from "./marketDataService";

// ============================================================
// Input Schemas
// ============================================================

const portfolioConfigInput = z.object({
  aumBrl: z.number().min(10000, "AUM mínimo: R$ 10.000"),
  volTargetAnnual: z.number().min(0.01).max(0.50).default(0.10),
  fxInstrument: z.enum(["DOL", "WDO"]).default("WDO"),
  enableFx: z.boolean().default(true),
  enableFront: z.boolean().default(true),
  enableBelly: z.boolean().default(true),
  enableLong: z.boolean().default(true),
  enableHard: z.boolean().default(true),
  enableNtnb: z.boolean().default(true),
  maxDrawdownPct: z.number().min(-0.50).max(-0.01).default(-0.10),
  maxLeverageGross: z.number().min(1).max(20).default(5.0),
});

const executeTradeInput = z.object({
  tradeId: z.number(),
  executedPrice: z.number(),
  contracts: z.number().optional(),
  notes: z.string().optional(),
});

const recordTradeInput = z.object({
  instrument: z.enum(["fx", "front", "belly", "long", "hard", "ntnb"]),
  b3Ticker: z.string().min(3),
  b3InstrumentType: z.string().min(2),
  action: z.enum(["BUY", "SELL"]),
  contracts: z.number().min(1),
  executedPrice: z.number(),
  notionalBrl: z.number(),
  notionalUsd: z.number().optional(),
  commissionBrl: z.number().default(0),
  tradeType: z.enum(["manual_adjustment", "stop_loss", "take_profit", "roll"]).default("manual_adjustment"),
  notes: z.string().optional(),
});

const recordPnlInput = z.object({
  pnlDate: z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
  // Market prices for MTM
  spotUsdbrl: z.number().optional(),
  di1y: z.number().optional(),
  di5y: z.number().optional(),
  di10y: z.number().optional(),
  embiSpread: z.number().optional(),
  // Or direct P&L input
  fxPnlBrl: z.number().optional(),
  frontPnlBrl: z.number().optional(),
  bellyPnlBrl: z.number().optional(),
  longPnlBrl: z.number().optional(),
  hardPnlBrl: z.number().optional(),
  ntnbPnlBrl: z.number().optional(),
  ntnbRealYield: z.number().optional(),
});

// ============================================================
// Helper: Extract market data from model dashboard
// ============================================================

function extractMarketData(dashboard: Record<string, unknown>): MarketData {
  const d = dashboard as any;
  // SELIC target in the model may be stored as a fraction (4.59) or percentage (14.59)
  // If selic_target < 8, it's likely missing the 10% base — use di_1y as proxy
  const selicRaw = d.selic_target ?? d.di_1y ?? 14.0;
  const selic = selicRaw < 8 ? d.di_1y ?? 14.0 : selicRaw;
  return {
    spotUsdbrl: d.current_spot ?? d.spot ?? 5.0,
    di1y: d.di_1y ?? selic,
    di5y: d.di_5y ?? d.di_1y ?? 13.5,
    di10y: d.di_10y ?? d.di_5y ?? 13.0,
    embiSpread: d.embi_spread ?? 200,
    vol30d: d.vix ?? 15.0, // Use VIX as proxy if no FX vol available
    cdiDaily: selic / 252,
  };
}

function extractModelWeights(dashboard: Record<string, unknown>) {
  const d = dashboard as any;
  // Weights are nested inside positions object: positions.fx.weight, positions.front.weight, etc.
  const pos = d.positions ?? {};
  const weights: Record<string, number> = {
    fx: pos.fx?.weight ?? d.fx_weight ?? 0,
    front: pos.front?.weight ?? d.front_weight ?? 0,
    belly: pos.belly?.weight ?? d.belly_weight ?? 0,
    long: pos.long?.weight ?? d.long_weight ?? 0,
    hard: pos.hard?.weight ?? d.hard_weight ?? 0,
    ntnb: pos.ntnb?.weight ?? d.ntnb_weight ?? 0,
  };
  // Expected returns are annualized percentages in positions.*.expected_return_6m (6M, so *2 for annual)
  // Convert from percentage to decimal: 4.75% -> 0.0475
  const expectedReturns: Record<string, number> = {
    fx: (pos.fx?.expected_return_6m ?? 0) * 2 / 100,
    front: (pos.front?.expected_return_6m ?? 0) * 2 / 100,
    belly: (pos.belly?.expected_return_6m ?? 0) * 2 / 100,
    long: (pos.long?.expected_return_6m ?? 0) * 2 / 100,
    hard: (pos.hard?.expected_return_6m ?? 0) * 2 / 100,
    ntnb: (pos.ntnb?.expected_return_6m ?? 0) * 2 / 100,
  };
  return { weights, expectedReturns };
}

function sizingToDbPosition(sizing: ContractSizing, configId: number, snapshotId?: number) {
  return {
    configId,
    snapshotId: snapshotId ?? null,
    instrument: sizing.instrument as "fx" | "front" | "belly" | "long" | "hard" | "ntnb",
    b3Ticker: sizing.b3Ticker,
    b3InstrumentType: sizing.b3Type,
    direction: sizing.direction,
    modelWeight: sizing.modelWeight,
    riskAllocationBrl: sizing.riskAllocationBrl,
    riskAllocationPct: 0,
    notionalBrl: sizing.notionalBrl,
    notionalUsd: sizing.notionalUsd || null,
    contracts: sizing.contracts,
    contractSize: sizing.contractSize,
    dv01Brl: sizing.dv01Brl,
    fxDeltaBrl: sizing.fxDeltaBrl,
    spreadDv01Usd: sizing.spreadDv01Usd,
    entryPrice: sizing.entryPrice,
    currentPrice: sizing.entryPrice,
    unrealizedPnlBrl: 0,
    isActive: true,
  };
}

function filterWeights(config: any, weights: Record<string, number>, returns: Record<string, number>) {
  const fw: Record<string, number> = {};
  const fr: Record<string, number> = {};
  if (config.enableFx) { fw.fx = weights.fx; fr.fx = returns.fx; }
  if (config.enableFront) { fw.front = weights.front; fr.front = returns.front; }
  if (config.enableBelly) { fw.belly = weights.belly; fr.belly = returns.belly; }
  if (config.enableLong) { fw.long = weights.long; fr.long = returns.long; }
  if (config.enableHard) { fw.hard = weights.hard; fr.hard = returns.hard; }
  if (config.enableNtnb) { fw.ntnb = weights.ntnb; fr.ntnb = returns.ntnb; }
  return { filteredWeights: fw, filteredReturns: fr };
}

function dbPosToContractSizing(p: any): ContractSizing {
  return {
    instrument: p.instrument,
    b3Ticker: p.b3Ticker,
    b3Type: p.b3InstrumentType,
    direction: p.direction as "long" | "short" | "flat",
    modelWeight: p.modelWeight,
    riskAllocationBrl: p.riskAllocationBrl,
    notionalBrl: p.notionalBrl,
    notionalUsd: p.notionalUsd || 0,
    contractsExact: p.contracts,
    contracts: p.contracts,
    contractSize: p.contractSize,
    contractUnit: ["DOL", "WDO", "DDI"].includes(p.b3InstrumentType) ? "USD" : "BRL_PU",
    dv01Brl: p.dv01Brl,
    fxDeltaBrl: p.fxDeltaBrl,
    spreadDv01Usd: p.spreadDv01Usd,
    marginRequiredBrl: 0,
    marginPct: 0,
    entryPrice: p.entryPrice || 0,
  };
}

// ============================================================
// Portfolio Router
// ============================================================

export const portfolioRouter = router({
  config: router({
    get: protectedProcedure.query(async () => {
      const config = await getActivePortfolioConfig();
      return config || null;
    }),

    save: protectedProcedure
      .input(portfolioConfigInput)
      .mutation(async ({ input }) => {
        const riskBudgetBrl = input.aumBrl * input.volTargetAnnual;
        const configId = await upsertPortfolioConfig({
          aumBrl: input.aumBrl,
          volTargetAnnual: input.volTargetAnnual,
          riskBudgetBrl,
          baseCurrency: "BRL",
          enableFx: input.enableFx,
          enableFront: input.enableFront,
          enableBelly: input.enableBelly,
          enableLong: input.enableLong,
          enableHard: input.enableHard,
            enableNtnb: input.enableNtnb,
          fxInstrument: input.fxInstrument,
          maxDrawdownPct: input.maxDrawdownPct,
          maxLeverageGross: input.maxLeverageGross,
          isActive: true,
        });
        return { success: true, configId, riskBudgetBrl };
      }),
  }),

  /**
   * Compute full portfolio from latest model output + active config.
   * Does NOT save to DB — use rebalance to persist.
   */
  compute: protectedProcedure.query(async () => {
    const config = await getActivePortfolioConfig();
    if (!config) return { error: "Configure o portfólio primeiro (aba Setup).", data: null };

    const modelRun = await getLatestModelRun();
    if (!modelRun) return { error: "Aguarde a execução do modelo.", data: null };

    const dashboard = modelRun.dashboardJson as Record<string, unknown>;
    const marketData = extractMarketData(dashboard);
    const { weights, expectedReturns } = extractModelWeights(dashboard);
    const { filteredWeights, filteredReturns } = filterWeights(config, weights, expectedReturns);

    const currentDbPositions = await getActivePositions(config.id);
    const currentPositions = currentDbPositions.map(dbPosToContractSizing);

    const result = computeFullPortfolio(
      config.aumBrl,
      config.volTargetAnnual,
      config.fxInstrument as "DOL" | "WDO",
      filteredWeights,
      filteredReturns,
      marketData,
      currentPositions,
      dashboard
    );

    return {
      error: null,
      data: {
        ...result,
        modelRunDate: modelRun.runDate,
        modelRunId: modelRun.id,
        hasActivePositions: currentDbPositions.length > 0,
      },
    };
  }),

  /**
   * Execute rebalancing: save new positions + create snapshot + create pending trades.
   */
  rebalance: protectedProcedure.mutation(async () => {
    const config = await getActivePortfolioConfig();
    if (!config) return { error: "No portfolio config found.", success: false };

    const modelRun = await getLatestModelRun();
    if (!modelRun) return { error: "No model run available.", success: false };

    const dashboard = modelRun.dashboardJson as Record<string, unknown>;
    const marketData = extractMarketData(dashboard);
    const { weights, expectedReturns } = extractModelWeights(dashboard);
    const { filteredWeights, filteredReturns } = filterWeights(config, weights, expectedReturns);

    const currentDbPositions = await getActivePositions(config.id);
    const currentPositions = currentDbPositions.map(dbPosToContractSizing);

    const result = computeFullPortfolio(
      config.aumBrl,
      config.volTargetAnnual,
      config.fxInstrument as "DOL" | "WDO",
      filteredWeights,
      filteredReturns,
      marketData,
      currentPositions,
      dashboard
    );

    // Create snapshot
    const snapshotId = await insertPortfolioSnapshot({
      configId: config.id,
      modelRunId: modelRun.id,
      snapshotDate: new Date().toISOString().slice(0, 10),
      snapshotType: "rebalance",
      aumBrl: config.aumBrl,
      totalPnlBrl: 0,
      totalPnlPct: 0,
      overlayPnlBrl: 0,
      cdiPnlBrl: 0,
      portfolioVolAnnual: config.volTargetAnnual,
      varDaily95Brl: result.var.varDaily95Brl,
      varDaily99Brl: result.var.varDaily99Brl,
      currentDrawdownPct: 0,
      maxDrawdownPct: 0,
      grossExposureBrl: result.exposure.grossExposureBrl,
      netExposureBrl: result.exposure.netExposureBrl,
      grossLeverage: result.exposure.grossLeverage,
      positionsJson: result.positions,
      riskDecompJson: result.var.componentVar,
      tradesJson: result.rebalancingPlan?.trades || [],
      exposureJson: result.exposure,
    });

    // Replace positions
    const dbPositions = result.positions.map(p => sizingToDbPosition(p, config.id, snapshotId));
    await replacePositions(config.id, dbPositions);

    // Create pending trades from rebalancing plan
    const activeTrades = result.rebalancingPlan?.trades.filter(t => t.action !== "HOLD") || [];
    for (const trade of activeTrades) {
      await insertTrade({
        configId: config.id,
        snapshotId,
        instrument: trade.instrument as any,
        b3Ticker: trade.b3Ticker,
        b3InstrumentType: trade.b3Type,
        tradeType: "model_recommended",
        action: trade.action as "BUY" | "SELL",
        contracts: Math.abs(trade.contractsDelta),
        executedPrice: 0, // to be filled on execution
        targetPrice: 0,
        notionalBrl: trade.notionalDeltaBrl,
        notionalUsd: null,
        commissionBrl: 0,
        slippageBrl: 0,
        totalCostBrl: trade.estimatedCostBrl,
        status: "pending",
        notes: trade.reason,
      });
    }

    return {
      success: true,
      error: null,
      snapshotId,
      tradesCount: activeTrades.length,
      summary: result.rebalancingPlan?.summary || "Rebalancing complete.",
    };
  }),

  positions: protectedProcedure.query(async () => {
    const config = await getActivePortfolioConfig();
    if (!config) return { positions: [], config: null };
    const positions = await getActivePositions(config.id);
    return { positions, config };
  }),

  snapshots: protectedProcedure.query(async () => {
    const config = await getActivePortfolioConfig();
    if (!config) return [];
    return getPortfolioSnapshots(config.id, 30);
  }),

  risk: protectedProcedure.query(async () => {
    const config = await getActivePortfolioConfig();
    if (!config) return { error: "No portfolio config found.", data: null };

    const positions = await getActivePositions(config.id);
    if (positions.length === 0) return { error: "Sem posições ativas. Execute um rebalanceamento.", data: null };

    const modelRun = await getLatestModelRun();
    const dashboard = modelRun?.dashboardJson as Record<string, unknown> | undefined;
    const marketData = dashboard ? extractMarketData(dashboard) : undefined;

    const contractSizings = positions.map(dbPosToContractSizing);
    const varResult = computeVaR(contractSizings, config.aumBrl, marketData);
    const exposure = computeExposure(contractSizings, config.aumBrl);
    const latestSnapshot = await getLatestPortfolioSnapshot(config.id);

    return {
      error: null,
      data: {
        var: varResult,
        exposure,
        config: {
          aumBrl: config.aumBrl,
          volTargetAnnual: config.volTargetAnnual,
          riskBudgetBrl: config.riskBudgetBrl,
          maxDrawdownPct: config.maxDrawdownPct,
          maxLeverageGross: config.maxLeverageGross,
        },
        latestSnapshot: latestSnapshot ? {
          date: latestSnapshot.snapshotDate,
          type: latestSnapshot.snapshotType,
          varDaily95Brl: latestSnapshot.varDaily95Brl,
          grossLeverage: latestSnapshot.grossLeverage,
        } : null,
      },
    };
  }),

  // ============================================================
  // TRADES
  // ============================================================

  trades: router({
    /**
     * Get pending (model-recommended) trades awaiting execution.
     */
    pending: protectedProcedure.query(async () => {
      const config = await getActivePortfolioConfig();
      if (!config) return [];
      return getPendingTrades(config.id);
    }),

    /**
     * Get trade history (all statuses).
     */
    history: protectedProcedure
      .input(z.object({ limit: z.number().default(100) }).optional())
      .query(async ({ input }) => {
        const config = await getActivePortfolioConfig();
        if (!config) return [];
        return getTrades(config.id, undefined, input?.limit || 100);
      }),

    /**
     * Mark a pending trade as executed — user inputs the actual execution price.
     */
    execute: protectedProcedure
      .input(executeTradeInput)
      .mutation(async ({ input }) => {
        await updateTradeExecution(
          input.tradeId,
          input.executedPrice,
          input.contracts,
          input.notes
        );
        return { success: true };
      }),

    /**
     * Record a manual trade (not model-recommended).
     */
    record: protectedProcedure
      .input(recordTradeInput)
      .mutation(async ({ input }) => {
        const config = await getActivePortfolioConfig();
        if (!config) return { error: "No portfolio config found.", success: false, tradeId: null };

        const tradeId = await insertTrade({
          configId: config.id,
          instrument: input.instrument,
          b3Ticker: input.b3Ticker,
          b3InstrumentType: input.b3InstrumentType,
          tradeType: input.tradeType,
          action: input.action,
          contracts: input.contracts,
          executedPrice: input.executedPrice,
          notionalBrl: input.notionalBrl,
          notionalUsd: input.notionalUsd ?? null,
          commissionBrl: input.commissionBrl,
          totalCostBrl: input.commissionBrl,
          status: "executed",
          executedAt: new Date(),
          notes: input.notes ?? null,
        });

        return { success: true, error: null, tradeId };
      }),

    /**
     * Cancel a pending trade.
     */
    cancel: protectedProcedure
      .input(z.object({ tradeId: z.number() }))
      .mutation(async ({ input }) => {
        await cancelTrade(input.tradeId);
        return { success: true };
      }),
  }),

  // ============================================================
  // P&L TRACKING
  // ============================================================

  pnl: router({
    /**
     * Get P&L summary: daily, MTD, YTD, since inception.
     */
    summary: protectedProcedure.query(async () => {
      const config = await getActivePortfolioConfig();
      if (!config) return null;

      const today = new Date().toISOString().slice(0, 10);
      const monthStart = today.slice(0, 8) + "01";
      const yearStart = today.slice(0, 5) + "01-01";

      // Get all P&L records
      const allPnl = await getDailyPnlHistory(config.id, 1000);
      if (allPnl.length === 0) return {
        daily: { pnl: 0, pnlPct: 0, cdi: 0 },
        mtd: { pnl: 0, pnlPct: 0, cdi: 0 },
        ytd: { pnl: 0, pnlPct: 0, cdi: 0 },
        inception: { pnl: 0, pnlPct: 0, cdi: 0 },
        hwm: config.aumBrl,
        currentDrawdown: 0,
        aumCurrent: config.aumBrl,
      };

      // Latest day
      const latestDay = allPnl[0];

      // MTD
      const mtdRecords = allPnl.filter(r => r.pnlDate >= monthStart);
      const mtdPnl = mtdRecords.reduce((s, r) => s + (r.totalPnlBrl || 0), 0);
      const mtdCdi = mtdRecords.reduce((s, r) => s + (r.cdiDailyPnlBrl || 0), 0);

      // YTD
      const ytdRecords = allPnl.filter(r => r.pnlDate >= yearStart);
      const ytdPnl = ytdRecords.reduce((s, r) => s + (r.totalPnlBrl || 0), 0);
      const ytdCdi = ytdRecords.reduce((s, r) => s + (r.cdiDailyPnlBrl || 0), 0);

      // Inception
      const inceptionPnl = allPnl.reduce((s, r) => s + (r.totalPnlBrl || 0), 0);
      const inceptionCdi = allPnl.reduce((s, r) => s + (r.cdiDailyPnlBrl || 0), 0);

      // HWM and drawdown
      const hwm = latestDay.hwmBrl || config.aumBrl;
      const currentAum = config.aumBrl + inceptionPnl;
      const drawdown = hwm > 0 ? ((currentAum - hwm) / hwm) * 100 : 0;

      return {
        daily: {
          pnl: latestDay.totalPnlBrl || 0,
          pnlPct: latestDay.totalPnlBrl ? (latestDay.totalPnlBrl / config.aumBrl) * 100 : 0,
          cdi: latestDay.cdiDailyPnlBrl || 0,
        },
        mtd: {
          pnl: mtdPnl,
          pnlPct: config.aumBrl > 0 ? (mtdPnl / config.aumBrl) * 100 : 0,
          cdi: mtdCdi,
        },
        ytd: {
          pnl: ytdPnl,
          pnlPct: config.aumBrl > 0 ? (ytdPnl / config.aumBrl) * 100 : 0,
          cdi: ytdCdi,
        },
        inception: {
          pnl: inceptionPnl,
          pnlPct: config.aumBrl > 0 ? (inceptionPnl / config.aumBrl) * 100 : 0,
          cdi: inceptionCdi,
        },
        hwm,
        currentDrawdown: drawdown,
        aumCurrent: currentAum,
      };
    }),

    /**
     * Get daily P&L history for charting.
     */
    history: protectedProcedure
      .input(z.object({ limit: z.number().default(252) }).optional())
      .query(async ({ input }) => {
        const config = await getActivePortfolioConfig();
        if (!config) return [];
        return getDailyPnlHistory(config.id, input?.limit || 252);
      }),

    /**
     * Record daily P&L (manual MTM input or computed from prices).
     */
    record: protectedProcedure
      .input(recordPnlInput)
      .mutation(async ({ input }) => {
        const config = await getActivePortfolioConfig();
        if (!config) return { error: "No portfolio config found.", success: false };

        const positions = await getActivePositions(config.id);
        if (positions.length === 0) return { error: "No active positions.", success: false };

        // Compute P&L from direct input or market prices
        let fxPnl = input.fxPnlBrl || 0;
        let frontPnl = input.frontPnlBrl || 0;
        let bellyPnl = input.bellyPnlBrl || 0;
        let longPnl = input.longPnlBrl || 0;
        let hardPnl = input.hardPnlBrl || 0;
        let ntnbPnl = input.ntnbPnlBrl || 0;

        // If market prices provided, compute MTM P&L
        if (input.spotUsdbrl || input.di1y || input.di5y || input.di10y || input.embiSpread) {
          for (const pos of positions) {
            const sign = pos.direction === "long" ? 1 : pos.direction === "short" ? -1 : 0;
            const entryPrice = pos.entryPrice || 0;

            if (pos.instrument === "fx" && input.spotUsdbrl) {
              const priceDelta = input.spotUsdbrl - entryPrice;
              fxPnl = (pos.notionalUsd || 0) * priceDelta * sign * -1;
            }
            if (pos.instrument === "front" && input.di1y) {
              const yieldDelta = (input.di1y - entryPrice) * 100; // bps
              frontPnl = (pos.dv01Brl || 0) * yieldDelta * sign * -1;
            }
            if (pos.instrument === "belly" && input.di5y) {
              const yieldDelta = (input.di5y - entryPrice) * 100;
              bellyPnl = (pos.dv01Brl || 0) * yieldDelta * sign * -1;
            }
            if (pos.instrument === "long" && input.di10y) {
              const yieldDelta = (input.di10y - entryPrice) * 100;
              longPnl = (pos.dv01Brl || 0) * yieldDelta * sign * -1;
            }
            if (pos.instrument === "hard" && input.embiSpread) {
              const spreadDelta = (input.embiSpread - entryPrice);
              hardPnl = (pos.spreadDv01Usd || 0) * spreadDelta * sign * -1;
            }
            if (pos.instrument === "ntnb" && input.ntnbRealYield) {
              const yieldDelta = (input.ntnbRealYield - entryPrice) * 100;
              ntnbPnl = (pos.dv01Brl || 0) * yieldDelta * sign * -1;
            }
          }
        }

        const overlayPnl = fxPnl + frontPnl + bellyPnl + longPnl + hardPnl + ntnbPnl;
        const cdiPnl = config.aumBrl * ((config.volTargetAnnual > 0 ? 0.1375 : 0.1375) / 252); // CDI ~13.75% a.a.
        const totalPnl = overlayPnl + cdiPnl;

        // Get previous cumulative
        const prevHistory = await getDailyPnlHistory(config.id, 1);
        const prevCumPnl = prevHistory.length > 0 ? (prevHistory[0].cumulativePnlBrl || 0) : 0;
        const prevCumCdi = prevHistory.length > 0 ? (prevHistory[0].cumulativeCdiPnlBrl || 0) : 0;
        const prevHwm = prevHistory.length > 0 ? (prevHistory[0].hwmBrl || config.aumBrl) : config.aumBrl;

        const cumulativePnl = prevCumPnl + totalPnl;
        const cumulativeCdi = prevCumCdi + cdiPnl;
        const currentAum = config.aumBrl + cumulativePnl;
        const hwm = Math.max(prevHwm, currentAum);
        const drawdown = hwm > 0 ? ((currentAum - hwm) / hwm) * 100 : 0;

        await upsertDailyPnl({
          configId: config.id,
          pnlDate: input.pnlDate,
          totalPnlBrl: totalPnl,
          overlayPnlBrl: overlayPnl,
          cdiPnlBrl: cdiPnl,
          fxPnlBrl: fxPnl,
          frontPnlBrl: frontPnl,
          bellyPnlBrl: bellyPnl,
          longPnlBrl: longPnl,
          hardPnlBrl: hardPnl,
          ntnbPnlBrl: ntnbPnl,
          cumulativePnlBrl: cumulativePnl,
          cumulativePnlPct: config.aumBrl > 0 ? (cumulativePnl / config.aumBrl) * 100 : 0,
          cdiDailyPnlBrl: cdiPnl,
          cumulativeCdiPnlBrl: cumulativeCdi,
          aumBrl: currentAum,
          drawdownPct: drawdown,
          hwmBrl: hwm,
        });

        // Check alerts
        if (drawdown < (config.maxDrawdownPct || -10)) {
          await insertAlert({
            configId: config.id,
            alertType: "drawdown_breach",
            severity: "critical",
            title: `Drawdown excedeu limite: ${drawdown.toFixed(2)}%`,
            message: `O drawdown atual de ${drawdown.toFixed(2)}% excedeu o limite configurado de ${config.maxDrawdownPct}%. Considere reduzir posições.`,
            metricValue: drawdown,
            thresholdValue: config.maxDrawdownPct,
          });
          try {
            await notifyOwner({
              title: "⚠️ ALERTA: Drawdown excedeu limite",
              content: `Drawdown: ${drawdown.toFixed(2)}% (limite: ${config.maxDrawdownPct}%)`,
            });
          } catch (e) { /* notification is best-effort */ }
        }

        return { success: true, error: null, totalPnl, overlayPnl, cdiPnl, cumulativePnl, drawdown };
      }),
  }),

  // ============================================================
  // ALERTS
  // ============================================================

  alerts: router({
    active: protectedProcedure.query(async () => {
      const config = await getActivePortfolioConfig();
      if (!config) return [];
      return getActiveAlerts(config.id);
    }),

    dismiss: protectedProcedure
      .input(z.object({ alertId: z.number() }))
      .mutation(async ({ input }) => {
        await dismissAlert(input.alertId);
        return { success: true };
      }),

    /**
     * Run alert checks against current portfolio state.
     */
    check: protectedProcedure.mutation(async () => {
      const config = await getActivePortfolioConfig();
      if (!config) return { alerts: [] };

      const positions = await getActivePositions(config.id);
      if (positions.length === 0) return { alerts: [] };

      const modelRun = await getLatestModelRun();
      const dashboard = modelRun?.dashboardJson as Record<string, unknown> | undefined;
      const marketData = dashboard ? extractMarketData(dashboard) : undefined;

      const contractSizings = positions.map(dbPosToContractSizing);
      const varResult = computeVaR(contractSizings, config.aumBrl, marketData);
      const exposure = computeExposure(contractSizings, config.aumBrl);

      const newAlerts: string[] = [];

      // VaR check
      if (varResult.varDaily95Pct > 1.5) {
        await insertAlert({
          configId: config.id,
          alertType: "var_breach",
          severity: "critical",
          title: `VaR diário 95% excedeu 1.5% do AUM`,
          message: `VaR atual: ${varResult.varDaily95Pct.toFixed(2)}% do AUM (R$ ${(varResult.varDaily95Brl / 1000).toFixed(0)}k). Considere reduzir posições.`,
          metricValue: varResult.varDaily95Pct,
          thresholdValue: 1.5,
        });
        newAlerts.push("VaR breach");
      }

      // Margin check
      if (exposure.marginUtilizationPct > 30) {
        await insertAlert({
          configId: config.id,
          alertType: "margin_warning",
          severity: "warning",
          title: `Margem utilizada acima de 30%`,
          message: `Margem: ${exposure.marginUtilizationPct.toFixed(1)}% do AUM (R$ ${(exposure.totalMarginBrl / 1000).toFixed(0)}k). Risco de chamada de margem em stress.`,
          metricValue: exposure.marginUtilizationPct,
          thresholdValue: 30,
        });
        newAlerts.push("Margin warning");
      }

      // Leverage check
      if (exposure.grossLeverage > (config.maxLeverageGross || 5)) {
        await insertAlert({
          configId: config.id,
          alertType: "position_limit",
          severity: "warning",
          title: `Alavancagem bruta excedeu limite`,
          message: `Alavancagem: ${exposure.grossLeverage.toFixed(1)}x (limite: ${config.maxLeverageGross}x).`,
          metricValue: exposure.grossLeverage,
          thresholdValue: config.maxLeverageGross,
        });
        newAlerts.push("Leverage breach");
      }

      // Regime change check
      if (dashboard) {
        const regime = (dashboard as any)?.regime_dominant;
        const latestSnapshot = await getLatestPortfolioSnapshot(config.id);
        if (latestSnapshot?.positionsJson) {
          const prevDash = latestSnapshot.exposureJson as any;
          // Simple regime change detection
          if (regime === "risk_off" || regime === "domestic_stress") {
            await insertAlert({
              configId: config.id,
              alertType: "regime_change",
              severity: regime === "risk_off" ? "critical" : "warning",
              title: `Regime mudou para ${regime === "risk_off" ? "Risk-Off" : "Domestic Stress"}`,
              message: `O modelo detectou mudança de regime. Considere revisar posições e executar rebalanceamento.`,
              metricValue: null,
              thresholdValue: null,
            });
            newAlerts.push("Regime change");
          }
        }
      }

      return { alerts: newAlerts };
    }),
  }),

  // ============================================================
  // MARKET DATA — Real-time prices
  // ============================================================

  market: router({
    /**
     * Get latest market prices from BCB/Yahoo.
     */
    prices: protectedProcedure
      .input(z.object({ forceRefresh: z.boolean().default(false) }).optional())
      .query(async ({ input }) => {
        try {
          const prices = await fetchMarketPrices(input?.forceRefresh || false);
          return { error: null, data: prices };
        } catch (e: any) {
          return { error: e.message || "Erro ao buscar preços", data: null };
        }
      }),

    /**
     * Compute mark-to-market P&L for all active positions.
     */
    mtm: protectedProcedure.query(async () => {
      const config = await getActivePortfolioConfig();
      if (!config) return { error: "Configure o portfólio primeiro.", data: null };

      const positions = await getActivePositions(config.id);
      if (positions.length === 0) return { error: "Sem posições ativas.", data: null };

      try {
        const prices = await fetchMarketPrices();
        const mtmPositions: MtmPosition[] = positions.map(p => ({
          instrument: p.instrument,
          b3Ticker: p.b3Ticker,
          b3InstrumentType: p.b3InstrumentType,
          direction: p.direction,
          contracts: p.contracts,
          notionalBrl: p.notionalBrl,
          notionalUsd: p.notionalUsd,
          entryPrice: p.entryPrice || 0,
          dv01Brl: p.dv01Brl,
          fxDeltaBrl: p.fxDeltaBrl,
          spreadDv01Usd: p.spreadDv01Usd,
        }));

        const result = computeMtm(mtmPositions, prices, config.aumBrl);
        return { error: null, data: { ...result, prices } };
      } catch (e: any) {
        return { error: e.message || "Erro ao calcular MTM", data: null };
      }
    }),

    /**
     * Record daily P&L from MTM computation (auto or manual).
     */
    recordMtm: protectedProcedure
      .input(z.object({
        pnlDate: z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
        useAutoMtm: z.boolean().default(true),
        // Manual overrides
        spotUsdbrl: z.number().optional(),
        di1y: z.number().optional(),
        di5y: z.number().optional(),
        di10y: z.number().optional(),
        embiSpread: z.number().optional(),
      }))
      .mutation(async ({ input }) => {
        const config = await getActivePortfolioConfig();
        if (!config) return { error: "No config.", success: false };

        const positions = await getActivePositions(config.id);
        if (positions.length === 0) return { error: "No positions.", success: false };

        let prices;
        if (input.useAutoMtm) {
          prices = await fetchMarketPrices();
        } else {
          prices = await fetchMarketPrices();
          // Override with manual values
          if (input.spotUsdbrl) prices.spotUsdbrl = input.spotUsdbrl;
          if (input.di1y) prices.di1y = input.di1y;
          if (input.di5y) prices.di5y = input.di5y;
          if (input.di10y) prices.di10y = input.di10y;
          if (input.embiSpread) prices.embiSpread = input.embiSpread;
        }

        const mtmPositions: MtmPosition[] = positions.map(p => ({
          instrument: p.instrument,
          b3Ticker: p.b3Ticker,
          b3InstrumentType: p.b3InstrumentType,
          direction: p.direction,
          contracts: p.contracts,
          notionalBrl: p.notionalBrl,
          notionalUsd: p.notionalUsd,
          entryPrice: p.entryPrice || 0,
          dv01Brl: p.dv01Brl,
          fxDeltaBrl: p.fxDeltaBrl,
          spreadDv01Usd: p.spreadDv01Usd,
        }));

        const mtm = computeMtm(mtmPositions, prices, config.aumBrl);

        // Get previous cumulative
        const prevHistory = await getDailyPnlHistory(config.id, 1);
        const prevCumPnl = prevHistory.length > 0 ? (prevHistory[0].cumulativePnlBrl || 0) : 0;
        const prevCumCdi = prevHistory.length > 0 ? (prevHistory[0].cumulativeCdiPnlBrl || 0) : 0;
        const prevHwm = prevHistory.length > 0 ? (prevHistory[0].hwmBrl || config.aumBrl) : config.aumBrl;

        const cumulativePnl = prevCumPnl + mtm.totalPnlBrl;
        const cumulativeCdi = prevCumCdi + mtm.cdiPnlBrl;
        const currentAum = config.aumBrl + cumulativePnl;
        const hwm = Math.max(prevHwm, currentAum);
        const drawdown = hwm > 0 ? ((currentAum - hwm) / hwm) * 100 : 0;

        await upsertDailyPnl({
          configId: config.id,
          pnlDate: input.pnlDate,
          totalPnlBrl: mtm.totalPnlBrl,
          overlayPnlBrl: mtm.totalOverlayPnlBrl,
          cdiPnlBrl: mtm.cdiPnlBrl,
          fxPnlBrl: mtm.fxPnlBrl,
          frontPnlBrl: mtm.frontPnlBrl,
          bellyPnlBrl: mtm.bellyPnlBrl,
          longPnlBrl: mtm.longPnlBrl,
          hardPnlBrl: mtm.hardPnlBrl,
          cumulativePnlBrl: cumulativePnl,
          cumulativePnlPct: config.aumBrl > 0 ? (cumulativePnl / config.aumBrl) * 100 : 0,
          cdiDailyPnlBrl: mtm.cdiPnlBrl,
          cumulativeCdiPnlBrl: cumulativeCdi,
          aumBrl: currentAum,
          drawdownPct: drawdown,
          hwmBrl: hwm,
        });

        // Check for drawdown alert
        if (drawdown < (config.maxDrawdownPct || -10)) {
          await insertAlert({
            configId: config.id,
            alertType: "drawdown_breach",
            severity: "critical",
            title: `Drawdown excedeu limite: ${drawdown.toFixed(2)}%`,
            message: `Drawdown: ${drawdown.toFixed(2)}% (limite: ${config.maxDrawdownPct}%).`,
            metricValue: drawdown,
            thresholdValue: config.maxDrawdownPct,
          });
          try {
            await notifyOwner({
              title: "ALERTA: Drawdown excedeu limite",
              content: `Drawdown: ${drawdown.toFixed(2)}% (limite: ${config.maxDrawdownPct}%)`,
            });
          } catch { /* best-effort */ }
        }

        // Update position current prices
        for (const pos of positions) {
          const mtmPos = mtm.positions.find(m => m.instrument === pos.instrument);
          if (mtmPos) {
            // Update current price and unrealized P&L in DB
            // (simplified — in production, use a batch update)
          }
        }

        return {
          success: true,
          error: null,
          pnl: {
            total: mtm.totalPnlBrl,
            overlay: mtm.totalOverlayPnlBrl,
            cdi: mtm.cdiPnlBrl,
            cumulative: cumulativePnl,
            drawdown,
          },
        };
      }),
  }),

  // ============================================================
  // RISK DASHBOARD — Consolidated view
  // ============================================================

  riskDashboard: protectedProcedure.query(async () => {
    const config = await getActivePortfolioConfig();
    if (!config) return { error: "Configure o portfólio primeiro.", data: null };

    const positions = await getActivePositions(config.id);
    if (positions.length === 0) return { error: "Sem posições ativas.", data: null };

    const modelRun = await getLatestModelRun();
    const dashboard = modelRun?.dashboardJson as Record<string, unknown> | undefined;
    const marketData = dashboard ? extractMarketData(dashboard) : undefined;

    const contractSizings = positions.map(dbPosToContractSizing);
    const varResult = computeVaR(contractSizings, config.aumBrl, marketData);
    const exposure = computeExposure(contractSizings, config.aumBrl);

    // Factor exposure
    const mtmPositions: MtmPosition[] = positions.map(p => ({
      instrument: p.instrument,
      b3Ticker: p.b3Ticker,
      b3InstrumentType: p.b3InstrumentType,
      direction: p.direction,
      contracts: p.contracts,
      notionalBrl: p.notionalBrl,
      notionalUsd: p.notionalUsd,
      entryPrice: p.entryPrice || 0,
      dv01Brl: p.dv01Brl,
      fxDeltaBrl: p.fxDeltaBrl,
      spreadDv01Usd: p.spreadDv01Usd,
    }));
    const factorExposures = computeFactorExposure(mtmPositions, config.aumBrl);

    // P&L data
    const pnlHistory = await getDailyPnlHistory(config.id, 252);
    const latestSnapshot = await getLatestPortfolioSnapshot(config.id);

    // Current drawdown
    const latestPnl = pnlHistory.length > 0 ? pnlHistory[0] : null;
    const currentDrawdown = latestPnl?.drawdownPct || 0;

    // Risk alerts
    const riskAlerts = checkRiskLimits({
      varDaily95Pct: varResult.varDaily95Pct,
      currentDrawdownPct: currentDrawdown,
      grossLeverage: exposure.grossLeverage,
      marginUtilizationPct: exposure.marginUtilizationPct,
      factorExposures,
      regime: (dashboard as any)?.regime_dominant,
      lastRebalanceDate: latestSnapshot?.snapshotDate,
    });

    // Active alerts from DB
    const dbAlerts = await getActiveAlerts(config.id);

    return {
      error: null,
      data: {
        // Portfolio summary
        config: {
          aumBrl: config.aumBrl,
          volTargetAnnual: config.volTargetAnnual,
          riskBudgetBrl: config.riskBudgetBrl,
          maxDrawdownPct: config.maxDrawdownPct,
          maxLeverageGross: config.maxLeverageGross,
        },
        // VaR
        var: varResult,
        // Exposure
        exposure,
        // Factor breakdown
        factorExposures,
        // P&L
        pnl: {
          daily: latestPnl ? {
            date: latestPnl.pnlDate,
            total: latestPnl.totalPnlBrl || 0,
            overlay: latestPnl.overlayPnlBrl || 0,
            cdi: latestPnl.cdiDailyPnlBrl || 0,
          } : null,
          cumulative: latestPnl?.cumulativePnlBrl || 0,
          cumulativePct: latestPnl?.cumulativePnlPct || 0,
          drawdown: currentDrawdown,
          hwm: latestPnl?.hwmBrl || config.aumBrl,
          history: pnlHistory.slice(0, 30).reverse(),
        },
        // Limits & alerts
        limits: DEFAULT_RISK_LIMITS,
        riskAlerts,
        dbAlerts,
        // Snapshot
        lastRebalance: latestSnapshot ? {
          date: latestSnapshot.snapshotDate,
          type: latestSnapshot.snapshotType,
        } : null,
        // Regime
        regime: (dashboard as any)?.regime_dominant || "unknown",
      },
    };
  }),

  // ============================================================
  // TRADE WORKFLOW — Approval flow with slippage tracking
  // ============================================================

  tradeWorkflow: router({
    /**
     * Approve a pending trade (move from pending → approved).
     */
    approve: protectedProcedure
      .input(z.object({
        tradeId: z.number(),
        targetPrice: z.number().optional(),
        notes: z.string().optional(),
      }))
      .mutation(async ({ input }) => {
        // Get the trade
        const config = await getActivePortfolioConfig();
        if (!config) return { error: "No config.", success: false };

        const trades = await getPendingTrades(config.id);
        const trade = trades.find((t: any) => t.id === input.tradeId);
        if (!trade) return { error: "Trade não encontrado.", success: false };

        // Update status to approved (reuse updateTradeExecution with status change)
        // For now, we mark it as executed with the target price
        // In a full implementation, we'd have a separate status column
        await updateTradeExecution(
          input.tradeId,
          input.targetPrice || (trade as any).targetPrice || 0,
          (trade as any).contracts,
          `APROVADO: ${input.notes || ""}`
        );

        return { success: true, error: null };
      }),

    /**
     * Execute an approved trade with actual fill details.
     */
    fill: protectedProcedure
      .input(z.object({
        tradeId: z.number(),
        executedPrice: z.number(),
        executedContracts: z.number(),
        commissionBrl: z.number().default(0),
        notes: z.string().optional(),
      }))
      .mutation(async ({ input }) => {
        const config = await getActivePortfolioConfig();
        if (!config) return { error: "No config.", success: false, slippage: null };

        // Get the trade to compute slippage
        const allTrades = await getTrades(config.id, undefined, 500);
        const trade = allTrades.find((t: any) => t.id === input.tradeId);
        if (!trade) return { error: "Trade não encontrado.", success: false, slippage: null };

        const prices = await fetchMarketPrices();
        const slippage = computeSlippage(
          (trade as any).instrument,
          (trade as any).targetPrice || (trade as any).executedPrice || input.executedPrice,
          input.executedPrice,
          input.executedContracts,
          prices.spotUsdbrl,
        );

        await updateTradeExecution(
          input.tradeId,
          input.executedPrice,
          input.executedContracts,
          `EXECUTADO: ${input.notes || ""} | Slippage: ${slippage.slippageBps}bps (R$ ${slippage.slippageBrl.toFixed(2)})`
        );

        return { success: true, error: null, slippage };
      }),

    /**
     * Reject a trade recommendation.
     */
    reject: protectedProcedure
      .input(z.object({
        tradeId: z.number(),
        reason: z.string().optional(),
      }))
      .mutation(async ({ input }) => {
        await cancelTrade(input.tradeId);
        return { success: true };
      }),
  }),
});
