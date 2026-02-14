/**
 * Alert Engine — Automatic alert generation after each model run.
 * Compares current run with previous run to detect:
 * 1. Regime changes (carry → riskoff, etc.)
 * 2. SHAP feature importance shifts (>20% relative importance)
 * 3. Score changes (significant composite score moves)
 * 4. Drawdown warnings
 */

import { getDb } from "./db";
import { modelAlerts, InsertModelAlert, modelChangelog, InsertModelChangelog, modelRuns } from "../drizzle/schema";
import { desc, eq } from "drizzle-orm";

// ============================================================
// Types
// ============================================================

interface ModelRunData {
  id: number;
  dashboardJson: Record<string, unknown>;
  backtestJson: Record<string, unknown> | null;
  shapJson: Record<string, unknown> | null;
  shapHistoryJson: unknown[] | null;
  runDate: string;
}

interface AlertCandidate {
  alertType: InsertModelAlert["alertType"];
  severity: InsertModelAlert["severity"];
  title: string;
  message: string;
  previousValue?: string;
  currentValue?: string;
  threshold?: number;
  instrument?: string;
  feature?: string;
  detailsJson?: unknown;
}

// ============================================================
// Alert Generation
// ============================================================

/**
 * Main entry point: generate alerts and changelog after a model run.
 * Called from modelRunner.ts after successful execution.
 */
export async function generatePostRunAlerts(currentRunId: number): Promise<{
  alerts: number;
  changelog: boolean;
}> {
  const db = await getDb();
  if (!db) {
    console.warn("[AlertEngine] DB not available, skipping alert generation");
    return { alerts: 0, changelog: false };
  }

  try {
    // Get current and previous runs
    const runs = await db
      .select()
      .from(modelRuns)
      .where(eq(modelRuns.status, "completed"))
      .orderBy(desc(modelRuns.createdAt))
      .limit(2);

    if (runs.length === 0) {
      console.warn("[AlertEngine] No completed runs found");
      return { alerts: 0, changelog: false };
    }

    const current = runs[0] as unknown as ModelRunData;
    const previous = runs.length > 1 ? (runs[1] as unknown as ModelRunData) : null;

    // Generate alerts
    const candidates: AlertCandidate[] = [];

    candidates.push(...detectRegimeChange(current, previous));
    candidates.push(...detectShapShifts(current, previous));
    candidates.push(...detectScoreChange(current, previous));
    candidates.push(...detectDrawdownWarning(current));

    // Insert alerts
    for (const alert of candidates) {
      await db.insert(modelAlerts).values({
        modelRunId: currentRunId,
        ...alert,
      });
    }

    // Generate changelog entry
    const changelogCreated = await generateChangelogEntry(db, current, previous, currentRunId);

    console.log(`[AlertEngine] Generated ${candidates.length} alerts, changelog: ${changelogCreated}`);
    return { alerts: candidates.length, changelog: changelogCreated };
  } catch (error) {
    console.error("[AlertEngine] Error generating alerts:", error);
    return { alerts: 0, changelog: false };
  }
}

// ============================================================
// Regime Change Detection
// ============================================================

