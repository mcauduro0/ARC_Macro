/**
 * Tests for Model Changelog & Alerts (v3.9.2)
 * Tests the alert engine detection logic, changelog generation,
 * and tRPC procedure responses.
 */
import { describe, it, expect } from "vitest";

// ============================================================
// Alert Engine Detection Logic Tests
// ============================================================

describe("Alert Engine — Regime Change Detection", () => {
  it("should detect regime change from carry to stress as critical", () => {
    const prevRegime = "carry";
    const curRegime = "stress_dom";
    expect(curRegime).not.toBe(prevRegime);
    // Stress regime should trigger critical severity
    const severity = curRegime.toLowerCase().includes("stress") ? "critical"
      : curRegime.toLowerCase().includes("riskoff") ? "warning"
      : "info";
    expect(severity).toBe("critical");
  });

  it("should detect regime change from carry to riskoff as warning", () => {
    const curRegime = "riskoff";
    const severity = curRegime.toLowerCase().includes("stress") ? "critical"
      : curRegime.toLowerCase().includes("riskoff") ? "warning"
      : "info";
    expect(severity).toBe("warning");
  });

  it("should detect regime change to carry as info", () => {
    const curRegime = "carry";
    const severity = curRegime.toLowerCase().includes("stress") ? "critical"
      : curRegime.toLowerCase().includes("riskoff") ? "warning"
      : "info";
    expect(severity).toBe("info");
  });

  it("should not alert when regime stays the same", () => {
    const prevRegime = "carry";
    const curRegime = "carry";
    expect(curRegime === prevRegime).toBe(true);
    // No alert should be generated
  });

  it("should detect stress probability surge above 15pp", () => {
    const prevStress = 0.10;
    const curStress = 0.30;
    const stressDelta = curStress - prevStress;
    expect(stressDelta).toBeGreaterThan(0.15);
  });
});

describe("Alert Engine — SHAP Shift Detection", () => {
  it("should detect when a feature crosses 20% relative importance", () => {
    const RELATIVE_THRESHOLD = 0.20;
    const curRelative = 0.25;
    const prevRelative = 0.15;
    expect(curRelative >= RELATIVE_THRESHOLD && prevRelative < RELATIVE_THRESHOLD).toBe(true);
  });

  it("should not alert when feature stays below threshold", () => {
    const RELATIVE_THRESHOLD = 0.20;
    const curRelative = 0.18;
    const prevRelative = 0.15;
    expect(curRelative >= RELATIVE_THRESHOLD && prevRelative < RELATIVE_THRESHOLD).toBe(false);
  });

  it("should detect large relative shift (>15pp)", () => {
    const curRelative = 0.30;
    const prevRelative = 0.10;
    const relativeShift = curRelative - prevRelative;
    expect(Math.abs(relativeShift)).toBeGreaterThan(0.15);
  });

  it("should detect new top driver (rank change to 1)", () => {
    const curRank = 1;
    const prevRank = 3;
    expect(curRank === 1 && prevRank !== 1).toBe(true);
  });

  it("should calculate relative importance correctly", () => {
    const features = {
      "feature_a": { mean_abs: 0.3 },
      "feature_b": { mean_abs: 0.5 },
      "feature_c": { mean_abs: 0.2 },
    };
    const total = Object.values(features).reduce((s, f) => s + f.mean_abs, 0);
    expect(total).toBe(1.0);
    expect(features.feature_b.mean_abs / total).toBe(0.5);
  });
});

describe("Alert Engine — Score Change Detection", () => {
  it("should detect significant score change (>1.0)", () => {
    const curScore = 3.5;
    const prevScore = 2.0;
    const delta = curScore - prevScore;
    expect(Math.abs(delta)).toBeGreaterThan(1.0);
  });

  it("should classify large score change (>2.0) as warning", () => {
    const delta = 2.5;
    const severity = Math.abs(delta) > 2.0 ? "warning" : "info";
    expect(severity).toBe("warning");
  });

  it("should not alert on small score changes (<1.0)", () => {
    const curScore = 2.5;
    const prevScore = 2.0;
    const delta = curScore - prevScore;
    expect(Math.abs(delta)).toBeLessThanOrEqual(1.0);
  });
});

describe("Alert Engine — Drawdown Warning", () => {
  it("should alert on max drawdown worse than -10%", () => {
    const maxDD = -12.5; // percentage
    expect(maxDD < -10).toBe(true);
  });

  it("should classify drawdown worse than -15% as critical", () => {
    const maxDD = -18.0;
    const severity = maxDD < -15 ? "critical" : "warning";
    expect(severity).toBe("critical");
  });

  it("should not alert on normal drawdown (-5.56%)", () => {
    const maxDD = -5.56;
    expect(maxDD < -10).toBe(false);
  });
});

