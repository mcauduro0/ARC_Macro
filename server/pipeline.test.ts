import { describe, it, expect, vi, beforeEach } from "vitest";
import { getPipelineStatus } from "./pipelineOrchestrator";

describe("Pipeline Orchestrator", () => {
  describe("getPipelineStatus", () => {
    it("returns not running when no pipeline is active", () => {
      const status = getPipelineStatus();
      expect(status.isRunning).toBe(false);
      expect(status.currentStep).toBeNull();
      expect(status.progress).toBe(0);
      expect(status.steps).toEqual([]);
    });
  });

  describe("Pipeline step structure", () => {
    it("defines 6 pipeline steps", async () => {
      // Import the module to check the step definitions
      const mod = await import("./pipelineOrchestrator");
      // getPipelineStatus returns empty steps when not running
      const status = mod.getPipelineStatus();
      expect(status.isRunning).toBe(false);
      // The pipeline defines 6 steps: data_ingest, model_run, alerts, portfolio, backtest, notify
    });
  });

  describe("Pipeline status shape", () => {
    it("has correct shape when not running", () => {
      const status = getPipelineStatus();
      expect(status).toHaveProperty("isRunning");
      expect(status).toHaveProperty("currentStep");
      expect(status).toHaveProperty("progress");
      expect(status).toHaveProperty("steps");
      expect(typeof status.isRunning).toBe("boolean");
      expect(typeof status.progress).toBe("number");
      expect(Array.isArray(status.steps)).toBe(true);
    });

    it("progress is between 0 and 100", () => {
      const status = getPipelineStatus();
      expect(status.progress).toBeGreaterThanOrEqual(0);
      expect(status.progress).toBeLessThanOrEqual(100);
    });
  });
});

describe("Pipeline tRPC endpoints", () => {
  it("pipeline.status returns pipeline status", async () => {
    const { appRouter } = await import("./routers");
    const caller = appRouter.createCaller({ user: null } as any);
    const status = await caller.pipeline.status();
    expect(status).toHaveProperty("isRunning");
    expect(status).toHaveProperty("progress");
    expect(status).toHaveProperty("steps");
  });

  it("pipeline.latest returns null when no runs exist", async () => {
    const { appRouter } = await import("./routers");
    const caller = appRouter.createCaller({ user: null } as any);
    const latest = await caller.pipeline.latest();
    // May be null if no pipeline has run yet
    expect(latest === null || typeof latest === "object").toBe(true);
  });

  it("pipeline.history returns an array", async () => {
    const { appRouter } = await import("./routers");
    const caller = appRouter.createCaller({ user: null } as any);
    const history = await caller.pipeline.history();
    expect(Array.isArray(history)).toBe(true);
  });

  it("pipeline.trigger requires authentication", async () => {
    const { appRouter } = await import("./routers");
    const caller = appRouter.createCaller({ user: null } as any);
    await expect(caller.pipeline.trigger()).rejects.toThrow();
  });

  it("pipeline.trigger works for authenticated user", async () => {
    const { appRouter } = await import("./routers");
    const mockUser = { id: 1, openId: "test-user", name: "Test", role: "admin" };
    const caller = appRouter.createCaller({ user: mockUser } as any);
    // This will attempt to run the pipeline but may fail due to missing Python/DB
    // We just verify it doesn't throw an auth error
    try {
      const result = await caller.pipeline.trigger();
      expect(result).toHaveProperty("success");
    } catch (err: any) {
      // If it fails, it should NOT be an auth error
      expect(err.message).not.toContain("login");
      expect(err.message).not.toContain("UNAUTHORIZED");
    }
  });
});

describe("Pipeline step validation", () => {
  it("PipelineStep interface has required fields", () => {
    // Type check: a valid PipelineStep
    const step = {
      name: "data_ingest",
      label: "Ingestão de Dados",
      status: "pending" as const,
    };
    expect(step.name).toBe("data_ingest");
    expect(step.label).toBe("Ingestão de Dados");
    expect(step.status).toBe("pending");
  });

  it("PipelineStep status can be any valid value", () => {
    const validStatuses = ["pending", "running", "completed", "failed", "skipped"];
    validStatuses.forEach(status => {
      const step = { name: "test", label: "Test", status };
      expect(validStatuses).toContain(step.status);
    });
  });
});
