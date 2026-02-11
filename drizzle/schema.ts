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
