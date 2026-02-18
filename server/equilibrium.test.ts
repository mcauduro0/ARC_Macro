import { describe, expect, it, vi } from "vitest";
import { appRouter } from "./routers";
import type { TrpcContext } from "./_core/context";

/**
 * Test the equilibrium data flow through the model.latest tRPC procedure.
 * Verifies that equilibrium data (composite r*, SELIC*, model contributions)
 * is correctly returned from the API when present in the database.
 */

function createPublicContext(): TrpcContext {
  return {
    user: null,
    req: {
      protocol: "https",
      headers: {},
    } as TrpcContext["req"],
    res: {
      clearCookie: vi.fn(),
    } as unknown as TrpcContext["res"],
  };
}

// Mock the db module to return controlled data
vi.mock("./db", () => ({
  getLatestModelRun: vi.fn(),
  getModelRunHistory: vi.fn().mockResolvedValue([]),
}));

// Mock the modelRunner module
vi.mock("./modelRunner", () => ({
  executeModel: vi.fn(),
  isModelRunning: vi.fn().mockReturnValue(false),
}));

// Mock the alertEngine module
vi.mock("./alertEngine", () => ({
  getModelChangelog: vi.fn().mockResolvedValue([]),
  getModelAlerts: vi.fn().mockResolvedValue([]),
  getUnreadAlertCount: vi.fn().mockResolvedValue(0),
  markModelAlertRead: vi.fn(),
  dismissModelAlert: vi.fn(),
  dismissAllModelAlerts: vi.fn(),
}));