function detectRegimeChange(current: ModelRunData, previous: ModelRunData | null): AlertCandidate[] {
  if (!previous) return [];

  const alerts: AlertCandidate[] = [];
  const curDash = current.dashboardJson;
  const prevDash = previous.dashboardJson;

  const curRegime = curDash.current_regime as string | undefined;
  const prevRegime = prevDash.current_regime as string | undefined;

  if (curRegime && prevRegime && curRegime !== prevRegime) {
    const severity = curRegime.toLowerCase().includes("stress") ? "critical" as const
      : curRegime.toLowerCase().includes("riskoff") ? "warning" as const
      : "info" as const;

    alerts.push({
      alertType: "regime_change",
      severity,
      title: `Regime Change: ${formatRegime(prevRegime)} → ${formatRegime(curRegime)}`,
      message: buildRegimeMessage(curDash, prevDash, curRegime, prevRegime),
      previousValue: prevRegime,
      currentValue: curRegime,
      detailsJson: {
        prev_probs: prevDash.regime_probabilities,
        curr_probs: curDash.regime_probabilities,
      },
    });
  }

  // Also check for significant probability shifts even without regime change
  const curProbs = curDash.regime_probabilities as Record<string, number> | undefined;
  const prevProbs = prevDash.regime_probabilities as Record<string, number> | undefined;

  if (curProbs && prevProbs) {
    const stressKey = "P_StressDom";
    const curStress = curProbs[stressKey] || 0;
    const prevStress = prevProbs[stressKey] || 0;
    const stressDelta = curStress - prevStress;

    if (stressDelta > 0.15 && curRegime === prevRegime) {
      alerts.push({
        alertType: "regime_change",
        severity: "warning",
        title: `Stress Probability Surge: +${(stressDelta * 100).toFixed(1)}pp`,
        message: `Probabilidade de stress doméstico subiu de ${(prevStress * 100).toFixed(1)}% para ${(curStress * 100).toFixed(1)}% sem mudança de regime. Monitorar de perto.`,
        previousValue: `${(prevStress * 100).toFixed(1)}%`,
        currentValue: `${(curStress * 100).toFixed(1)}%`,
        threshold: 0.15,
      });
    }
  }

  return alerts;
}

function formatRegime(regime: string): string {
  const map: Record<string, string> = {
    carry: "Carry",
    riskoff: "Risk-Off",
    stress_dom: "Stress Doméstico",
    P_Carry: "Carry",
    P_RiskOff: "Risk-Off",
    P_StressDom: "Stress Doméstico",
  };
  return map[regime] || regime;
}

function buildRegimeMessage(
  curDash: Record<string, unknown>,
  prevDash: Record<string, unknown>,
  curRegime: string,
  prevRegime: string
): string {
  const curProbs = curDash.regime_probabilities as Record<string, number> | undefined;
  let probStr = "";
  if (curProbs) {
    probStr = ` Probabilidades atuais: Carry ${((curProbs.P_Carry || 0) * 100).toFixed(0)}%, Risk-Off ${((curProbs.P_RiskOff || 0) * 100).toFixed(0)}%, Stress ${((curProbs.P_StressDom || 0) * 100).toFixed(0)}%.`;
  }

  const implications: Record<string, string> = {
    carry: "Ambiente favorável para posições de carry. Custos de transação reduzidos (5bps).",
    riskoff: "Ambiente de aversão a risco. Custos de transação moderados (15bps). Considerar redução de exposição.",
    stress_dom: "Stress doméstico detectado. Custos de transação elevados (20bps). Máxima cautela com posições.",
  };

  return `Regime mudou de ${formatRegime(prevRegime)} para ${formatRegime(curRegime)}.${probStr} ${implications[curRegime] || ""}`;
}

// ============================================================
// SHAP Feature Importance Shift Detection
// ============================================================

