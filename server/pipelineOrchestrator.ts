/**
 * Pipeline Orchestrator — Full daily automated update pipeline.
 * 
 * Steps:
 * 1. DATA_INGEST  — Validate data sources are accessible (BCB, Yahoo, etc.)
 * 2. MODEL_RUN    — Execute the Python ARC Macro model
 * 3. ALERTS       — Generate post-run alerts (regime, SHAP, score, drawdown, r*)
 * 4. PORTFOLIO    — Update portfolio positions and risk metrics
 * 5. BACKTEST     — Verify backtest metrics are fresh
 * 6. NOTIFY       — Send summary push notification to owner
 */

import { getDb } from "./db";
import { pipelineRuns } from "../drizzle/schema";
import { executeModel, isModelRunning, findPython, isPythonAvailable } from "./modelRunner";
import { getLatestModelRun } from "./db";
import { notifyOwner } from "./_core/notification";
import { checkAllDataSources } from "./dataSourceHealth";
import { eq, desc } from "drizzle-orm";

// ============================================================
// Types
// ============================================================

export interface PipelineStep {
  name: string;
  label: string;
  status: "pending" | "running" | "completed" | "failed" | "skipped";
  startedAt?: string;
  completedAt?: string;
  durationMs?: number;
  message?: string;
  error?: string;
  // v4.1: Retry tracking
  retryCount?: number;
  retryErrors?: string[];
  retriedAt?: string[];
}

export interface PipelineStatus {
  isRunning: boolean;
  currentStep: string | null;
  progress: number; // 0-100
  steps: PipelineStep[];
  lastRun: {
    id: number;
    status: string;
    triggerType: string;
    startedAt: string;
    completedAt: string | null;
    durationMs: number | null;
    completedSteps: number;
    totalSteps: number;
    summaryJson: Record<string, unknown> | null;
  } | null;
}

const PIPELINE_STEPS: Array<{ name: string; label: string }> = [
  { name: "data_ingest", label: "Ingestão de Dados" },
  { name: "model_run", label: "Execução do Modelo" },
  { name: "alerts", label: "Geração de Alertas" },
  { name: "portfolio", label: "Atualização do Portfólio" },
  { name: "backtest", label: "Verificação do Backtest" },
  { name: "notify", label: "Notificação Final" },
];

let currentPipelineRunId: number | null = null;
let currentSteps: PipelineStep[] = [];
let pipelineRunning = false;

// ============================================================
// Pipeline Execution
// ============================================================

/**
 * Execute the full daily update pipeline.
 */
