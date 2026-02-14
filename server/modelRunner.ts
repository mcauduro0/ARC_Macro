import { spawn } from "child_process";
import path from "path";
import { fileURLToPath } from "url";
import { insertModelRun, getLatestModelRun } from "./db";
import { generatePostRunAlerts } from "./alertEngine";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const MODEL_SCRIPT = path.join(__dirname, "model", "run_model.py");

interface ModelOutput {
  dashboard: Record<string, unknown>;
  timeseries: Array<Record<string, unknown>>;
  regime: Array<Record<string, unknown>>;
  state_variables_ts?: Array<Record<string, unknown>>;
  cyclical_factors_ts?: Array<Record<string, unknown>>;
  score_ts?: Array<Record<string, unknown>>;
  backtest_ts?: {
    timeseries: Array<Record<string, unknown>>;
    summary: Record<string, unknown>;
  };
  stress_tests?: Record<string, Record<string, unknown>>;
  fair_value_ts?: Array<Record<string, unknown>>;
  shap_importance?: Record<string, Record<string, { mean_abs: number; current: number; rank: number }>>;
  shap_history?: Array<{ date: string; instrument: string; feature: string; importance: number }>;
  // Legacy fields (from old FX-only model, via run_model.py)
  legacy_fx?: { dashboard: Record<string, unknown> } | null;
  legacy_timeseries?: Array<Record<string, unknown>>;
  legacy_regime?: Array<Record<string, unknown>>;
  legacy_cyclical?: Array<Record<string, unknown>>;
}

let isRunning = false;

/**
 * Execute the Python model and store results in the database.
 * Returns the model run ID on success.
 */
export async function executeModel(): Promise<{ success: boolean; runId?: number; error?: string }> {
  if (isRunning) {
    return { success: false, error: "Model is already running" };
  }

  isRunning = true;
  console.log("[ModelRunner] Starting Macro Risk OS execution...");

  try {
    const output = await runPythonModel();
    const parsed: ModelOutput = JSON.parse(output);

    // v2.3: Embed stress_tests into dashboard for storage
    if (parsed.stress_tests) {
      parsed.dashboard.stress_tests = parsed.stress_tests;
    }
    // v2.3: Embed fair_value_ts into dashboard for storage
    if (parsed.fair_value_ts) {
      parsed.dashboard.fair_value_ts = parsed.fair_value_ts;
    }

    const runId = await insertModelRun({
      runDate: parsed.dashboard.run_date as string || new Date().toISOString().slice(0, 10),
      currentSpot: parsed.dashboard.current_spot as number || 0,
      dashboardJson: parsed.dashboard,
      timeseriesJson: parsed.timeseries,
      regimeJson: parsed.regime,
      cyclicalJson: parsed.cyclical_factors_ts || [],  // Raw macro factors (DXY, VIX, EMBI, etc.)
      stateVariablesJson: parsed.state_variables_ts || [],
      scoreJson: parsed.score_ts || [],
      backtestJson: parsed.backtest_ts || null,
      shapJson: parsed.shap_importance || null,  // v3.8: SHAP feature importance
      shapHistoryJson: parsed.shap_history || null,  // v3.9: SHAP temporal evolution
      legacyDashboardJson: parsed.legacy_fx?.dashboard || null,
      legacyTimeseriesJson: parsed.legacy_timeseries || null,
      legacyRegimeJson: parsed.legacy_regime || null,
      legacyCyclicalJson: parsed.legacy_cyclical || null,
      status: "completed",
    });

    console.log(`[ModelRunner] Macro Risk OS completed successfully. Run ID: ${runId}`);

    // Generate alerts and changelog entry
    try {
      const alertResult = await generatePostRunAlerts(runId);
      console.log(`[ModelRunner] Alert engine: ${alertResult.alerts} alerts, changelog: ${alertResult.changelog}`);
    } catch (alertErr) {
      console.error("[ModelRunner] Alert generation failed (non-fatal):", alertErr);
    }

    return { success: true, runId };
  } catch (error) {
    const errMsg = error instanceof Error ? error.message : String(error);
    console.error(`[ModelRunner] Model execution failed: ${errMsg}`);
    return { success: false, error: errMsg };
  } finally {
    isRunning = false;
  }
}

/**
 * Run the Python model script and capture stdout as JSON.
 */
function runPythonModel(): Promise<string> {
  return new Promise((resolve, reject) => {
    // Clean environment to prevent Python version conflicts
    const cleanEnv = { ...process.env };
    delete cleanEnv.PYTHONPATH;
    cleanEnv.PYTHONHOME = '/usr';
    cleanEnv.PATH = `/usr/bin:/usr/local/bin:${cleanEnv.PATH || ''}`;

    const proc = spawn("/usr/bin/python3.11", [MODEL_SCRIPT], {
      cwd: path.join(__dirname, "model"),
      env: cleanEnv,
      timeout: 600_000, // 10 minute timeout (Macro Risk OS is more complex)
    });

    let stdout = "";
    let stderr = "";

    proc.stdout.on("data", (data: Buffer) => {
      stdout += data.toString();
    });

    proc.stderr.on("data", (data: Buffer) => {
      stderr += data.toString();
      const lines = data.toString().trim().split("\n");
      for (const line of lines) {
        if (line.trim()) {
          console.log(`[Python] ${line.trim()}`);
        }
      }
    });

    proc.on("close", (code: number | null) => {
      if (code === 0 && stdout.trim()) {
        resolve(stdout.trim());
      } else {
        reject(new Error(`Python process exited with code ${code}. Stderr: ${stderr.slice(-1000)}`));
      }
    });

    proc.on("error", (err: Error) => {
      reject(new Error(`Failed to spawn Python process: ${err.message}`));
    });
  });
}

/**
 * Check if the model is currently running.
 */
export function isModelRunning(): boolean {
  return isRunning;
}

/**
 * Start the daily scheduler. Runs the model once at startup if no recent run exists,
 * then schedules daily execution.
 */
export async function startModelScheduler() {
  console.log("[ModelRunner] Initializing Macro Risk OS scheduler...");

  const latest = await getLatestModelRun();
  const today = new Date().toISOString().slice(0, 10);

  if (!latest || latest.runDate !== today) {
    console.log("[ModelRunner] No run for today. Executing Macro Risk OS now...");
    executeModel().catch(err => {
      console.error("[ModelRunner] Initial model run failed:", err);
    });
  } else {
    console.log(`[ModelRunner] Latest run found: ${latest.runDate} (spot=${latest.currentSpot})`);
  }

  scheduleDailyRun();
}

function scheduleDailyRun() {
  const now = new Date();
  const next = new Date(now);
  next.setUTCHours(7, 0, 0, 0); // 07:00 UTC

  if (next <= now) {
    next.setDate(next.getDate() + 1);
  }

  const delay = next.getTime() - now.getTime();
  console.log(`[ModelRunner] Next scheduled run at ${next.toISOString()} (in ${Math.round(delay / 60000)} minutes)`);

  setTimeout(async () => {
    console.log("[ModelRunner] Scheduled daily run starting...");
    await executeModel();
    scheduleDailyRun();
  }, delay);
}
