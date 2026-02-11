import { eq, desc, and } from "drizzle-orm";
import { drizzle } from "drizzle-orm/mysql2";
import { InsertUser, users, modelRuns, InsertModelRun } from "../drizzle/schema";
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