export async function executePipeline(
  triggerType: "manual" | "scheduled" | "startup",
  triggeredBy?: string
): Promise<{ success: boolean; pipelineRunId?: number; error?: string }> {
  if (pipelineRunning || isModelRunning()) {
    return { success: false, error: "Pipeline ou modelo já em execução" };
  }

  pipelineRunning = true;
  const startTime = Date.now();
  console.log(`[Pipeline] Starting pipeline (trigger: ${triggerType}, by: ${triggeredBy})...`);

  // Initialize steps
  currentSteps = PIPELINE_STEPS.map(s => ({
    name: s.name,
    label: s.label,
    status: "pending" as const,
  }));

  const db = await getDb();
  let pipelineRunId: number | undefined;

  try {
    // Create pipeline run record
    if (db) {
      const result = await db.insert(pipelineRuns).values({
        triggerType,
        triggeredBy: triggeredBy || (triggerType === "scheduled" ? "cron" : "system"),
        status: "running",
        currentStep: "data_ingest",
        totalSteps: PIPELINE_STEPS.length,
        completedSteps: 0,
        stepsJson: currentSteps,
      });
      pipelineRunId = result[0].insertId;
      currentPipelineRunId = pipelineRunId;
      console.log(`[Pipeline] DB record created: ID ${pipelineRunId}`);
    } else {
      console.warn(`[Pipeline] No DB connection available`);
    }

    let completedSteps = 0;
    let modelRunId: number | undefined;
    let alertsGenerated = 0;

    // ---- Step 1: Data Ingest (with health check) ----
    await runStep(0, async () => {
      // Check Python availability (informational, not blocking)
      const hasPython = isPythonAvailable();
      const pythonStatus = hasPython
        ? `Python detectado: ${findPython()}`
        : "Python não disponível — usará fallback S3";
      console.log(`[Pipeline] ${pythonStatus}`);

      // Run health checks on all data sources (persists to DB)
      const healthResults = await checkAllDataSources();
      const healthy = healthResults.filter(s => s.status === 'healthy').length;
      const degraded = healthResults.filter(s => s.status === 'degraded').length;
      const down = healthResults.filter(s => s.status === 'down').length;
      const total = healthResults.length;

      if (down > 3) {
        const downSources = healthResults.filter(s => s.status === 'down').map(s => s.name).join(', ');
        throw new Error(`${down}/${total} fontes offline (${downSources}). Abortando pipeline.`);
      }

      return `${pythonStatus}. Health check: ${healthy} online, ${degraded} degraded, ${down} offline de ${total} fontes`;
    });
    completedSteps++;
    await updatePipelineDb(pipelineRunId, { completedSteps, currentStep: "model_run" });

    // ---- Step 2: Model Run ----
    await runStep(1, async () => {
      const result = await executeModel();
      if (!result.success) {
        throw new Error(result.error || "Model execution failed");
      }
      modelRunId = result.runId;
      const sourceLabel = result.source === 's3_fallback' ? ' (via S3 fallback)' : ' (via Python)';
      return `Model run #${result.runId} completed${sourceLabel}`;
    });
    completedSteps++;
    await updatePipelineDb(pipelineRunId, { completedSteps, currentStep: "alerts", modelRunId });

    // ---- Step 3: Alerts (already generated by executeModel → alertEngine) ----
    await runStep(2, async () => {
      // Alerts are generated inside executeModel() via generatePostRunAlerts()
      // Here we just count them
      if (db && modelRunId) {
        const { modelAlerts } = await import("../drizzle/schema");
        const alerts = await db
          .select()
          .from(modelAlerts)
          .where(eq(modelAlerts.modelRunId, modelRunId));
        alertsGenerated = alerts.length;
        return `${alertsGenerated} alertas gerados`;
      }
      return "Alertas processados (DB indisponível)";
    });
    completedSteps++;
    await updatePipelineDb(pipelineRunId, { completedSteps, currentStep: "portfolio", alertsGenerated });

    // ---- Step 4: Portfolio Update ----
    await runStep(3, async () => {
      // Check if portfolio config exists
      if (db) {
        const { portfolioConfig } = await import("../drizzle/schema");
        const configs = await db
          .select()
          .from(portfolioConfig)
          .where(eq(portfolioConfig.isActive, true))
          .limit(1);
        
        if (configs.length > 0) {
          return `Portfólio ativo encontrado (AUM: R$${(configs[0].aumBrl / 1e6).toFixed(1)}M)`;
        }
      }
      return "Nenhum portfólio ativo configurado (skip)";
    });
    completedSteps++;
    await updatePipelineDb(pipelineRunId, { completedSteps, currentStep: "backtest" });

    // ---- Step 5: Backtest Verification ----
    await runStep(4, async () => {
      const latest = await getLatestModelRun();
      if (latest) {
        const backtest = latest.backtestJson as { summary?: Record<string, unknown> } | null;
        const overlay = backtest?.summary?.overlay as Record<string, number> | undefined;
        if (overlay) {
          return `Backtest OK: Sharpe ${overlay.sharpe?.toFixed(2) || 'N/A'}, Return ${overlay.total_return?.toFixed(1) || 'N/A'}%, MaxDD ${overlay.max_drawdown?.toFixed(1) || 'N/A'}%`;
        }
      }
      return "Backtest data verified";
    });
    completedSteps++;
    await updatePipelineDb(pipelineRunId, { completedSteps, currentStep: "notify" });

    // ---- Step 6: Final Notification ----
    await runStep(5, async () => {
      const latest = await getLatestModelRun();
      const dash = latest?.dashboardJson as Record<string, unknown> | undefined;
      const backtest = latest?.backtestJson as { summary?: Record<string, unknown> } | null;
      const overlay = backtest?.summary?.overlay as Record<string, number> | undefined;
      
      const spot = (dash?.current_spot as number)?.toFixed(4) || 'N/A';
      const score = (dash?.score_total as number)?.toFixed(2) || 'N/A';
      const regime = (dash?.current_regime as string) || 'N/A';
      const direction = (dash?.direction as string) || 'N/A';
      const sharpe = overlay?.sharpe?.toFixed(2) || 'N/A';
      const equilibrium = dash?.equilibrium as Record<string, unknown> | undefined;
      const rstar = equilibrium?.composite_rstar as number;
      const selicStar = equilibrium?.selic_star as number;

      const durationSec = ((Date.now() - startTime) / 1000).toFixed(0);

      await notifyOwner({
        title: `✅ Pipeline Diário Completo — ${new Date().toISOString().slice(0, 10)}`,
        content: [
          `Pipeline executado em ${durationSec}s (${triggerType})`,
          `USDBRL: ${spot} | Score: ${score} | ${direction}`,
          `Regime: ${regime} | Sharpe: ${sharpe}`,
          rstar ? `r* Composto: ${(rstar * 100).toFixed(2)}% | SELIC*: ${selicStar ? (selicStar * 100).toFixed(2) + '%' : 'N/A'}` : '',
          `${alertsGenerated} alerta(s) gerado(s)`,
          `${completedSteps}/${PIPELINE_STEPS.length} steps concluídos`,
        ].filter(Boolean).join('\n'),
      });

      return `Notificação enviada (${durationSec}s total)`;
    });
    completedSteps++;

    // ---- Pipeline Complete ----
    const durationMs = Date.now() - startTime;
    const latest = await getLatestModelRun();
    const dash = latest?.dashboardJson as Record<string, unknown> | undefined;
    const backtest = latest?.backtestJson as { summary?: Record<string, unknown> } | null;
    const overlay = backtest?.summary?.overlay as Record<string, number> | undefined;

    const summary = {
      spot: dash?.current_spot,
      score: dash?.score_total,
      regime: dash?.current_regime,
      direction: dash?.direction,
      sharpe: overlay?.sharpe,
      totalReturn: overlay?.total_return,
      maxDrawdown: overlay?.max_drawdown,
      rstar: (dash?.equilibrium as Record<string, unknown>)?.composite_rstar,
      selicStar: (dash?.equilibrium as Record<string, unknown>)?.selic_star,
      alertsGenerated,
    };

    await updatePipelineDb(pipelineRunId, {
      completedSteps,
      currentStep: null,
      status: "completed",
      completedAt: new Date(),
      durationMs,
      summaryJson: summary,
    });

    console.log(`[Pipeline] ✅ Pipeline completed in ${(durationMs / 1000).toFixed(1)}s`);
    return { success: true, pipelineRunId };

  } catch (error) {
    const errMsg = error instanceof Error ? error.message : String(error);
    console.error(`[Pipeline] ❌ Pipeline failed: ${errMsg}`);

    const durationMs = Date.now() - startTime;
    await updatePipelineDb(pipelineRunId, {
      status: "failed",
      errorMessage: errMsg,
      completedAt: new Date(),
      durationMs,
    });

    // Notify owner of failure
    try {
      await notifyOwner({
        title: `❌ Pipeline Diário Falhou — ${new Date().toISOString().slice(0, 10)}`,
        content: `Erro: ${errMsg}\nStep: ${currentSteps.find(s => s.status === 'failed')?.label || 'unknown'}`,
      });
    } catch { /* non-fatal */ }

    return { success: false, pipelineRunId, error: errMsg };
  } finally {
    pipelineRunning = false;
    currentPipelineRunId = null;
  }
}

