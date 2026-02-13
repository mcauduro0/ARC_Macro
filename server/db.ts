import { eq, desc, and, gte, lte, sql } from "drizzle-orm";
import { drizzle } from "drizzle-orm/mysql2";
import { InsertUser, users, modelRuns, InsertModelRun, portfolioConfig, InsertPortfolioConfig, portfolioPositions, InsertPortfolioPosition, portfolioSnapshots, InsertPortfolioSnapshot, portfolioTrades, InsertPortfolioTrade, portfolioAlerts, InsertPortfolioAlert, portfolioPnlDaily, InsertPortfolioPnlDaily } from "../drizzle/schema";
import { ENV } from './_core/env';

let _db: ReturnType<typeof drizzle> | null = null;

// Lazily create the drizzle instance so local tooling can run without a DB.
export async function getDb() {
  if (!_db && process.env.DATABASE_URL) {
    try {
      _db = drizzle(process.env.DATABASE_URL);
    } catch (error) {
      console.warn("[Database] Failed to connect:", error);
      _db = null;
    }
  }
  return _db;
}

export async function upsertUser(user: InsertUser): Promise<void> {
  if (!user.openId) {
    throw new Error("User openId is required for upsert");
  }

  const db = await getDb();
  if (!db) {
    console.warn("[Database] Cannot upsert user: database not available");
    return;
  }

  try {
    const values: InsertUser = {
      openId: user.openId,
    };
    const updateSet: Record<string, unknown> = {};

    const textFields = ["name", "email", "loginMethod"] as const;
    type TextField = (typeof textFields)[number];

    const assignNullable = (field: TextField) => {
      const value = user[field];
      if (value === undefined) return;
      const normalized = value ?? null;
      values[field] = normalized;
      updateSet[field] = normalized;
    };

    textFields.forEach(assignNullable);

    if (user.lastSignedIn !== undefined) {
      values.lastSignedIn = user.lastSignedIn;
      updateSet.lastSignedIn = user.lastSignedIn;
    }
    if (user.role !== undefined) {
      values.role = user.role;
      updateSet.role = user.role;
    } else if (user.openId === ENV.ownerOpenId) {
      values.role = 'admin';
      updateSet.role = 'admin';
    }

    if (!values.lastSignedIn) {
      values.lastSignedIn = new Date();
    }

    if (Object.keys(updateSet).length === 0) {
      updateSet.lastSignedIn = new Date();
    }

    await db.insert(users).values(values).onDuplicateKeyUpdate({
      set: updateSet,
    });
  } catch (error) {
    console.error("[Database] Failed to upsert user:", error);
    throw error;
  }
}

export async function getUserByOpenId(openId: string) {
  const db = await getDb();
  if (!db) {
    console.warn("[Database] Cannot get user: database not available");
    return undefined;
  }

  const result = await db.select().from(users).where(eq(users.openId, openId)).limit(1);

  return result.length > 0 ? result[0] : undefined;
}

// ============================================================
// Model Run Queries
// ============================================================

/**
 * Get the latest completed model run
 */
export async function getLatestModelRun() {
  const db = await getDb();
  if (!db) return undefined;

  const result = await db
    .select()
    .from(modelRuns)
    .where(eq(modelRuns.status, "completed"))
    .orderBy(desc(modelRuns.createdAt))
    .limit(1);

  return result.length > 0 ? result[0] : undefined;
}

/**
 * Get all model runs (for history)
 */
export async function getModelRunHistory(limit = 30) {
  const db = await getDb();
  if (!db) return [];

  return db
    .select({
      id: modelRuns.id,
      runDate: modelRuns.runDate,
      currentSpot: modelRuns.currentSpot,
      status: modelRuns.status,
      isLatest: modelRuns.isLatest,
      createdAt: modelRuns.createdAt,
    })
    .from(modelRuns)
    .orderBy(desc(modelRuns.createdAt))
    .limit(limit);
}

/**
 * Insert a new model run
 */
export async function insertModelRun(data: InsertModelRun) {
  const db = await getDb();
  if (!db) throw new Error("Database not available");

  // Clear isLatest flag on all existing runs
  await db.update(modelRuns).set({ isLatest: false });

  // Insert new run with isLatest = true
  const result = await db.insert(modelRuns).values({
    ...data,
    isLatest: true,
  });

  return result[0].insertId;
}

/**
 * Update model run status
 */
export async function updateModelRunStatus(id: number, status: "running" | "completed" | "failed", errorMessage?: string) {
  const db = await getDb();
  if (!db) return;

  await db
    .update(modelRuns)
    .set({ status, errorMessage: errorMessage ?? null })
    .where(eq(modelRuns.id, id));
}

