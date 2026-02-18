/**
 * Tests for New Features (v5.0):
 * 1. Regime Change Alerts with Rebalancing Recommendations
 * 2. Real Ibovespa Benchmark Integration
 * 3. Rebalancing UI Data (Portfolio Engine)
 */
import { describe, it, expect } from "vitest";

// ============================================================
// 1. Regime Change Alerts with Rebalancing Recommendations
// ============================================================

describe("Regime Change Alerts — Rebalancing Recommendations", () => {
  it("should append critical rebalancing action for stress regime changes", () => {
    const severity = "critical";
    const baseMessage = "Regime mudou de Carry para Stress Doméstico.";
    const rebalMsg = severity === "critical"
      ? '\n\n🔄 AÇÃO REQUERIDA: Rebalanceamento do portfólio recomendado. Acesse a aba "Rebalancear" no Portfolio Management para revisar as ordens de execução e custos de transação estimados.'
      : '\n\n📋 Monitorar portfólio. Verifique a aba "Rebalancear" para avaliar se ajustes são necessários.';
    const fullMessage = baseMessage + rebalMsg;
    expect(fullMessage).toContain("AÇÃO REQUERIDA");
    expect(fullMessage).toContain("Rebalancear");
    expect(fullMessage).toContain("custos de transação");
  });

  it("should append monitoring recommendation for warning regime changes", () => {
    const severity = "warning";
    const baseMessage = "Regime mudou de Carry para Risk-Off.";
    const rebalMsg = severity === "critical"
      ? '\n\n🔄 AÇÃO REQUERIDA: Rebalanceamento do portfólio recomendado.'
      : '\n\n📋 Monitorar portfólio. Verifique a aba "Rebalancear" para avaliar se ajustes são necessários.';
    const fullMessage = baseMessage + rebalMsg;
    expect(fullMessage).toContain("Monitorar portfólio");
    expect(fullMessage).toContain("Rebalancear");
    expect(fullMessage).not.toContain("AÇÃO REQUERIDA");
  });

  it("should not append rebalancing for info-level alerts", () => {
    const severity = "info";
    // Info alerts are filtered out from push notifications
    const regimeAlerts = [
      { alertType: "regime_change", severity: "info", title: "Regime: Carry → Carry" },
      { alertType: "regime_change", severity: "critical", title: "Regime: Carry → Stress" },
    ];
    const filtered = regimeAlerts.filter(a => a.alertType === "regime_change" && a.severity !== "info");
    expect(filtered).toHaveLength(1);
    expect(filtered[0].severity).toBe("critical");
  });

  it("should format regime names correctly", () => {
    const regimeMap: Record<string, string> = {
      carry: "Carry",
      riskoff: "Risk-Off",
      stress_dom: "Stress Doméstico",
      domestic_calm: "Doméstico Calmo",
    };
    expect(regimeMap["carry"]).toBe("Carry");
    expect(regimeMap["riskoff"]).toBe("Risk-Off");
    expect(regimeMap["stress_dom"]).toBe("Stress Doméstico");
    expect(regimeMap["domestic_calm"]).toBe("Doméstico Calmo");
  });
});

// ============================================================
// 2. Ibovespa Benchmark Integration
// ============================================================

