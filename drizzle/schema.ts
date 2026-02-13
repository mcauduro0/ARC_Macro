import { int, mysqlEnum, mysqlTable, text, timestamp, varchar, json, double, boolean } from "drizzle-orm/mysql-core";

/**
 * Core user table backing auth flow.
 */
export const users = mysqlTable("users", {
  id: int("id").autoincrement().primaryKey(),
  openId: varchar("openId", { length: 64 }).notNull().unique(),
  name: text("name"),
  email: varchar("email", { length: 320 }),
  loginMethod: varchar("loginMethod", { length: 64 }),
  role: mysqlEnum("role", ["user", "admin"]).default("user").notNull(),
  createdAt: timestamp("createdAt").defaultNow().notNull(),
  updatedAt: timestamp("updatedAt").defaultNow().onUpdateNow().notNull(),
  lastSignedIn: timestamp("lastSignedIn").defaultNow().notNull(),
});

export type User = typeof users.$inferSelect;
export type InsertUser = typeof users.$inferInsert;

/**
 * Model run snapshots - stores the full Macro Risk OS output for each execution.
 * Includes cross-asset data: FX, Rates (front/long), Hard Currency, Regime, Risk.
 */
export const modelRuns = mysqlTable("model_runs", {
  id: int("id").autoincrement().primaryKey(),
  runDate: varchar("runDate", { length: 10 }).notNull(), // YYYY-MM-DD
  currentSpot: double("currentSpot").notNull(),
  dashboardJson: json("dashboardJson").notNull(), // Full dashboard data (cross-asset)
  timeseriesJson: json("timeseriesJson").notNull(), // FX timeseries + fair values
  regimeJson: json("regimeJson").notNull(), // 3-state regime probabilities
  stateVariablesJson: json("stateVariablesJson"), // X1-X7 Z-score timeseries
  scoreJson: json("scoreJson"), // Score timeseries (total, structural, cyclical, regime)
  backtestJson: json("backtestJson"), // Backtest equity curve, drawdown, and performance metrics
  // Legacy data for backward compatibility
  cyclicalJson: json("cyclicalJson").notNull(), // Cyclical factor Z-scores
  legacyDashboardJson: json("legacyDashboardJson"), // Legacy FX-only model
  legacyTimeseriesJson: json("legacyTimeseriesJson"), // Legacy timeseries
  legacyRegimeJson: json("legacyRegimeJson"), // Legacy regime probs
  legacyCyclicalJson: json("legacyCyclicalJson"), // Legacy cyclical factors
  status: mysqlEnum("status", ["running", "completed", "failed"]).default("completed").notNull(),
  errorMessage: text("errorMessage"),
  isLatest: boolean("isLatest").default(false).notNull(),
  createdAt: timestamp("createdAt").defaultNow().notNull(),
});

export type ModelRun = typeof modelRuns.$inferSelect;
export type InsertModelRun = typeof modelRuns.$inferInsert;

// ============================================================
// Portfolio Management
// ============================================================

/**
 * Portfolio configuration — AUM, vol target, instrument preferences.
 * One active config per user (owner).
 */
export const portfolioConfig = mysqlTable("portfolio_config", {
  id: int("id").autoincrement().primaryKey(),
  aumBrl: double("aumBrl").notNull(), // AUM in BRL
  volTargetAnnual: double("volTargetAnnual").notNull().default(0.10), // 10% default
  riskBudgetBrl: double("riskBudgetBrl").notNull(), // AUM * volTarget
  baseCurrency: varchar("baseCurrency", { length: 3 }).notNull().default("BRL"),
  // Instrument preferences (enabled/disabled)
  enableFx: boolean("enableFx").notNull().default(true),
  enableFront: boolean("enableFront").notNull().default(true),
  enableBelly: boolean("enableBelly").notNull().default(true),
  enableLong: boolean("enableLong").notNull().default(true),
  enableHard: boolean("enableHard").notNull().default(true),
  // B3 instrument preferences
  fxInstrument: mysqlEnum("fxInstrument", ["DOL", "WDO"]).notNull().default("WDO"),
  // Risk limits
  maxDrawdownPct: double("maxDrawdownPct").notNull().default(-0.10),
  maxLeverageGross: double("maxLeverageGross").notNull().default(5.0),
  // Status
  isActive: boolean("isActive").notNull().default(true),
  createdAt: timestamp("createdAt").defaultNow().notNull(),
  updatedAt: timestamp("updatedAt").defaultNow().onUpdateNow().notNull(),
});

export type PortfolioConfig = typeof portfolioConfig.$inferSelect;
export type InsertPortfolioConfig = typeof portfolioConfig.$inferInsert;

/**
 * Portfolio positions — current live positions per instrument.
 * Updated on each rebalancing.
 */
