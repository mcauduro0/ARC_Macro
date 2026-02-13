import { describe, expect, it } from "vitest";
import { appRouter } from "./routers";
import type { TrpcContext } from "./_core/context";

/**
 * Tests for v3.9 features:
 * - SHAP historical evolution (temporal snapshots of feature importance)
 * - shapHistory field in model.latest response
 * - shapHistoryJson column in database schema
 */

function createPublicContext(): TrpcContext {
  return {
    user: null,
    req: {
      protocol: "https",
      headers: {},
    } as TrpcContext["req"],
    res: {
      clearCookie: () => {},
    } as TrpcContext["res"],
  };
}

interface ShapHistoryEntry {
  date: string;
  instrument: string;
  feature: string;
  importance: number;
}

describe("model.latest v3.9 SHAP historical evolution", () => {
  it("returns shapHistory field in the response", async () => {
    const ctx = createPublicContext();
    const caller = appRouter.createCaller(ctx);
    const result = await caller.model.latest();

    // shapHistory should be present in the response (may be null if no data)
    expect(result).toHaveProperty("shapHistory");
  });

  it("shapHistory has correct structure when available", async () => {
    const ctx = createPublicContext();
    const caller = appRouter.createCaller(ctx);
    const result = await caller.model.latest();

    if (result.shapHistory && Array.isArray(result.shapHistory)) {
      const history = result.shapHistory as ShapHistoryEntry[];

      // Should have entries
      expect(history.length).toBeGreaterThan(0);

      // Each entry should have required fields
      const entry = history[0];
      expect(entry).toHaveProperty("date");
      expect(entry).toHaveProperty("instrument");
      expect(entry).toHaveProperty("feature");
      expect(entry).toHaveProperty("importance");

      // Validate types
      expect(typeof entry.date).toBe("string");
      expect(typeof entry.instrument).toBe("string");
      expect(typeof entry.feature).toBe("string");
      expect(typeof entry.importance).toBe("number");
    }
  });

  it("shapHistory contains multiple dates (temporal snapshots)", async () => {
    const ctx = createPublicContext();
    const caller = appRouter.createCaller(ctx);
    const result = await caller.model.latest();

    if (result.shapHistory && Array.isArray(result.shapHistory)) {
      const history = result.shapHistory as ShapHistoryEntry[];

      // Extract unique dates
      const uniqueDates = [...new Set(history.map((h) => h.date))];

      // Should have multiple temporal snapshots (we compute every 6 months)
      expect(uniqueDates.length).toBeGreaterThanOrEqual(2);

      // Dates should be in YYYY-MM-DD format
      for (const d of uniqueDates) {
        expect(d).toMatch(/^\d{4}-\d{2}-\d{2}$/);
      }

      // Dates should be chronologically ordered when sorted
      const sortedDates = [...uniqueDates].sort();
      expect(sortedDates[0]).not.toBe(sortedDates[sortedDates.length - 1]);
    }
  });

  it("shapHistory covers expected instruments", async () => {
    const ctx = createPublicContext();
    const caller = appRouter.createCaller(ctx);
    const result = await caller.model.latest();

    if (result.shapHistory && Array.isArray(result.shapHistory)) {
      const history = result.shapHistory as ShapHistoryEntry[];

      // Extract unique instruments
      const instruments = [...new Set(history.map((h) => h.instrument))];

      // Should have the 5 expected instruments
      const expectedInstruments = ["fx", "front", "belly", "long", "hard"];
      for (const inst of expectedInstruments) {
        expect(instruments).toContain(inst);
      }
    }
  });

  it("shapHistory entries have valid mean_abs values (non-negative)", async () => {
    const ctx = createPublicContext();
    const caller = appRouter.createCaller(ctx);
    const result = await caller.model.latest();

    if (result.shapHistory && Array.isArray(result.shapHistory)) {
      const history = result.shapHistory as ShapHistoryEntry[];

      // All importance values should be non-negative
      for (const entry of history) {
        expect(entry.importance).toBeGreaterThanOrEqual(0);
      }
    }
  });

  it("returns null shapHistory in embedded fallback", async () => {
    const ctx = createPublicContext();
    const caller = appRouter.createCaller(ctx);
    const result = await caller.model.latest();

    if (result.source === "embedded") {
      expect(result.shapHistory).toBeNull();
    }
  });

  it("shapHistory has consistent feature sets per instrument per date", async () => {
    const ctx = createPublicContext();
    const caller = appRouter.createCaller(ctx);
    const result = await caller.model.latest();

    if (result.shapHistory && Array.isArray(result.shapHistory)) {
      const history = result.shapHistory as ShapHistoryEntry[];

      // Group by instrument
      const byInstrument = new Map<string, ShapHistoryEntry[]>();
      for (const entry of history) {
        const key = entry.instrument;
        if (!byInstrument.has(key)) byInstrument.set(key, []);
        byInstrument.get(key)!.push(entry);
      }

      // For each instrument, features should be consistent across dates
      for (const [instrument, entries] of byInstrument) {
        const byDate = new Map<string, Set<string>>();
        for (const e of entries) {
          if (!byDate.has(e.date)) byDate.set(e.date, new Set());
          byDate.get(e.date)!.add(e.feature);
        }

        // All dates for this instrument should have the same number of features
        const featureCounts = [...byDate.values()].map((s) => s.size);
        if (featureCounts.length > 1) {
          // Feature count should be consistent (same features each snapshot)
          const firstCount = featureCounts[0];
          for (const count of featureCounts) {
            expect(count).toBe(firstCount);
          }
        }
      }
    }
  });
});
