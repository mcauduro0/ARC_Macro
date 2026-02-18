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
import { notifyOwner } from "./_core/notification";

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
    candidates.push(...detectFeatureStabilityChanges(current, previous));
    candidates.push(...detectRebalancingDeviation(current, previous));

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

    // Send push notifications for critical/warning alerts
    await sendPushNotifications(candidates, current);

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
    // Dashboard JSON uses lowercase keys: P_stress (not P_StressDom)
    const curStress = curProbs.P_stress ?? curProbs.P_StressDom ?? 0;
    const prevStress = prevProbs.P_stress ?? prevProbs.P_StressDom ?? 0;
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
    stress: "Stress",
    stress_dom: "Stress Doméstico",
    domestic_stress: "Stress Doméstico",
    domestic_calm: "Doméstico Calmo",
    P_Carry: "Carry",
    P_carry: "Carry",
    P_RiskOff: "Risk-Off",
    P_riskoff: "Risk-Off",
    P_StressDom: "Stress Doméstico",
    P_stress: "Stress",
    P_domestic_stress: "Stress Doméstico",
    P_domestic_calm: "Doméstico Calmo",
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
    // Dashboard JSON uses lowercase keys: P_carry, P_riskoff, P_stress
    // (different from regime timeseries which uses P_Carry, P_RiskOff, P_StressDom)
    const pCarry = curProbs.P_carry ?? curProbs.P_Carry ?? 0;
    const pRiskoff = curProbs.P_riskoff ?? curProbs.P_RiskOff ?? 0;
    const pStress = curProbs.P_stress ?? curProbs.P_StressDom ?? 0;
    probStr = ` Probabilidades atuais: Carry ${(pCarry * 100).toFixed(1)}%, Risk-Off ${(pRiskoff * 100).toFixed(1)}%, Stress ${(pStress * 100).toFixed(1)}%.`;
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
// Feature Stability Change Detection (v4.5)
// ============================================================

function detectFeatureStabilityChanges(
  current: ModelRunData,
  previous: ModelRunData | null
): AlertCandidate[] {
  if (!previous) return [];

  const alerts: AlertCandidate[] = [];

  // Extract feature_selection data from dashboardJson
  const curDash = current.dashboardJson;
  const prevDash = previous.dashboardJson;

  const curFS = curDash.feature_selection as Record<string, unknown> | undefined;
  const prevFS = prevDash.feature_selection as Record<string, unknown> | undefined;

  if (!curFS || !prevFS) return alerts;

  const curInstruments = (curFS.per_instrument || curFS) as Record<string, Record<string, unknown>>;
  const prevInstruments = (prevFS.per_instrument || prevFS) as Record<string, Record<string, unknown>>;

  for (const [inst, curData] of Object.entries(curInstruments)) {
    if (!curData || typeof curData !== 'object') continue;
    const prevData = prevInstruments[inst];
    if (!prevData || typeof prevData !== 'object') continue;

    const curStability = curData.stability as Record<string, unknown> | undefined;
    const prevStability = prevData.stability as Record<string, unknown> | undefined;
    if (!curStability || !prevStability) continue;

    const curClassification = curStability.classification as Record<string, string> | undefined;
    const prevClassification = prevStability.classification as Record<string, string> | undefined;
    if (!curClassification || !prevClassification) continue;

    for (const [feature, curClass] of Object.entries(curClassification)) {
      const prevClass = prevClassification[feature];
      if (!prevClass || prevClass === curClass) continue;

      // Robust → Unstable = critical
      if (prevClass === 'robust' && curClass === 'unstable') {
        alerts.push({
          alertType: 'feature_stability',
          severity: 'critical',
          title: `Feature Instability: ${feature} (${inst.toUpperCase()})`,
          message: `Feature "${feature}" no instrumento ${inst.toUpperCase()} caiu de Robust para Unstable entre runs consecutivos. Isso pode indicar uma mudança de regime ou quebra estrutural no driver.`,
          previousValue: prevClass,
          currentValue: curClass,
          instrument: inst,
          feature,
          detailsJson: {
            transition: `${prevClass} → ${curClass}`,
            prev_composite: (prevStability.composite_scores as Record<string, number>)?.[feature],
            curr_composite: (curStability.composite_scores as Record<string, number>)?.[feature],
          },
        });
      }
      // Robust → Moderate = warning
      else if (prevClass === 'robust' && curClass === 'moderate') {
        alerts.push({
          alertType: 'feature_stability',
          severity: 'warning',
          title: `Feature Weakening: ${feature} (${inst.toUpperCase()})`,
          message: `Feature "${feature}" no instrumento ${inst.toUpperCase()} enfraqueceu de Robust para Moderate. Monitorar de perto — pode indicar perda de poder preditivo.`,
          previousValue: prevClass,
          currentValue: curClass,
          instrument: inst,
          feature,
        });
      }
      // Unstable → Robust = positive signal
      else if (prevClass === 'unstable' && curClass === 'robust') {
        alerts.push({
          alertType: 'feature_stability',
          severity: 'info',
          title: `Feature Strengthening: ${feature} (${inst.toUpperCase()})`,
          message: `Feature "${feature}" no instrumento ${inst.toUpperCase()} fortaleceu de Unstable para Robust. Novo sinal emergente — considerar aumento de peso no ensemble.`,
          previousValue: prevClass,
          currentValue: curClass,
          instrument: inst,
          feature,
        });
      }
    }
  }

  return alerts;
}

