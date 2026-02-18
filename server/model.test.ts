import { describe, expect, it, vi, beforeEach } from "vitest";
import { appRouter } from "./routers";
import type { TrpcContext } from "./_core/context";

// Mock the db module
vi.mock("./db", () => ({
  getLatestModelRun: vi.fn(),
  getModelRunHistory: vi.fn(),
  insertModelRun: vi.fn(),
  upsertUser: vi.fn(),
  getUserByOpenId: vi.fn(),
  getDb: vi.fn(),
  updateModelRunStatus: vi.fn(),
}));

// Mock the modelRunner module
vi.mock("./modelRunner", () => ({
  executeModel: vi.fn(),
  isModelRunning: vi.fn(),
}));

import { getLatestModelRun, getModelRunHistory } from "./db";
import { isModelRunning, executeModel } from "./modelRunner";

const mockedGetLatestModelRun = vi.mocked(getLatestModelRun);
const mockedGetModelRunHistory = vi.mocked(getModelRunHistory);
const mockedIsModelRunning = vi.mocked(isModelRunning);
const mockedExecuteModel = vi.mocked(executeModel);

type AuthenticatedUser = NonNullable<TrpcContext["user"]>;

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

function createAuthContext(): TrpcContext {
  const user: AuthenticatedUser = {
    id: 1,
    openId: "test-user",
    email: "test@example.com",
    name: "Test User",
    loginMethod: "manus",
    role: "admin",
    createdAt: new Date(),
    updatedAt: new Date(),
    lastSignedIn: new Date(),
  };

  return {
    user,
    req: {
      protocol: "https",
      headers: {},
    } as TrpcContext["req"],
    res: {
      clearCookie: vi.fn(),
    } as unknown as TrpcContext["res"],
  };
}

describe("model.latest - ARC Macro cross-asset data", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("returns database data with cross-asset fields when a completed run exists", async () => {
    const mockRun = {
      id: 30001,
      runDate: "2026-02-11",
      currentSpot: 5.1916,
      dashboardJson: {
        run_date: "2026-02-11",
        current_spot: 5.1916,
        current_regime: "Carry",
        direction: "NEUTRAL",
        score_total: -0.25,
        state_variables: { Z_X1: 1.53, Z_X5: -0.85 },
        positions: {
          fx: { weight: 0.023, expected_return_6m: 0.0546 },
          front: { weight: -2.0, expected_return_6m: -0.0009 },
          long: { weight: -0.433, expected_return_6m: -0.0002 },
          hard: { weight: -0.797, expected_return_6m: -0.0023 },
        },
        regime_probabilities: { Carry: 0.76, RiskOff: 0.077, StressDom: 0.163 },
        risk_metrics: { portfolio_vol: 0.0289 },
      },
      timeseriesJson: [{ date: "2025-01-01", spot: 5.0, fx_fair: 4.8 }],
      regimeJson: [{ date: "2025-01-01", Carry: 0.8, RiskOff: 0.1, StressDom: 0.1 }],
      cyclicalJson: [],
      stateVariablesJson: [{ date: "2025-01-01", Z_DXY: 0.5, Z_COMMODITIES: 0.3 }],
      legacyDashboardJson: { current_spot: 5.1916, score_total: 0.8 },
      legacyTimeseriesJson: null,
      legacyRegimeJson: null,
      legacyCyclicalJson: null,
      status: "completed" as const,
      errorMessage: null,
      isLatest: true,
      createdAt: new Date("2026-02-11T14:00:00Z"),
    };

    mockedGetLatestModelRun.mockResolvedValue(mockRun);

    const caller = appRouter.createCaller(createPublicContext());
    const result = await caller.model.latest();

    expect(result.source).toBe("database");
    expect(result.runDate).toBe("2026-02-11");
    expect(result.dashboard).toEqual(mockRun.dashboardJson);
    expect(result.timeseries).toEqual(mockRun.timeseriesJson);
    expect(result.regime).toEqual(mockRun.regimeJson);
    expect(result.cyclical).toEqual(mockRun.cyclicalJson);
    expect(result.stateVariables).toEqual(mockRun.stateVariablesJson);
    expect(result.legacyDashboard).toEqual(mockRun.legacyDashboardJson);
    expect(result.updatedAt).toEqual(mockRun.createdAt);
  });

  it("returns stateVariables as empty array when null in DB", async () => {
    const mockRun = {
      id: 1,
      runDate: "2026-02-11",
      currentSpot: 5.2,
      dashboardJson: { run_date: "2026-02-11" },
      timeseriesJson: [],
      regimeJson: [],
      cyclicalJson: [],
      stateVariablesJson: null,
      legacyDashboardJson: null,
      legacyTimeseriesJson: null,
      legacyRegimeJson: null,
      legacyCyclicalJson: null,
      status: "completed" as const,
      errorMessage: null,
      isLatest: true,
      createdAt: new Date(),
    };

    mockedGetLatestModelRun.mockResolvedValue(mockRun);

    const caller = appRouter.createCaller(createPublicContext());
    const result = await caller.model.latest();

    expect(result.stateVariables).toEqual([]);
  });

  it("returns embedded source with null fields when no database run exists", async () => {
    mockedGetLatestModelRun.mockResolvedValue(undefined);

    const caller = appRouter.createCaller(createPublicContext());
    const result = await caller.model.latest();

    expect(result.source).toBe("embedded");
    expect(result.dashboard).toBeNull();
    expect(result.timeseries).toBeNull();
    expect(result.regime).toBeNull();
    expect(result.cyclical).toBeNull();
    expect(result.stateVariables).toBeNull();
    expect(result.legacyDashboard).toBeNull();
    expect(result.legacyTimeseries).toBeNull();
    expect(result.legacyRegime).toBeNull();
    expect(result.legacyCyclical).toBeNull();
  });
});

