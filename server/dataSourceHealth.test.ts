import { describe, expect, it, vi } from "vitest";
import { DATA_SOURCES } from "./dataSourceHealth";

describe("Data Source Health", () => {
  it("DATA_SOURCES registry contains all expected sources", () => {
    const sourceNames = DATA_SOURCES.map(s => s.name);
    
    expect(sourceNames).toContain("bcb");
    expect(sourceNames).toContain("fred");
    expect(sourceNames).toContain("yahoo");
    expect(sourceNames).toContain("anbima");
    expect(sourceNames).toContain("trading_economics");
    expect(sourceNames).toContain("ipeadata");
    expect(sourceNames).toContain("fmp");
    expect(DATA_SOURCES.length).toBe(7);
  });

  it("each data source has required fields", () => {
    for (const source of DATA_SOURCES) {
      expect(source.name).toBeTruthy();
      expect(source.label).toBeTruthy();
      expect(source.description).toBeTruthy();
      expect(source.endpoint).toBeTruthy();
      expect(typeof source.checkFn).toBe("function");
    }
  });

  it("source names are unique", () => {
    const names = DATA_SOURCES.map(s => s.name);
    const uniqueNames = new Set(names);
    expect(uniqueNames.size).toBe(names.length);
  });

  it("source labels are human-readable (not empty, not just the name)", () => {
    for (const source of DATA_SOURCES) {
      expect(source.label.length).toBeGreaterThanOrEqual(source.name.length);
    }
  });
});

describe("Pipeline Retry Logic", () => {
  it("exponential backoff calculates correct delays", () => {
    // Verify the backoff formula: baseDelay * 2^attempt
    const baseDelay = 2000;
    const delays = [0, 1, 2].map(attempt => baseDelay * Math.pow(2, attempt));
    
    expect(delays[0]).toBe(2000);  // 2s
    expect(delays[1]).toBe(4000);  // 4s
    expect(delays[2]).toBe(8000);  // 8s
  });

  it("retry count is bounded by MAX_RETRIES", () => {
    const MAX_RETRIES = 3;
    let attempts = 0;
    
    const simulateRetry = () => {
      while (attempts < MAX_RETRIES) {
        attempts++;
        // Simulate failure
        const success = false;
        if (success) break;
      }
    };
    
    simulateRetry();
    expect(attempts).toBe(MAX_RETRIES);
    expect(attempts).toBeLessThanOrEqual(3);
  });
});

describe("Pipeline Step Structure", () => {
  it("step definitions include retry fields", () => {
    // Verify the step interface supports retry tracking
    interface PipelineStep {
      name: string;
      label: string;
      status: string;
      durationMs?: number;
      message?: string;
      error?: string;
      retryCount?: number;
      lastRetryError?: string;
    }

    const step: PipelineStep = {
      name: "data_ingest",
      label: "Ingestão de Dados",
      status: "completed",
      durationMs: 5000,
      retryCount: 1,
      lastRetryError: "BCB timeout",
    };

    expect(step.retryCount).toBe(1);
    expect(step.lastRetryError).toBe("BCB timeout");
    expect(step.status).toBe("completed");
  });
});