// ============================================================
// Rebalancing Deviation Detection
// ============================================================

/**
 * Detect when current portfolio weights deviate significantly from model targets.
 * Triggers when any instrument's weight differs from target by more than the threshold.
 * Also detects when total portfolio risk exceeds configured limits.
 */
function detectRebalancingDeviation(
  current: ModelRunData,
  previous: ModelRunData | null
): AlertCandidate[] {
  const alerts: AlertCandidate[] = [];
  const dash = current.dashboardJson;
  const positions = dash.positions as Record<string, { weight: number }> | undefined;
  const mu = dash.mu as Record<string, number> | undefined;

  if (!positions || !mu) return alerts;

  // Check weight deviation from model target
  const WEIGHT_DEVIATION_THRESHOLD = 0.10; // 10% absolute deviation
  const instruments = ['fx', 'front', 'belly', 'long', 'hard', 'ntnb'];

  let totalAbsWeight = 0;
  let totalDeviation = 0;
  const deviations: Array<{ inst: string; current: number; target: number; delta: number }> = [];

  for (const inst of instruments) {
    const currentWeight = positions[inst]?.weight || 0;
    totalAbsWeight += Math.abs(currentWeight);

    // If we have previous run, compare weight changes
    if (previous) {
      const prevPositions = previous.dashboardJson.positions as Record<string, { weight: number }> | undefined;
      const prevWeight = prevPositions?.[inst]?.weight || 0;
      const delta = Math.abs(currentWeight - prevWeight);
      totalDeviation += delta;

      if (delta > WEIGHT_DEVIATION_THRESHOLD) {
        deviations.push({
          inst,
          current: currentWeight,
          target: prevWeight,
          delta,
        });
      }
    }
  }

  // Alert if significant rebalancing is needed
  if (deviations.length > 0) {
    const severity = deviations.some(d => d.delta > 0.20) ? 'warning' as const : 'info' as const;
    const details = deviations.map(d =>
      `${d.inst.toUpperCase()}: ${(d.target * 100).toFixed(1)}% → ${(d.current * 100).toFixed(1)}% (Δ${(d.delta * 100).toFixed(1)}pp)`
    ).join(', ');

    alerts.push({
      alertType: 'rebalancing_deviation',
      severity,
      title: `Rebalancing Needed: ${deviations.length} instrument(s) deviated >${(WEIGHT_DEVIATION_THRESHOLD * 100).toFixed(0)}pp`,
      message: `${deviations.length} instrumento(s) com desvio significativo do target anterior: ${details}. Turnover total: ${(totalDeviation * 100).toFixed(1)}pp.`,
      currentValue: `${deviations.length} instruments`,
      threshold: WEIGHT_DEVIATION_THRESHOLD,
      detailsJson: {
        deviations,
        total_turnover: totalDeviation,
        total_abs_weight: totalAbsWeight,
      },
    });
  }

  // Alert if total portfolio leverage is excessive
  const MAX_LEVERAGE = 2.0; // 200% gross exposure
  if (totalAbsWeight > MAX_LEVERAGE) {
    alerts.push({
      alertType: 'rebalancing_deviation',
      severity: 'critical',
      title: `Leverage Alert: ${(totalAbsWeight * 100).toFixed(0)}% gross exposure`,
      message: `A exposição bruta do portfólio atingiu ${(totalAbsWeight * 100).toFixed(0)}%, acima do limite de ${(MAX_LEVERAGE * 100).toFixed(0)}%. Considerar redução de posições.`,
      currentValue: `${(totalAbsWeight * 100).toFixed(0)}%`,
      threshold: MAX_LEVERAGE,
    });
  }

  // Alert if model mu signals are conflicting with current positions
  for (const inst of instruments) {
    const weight = positions[inst]?.weight || 0;
    const muVal = mu[inst] || 0;

    // Position is opposite to model signal
    if (Math.abs(weight) > 0.05 && Math.abs(muVal) > 0.005) {
      if ((weight > 0 && muVal < -0.01) || (weight < 0 && muVal > 0.01)) {
        alerts.push({
          alertType: 'rebalancing_deviation',
          severity: 'warning',
          title: `Signal Conflict: ${inst.toUpperCase()} position vs model`,
          message: `Posição em ${inst.toUpperCase()} (${(weight * 100).toFixed(1)}%) está na direção oposta ao sinal do modelo (μ=${(muVal * 100).toFixed(2)}%). Considerar rebalanceamento.`,
          previousValue: `weight=${(weight * 100).toFixed(1)}%`,
          currentValue: `mu=${(muVal * 100).toFixed(2)}%`,
          instrument: inst,
        });
      }
    }
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
        for (const inst of ["fx", "front", "belly", "long", "hard", "ntnb"]) {
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
      // Dashboard JSON uses lowercase keys: P_carry, P_riskoff, P_stress
      regimeCarryProb: regimeProbs?.P_carry ?? regimeProbs?.P_Carry ?? null,
      regimeRiskoffProb: regimeProbs?.P_riskoff ?? regimeProbs?.P_RiskOff ?? null,
      regimeStressProb: regimeProbs?.P_stress ?? regimeProbs?.P_StressDom ?? null,
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
      weightNtnb: positions?.ntnb?.weight || null,
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
// Push Notifications
// ============================================================

/**
 * Send push notifications to the project owner for critical/warning alerts.
 * Triggers on: regime changes, drawdown > -5%, score reversals, SHAP shifts.
 * Also sends a summary notification after each model run.
 */
async function sendPushNotifications(
  candidates: AlertCandidate[],
  current: ModelRunData
): Promise<void> {
  try {
    // 1. Regime change notification (with rebalancing recommendation)
    const regimeAlerts = candidates.filter(a => a.alertType === 'regime_change' && a.severity !== 'info');
    for (const alert of regimeAlerts) {
      const rebalMsg = alert.severity === 'critical'
        ? '\n\n🔄 AÇÃO REQUERIDA: Rebalanceamento do portfólio recomendado. Acesse a aba "Rebalancear" no Portfolio Management para revisar as ordens de execução e custos de transação estimados.'
        : '\n\n📋 Monitorar portfólio. Verifique a aba "Rebalancear" para avaliar se ajustes são necessários.';
      await notifyOwner({
        title: `⚠️ ${alert.title}`,
        content: alert.message + rebalMsg,
      });
      console.log(`[AlertEngine] Push notification sent: ${alert.title}`);
    }

    // 2. Drawdown warning notification (threshold: -5%)
    const backtest = current.backtestJson as { summary?: Record<string, unknown> } | null;
    const overlay = backtest?.summary?.overlay as Record<string, number> | undefined;
    const maxDD = overlay?.max_drawdown;
    if (maxDD !== undefined && maxDD < -5) {
      const ddAlert = candidates.find(a => a.alertType === 'drawdown_warning');
      if (ddAlert) {
        await notifyOwner({
          title: `📉 Drawdown Alert: ${maxDD.toFixed(1)}%`,
          content: ddAlert.message,
        });
        console.log(`[AlertEngine] Push notification sent: Drawdown ${maxDD.toFixed(1)}%`);
      } else {
        // Even if no formal alert was generated (threshold was -10%), notify at -5%
        await notifyOwner({
          title: `📉 Drawdown Warning: ${maxDD.toFixed(1)}%`,
          content: `O max drawdown do overlay atingiu ${maxDD.toFixed(1)}%. Monitorar de perto.`,
        });
        console.log(`[AlertEngine] Push notification sent: Drawdown warning ${maxDD.toFixed(1)}%`);
      }
    }

    // 3. Score direction reversal notification
    const reversalAlerts = candidates.filter(
      a => a.alertType === 'score_change' && a.title.includes('Direction Reversal')
    );
    for (const alert of reversalAlerts) {
      await notifyOwner({
        title: `🔄 ${alert.title}`,
        content: alert.message,
      });
      console.log(`[AlertEngine] Push notification sent: ${alert.title}`);
    }

    // 4. SHAP feature importance surge notification
    const shapAlerts = candidates.filter(
      a => a.alertType === 'shap_shift' && a.severity === 'warning'
    );
    for (const alert of shapAlerts) {
      await notifyOwner({
        title: `📊 ${alert.title}`,
        content: alert.message,
      });
      console.log(`[AlertEngine] Push notification sent: ${alert.title}`);
    }

    // 5. Feature stability change notifications (v4.5)
    const stabilityAlerts = candidates.filter(
      a => a.alertType === 'feature_stability' && (a.severity === 'critical' || a.severity === 'warning')
    );
    if (stabilityAlerts.length > 0) {
      // Group by severity for a consolidated notification
      const critical = stabilityAlerts.filter(a => a.severity === 'critical');
      const warnings = stabilityAlerts.filter(a => a.severity === 'warning');

      if (critical.length > 0) {
        const details = critical.map(a =>
          `• ${a.feature} (${a.instrument?.toUpperCase()}): ${a.previousValue} → ${a.currentValue}`
        ).join('\n');
        await notifyOwner({
          title: `🚨 Feature Instability Alert: ${critical.length} feature(s) Robust→Unstable`,
          content: `${critical.length} feature(s) caíram de Robust para Unstable — possível mudança de regime:\n${details}`,
        });
        console.log(`[AlertEngine] Push: ${critical.length} critical stability alerts`);
      }

      if (warnings.length > 0) {
        const details = warnings.map(a =>
          `• ${a.feature} (${a.instrument?.toUpperCase()}): ${a.previousValue} → ${a.currentValue}`
        ).join('\n');
        await notifyOwner({
          title: `⚠️ Feature Weakening: ${warnings.length} feature(s) Robust→Moderate`,
          content: `${warnings.length} feature(s) enfraqueceram de Robust para Moderate:\n${details}`,
        });
        console.log(`[AlertEngine] Push: ${warnings.length} stability warning alerts`);
      }
    }

    // 6. Rebalancing deviation notifications
    const rebalAlerts = candidates.filter(
      a => a.alertType === 'rebalancing_deviation' && (a.severity === 'critical' || a.severity === 'warning')
    );
    for (const alert of rebalAlerts) {
      const icon = alert.severity === 'critical' ? '🚨' : '⚠️';
      await notifyOwner({
        title: `${icon} ${alert.title}`,
        content: alert.message,
      });
      console.log(`[AlertEngine] Push notification sent: ${alert.title}`);
    }

    // 7. Model run completion summary (always send)
    const dash = current.dashboardJson;
    const spot = (dash.current_spot as number)?.toFixed(4) || 'N/A';
    const score = (dash.score_total as number)?.toFixed(2) || 'N/A';
    const regime = formatRegime((dash.current_regime as string) || 'unknown');
    const direction = (dash.direction as string) || 'N/A';
    const sharpe = overlay?.sharpe?.toFixed(2) || 'N/A';
    const nAlerts = candidates.length;

    await notifyOwner({
      title: `ARC Macro — Model Update: ${current.runDate}`,
      content: [
        `Spot: ${spot} | Score: ${score} | Direction: ${direction}`,
        `Regime: ${regime} | Sharpe: ${sharpe}`,
        maxDD !== undefined ? `Max DD: ${maxDD.toFixed(1)}%` : '',
        nAlerts > 0 ? `${nAlerts} alerta(s) gerado(s)` : 'Sem alertas',
      ].filter(Boolean).join('\n'),
    });
    console.log(`[AlertEngine] Model run summary notification sent`);

  } catch (error) {
    // Non-fatal: log but don't fail the alert pipeline
    console.warn('[AlertEngine] Push notification error (non-fatal):', error);
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