// ============================================================
// Portfolio Management Queries
// ============================================================

/**
 * Get the active portfolio config
 */
export async function getActivePortfolioConfig() {
  const db = await getDb();
  if (!db) return undefined;

  const result = await db
    .select()
    .from(portfolioConfig)
    .where(eq(portfolioConfig.isActive, true))
    .orderBy(desc(portfolioConfig.updatedAt))
    .limit(1);

  return result.length > 0 ? result[0] : undefined;
}

/**
 * Upsert portfolio config (deactivate old, insert new)
 */
export async function upsertPortfolioConfig(data: Omit<InsertPortfolioConfig, 'id' | 'createdAt' | 'updatedAt'>) {
  const db = await getDb();
  if (!db) throw new Error("Database not available");

  // Deactivate all existing configs
  await db.update(portfolioConfig).set({ isActive: false });

  // Insert new active config
  const result = await db.insert(portfolioConfig).values({
    ...data,
    isActive: true,
  });

  return result[0].insertId;
}

/**
 * Get current active positions for a config
 */
export async function getActivePositions(configId: number) {
  const db = await getDb();
  if (!db) return [];

  return db
    .select()
    .from(portfolioPositions)
    .where(and(
      eq(portfolioPositions.configId, configId),
      eq(portfolioPositions.isActive, true)
    ));
}

/**
 * Replace all active positions (deactivate old, insert new)
 */
export async function replacePositions(configId: number, positions: Omit<InsertPortfolioPosition, 'id' | 'createdAt' | 'updatedAt'>[]) {
  const db = await getDb();
  if (!db) throw new Error("Database not available");

  // Deactivate all existing positions for this config
  await db.update(portfolioPositions)
    .set({ isActive: false })
    .where(eq(portfolioPositions.configId, configId));

  // Insert new positions
  if (positions.length > 0) {
    await db.insert(portfolioPositions).values(positions);
  }
}

/**
 * Insert a portfolio snapshot
 */
export async function insertPortfolioSnapshot(data: Omit<InsertPortfolioSnapshot, 'id' | 'createdAt'>) {
  const db = await getDb();
  if (!db) throw new Error("Database not available");

  const result = await db.insert(portfolioSnapshots).values(data);
  return result[0].insertId;
}

/**
 * Get portfolio snapshot history
 */
export async function getPortfolioSnapshots(configId: number, limit = 30) {
  const db = await getDb();
  if (!db) return [];

  return db
    .select()
    .from(portfolioSnapshots)
    .where(eq(portfolioSnapshots.configId, configId))
    .orderBy(desc(portfolioSnapshots.createdAt))
    .limit(limit);
}

/**
 * Get the latest portfolio snapshot
 */
export async function getLatestPortfolioSnapshot(configId: number) {
  const db = await getDb();
  if (!db) return undefined;

  const result = await db
    .select()
    .from(portfolioSnapshots)
    .where(eq(portfolioSnapshots.configId, configId))
    .orderBy(desc(portfolioSnapshots.createdAt))
    .limit(1);

  return result.length > 0 ? result[0] : undefined;
}

// ============================================================
// Portfolio Trades
// ============================================================

/**
 * Insert a new trade record
 */
export async function insertTrade(data: Omit<InsertPortfolioTrade, 'id' | 'createdAt' | 'updatedAt'>) {
  const db = await getDb();
  if (!db) throw new Error("Database not available");

  const result = await db.insert(portfolioTrades).values(data);
  return result[0].insertId;
}

/**
 * Get trades for a config (optionally filtered by status)
 */
export async function getTrades(configId: number, status?: string, limit = 100) {
  const db = await getDb();
  if (!db) return [];

  const conditions = [eq(portfolioTrades.configId, configId)];
  if (status) {
    conditions.push(eq(portfolioTrades.status, status as any));
  }

  return db
    .select()
    .from(portfolioTrades)
    .where(and(...conditions))
    .orderBy(desc(portfolioTrades.createdAt))
    .limit(limit);
}

/**
 * Get pending trades (model-recommended, not yet executed)
 */
export async function getPendingTrades(configId: number) {
  const db = await getDb();
  if (!db) return [];

  return db
    .select()
    .from(portfolioTrades)
    .where(and(
      eq(portfolioTrades.configId, configId),
      eq(portfolioTrades.status, "pending")
    ))
    .orderBy(desc(portfolioTrades.createdAt));
}