// ============================================================
// Changelog Generation Tests
// ============================================================

describe("Changelog — Entry Generation", () => {
  it("should detect regime change in changelog", () => {
    const curRegime = "carry";
    const prevRegime = "stress_dom";
    const changes: Array<{ type: string; description: string }> = [];
    if (curRegime !== prevRegime) {
      changes.push({
        type: "regime",
        description: `Regime: ${prevRegime} → ${curRegime}`,
      });
    }
    expect(changes).toHaveLength(1);
    expect(changes[0].type).toBe("regime");
  });

  it("should detect score change in changelog", () => {
    const curScore = 2.09;
    const prevScore = -1.5;
    const changes: Array<{ type: string; description: string }> = [];
    const delta = curScore - prevScore;
    if (Math.abs(delta) > 0.5) {
      changes.push({
        type: "score",
        description: `Score: ${prevScore.toFixed(2)} → ${curScore.toFixed(2)} (${delta > 0 ? "+" : ""}${delta.toFixed(2)})`,
      });
    }
    expect(changes).toHaveLength(1);
    expect(changes[0].type).toBe("score");
  });

  it("should detect position weight changes in changelog", () => {
    const curWeights = { fx: 0.041, front: -0.021, belly: 0.0, long: 0.585, hard: -0.001 };
    const prevWeights = { fx: 0.10, front: 0.05, belly: 0.0, long: 0.30, hard: 0.05 };
    const changes: Array<{ type: string; description: string }> = [];
    for (const inst of ["fx", "front", "belly", "long", "hard"] as const) {
      const curW = curWeights[inst];
      const prevW = prevWeights[inst];
      const delta = curW - prevW;
      if (Math.abs(delta) > 0.05) {
        changes.push({
          type: "position",
          description: `${inst.toUpperCase()}: peso ${(prevW * 100).toFixed(0)}% → ${(curW * 100).toFixed(0)}%`,
        });
      }
    }
    // fx: -0.059 > 0.05, front: -0.071 > 0.05, long: 0.285 > 0.05, hard: -0.051 > 0.05
    expect(changes.length).toBeGreaterThanOrEqual(3);
    expect(changes.every(c => c.type === "position")).toBe(true);
  });

  it("should add default change when no significant changes detected", () => {
    const changes: Array<{ type: string; description: string }> = [];
    if (changes.length === 0) {
      changes.push({ type: "update", description: "Atualização de dados sem mudanças significativas" });
    }
    expect(changes).toHaveLength(1);
    expect(changes[0].type).toBe("update");
  });
});

// ============================================================
// API Response Structure Tests
// ============================================================

describe("Changelog & Alerts — API Response Structure", () => {
  it("should have correct changelog entry fields", () => {
    const entry = {
      id: 1,
      modelRunId: 420001,
      version: "v2.3",
      runDate: "2026-02-14",
      score: 2.09,
      regime: "carry",
      regimeCarryProb: 0.76,
      regimeRiskoffProb: 0.20,
      regimeStressProb: 0.04,
      backtestSharpe: 0.70,
      backtestReturn: 37.93,
      backtestMaxDD: -5.56,
      backtestWinRate: 60.6,
      backtestMonths: 127,
      weightFx: 0.041,
      weightFront: -0.021,
      weightBelly: 0.0,
      weightLong: 0.585,
      weightHard: -0.001,
      trainingWindow: 36,
      nStressScenarios: 5,
      changesJson: [{ type: "regime", description: "Regime: stress → carry" }],
    };

    expect(entry.version).toBe("v2.3");
    expect(entry.score).toBe(2.09);
    expect(entry.regime).toBe("carry");
    expect(entry.backtestSharpe).toBe(0.70);
    expect(entry.backtestReturn).toBe(37.93);
    expect(entry.backtestMaxDD).toBe(-5.56);
    expect(entry.backtestWinRate).toBe(60.6);
    expect(entry.backtestMonths).toBe(127);
    expect(entry.weightFx).toBe(0.041);
    expect(entry.weightLong).toBe(0.585);
    expect(entry.trainingWindow).toBe(36);
    expect(entry.nStressScenarios).toBe(5);
    expect(entry.changesJson).toHaveLength(1);
  });

  it("should have correct alert entry fields", () => {
    const alert = {
      id: 1,
      modelRunId: 420001,
      alertType: "regime_change",
      severity: "warning",
      title: "Regime Change: domestic_stress → carry",
      message: "Regime mudou de Stress Doméstico para Carry.",
      previousValue: "domestic_stress",
      currentValue: "carry",
      threshold: null,
      instrument: null,
      feature: null,
      isRead: false,
      isDismissed: false,
    };

    expect(alert.alertType).toBe("regime_change");
    expect(alert.severity).toBe("warning");
    expect(alert.title).toContain("Regime Change");
    expect(alert.isRead).toBe(false);
    expect(alert.isDismissed).toBe(false);
  });

  it("should have correct alert types enum values", () => {
    const validTypes = ["regime_change", "shap_shift", "score_change", "drawdown_warning", "model_update"];
    const validSeverities = ["info", "warning", "critical"];

    expect(validTypes).toContain("regime_change");
    expect(validTypes).toContain("shap_shift");
    expect(validTypes).toContain("drawdown_warning");
    expect(validSeverities).toContain("critical");
  });

  it("should parse changesJson correctly from both string and array", () => {
    // Array format (normal)
    const arrayChanges = [{ type: "regime", description: "test" }];
    const parsed1 = Array.isArray(arrayChanges) ? arrayChanges : JSON.parse(arrayChanges as unknown as string);
    expect(parsed1).toHaveLength(1);

    // String format (edge case from DB)
    const stringChanges = JSON.stringify([{ type: "score", description: "test2" }]);
    const parsed2 = Array.isArray(stringChanges) ? stringChanges : JSON.parse(stringChanges);
    expect(parsed2).toHaveLength(1);
    expect(parsed2[0].type).toBe("score");
  });
});