function detectShapShifts(current: ModelRunData, previous: ModelRunData | null): AlertCandidate[] {
  if (!previous) return [];

  const alerts: AlertCandidate[] = [];
  const curShap = current.shapJson as Record<string, Record<string, { mean_abs: number; current: number; rank: number }>> | null;
  const prevShap = previous.shapJson as Record<string, Record<string, { mean_abs: number; current: number; rank: number }>> | null;

  if (!curShap || !prevShap) return alerts;

  const RELATIVE_THRESHOLD = 0.20; // 20% relative importance threshold
  const ABSOLUTE_THRESHOLD = 0.05; // minimum 5% absolute importance to trigger

  for (const [instrument, features] of Object.entries(curShap)) {
    const prevFeatures = prevShap[instrument];
    if (!prevFeatures) continue;

    // Calculate total importance for normalization
    const curTotal = Object.values(features).reduce((s, f) => s + (f.mean_abs || 0), 0);
    const prevTotal = Object.values(prevFeatures).reduce((s, f) => s + (f.mean_abs || 0), 0);

    if (curTotal === 0 || prevTotal === 0) continue;

    for (const [feature, curData] of Object.entries(features)) {
      const prevData = prevFeatures[feature];
      if (!prevData) continue;

      const curRelative = curData.mean_abs / curTotal;
      const prevRelative = prevData.mean_abs / prevTotal;
      const relativeShift = curRelative - prevRelative;

      // Alert if feature crosses 20% relative importance OR shifts by >15pp
      if (curRelative >= RELATIVE_THRESHOLD && prevRelative < RELATIVE_THRESHOLD) {
        alerts.push({
          alertType: "shap_shift",
          severity: "warning",
          title: `SHAP Alert: ${feature} crossed 20% threshold (${instrument.toUpperCase()})`,
          message: `Feature "${feature}" no instrumento ${instrument.toUpperCase()} ultrapassou 20% de importância relativa: ${(prevRelative * 100).toFixed(1)}% → ${(curRelative * 100).toFixed(1)}%. Isso pode indicar uma mudança estrutural nos drivers do modelo.`,
          previousValue: `${(prevRelative * 100).toFixed(1)}%`,
          currentValue: `${(curRelative * 100).toFixed(1)}%`,
          threshold: RELATIVE_THRESHOLD,
          instrument,
          feature,
          detailsJson: {
            prev_mean_abs: prevData.mean_abs,
            curr_mean_abs: curData.mean_abs,
            prev_rank: prevData.rank,
            curr_rank: curData.rank,
          },
        });
      } else if (Math.abs(relativeShift) > 0.15 && curRelative >= ABSOLUTE_THRESHOLD) {
        // Large shift (>15pp) in any feature above minimum threshold
        const direction = relativeShift > 0 ? "subiu" : "caiu";
        alerts.push({
          alertType: "shap_shift",
          severity: "info",
          title: `SHAP Shift: ${feature} ${direction} ${Math.abs(relativeShift * 100).toFixed(1)}pp (${instrument.toUpperCase()})`,
          message: `Feature "${feature}" no instrumento ${instrument.toUpperCase()} ${direction} ${Math.abs(relativeShift * 100).toFixed(1)}pp em importância relativa: ${(prevRelative * 100).toFixed(1)}% → ${(curRelative * 100).toFixed(1)}%.`,
          previousValue: `${(prevRelative * 100).toFixed(1)}%`,
          currentValue: `${(curRelative * 100).toFixed(1)}%`,
          threshold: 0.15,
          instrument,
          feature,
        });
      }

      // Check for rank changes (top feature changed)
      if (curData.rank === 1 && prevData.rank !== 1) {
        alerts.push({
          alertType: "shap_shift",
          severity: "info",
          title: `New Top Driver: ${feature} (${instrument.toUpperCase()})`,
          message: `"${feature}" se tornou o driver principal do instrumento ${instrument.toUpperCase()} (rank ${prevData.rank} → 1). Importância relativa: ${(curRelative * 100).toFixed(1)}%.`,
          previousValue: `rank ${prevData.rank}`,
          currentValue: "rank 1",
          instrument,
          feature,
        });
      }
    }
  }

  return alerts;
}

// ============================================================
// Score Change Detection
// ============================================================