/**
 * Update trade status (mark as executed with price)
 */
export async function updateTradeExecution(tradeId: number, executedPrice: number, contracts?: number, notes?: string) {
  const db = await getDb();
  if (!db) throw new Error("Database not available");

  const updateData: Record<string, unknown> = {
    status: "executed",
    executedPrice,
    currentPrice: executedPrice,
    executedAt: new Date(),
  };
  if (contracts !== undefined) updateData.contracts = contracts;
  if (notes) updateData.notes = notes;

  await db.update(portfolioTrades)
    .set(updateData)
    .where(eq(portfolioTrades.id, tradeId));
}

/**
 * Cancel a pending trade
 */
export async function cancelTrade(tradeId: number) {
  const db = await getDb();
  if (!db) throw new Error("Database not available");

  await db.update(portfolioTrades)
    .set({ status: "cancelled" })
    .where(eq(portfolioTrades.id, tradeId));
}

/**
 * Update trade MTM price and P&L
 */
export async function updateTradeMtm(tradeId: number, currentPrice: number, unrealizedPnlBrl: number) {
  const db = await getDb();
  if (!db) throw new Error("Database not available");

  await db.update(portfolioTrades)
    .set({ currentPrice, unrealizedPnlBrl })
    .where(eq(portfolioTrades.id, tradeId));
}

// ============================================================
// Portfolio Alerts
// ============================================================

/**
 * Insert a new alert
 */
export async function insertAlert(data: Omit<InsertPortfolioAlert, 'id' | 'createdAt'>) {
  const db = await getDb();
  if (!db) throw new Error("Database not available");

  const result = await db.insert(portfolioAlerts).values(data);
  return result[0].insertId;
}

/**
 * Get active (unread/undismissed) alerts
 */
export async function getActiveAlerts(configId: number, limit = 50) {
  const db = await getDb();
  if (!db) return [];

  return db
    .select()
    .from(portfolioAlerts)
    .where(and(
      eq(portfolioAlerts.configId, configId),
      eq(portfolioAlerts.isDismissed, false)
    ))
    .orderBy(desc(portfolioAlerts.createdAt))
    .limit(limit);
}

/**
 * Mark alert as read
 */
export async function markAlertRead(alertId: number) {
  const db = await getDb();
  if (!db) throw new Error("Database not available");

  await db.update(portfolioAlerts)
    .set({ isRead: true })
    .where(eq(portfolioAlerts.id, alertId));
}

/**
 * Dismiss alert
 */
export async function dismissAlert(alertId: number) {
  const db = await getDb();
  if (!db) throw new Error("Database not available");

  await db.update(portfolioAlerts)
    .set({ isDismissed: true })
    .where(eq(portfolioAlerts.id, alertId));
}

// ============================================================
// Portfolio P&L Daily
// ============================================================

/**
 * Insert or update daily P&L record
 */
export async function upsertDailyPnl(data: Omit<InsertPortfolioPnlDaily, 'id' | 'createdAt'>) {
  const db = await getDb();
  if (!db) throw new Error("Database not available");

  // Check if record exists for this date
  const existing = await db
    .select()
    .from(portfolioPnlDaily)
    .where(and(
      eq(portfolioPnlDaily.configId, data.configId),
      eq(portfolioPnlDaily.pnlDate, data.pnlDate)
    ))
    .limit(1);

  if (existing.length > 0) {
    await db.update(portfolioPnlDaily)
      .set(data)
      .where(eq(portfolioPnlDaily.id, existing[0].id));
    return existing[0].id;
  } else {
    const result = await db.insert(portfolioPnlDaily).values(data);
    return result[0].insertId;
  }
}

/**
 * Get daily P&L history
 */
export async function getDailyPnlHistory(configId: number, limit = 252) {
  const db = await getDb();
  if (!db) return [];

  return db
    .select()
    .from(portfolioPnlDaily)
    .where(eq(portfolioPnlDaily.configId, configId))
    .orderBy(desc(portfolioPnlDaily.pnlDate))
    .limit(limit);
}

/**
 * Get P&L for a specific date range
 */
export async function getDailyPnlRange(configId: number, startDate: string, endDate: string) {
  const db = await getDb();
  if (!db) return [];

  return db
    .select()
    .from(portfolioPnlDaily)
    .where(and(
      eq(portfolioPnlDaily.configId, configId),
      gte(portfolioPnlDaily.pnlDate, startDate),
      lte(portfolioPnlDaily.pnlDate, endDate)
    ))
    .orderBy(portfolioPnlDaily.pnlDate);
}