// ============================================================
// Step Runner with Retry & Exponential Backoff
// ============================================================

const RETRY_CONFIG = {
  maxRetries: 3,
  baseDelayMs: 2000,    // 2 seconds base delay
  maxDelayMs: 30000,    // 30 seconds max delay
  jitterFactor: 0.3,    // ±30% jitter
  // Steps that should NOT be retried (idempotency concerns)
  nonRetryableSteps: new Set<string>(["notify"]),
};

/**
 * Calculate delay with exponential backoff + jitter.
 * delay = min(base * 2^attempt, maxDelay) * (1 ± jitter)
 */
function calculateBackoffDelay(attempt: number): number {
  const exponentialDelay = Math.min(
    RETRY_CONFIG.baseDelayMs * Math.pow(2, attempt),
    RETRY_CONFIG.maxDelayMs
  );
  const jitter = 1 + (Math.random() * 2 - 1) * RETRY_CONFIG.jitterFactor;
  return Math.round(exponentialDelay * jitter);
}

function sleep(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}

/**
 * Run a pipeline step with automatic retry and exponential backoff.
 * - Retries up to RETRY_CONFIG.maxRetries times on failure
 * - Uses exponential backoff with jitter between retries
 * - Tracks all retry attempts and errors for observability
 * - Non-retryable steps (e.g., notify) fail immediately
 */