function detectScoreChange(current: ModelRunData, previous: ModelRunData | null): AlertCandidate[] {
  if (!previous) return [];

  const alerts: AlertCandidate[] = [];
  const curScore = current.dashboardJson.score_total as number | undefined;
  const prevScore = previous.dashboardJson.score_total as number | undefined;

  if (curScore !== undefined && prevScore !== undefined) {
    const delta = curScore - prevScore;
    const absDelta = Math.abs(delta);

    // Alert on significant score changes (>1.0 absolute)
    if (absDelta > 1.0) {
      const direction = delta > 0 ? "subiu" : "caiu";
      const severity = absDelta > 2.0 ? "warning" as const : "info" as const;

      alerts.push({
        alertType: "score_change",
        severity,
        title: `Score ${direction}: ${prevScore.toFixed(2)} → ${curScore.toFixed(2)} (Δ${delta > 0 ? "+" : ""}${delta.toFixed(2)})`,
        message: `O score consolidado ${direction} de ${prevScore.toFixed(2)} para ${curScore.toFixed(2)} (variação de ${delta > 0 ? "+" : ""}${delta.toFixed(2)}). ${absDelta > 2.0 ? "Variação significativa — revisar posições." : "Variação moderada."}`,
        previousValue: prevScore.toFixed(2),
        currentValue: curScore.toFixed(2),
        threshold: 1.0,
      });
    }

    // Direction reversal alert
    const curDir = current.dashboardJson.direction as string | undefined;
    const prevDir = previous.dashboardJson.direction as string | undefined;
    if (curDir && prevDir && curDir !== prevDir) {
      alerts.push({
        alertType: "score_change",
        severity: "warning",
        title: `Direction Reversal: ${prevDir} → ${curDir}`,
        message: `A direção do modelo mudou de ${prevDir} para ${curDir}. Score: ${prevScore.toFixed(2)} → ${curScore.toFixed(2)}.`,
        previousValue: prevDir,
        currentValue: curDir,
      });
    }
  }

  return alerts;
}

// ============================================================
// Drawdown Warning
// ============================================================

function detectDrawdownWarning(current: ModelRunData): AlertCandidate[] {
  const alerts: AlertCandidate[] = [];

  const backtest = current.backtestJson as { summary?: Record<string, unknown> } | null;
  if (!backtest?.summary) return alerts;

  const overlay = backtest.summary.overlay as Record<string, number> | undefined;
  if (!overlay) return alerts;

  // max_drawdown is stored as percentage (e.g., -5.56 means -5.56%)
  const maxDD = overlay.max_drawdown;
  if (maxDD !== undefined && maxDD < -10) {
    alerts.push({
      alertType: "drawdown_warning",
      severity: maxDD < -15 ? "critical" : "warning",
      title: `Drawdown Alert: ${maxDD.toFixed(1)}%`,
      message: `O max drawdown do overlay atingiu ${maxDD.toFixed(1)}%. ${maxDD < -15 ? "Nível crítico — considerar redução de risco." : "Monitorar de perto."}`,
      currentValue: `${maxDD.toFixed(1)}%`,
      threshold: -10,
    });
  }

  return alerts;
}

// ============================================================
// Changelog Generation
// ============================================================