describe("model.status", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("returns isRunning false when model is idle", async () => {
    mockedIsModelRunning.mockReturnValue(false);

    const caller = appRouter.createCaller(createPublicContext());
    const result = await caller.model.status();

    expect(result.isRunning).toBe(false);
  });

  it("returns isRunning true when model is executing", async () => {
    mockedIsModelRunning.mockReturnValue(true);

    const caller = appRouter.createCaller(createPublicContext());
    const result = await caller.model.status();

    expect(result.isRunning).toBe(true);
  });
});

describe("model.history", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("returns model run history", async () => {
    const mockHistory = [
      {
        id: 30001,
        runDate: "2026-02-11",
        currentSpot: 5.1916,
        status: "completed" as const,
        isLatest: true,
        createdAt: new Date("2026-02-11T14:00:00Z"),
      },
      {
        id: 1,
        runDate: "2026-02-11",
        currentSpot: 5.2183,
        status: "completed" as const,
        isLatest: false,
        createdAt: new Date("2026-02-11T12:00:00Z"),
      },
    ];

    mockedGetModelRunHistory.mockResolvedValue(mockHistory);

    const caller = appRouter.createCaller(createPublicContext());
    const result = await caller.model.history();

    expect(result).toHaveLength(2);
    expect(result[0].id).toBe(30001);
    expect(result[0].isLatest).toBe(true);
    expect(result[1].id).toBe(1);
    expect(result[1].isLatest).toBe(false);
  });

  it("returns empty array when no history exists", async () => {
    mockedGetModelRunHistory.mockResolvedValue([]);

    const caller = appRouter.createCaller(createPublicContext());
    const result = await caller.model.history();

    expect(result).toEqual([]);
  });
});

describe("model.run - ARC Macro execution trigger", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("starts ARC Macro execution when not already running", async () => {
    mockedIsModelRunning.mockReturnValue(false);
    mockedExecuteModel.mockResolvedValue({ success: true, runId: 30002 });

    const caller = appRouter.createCaller(createAuthContext());
    const result = await caller.model.run();

    expect(result.success).toBe(true);
    expect(result.message).toBe("ARC Macro execution started");
  });

  it("returns error when model is already running", async () => {
    mockedIsModelRunning.mockReturnValue(true);

    const caller = appRouter.createCaller(createAuthContext());
    const result = await caller.model.run();

    expect(result.success).toBe(false);
    expect(result.error).toBe("Model is already running");
  });

  it("requires authentication to trigger model run", async () => {
    const caller = appRouter.createCaller(createPublicContext());

    await expect(caller.model.run()).rejects.toThrow();
  });
});