export const portfolioPositions = mysqlTable("portfolio_positions", {
  id: int("id").autoincrement().primaryKey(),
  configId: int("configId").notNull(),
  snapshotId: int("snapshotId"), // links to the snapshot that generated this position
  // Instrument identification
  instrument: mysqlEnum("instrument", ["fx", "front", "belly", "long", "hard"]).notNull(),
  b3Ticker: varchar("b3Ticker", { length: 20 }).notNull(), // e.g. WDOH26, DI1F27, etc.
  b3InstrumentType: varchar("b3InstrumentType", { length: 20 }).notNull(), // DOL, WDO, DI1, FRA, DDI, NTNB
  // Position details
  direction: mysqlEnum("direction", ["long", "short", "flat"]).notNull(),
  modelWeight: double("modelWeight").notNull(), // raw model weight (risk units)
  riskAllocationBrl: double("riskAllocationBrl").notNull(), // weight * riskBudget
  riskAllocationPct: double("riskAllocationPct").notNull(), // % of total risk
  notionalBrl: double("notionalBrl").notNull(), // notional in BRL
  notionalUsd: double("notionalUsd"), // notional in USD (for FX/Hard)
  contracts: int("contracts").notNull(), // number of B3 contracts
  contractSize: double("contractSize").notNull(), // size per contract
  // Risk metrics
  dv01Brl: double("dv01Brl"), // DV01 in BRL (for rates)
  fxDeltaBrl: double("fxDeltaBrl"), // FX delta in BRL (for FX)
  spreadDv01Usd: double("spreadDv01Usd"), // spread DV01 in USD (for hard)
  entryPrice: double("entryPrice"), // entry price/yield
  currentPrice: double("currentPrice"), // current price/yield
  unrealizedPnlBrl: double("unrealizedPnlBrl").default(0),
  // Metadata
  isActive: boolean("isActive").notNull().default(true),
  createdAt: timestamp("createdAt").defaultNow().notNull(),
  updatedAt: timestamp("updatedAt").defaultNow().onUpdateNow().notNull(),
});

export type PortfolioPosition = typeof portfolioPositions.$inferSelect;
export type InsertPortfolioPosition = typeof portfolioPositions.$inferInsert;

/**
 * Portfolio snapshots — point-in-time snapshots of portfolio state.
 * Created on each rebalancing or daily mark-to-market.
 */
export const portfolioSnapshots = mysqlTable("portfolio_snapshots", {
  id: int("id").autoincrement().primaryKey(),
  configId: int("configId").notNull(),
  modelRunId: int("modelRunId"), // links to the model run that triggered this snapshot
  snapshotDate: varchar("snapshotDate", { length: 10 }).notNull(), // YYYY-MM-DD
  snapshotType: mysqlEnum("snapshotType", ["rebalance", "daily_mtm", "manual"]).notNull(),
  // Portfolio-level metrics
  aumBrl: double("aumBrl").notNull(),
  totalPnlBrl: double("totalPnlBrl").notNull().default(0),
  totalPnlPct: double("totalPnlPct").notNull().default(0),
  overlayPnlBrl: double("overlayPnlBrl").notNull().default(0),
  cdiPnlBrl: double("cdiPnlBrl").notNull().default(0),
  // Risk metrics
  portfolioVolAnnual: double("portfolioVolAnnual"),
  varDaily95Brl: double("varDaily95Brl"), // 1-day 95% VaR in BRL
  varDaily99Brl: double("varDaily99Brl"), // 1-day 99% VaR in BRL
  currentDrawdownPct: double("currentDrawdownPct"),
  maxDrawdownPct: double("maxDrawdownPct"),
  grossExposureBrl: double("grossExposureBrl"),
  netExposureBrl: double("netExposureBrl"),
  grossLeverage: double("grossLeverage"),
  // Detailed JSON data
  positionsJson: json("positionsJson"), // full position detail array
  riskDecompJson: json("riskDecompJson"), // risk decomposition by instrument
  tradesJson: json("tradesJson"), // trades executed in this rebalancing
  exposureJson: json("exposureJson"), // exposure breakdown (DV01 ladder, FX delta, etc.)
  // Status
  createdAt: timestamp("createdAt").defaultNow().notNull(),
});

export type PortfolioSnapshot = typeof portfolioSnapshots.$inferSelect;
export type InsertPortfolioSnapshot = typeof portfolioSnapshots.$inferInsert;

/**
 * Portfolio trades — records of executed trades (both model-recommended and manual).
 * Links to snapshots for attribution analysis.
 */
