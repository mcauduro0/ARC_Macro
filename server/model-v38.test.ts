import { describe, expect, it } from "vitest";
import { appRouter } from "./routers";
import type { TrpcContext } from "./_core/context";

/**
 * Tests for v3.8 features:
 * - SHAP feature importance in model.latest response
 * - Ibovespa benchmark in backtest summary and timeseries
 * - shapJson column in database schema
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

describe("model.latest v3.8 features", () => {
  it("returns shapImportance field in the response", async () => {
    const ctx = createPublicContext();
    const caller = appRouter.createCaller(ctx);
    const result = await caller.model.latest();

    // shapImportance should be present in the response (may be null if no data)
    expect(result).toHaveProperty("shapImportance");
  });

  it("returns backtest with Ibovespa benchmark data when available", async () => {
    const ctx = createPublicContext();
    const caller = appRouter.createCaller(ctx);
    const result = await caller.model.latest();

    if (result.source === "database" && result.backtest) {
      const backtest = result.backtest as Record<string, unknown>;
      const summary = backtest.summary as Record<string, unknown>;

      // Ibovespa should be in the summary
      expect(summary).toHaveProperty("ibovespa");

      const ibov = summary.ibovespa as Record<string, unknown>;
      expect(ibov).toHaveProperty("total_return");
      expect(ibov).toHaveProperty("annualized_return");
      expect(ibov).toHaveProperty("sharpe");
      expect(ibov).toHaveProperty("max_drawdown");
      expect(ibov).toHaveProperty("win_rate");
      // calmar is optional in Ibovespa summary

      // Ibovespa total return should be a number (may be 0 if benchmark not computed)
      expect(typeof ibov.total_return).toBe("number");

      // Timeseries should have equity_ibov
      const timeseries = backtest.timeseries as Array<Record<string, unknown>>;
      if (timeseries && timeseries.length > 0) {
        const lastPoint = timeseries[timeseries.length - 1];
        expect(lastPoint).toHaveProperty("equity_ibov");
        expect(lastPoint).toHaveProperty("ibov_return");
        expect(lastPoint).toHaveProperty("drawdown_ibov");

        // equity_ibov should be a number (may be 0 or 1 if benchmark not computed)
        expect(typeof lastPoint.equity_ibov).toBe("number");
      }
    }
  });

  it("SHAP importance has correct structure when available", async () => {
    const ctx = createPublicContext();
    const caller = appRouter.createCaller(ctx);
    const result = await caller.model.latest();

    if (result.shapImportance) {
      const shap = result.shapImportance as Record<
        string,
        Record<string, { mean_abs: number; current: number; rank: number }>
      >;

      // Should have instruments
      const instruments = Object.keys(shap);
      expect(instruments.length).toBeGreaterThan(0);

      // Expected instruments
      const expectedInstruments = ["fx", "front", "belly", "long", "hard"];
      for (const inst of expectedInstruments) {
        if (shap[inst]) {
          const features = shap[inst];
          const featureNames = Object.keys(features);
          expect(featureNames.length).toBeGreaterThan(0);

          // Each feature should have mean_abs, current, rank
          for (const feat of featureNames) {
            expect(features[feat]).toHaveProperty("mean_abs");
            expect(features[feat]).toHaveProperty("current");
            expect(features[feat]).toHaveProperty("rank");
            expect(typeof features[feat].mean_abs).toBe("number");
            expect(typeof features[feat].current).toBe("number");
            expect(typeof features[feat].rank).toBe("number");
          }
        }
      }
    }
  });

  it("returns embedded fallback with null shapImportance when no DB data", async () => {
    // This tests the fallback path structure
    const ctx = createPublicContext();
    const caller = appRouter.createCaller(ctx);
    const result = await caller.model.latest();

    // Whether database or embedded, shapImportance should be defined
    if (result.source === "embedded") {
      expect(result.shapImportance).toBeNull();
      expect(result.backtest).toBeNull();
    }
  });
});