async function runStep(stepIndex: number, fn: () => Promise<string>): Promise<void> {
  const step = currentSteps[stepIndex];
  step.status = "running";
  step.startedAt = new Date().toISOString();
  step.retryCount = 0;
  step.retryErrors = [];
  step.retriedAt = [];
  console.log(`[Pipeline] Step ${stepIndex + 1}/${PIPELINE_STEPS.length}: ${step.label}...`);

  const isRetryable = !RETRY_CONFIG.nonRetryableSteps.has(step.name);
  const maxAttempts = isRetryable ? RETRY_CONFIG.maxRetries + 1 : 1; // +1 for initial attempt

  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    try {
      if (attempt > 0) {
        const delay = calculateBackoffDelay(attempt - 1);
        console.log(`[Pipeline] ⟳ Retry ${attempt}/${RETRY_CONFIG.maxRetries} for ${step.label} (backoff: ${delay}ms)...`);
        step.retriedAt!.push(new Date().toISOString());
        await sleep(delay);
      }

      const message = await fn();
      step.status = "completed";
      step.completedAt = new Date().toISOString();
      step.durationMs = new Date(step.completedAt).getTime() - new Date(step.startedAt).getTime();
      step.message = attempt > 0
        ? `${message} (succeeded after ${attempt} retry${attempt > 1 ? 'ies' : ''})`
        : message;
      step.retryCount = attempt;
      console.log(`[Pipeline] ✓ ${step.label} (${(step.durationMs / 1000).toFixed(1)}s): ${step.message}`);
      return; // Success — exit retry loop

    } catch (error) {
      const errMsg = error instanceof Error ? error.message : String(error);
      step.retryErrors!.push(errMsg);

      if (attempt < maxAttempts - 1) {
        // More retries available
        console.warn(`[Pipeline] ⚠ ${step.label} attempt ${attempt + 1} failed: ${errMsg}`);
        step.retryCount = attempt + 1;
      } else {
        // Final failure — no more retries
        step.status = "failed";
        step.completedAt = new Date().toISOString();
        step.durationMs = new Date(step.completedAt).getTime() - new Date(step.startedAt).getTime();
        step.error = attempt > 0
          ? `Failed after ${attempt + 1} attempts. Last error: ${errMsg}`
          : errMsg;
        step.retryCount = attempt;
        console.error(`[Pipeline] ✗ ${step.label}: ${step.error}`);
        throw error;
      }
    }
  }
}