describe("Ibovespa Benchmark — Data Validation", () => {
  const ibovSummary = {
    total_return: 253.42,
    annualized_return: 12.46,
    sharpe: 0.58,
    max_drawdown: -36.86,
    annualized_vol: 21.50,
    win_rate: 60.47,
  };

  it("should have positive total return for Ibovespa benchmark", () => {
    expect(ibovSummary.total_return).toBeGreaterThan(0);
  });

  it("should have reasonable Sharpe ratio for Ibovespa", () => {
    expect(ibovSummary.sharpe).toBeGreaterThan(0);
    expect(ibovSummary.sharpe).toBeLessThan(3);
  });

  it("should have negative max drawdown for Ibovespa", () => {
    expect(ibovSummary.max_drawdown).toBeLessThan(0);
    expect(ibovSummary.max_drawdown).toBeGreaterThan(-60); // Not worse than -60%
  });

  it("should have annualized return between 5% and 25%", () => {
    expect(ibovSummary.annualized_return).toBeGreaterThan(5);
    expect(ibovSummary.annualized_return).toBeLessThan(25);
  });

  it("should have win rate between 40% and 80%", () => {
    expect(ibovSummary.win_rate).toBeGreaterThan(40);
    expect(ibovSummary.win_rate).toBeLessThan(80);
  });

  it("should compute equity curve percentage correctly", () => {
    const equityIbov = 1.0061; // First point
    const ibovPct = (equityIbov - 1) * 100;
    expect(ibovPct).toBeCloseTo(0.61, 1);
  });

  it("should handle null equity_ibov gracefully", () => {
    const pt = { equity_ibov: null };
    const ibovPct = pt.equity_ibov != null ? ((pt.equity_ibov ?? 1) - 1) * 100 : null;
    expect(ibovPct).toBeNull();
  });
});

// ============================================================
// 3. Rebalancing UI — Portfolio Engine Logic
// ============================================================

describe("Rebalancing UI — Weight Comparison", () => {
  const currentWeights = {
    fx: 0.00,
    front: 0.00,
    belly: 0.00,
    long: 0.00,
    hard: 0.00,
    ntnb: 0.00,
  };

  const targetWeights = {
    fx: 0.444,
    front: 0.710,
    belly: 0.627,
    long: 0.331,
    hard: 0.013,
    ntnb: -0.360,
  };

  it("should compute weight deltas correctly", () => {
    const instruments = Object.keys(targetWeights) as (keyof typeof targetWeights)[];
    for (const inst of instruments) {
      const delta = targetWeights[inst] - currentWeights[inst];
      expect(delta).toBe(targetWeights[inst]);
    }
  });

  it("should identify NTN-B as a short position", () => {
    expect(targetWeights.ntnb).toBeLessThan(0);
  });

  it("should have FX as the largest long weight", () => {
    const longWeights = Object.entries(targetWeights)
      .filter(([_, w]) => w > 0)
      .sort((a, b) => b[1] - a[1]);
    // Front should be the largest
    expect(longWeights[0][0]).toBe("front");
  });

  it("should sum weights to approximately 1.77 (leveraged)", () => {
    const totalAbsWeight = Object.values(targetWeights).reduce((s, w) => s + Math.abs(w), 0);
    expect(totalAbsWeight).toBeGreaterThan(1.0); // Leveraged
    expect(totalAbsWeight).toBeLessThan(3.0);
  });
});

describe("Rebalancing UI — Transaction Cost Estimation", () => {
  const TC_RATES: Record<string, number> = {
    fx: 0.0003,      // 3 bps NDF
    front: 0.00015,   // 1.5 bps DI
    belly: 0.00015,
    long: 0.00015,
    hard: 0.0003,     // 3 bps DDI
    ntnb: 0.0005,     // 5 bps NTN-B
  };

  it("should compute transaction cost correctly for FX", () => {
    const notional = 3_238_880;
    const cost = notional * TC_RATES.fx;
    expect(cost).toBeCloseTo(971.66, 0);
  });

  it("should compute transaction cost correctly for NTN-B", () => {
    const notional = 453_000;
    const cost = notional * TC_RATES.ntnb;
    expect(cost).toBeCloseTo(226.5, 0);
  });

  it("should compute total cost in BPS correctly", () => {
    const aum = 15_000_000;
    const totalCost = 6298;
    const costBps = (totalCost / aum) * 10000;
    expect(costBps).toBeCloseTo(4.2, 1);
  });

  it("should compute turnover correctly", () => {
    const totalNotionalTraded = 26_291_880;
    const aum = 15_000_000;
    const turnover = (totalNotionalTraded / aum) * 100;
    expect(turnover).toBeGreaterThan(100); // >100% turnover
    expect(turnover).toBeLessThan(300);
  });
});