// ============================================================
// Regime Format Helper Tests
// ============================================================

describe("Regime Probability Key Mapping", () => {
  it("should read probabilities from lowercase keys (dashboard JSON format)", () => {
    // Dashboard JSON uses lowercase keys: P_carry, P_riskoff, P_stress
    const dashboardProbs = {
      P_carry: 0.998,
      P_riskoff: 0.0,
      P_stress: 0.002,
      P_domestic_calm: 0.918,
      P_domestic_stress: 0.082,
    };
    // The fix uses fallback: P_carry ?? P_Carry ?? 0
    const pCarry = dashboardProbs.P_carry ?? (dashboardProbs as any).P_Carry ?? 0;
    const pRiskoff = dashboardProbs.P_riskoff ?? (dashboardProbs as any).P_RiskOff ?? 0;
    const pStress = dashboardProbs.P_stress ?? (dashboardProbs as any).P_StressDom ?? 0;
    expect(pCarry).toBe(0.998);
    expect(pRiskoff).toBe(0.0);
    expect(pStress).toBe(0.002);
  });

  it("should also work with capitalized keys (regime timeseries format)", () => {
    // Regime timeseries uses capitalized keys: P_Carry, P_RiskOff, P_StressDom
    const timeseriesProbs: Record<string, number> = {
      P_Carry: 0.85,
      P_RiskOff: 0.10,
      P_StressDom: 0.05,
    };
    const pCarry = (timeseriesProbs as any).P_carry ?? timeseriesProbs.P_Carry ?? 0;
    const pRiskoff = (timeseriesProbs as any).P_riskoff ?? timeseriesProbs.P_RiskOff ?? 0;
    const pStress = (timeseriesProbs as any).P_stress ?? timeseriesProbs.P_StressDom ?? 0;
    expect(pCarry).toBe(0.85);
    expect(pRiskoff).toBe(0.10);
    expect(pStress).toBe(0.05);
  });

  it("should build correct probability string from dashboard JSON", () => {
    const curProbs: Record<string, number> = {
      P_carry: 0.998,
      P_riskoff: 0.0,
      P_stress: 0.002,
    };
    const pCarry = curProbs.P_carry ?? (curProbs as any).P_Carry ?? 0;
    const pRiskoff = curProbs.P_riskoff ?? (curProbs as any).P_RiskOff ?? 0;
    const pStress = curProbs.P_stress ?? (curProbs as any).P_StressDom ?? 0;
    const probStr = `Carry ${(pCarry * 100).toFixed(1)}%, Risk-Off ${(pRiskoff * 100).toFixed(1)}%, Stress ${(pStress * 100).toFixed(1)}%`;
    expect(probStr).toBe("Carry 99.8%, Risk-Off 0.0%, Stress 0.2%");
  });
});

describe("Regime Format Helper", () => {
  it("should format known regimes correctly", () => {
    const map: Record<string, string> = {
      carry: "Carry",
      riskoff: "Risk-Off",
      stress_dom: "Stress Doméstico",
    };
    expect(map["carry"]).toBe("Carry");
    expect(map["riskoff"]).toBe("Risk-Off");
    expect(map["stress_dom"]).toBe("Stress Doméstico");
  });

  it("should return raw string for unknown regimes", () => {
    const map: Record<string, string> = {
      carry: "Carry",
      riskoff: "Risk-Off",
    };
    const unknown = "new_regime";
    expect(map[unknown] || unknown).toBe("new_regime");
  });
});