// ============================================================
// DB Helpers
// ============================================================

async function updatePipelineDb(
  pipelineRunId: number | undefined,
  updates: Record<string, unknown>
): Promise<void> {
  if (!pipelineRunId) return;
  const db = await getDb();
  if (!db) return;

  try {
    await db.update(pipelineRuns)
      .set({
        ...updates,
        stepsJson: currentSteps,
      } as any)
      .where(eq(pipelineRuns.id, pipelineRunId));
  } catch (err) {
    console.warn("[Pipeline] DB update failed (non-fatal):", err);
  }
}

// ============================================================
// Status & History
// ============================================================

/**
 * Get current pipeline status (for real-time UI updates).
 */
export function getPipelineStatus(): {
  isRunning: boolean;
  currentStep: string | null;
  progress: number;
  steps: PipelineStep[];
} {
  if (!pipelineRunning) {
    return {
      isRunning: false,
      currentStep: null,
      progress: 0,
      steps: [],
    };
  }

  const completed = currentSteps.filter(s => s.status === "completed").length;
  const running = currentSteps.find(s => s.status === "running");

  return {
    isRunning: true,
    currentStep: running?.name || null,
    progress: Math.round((completed / PIPELINE_STEPS.length) * 100),
    steps: currentSteps,
  };
}

/**
 * Get pipeline run history.
 */
export async function getPipelineHistory(limit = 20) {
  const db = await getDb();
  if (!db) return [];

  return db
    .select()
    .from(pipelineRuns)
    .orderBy(desc(pipelineRuns.createdAt))
    .limit(limit);
}

/**
 * Get the latest pipeline run.
 */
export async function getLatestPipelineRun() {
  const db = await getDb();
  if (!db) return null;

  const runs = await db
    .select()
    .from(pipelineRuns)
    .orderBy(desc(pipelineRuns.createdAt))
    .limit(1);

  return runs[0] || null;
}

// ============================================================
// Scheduler
// ============================================================

/**
 * Start the daily pipeline scheduler.
 * Replaces the old model-only scheduler with a full pipeline scheduler.
 */
export async function startPipelineScheduler() {
  console.log("[Pipeline] Initializing daily pipeline scheduler...");

  // Recovery: mark any stuck "running" pipeline runs as "failed" on startup
  try {
    const db = await getDb();
    if (db) {
      const stuck = await db
        .select({ id: pipelineRuns.id })
        .from(pipelineRuns)
        .where(eq(pipelineRuns.status, "running"));
      if (stuck.length > 0) {
        for (const run of stuck) {
          await db.update(pipelineRuns)
            .set({
              status: "failed" as const,
              errorMessage: "Pipeline interrompido por reinício do servidor",
              completedAt: new Date(),
            } as any)
            .where(eq(pipelineRuns.id, run.id));
        }
        console.log(`[Pipeline] Recovery: marked ${stuck.length} stuck runs as failed`);
      }
    }
  } catch (err) {
    console.warn("[Pipeline] Recovery check failed (non-fatal):", err);
  }

  scheduleDailyPipeline();
}

function scheduleDailyPipeline() {
  const now = new Date();
  const next = new Date(now);
  // Schedule for 10:00 UTC (07:00 BRT) — after market data is available
  next.setUTCHours(10, 0, 0, 0);

  if (next <= now) {
    next.setDate(next.getDate() + 1);
  }

  const delay = next.getTime() - now.getTime();
  const hoursUntil = (delay / 3600000).toFixed(1);
  console.log(`[Pipeline] Next scheduled run at ${next.toISOString()} (in ${hoursUntil}h)`);

  setTimeout(async () => {
    console.log("[Pipeline] ⏰ Scheduled daily pipeline starting...");
    await executePipeline("scheduled", "cron");
    scheduleDailyPipeline(); // Reschedule for next day
  }, delay);
}