export const portfolioTrades = mysqlTable("portfolio_trades", {
  id: int("id").autoincrement().primaryKey(),
  configId: int("configId").notNull(),
  snapshotId: int("snapshotId"), // links to the rebalancing snapshot
  // Trade identification
  instrument: mysqlEnum("instrument", ["fx", "front", "belly", "long", "hard"]).notNull(),
  b3Ticker: varchar("b3Ticker", { length: 20 }).notNull(),
  b3InstrumentType: varchar("b3InstrumentType", { length: 20 }).notNull(),
  // Trade details
  tradeType: mysqlEnum("tradeType", ["model_recommended", "manual_adjustment", "stop_loss", "take_profit", "roll"]).notNull().default("model_recommended"),
  action: mysqlEnum("action", ["BUY", "SELL"]).notNull(),
  contracts: int("contracts").notNull(),
  executedPrice: double("executedPrice").notNull(), // price/yield at execution
  targetPrice: double("targetPrice"), // model-recommended price (for slippage calc)
  notionalBrl: double("notionalBrl").notNull(),
  notionalUsd: double("notionalUsd"),
  // Cost & slippage
  commissionBrl: double("commissionBrl").default(0),
  slippageBrl: double("slippageBrl").default(0), // executedPrice vs targetPrice
  totalCostBrl: double("totalCostBrl").default(0), // commission + slippage
  // P&L (updated on MTM)
  currentPrice: double("currentPrice"),
  unrealizedPnlBrl: double("unrealizedPnlBrl").default(0),
  realizedPnlBrl: double("realizedPnlBrl").default(0),
  // Status
  status: mysqlEnum("status", ["pending", "executed", "partially_filled", "cancelled"]).notNull().default("pending"),
  executedAt: timestamp("executedAt"),
  notes: text("notes"),
  createdAt: timestamp("createdAt").defaultNow().notNull(),
  updatedAt: timestamp("updatedAt").defaultNow().onUpdateNow().notNull(),
});

export type PortfolioTrade = typeof portfolioTrades.$inferSelect;
export type InsertPortfolioTrade = typeof portfolioTrades.$inferInsert;

/**
 * Portfolio alerts — risk alerts and notifications.
 */
export const portfolioAlerts = mysqlTable("portfolio_alerts", {
  id: int("id").autoincrement().primaryKey(),
  configId: int("configId").notNull(),
  // Alert details
  alertType: mysqlEnum("alertType", [
    "var_breach", "drawdown_breach", "margin_warning",
    "regime_change", "rebalance_due", "model_update",
    "position_limit", "custom"
  ]).notNull(),
  severity: mysqlEnum("severity", ["info", "warning", "critical"]).notNull().default("info"),
  title: varchar("title", { length: 200 }).notNull(),
  message: text("message").notNull(),
  metricValue: double("metricValue"), // the value that triggered the alert
  thresholdValue: double("thresholdValue"), // the threshold that was breached
  // Status
  isRead: boolean("isRead").notNull().default(false),
  isDismissed: boolean("isDismissed").notNull().default(false),
  notifiedAt: timestamp("notifiedAt"),
  createdAt: timestamp("createdAt").defaultNow().notNull(),
});

export type PortfolioAlert = typeof portfolioAlerts.$inferSelect;
export type InsertPortfolioAlert = typeof portfolioAlerts.$inferInsert;

/**
 * Portfolio P&L daily — daily mark-to-market P&L tracking.
 */
export const portfolioPnlDaily = mysqlTable("portfolio_pnl_daily", {
  id: int("id").autoincrement().primaryKey(),
  configId: int("configId").notNull(),
  pnlDate: varchar("pnlDate", { length: 10 }).notNull(), // YYYY-MM-DD
  // P&L breakdown
  totalPnlBrl: double("totalPnlBrl").notNull().default(0),
  overlayPnlBrl: double("overlayPnlBrl").notNull().default(0),
  cdiPnlBrl: double("cdiPnlBrl").notNull().default(0),
  // By instrument
  fxPnlBrl: double("fxPnlBrl").default(0),
  frontPnlBrl: double("frontPnlBrl").default(0),
  bellyPnlBrl: double("bellyPnlBrl").default(0),
  longPnlBrl: double("longPnlBrl").default(0),
  hardPnlBrl: double("hardPnlBrl").default(0),
  // Cumulative
  cumulativePnlBrl: double("cumulativePnlBrl").notNull().default(0),
  cumulativePnlPct: double("cumulativePnlPct").notNull().default(0),
  // Benchmark
  cdiDailyPnlBrl: double("cdiDailyPnlBrl").default(0), // CDI benchmark P&L
  cumulativeCdiPnlBrl: double("cumulativeCdiPnlBrl").default(0),
  // Risk snapshot
  aumBrl: double("aumBrl").notNull(),
  drawdownPct: double("drawdownPct").default(0),
  hwmBrl: double("hwmBrl"), // high water mark
  createdAt: timestamp("createdAt").defaultNow().notNull(),
});

export type PortfolioPnlDaily = typeof portfolioPnlDaily.$inferSelect;
export type InsertPortfolioPnlDaily = typeof portfolioPnlDaily.$inferInsert;