async function generateChangelogEntry(
  db: NonNullable<Awaited<ReturnType<typeof getDb>>>,
  current: ModelRunData,
  previous: ModelRunData | null,
  runId: number
): Promise<boolean> {
  try {
    const dash = current.dashboardJson;
    const backtest = current.backtestJson as { summary?: Record<string, unknown> } | null;
    const overlay = backtest?.summary?.overlay as Record<string, number> | undefined;
    const positions = dash.positions as Record<string, { weight: number }> | undefined;
    const regimeProbs = dash.regime_probabilities as Record<string, number> | undefined;

    // Build changes list
    const changes: Array<{ type: string; description: string }> = [];

    if (previous) {
      const prevDash = previous.dashboardJson;
      const prevRegime = prevDash.current_regime as string;
      const curRegime = dash.current_regime as string;
      if (curRegime !== prevRegime) {
        changes.push({ type: "regime", description: `Regime: ${formatRegime(prevRegime)} → ${formatRegime(curRegime)}` });
      }

      const prevScore = prevDash.score_total as number;
      const curScore = dash.score_total as number;
      if (prevScore !== undefined && curScore !== undefined) {
        const delta = curScore - prevScore;
        if (Math.abs(delta) > 0.5) {
          changes.push({ type: "score", description: `Score: ${prevScore.toFixed(2)} → ${curScore.toFixed(2)} (${delta > 0 ? "+" : ""}${delta.toFixed(2)})` });
        }
      }

      // Position changes
      const prevPositions = prevDash.positions as Record<string, { weight: number }> | undefined;
      if (positions && prevPositions) {
        for (const inst of ["fx", "front", "belly", "long", "hard"]) {
          const curW = positions[inst]?.weight || 0;
          const prevW = prevPositions[inst]?.weight || 0;
          const delta = curW - prevW;
          if (Math.abs(delta) > 0.05) {
            changes.push({
              type: "position",
              description: `${inst.toUpperCase()}: peso ${(prevW * 100).toFixed(0)}% → ${(curW * 100).toFixed(0)}%`,
            });
          }
        }
      }
    } else {
      changes.push({ type: "initial", description: "Primeira execução do modelo" });
    }

    if (changes.length === 0) {
      changes.push({ type: "update", description: "Atualização de dados sem mudanças significativas" });
    }

    // Extract version from dashboard or use date-based
    const version = (dash.version as string) || `v${current.runDate.replace(/-/g, ".")}`;

    const entry: InsertModelChangelog = {
      modelRunId: runId,
      version,
      runDate: current.runDate,
      score: dash.score_total as number || null,
      regime: dash.current_regime as string || null,
      regimeCarryProb: regimeProbs?.P_Carry || null,
      regimeRiskoffProb: regimeProbs?.P_RiskOff || null,
      regimeStressProb: regimeProbs?.P_StressDom || null,
      backtestSharpe: overlay?.sharpe || null,
      backtestReturn: overlay?.total_return || null,
      backtestMaxDD: overlay?.max_drawdown || null,
      backtestWinRate: overlay?.win_rate || null,
      backtestMonths: (backtest?.summary?.n_months as number) || null,
      weightFx: positions?.fx?.weight || null,
      weightFront: positions?.front?.weight || null,
      weightBelly: positions?.belly?.weight || null,
      weightLong: positions?.long?.weight || null,
      weightHard: positions?.hard?.weight || null,
      trainingWindow: 36,
      nStressScenarios: Object.keys((dash.stress_tests as Record<string, unknown>) || {}).length || null,
      changesJson: changes,
      metricsJson: {
        overlay,
        regime_probs: regimeProbs,
        score: dash.score_total,
        direction: dash.direction,
        spot: dash.current_spot,
      },
    };

    await db.insert(modelChangelog).values(entry);
    return true;
  } catch (error) {
    console.error("[AlertEngine] Error generating changelog:", error);
    return false;
  }
}

// ============================================================
// Query Helpers
// ============================================================

export async function getModelChangelog(limit = 50) {
  const db = await getDb();
  if (!db) return [];

  return db
    .select()
    .from(modelChangelog)
    .orderBy(desc(modelChangelog.createdAt))
    .limit(limit);
}

export async function getModelAlerts(limit = 100, includeRead = false) {
  const db = await getDb();
  if (!db) return [];

  if (includeRead) {
    return db
      .select()
      .from(modelAlerts)
      .where(eq(modelAlerts.isDismissed, false))
      .orderBy(desc(modelAlerts.createdAt))
      .limit(limit);
  }

  return db
    .select()
    .from(modelAlerts)
    .where(eq(modelAlerts.isDismissed, false))
    .orderBy(desc(modelAlerts.createdAt))
    .limit(limit);
}

export async function getUnreadAlertCount(): Promise<number> {
  const db = await getDb();
  if (!db) return 0;

  const result = await db
    .select()
    .from(modelAlerts)
    .where(eq(modelAlerts.isRead, false));

  return result.length;
}

export async function markModelAlertRead(alertId: number) {
  const db = await getDb();
  if (!db) return;

  await db.update(modelAlerts)
    .set({ isRead: true })
    .where(eq(modelAlerts.id, alertId));
}

export async function dismissModelAlert(alertId: number) {
  const db = await getDb();
  if (!db) return;

  await db.update(modelAlerts)
    .set({ isDismissed: true })
    .where(eq(modelAlerts.id, alertId));
}

export async function dismissAllModelAlerts() {
  const db = await getDb();
  if (!db) return;

  await db.update(modelAlerts)
    .set({ isDismissed: true })
    .where(eq(modelAlerts.isDismissed, false));
}