describe("model.latest equilibrium data", () => {
  it("returns equilibrium data when present in dashboard JSON", async () => {
    const { getLatestModelRun } = await import("./db");
    const mockedGetLatest = vi.mocked(getLatestModelRun);

    const mockEquilibrium = {
      composite_rstar: 4.75,
      selic_star: 11.57,
      method: "composite_5model",
      model_contributions: {
        fiscal: { weight: 0.151, current_value: 6.42 },
        parity: { weight: 0.1, current_value: 6.18 },
        market_implied: { weight: 0.3, current_value: 6.72 },
        state_space: { weight: 0.349, current_value: 2.0 },
        regime: { weight: 0.1, current_value: 4.51 },
      },
      fiscal_decomposition: {
        base: 4.0,
        fiscal: 2.07,
        sovereign: 0.35,
      },
      acm_term_premium_5y: -0.1,
    };

    mockedGetLatest.mockResolvedValue({
      id: 1,
      runDate: "2026-02-14",
      createdAt: new Date("2026-02-14T12:00:00Z"),
      dashboardJson: {
        run_date: "2026-02-14",
        current_spot: 5.22,
        direction: "LONG BRL",
        score_total: 2.09,
        selic_target: 14.9,
        taylor_gap: 3.33,
        equilibrium: mockEquilibrium,
        selic_star: 11.57,
      },
      timeseriesJson: [],
      regimeJson: [],
      cyclicalJson: [],
      stateVariablesJson: [],
      scoreJson: [],
      backtestJson: null,
      shapJson: null,
      shapHistoryJson: null,
      legacyDashboardJson: null,
      legacyTimeseriesJson: null,
      legacyRegimeJson: null,
      legacyCyclicalJson: null,
    } as any);

    const ctx = createPublicContext();
    const caller = appRouter.createCaller(ctx);
    const result = await caller.model.latest();

    expect(result.source).toBe("database");
    expect(result.dashboard).toBeDefined();

    const dash = result.dashboard as Record<string, unknown>;
    const eq = dash.equilibrium as typeof mockEquilibrium;

    // Verify composite r* and SELIC*
    expect(eq).toBeDefined();
    expect(eq.composite_rstar).toBe(4.75);
    expect(eq.selic_star).toBe(11.57);
    expect(eq.method).toBe("composite_5model");

    // Verify model contributions
    expect(eq.model_contributions).toBeDefined();
    expect(Object.keys(eq.model_contributions)).toHaveLength(5);
    expect(eq.model_contributions.fiscal.weight).toBeCloseTo(0.151, 3);
    expect(eq.model_contributions.fiscal.current_value).toBeCloseTo(6.42, 2);
    expect(eq.model_contributions.state_space.weight).toBeCloseTo(0.349, 3);
    expect(eq.model_contributions.state_space.current_value).toBeCloseTo(2.0, 2);

    // Verify fiscal decomposition
    expect(eq.fiscal_decomposition).toBeDefined();
    expect(eq.fiscal_decomposition.base).toBe(4.0);
    expect(eq.fiscal_decomposition.fiscal).toBeCloseTo(2.07, 2);
    expect(eq.fiscal_decomposition.sovereign).toBeCloseTo(0.35, 2);

    // Verify ACM term premium
    expect(eq.acm_term_premium_5y).toBeCloseTo(-0.1, 2);

    // Verify weights sum approximately to 1
    const totalWeight = Object.values(eq.model_contributions)
      .reduce((sum, m) => sum + m.weight, 0);
    expect(totalWeight).toBeCloseTo(1.0, 1);

    // Verify top-level selic_star
    expect(dash.selic_star).toBe(11.57);
  });

  it("returns null equilibrium when not present in dashboard", async () => {
    const { getLatestModelRun } = await import("./db");
    const mockedGetLatest = vi.mocked(getLatestModelRun);

    mockedGetLatest.mockResolvedValue({
      id: 1,
      runDate: "2026-02-14",
      createdAt: new Date("2026-02-14T12:00:00Z"),
      dashboardJson: {
        run_date: "2026-02-14",
        current_spot: 5.22,
        direction: "LONG BRL",
        score_total: 2.09,
        // No equilibrium field
      },
      timeseriesJson: [],
      regimeJson: [],
      cyclicalJson: [],
      stateVariablesJson: [],
      scoreJson: [],
      backtestJson: null,
      shapJson: null,
      shapHistoryJson: null,
      legacyDashboardJson: null,
      legacyTimeseriesJson: null,
      legacyRegimeJson: null,
      legacyCyclicalJson: null,
    } as any);

    const ctx = createPublicContext();
    const caller = appRouter.createCaller(ctx);
    const result = await caller.model.latest();

    expect(result.source).toBe("database");
    const dash = result.dashboard as Record<string, unknown>;
    expect(dash.equilibrium).toBeUndefined();
  });

  it("returns embedded source when no DB run exists", async () => {
    const { getLatestModelRun } = await import("./db");
    const mockedGetLatest = vi.mocked(getLatestModelRun);

    mockedGetLatest.mockResolvedValue(null as any);

    const ctx = createPublicContext();
    const caller = appRouter.createCaller(ctx);
    const result = await caller.model.latest();

    expect(result.source).toBe("embedded");
    expect(result.dashboard).toBeNull();
  });

  it("verifies equilibrium model contribution structure", async () => {
    const { getLatestModelRun } = await import("./db");
    const mockedGetLatest = vi.mocked(getLatestModelRun);

    const mockContributions = {
      fiscal: { weight: 0.15, current_value: 6.42 },
      parity: { weight: 0.10, current_value: 6.18 },
      market_implied: { weight: 0.30, current_value: 6.72 },
      state_space: { weight: 0.35, current_value: 2.00 },
      regime: { weight: 0.10, current_value: 4.51 },
    };

    mockedGetLatest.mockResolvedValue({
      id: 1,
      runDate: "2026-02-14",
      createdAt: new Date("2026-02-14T12:00:00Z"),
      dashboardJson: {
        run_date: "2026-02-14",
        equilibrium: {
          composite_rstar: 4.75,
          selic_star: 11.57,
          method: "composite_5model",
          model_contributions: mockContributions,
        },
      },
      timeseriesJson: [],
      regimeJson: [],
      cyclicalJson: [],
      stateVariablesJson: [],
      scoreJson: [],
      backtestJson: null,
      shapJson: null,
      shapHistoryJson: null,
      legacyDashboardJson: null,
      legacyTimeseriesJson: null,
      legacyRegimeJson: null,
      legacyCyclicalJson: null,
    } as any);

    const ctx = createPublicContext();
    const caller = appRouter.createCaller(ctx);
    const result = await caller.model.latest();

    const dash = result.dashboard as Record<string, unknown>;
    const eq = dash.equilibrium as any;

    // Each model should have weight and current_value
    for (const [name, contrib] of Object.entries(eq.model_contributions) as [string, any][]) {
      expect(contrib).toHaveProperty("weight");
      expect(contrib).toHaveProperty("current_value");
      expect(typeof contrib.weight).toBe("number");
      expect(typeof contrib.current_value).toBe("number");
      expect(contrib.weight).toBeGreaterThanOrEqual(0);
      expect(contrib.weight).toBeLessThanOrEqual(1);
    }

    // Verify all 5 models are present
    const expectedModels = ["fiscal", "parity", "market_implied", "state_space", "regime"];
    for (const model of expectedModels) {
      expect(eq.model_contributions).toHaveProperty(model);
    }
  });
});