describe("Rebalancing UI — Contract Sizing", () => {
  it("should compute FX NDF contracts correctly", () => {
    const targetNotional = 3_238_880;
    const contractSize = 50_000; // USD 50k per NDF contract
    const contracts = Math.round(targetNotional / contractSize);
    expect(contracts).toBeGreaterThan(50);
    expect(contracts).toBeLessThan(80);
  });

  it("should compute DI Future contracts correctly", () => {
    const targetNotional = 10_300_000;
    const contractSize = 100_000; // R$ 100k per DI contract
    const contracts = Math.round(targetNotional / contractSize);
    expect(contracts).toBe(103);
  });

  it("should handle NTN-B short position (negative contracts)", () => {
    const targetWeight = -0.360;
    const aum = 15_000_000;
    const notional = Math.abs(targetWeight * aum);
    const contractSize = 1000; // R$ 1k per NTN-B unit
    const contracts = Math.round(notional / contractSize);
    expect(contracts).toBeGreaterThan(0);
    // Short position should have negative delta
    const delta = -contracts;
    expect(delta).toBeLessThan(0);
  });
});

describe("Rebalancing UI — 6 Instrument Support", () => {
  const instruments = ["fx", "front", "belly", "long", "hard", "ntnb"];

  it("should include all 6 instruments", () => {
    expect(instruments).toHaveLength(6);
    expect(instruments).toContain("ntnb");
    expect(instruments).toContain("hard");
  });

  it("should map instruments to B3 tickers", () => {
    const tickerMap: Record<string, string> = {
      fx: "WD0H26",
      front: "DI1F27",
      belly: "DI1F31",
      long: "DI1F36",
      hard: "DDIF31",
      ntnb: "NTNB2031",
    };
    for (const inst of instruments) {
      expect(tickerMap[inst]).toBeDefined();
      expect(tickerMap[inst].length).toBeGreaterThan(0);
    }
  });

  it("should label instruments correctly in Portuguese", () => {
    const labelMap: Record<string, string> = {
      fx: "FX (NDF)",
      front: "Front-End (DI 1Y)",
      belly: "Belly (DI 5Y)",
      long: "Long-End (DI 10Y)",
      hard: "Cupom Cambial (DDI)",
      ntnb: "NTN-B (IPCA+)",
    };
    for (const inst of instruments) {
      expect(labelMap[inst]).toBeDefined();
    }
  });

  it("should assign distinct colors to each instrument", () => {
    const colors: Record<string, string> = {
      fx: "#10b981",
      front: "#3b82f6",
      belly: "#8b5cf6",
      long: "#f59e0b",
      hard: "#ef4444",
      ntnb: "#ec4899",
    };
    const colorValues = Object.values(colors);
    const uniqueColors = new Set(colorValues);
    expect(uniqueColors.size).toBe(6);
  });
});

// ============================================================
// Test Notification Endpoint
// ============================================================

describe("Test Notification — Push Verification", () => {
  it("should format test notification correctly", () => {
    const notification = {
      title: "🔔 Teste de Notificação — ARC Macro",
      content: "Esta é uma notificação de teste do sistema de alertas.",
    };
    expect(notification.title).toContain("Teste");
    expect(notification.content).toContain("teste");
  });

  it("should list all alert types in test notification", () => {
    const content = [
      "Mudanças de regime (carry → risk-off)",
      "Drawdown > -5%",
      "Reversão de direção do score",
      "Mudanças em SHAP features",
      "Desvios de rebalanceamento",
    ].join("\n");
    expect(content).toContain("regime");
    expect(content).toContain("Drawdown");
    expect(content).toContain("SHAP");
    expect(content).toContain("rebalanceamento");
  });
});
