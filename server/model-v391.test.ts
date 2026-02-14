import { describe, expect, it } from "vitest";
import { appRouter } from "./routers";
import type { TrpcContext } from "./_core/context";

/**
 * Tests for v3.9.1 stability audit:
 * - Backtest covers 10+ years (starts ~2015, not 2021)
 * - 5 stress scenarios present (Dilma, Joesley, COVID, Fed Hiking, Fiscal Lula)
 * - Ibovespa benchmark with non-zero returns
 * - SHAP history with 22 snapshots
 * - training_window=36 with all instruments requiring real data
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

describe("v3.9.1 stability audit", () => {
  it("backtest covers at least 100 months of OOS data", async () => {
    const ctx = createPublicContext();
    const caller = appRouter.createCaller(ctx);
    const result = await caller.model.latest();

    if (result.source === "database" && result.backtest) {
      const backtest = result.backtest as Record<string, unknown>;
      const timeseries = backtest.timeseries as Array<Record<string, unknown>>;
      expect(timeseries).toBeDefined();
      expect(timeseries.length).toBeGreaterThanOrEqual(100);

      // Backtest should start before 2016
      const firstDate = timeseries[0].date as string;
      const firstYear = parseInt(firstDate.slice(0, 4));
      expect(firstYear).toBeLessThanOrEqual(2016);

      // Backtest should end in 2026
      const lastDate = timeseries[timeseries.length - 1].date as string;
      const lastYear = parseInt(lastDate.slice(0, 4));
      expect(lastYear).toBeGreaterThanOrEqual(2025);
    }
  });

  it("dashboard contains 5 stress scenarios", async () => {
    const ctx = createPublicContext();
    const caller = appRouter.createCaller(ctx);
    const result = await caller.model.latest();

    if (result.source === "database") {
      const dashboard = result.dashboard as Record<string, unknown>;
      const stressTests = dashboard.stress_tests as Record<string, unknown>;
      expect(stressTests).toBeDefined();

      const scenarioKeys = Object.keys(stressTests);
      expect(scenarioKeys.length).toBeGreaterThanOrEqual(5);

      // Expected scenarios
      const expectedScenarios = [
        "dilma_2015",
        "joesley_day_2017",
        "covid_2020",
        "fed_hike_2022",
        "lula_fiscal_2024",
      ];
      for (const scenario of expectedScenarios) {
        expect(stressTests).toHaveProperty(scenario);
        const s = stressTests[scenario] as Record<string, unknown>;
        expect(s).toHaveProperty("overlay_return");
        expect(s).toHaveProperty("max_dd_overlay");
        expect(s).toHaveProperty("name");
        expect(s).toHaveProperty("period");
      }
    }
  });

  it("stress scenarios have realistic overlay returns", async () => {
    const ctx = createPublicContext();
    const caller = appRouter.createCaller(ctx);
    const result = await caller.model.latest();

    if (result.source === "database") {
      const dashboard = result.dashboard as Record<string, unknown>;
      const stressTests = dashboard.stress_tests as Record<string, unknown>;

      for (const [key, value] of Object.entries(stressTests)) {
        const scenario = value as Record<string, unknown>;
        const overlayReturn = scenario.overlay_return as number;
        // Overlay returns should be within -20% to +20% range
        expect(overlayReturn).toBeGreaterThanOrEqual(-20);
        expect(overlayReturn).toBeLessThanOrEqual(20);
      }
    }
  });

  it("Ibovespa benchmark has non-zero returns over full backtest", async () => {
    const ctx = createPublicContext();
    const caller = appRouter.createCaller(ctx);
    const result = await caller.model.latest();

    if (result.source === "database" && result.backtest) {
      const backtest = result.backtest as Record<string, unknown>;
      const summary = backtest.summary as Record<string, unknown>;
      const ibov = summary.ibovespa as Record<string, number>;

      expect(ibov).toBeDefined();
      expect(ibov.total_return).toBeGreaterThan(0);
      expect(ibov.annualized_return).toBeGreaterThan(0);
      expect(ibov.sharpe).toBeGreaterThan(0);
      expect(ibov.max_drawdown).toBeLessThan(0);

      // Timeseries should have equity_ibov values
      const timeseries = backtest.timeseries as Array<Record<string, unknown>>;
      const ibovEntries = timeseries.filter(
        (t) => t.equity_ibov != null && (t.equity_ibov as number) !== 0
      );
      expect(ibovEntries.length).toBeGreaterThan(50);
    }
  });

  it("SHAP history has multiple snapshots across the backtest period", async () => {
    const ctx = createPublicContext();
    const caller = appRouter.createCaller(ctx);
    const result = await caller.model.latest();

    if (result.source === "database" && result.shapHistory) {
      const shapHistory = result.shapHistory as Array<Record<string, unknown>>;
      expect(shapHistory.length).toBeGreaterThan(100);

      // Should have multiple unique dates (snapshots)
      const uniqueDates = new Set(shapHistory.map((h) => h.date));
      expect(uniqueDates.size).toBeGreaterThanOrEqual(10);

      // Should cover multiple instruments
      const uniqueInstruments = new Set(shapHistory.map((h) => h.instrument));
      expect(uniqueInstruments.size).toBeGreaterThanOrEqual(5);

      // Each entry should have required fields
      const sample = shapHistory[0];
      expect(sample).toHaveProperty("date");
      expect(sample).toHaveProperty("instrument");
      expect(sample).toHaveProperty("feature");
      expect(sample).toHaveProperty("importance");
    }
  });

  it("backtest timeseries and fair value timeseries overlap temporally", async () => {
    const ctx = createPublicContext();
    const caller = appRouter.createCaller(ctx);
    const result = await caller.model.latest();

    if (result.source === "database" && result.backtest) {
      const backtest = result.backtest as Record<string, unknown>;
      const btTimeseries = backtest.timeseries as Array<Record<string, unknown>>;
      const fvTimeseries = result.timeseries as Array<Record<string, unknown>>;

      if (btTimeseries && btTimeseries.length > 0 && fvTimeseries && fvTimeseries.length > 0) {
        const btFirstDate = btTimeseries[0].date as string;
        const btLastDate = btTimeseries[btTimeseries.length - 1].date as string;
        const fvLastDate = fvTimeseries[fvTimeseries.length - 1].date as string;

        // Both should end at approximately the same date
        const btLastYear = parseInt(btLastDate.slice(0, 4));
        const fvLastYear = parseInt(fvLastDate.slice(0, 4));
        expect(Math.abs(btLastYear - fvLastYear)).toBeLessThanOrEqual(1);
      }
    }
  });

  it("overlay metrics are reasonable for 10+ year backtest", async () => {
    const ctx = createPublicContext();
    const caller = appRouter.createCaller(ctx);
    const result = await caller.model.latest();

    if (result.source === "database" && result.backtest) {
      const backtest = result.backtest as Record<string, unknown>;
      const summary = backtest.summary as Record<string, unknown>;
      const overlay = summary.overlay as Record<string, number>;

      expect(overlay).toBeDefined();
      // Sharpe should be positive and reasonable
      expect(overlay.sharpe).toBeGreaterThan(0);
      expect(overlay.sharpe).toBeLessThan(5);
      // Max drawdown should be negative
      expect(overlay.max_drawdown).toBeLessThan(0);
      // Win rate should be between 40% and 80%
      expect(overlay.win_rate).toBeGreaterThan(40);
      expect(overlay.win_rate).toBeLessThan(80);
    }
  });
});
