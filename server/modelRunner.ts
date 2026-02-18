import { spawn, execSync } from "child_process";
import path from "path";
import fs from "fs";
import { fileURLToPath } from "url";
import { insertModelRun, getLatestModelRun } from "./db";
import { generatePostRunAlerts } from "./alertEngine";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const MODEL_SCRIPT = path.join(__dirname, "model", "run_model.py");

/**
 * S3 URL for the latest model output (uploaded from sandbox).
 * This serves as a fallback when Python is not available in the production environment.
 * Updated each time a successful model run completes in the sandbox.
 */
const MODEL_OUTPUT_S3_URL =
  "https://files.manuscdn.com/user_upload_by_module/session_file/310519663121236345/UqwnWrRwRfODJlxL.json";

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
  shap_importance?: Record<
    string,
    Record<string, { mean_abs: number; current: number; rank: number }>
  >;
  shap_history?: Array<{
    date: string;
    instrument: string;
    feature: string;
    importance: number;
  }>;
  rstar_ts?: Array<Record<string, unknown>>;
  legacy_fx?: { dashboard: Record<string, unknown> } | null;
  legacy_timeseries?: Array<Record<string, unknown>>;
  legacy_regime?: Array<Record<string, unknown>>;
  legacy_cyclical?: Array<Record<string, unknown>>;
}

let isRunning = false;

// ============================================================
// Python Detection — find the best available Python 3.x binary
// ============================================================

let _cachedPythonPath: string | null | undefined = undefined; // undefined = not checked yet

/**
 * Detect the best available Python 3 binary.
 * Returns null if Python is not available (does NOT throw).
 * Caches the result for subsequent calls.
 */
export function findPython(): string | null {
  if (_cachedPythonPath !== undefined) return _cachedPythonPath;

  const candidates = [
    "/usr/bin/python3.11",
    "/usr/bin/python3.12",
    "/usr/bin/python3.10",
    "/usr/bin/python3",
    "/usr/local/bin/python3.11",
    "/usr/local/bin/python3.12",
    "/usr/local/bin/python3.10",
    "/usr/local/bin/python3",
    "python3.11",
    "python3.12",
    "python3.10",
    "python3",
    "python",
  ];

  for (const candidate of candidates) {
    try {
      const version = execSync(`${candidate} --version 2>&1`, {
        timeout: 5000,
        encoding: "utf-8",
      }).trim();
      if (version.startsWith("Python 3.")) {
        console.log(
          `[ModelRunner] Python detected: ${candidate} → ${version}`
        );
        _cachedPythonPath = candidate;
        return candidate;
      }
    } catch {
      // Not available, try next
    }
  }

  console.warn(
    "[ModelRunner] Python 3.x not found. Will use S3 fallback for model output."
  );
  _cachedPythonPath = null;
  return null;
}

/**
 * Check if Python is available in this environment.
 */
export function isPythonAvailable(): boolean {
  return findPython() !== null;
}

/**
 * Execute the model: tries Python first, falls back to S3-hosted output.
 * Returns the model run ID on success.
 */
export async function executeModel(): Promise<{
  success: boolean;
  runId?: number;
  error?: string;
  source?: "python" | "s3_fallback";
}> {
  if (isRunning) {
    return { success: false, error: "Model is already running" };
  }

  isRunning = true;
  console.log("[ModelRunner] Starting ARC Macro execution...");

  try {
    let output: string;
    let source: "python" | "s3_fallback";

    const pythonBin = findPython();
    if (pythonBin) {
      // Python available — run the full model
      console.log("[ModelRunner] Python available, running full model...");
      output = await runPythonModel(pythonBin);
      source = "python";
    } else {
      // No Python — fetch from S3 fallback
      console.log(
        "[ModelRunner] Python not available, fetching model output from S3..."
      );
      output = await fetchModelOutputFromS3();
      source = "s3_fallback";
    }

    const parsed: ModelOutput = JSON.parse(output);

    // Embed nested data into dashboard for storage
    if (parsed.stress_tests) {
      parsed.dashboard.stress_tests = parsed.stress_tests;
    }
    if (parsed.fair_value_ts) {
      parsed.dashboard.fair_value_ts = parsed.fair_value_ts;
    }
    if (parsed.rstar_ts && parsed.rstar_ts.length > 0) {
      parsed.dashboard.rstar_ts = parsed.rstar_ts;
      console.log(
        `[ModelRunner] r* timeseries: ${parsed.rstar_ts.length} monthly points`
      );
    }

    // Mark the source in the dashboard
    parsed.dashboard._source = source;
    if (source === "s3_fallback") {
      parsed.dashboard._fallback_note =
        "Data loaded from S3 fallback (Python not available in production). Run the model locally and re-upload output_final.json to update.";
    }

    const runId = await insertModelRun({
      runDate:
        (parsed.dashboard.run_date as string) ||
        new Date().toISOString().slice(0, 10),
      currentSpot: (parsed.dashboard.current_spot as number) || 0,
      dashboardJson: parsed.dashboard,
      timeseriesJson: parsed.timeseries,
      regimeJson: parsed.regime,
      cyclicalJson: parsed.cyclical_factors_ts || [],
      stateVariablesJson: parsed.state_variables_ts || [],
      scoreJson: parsed.score_ts || [],
      backtestJson: parsed.backtest_ts || null,
      shapJson: parsed.shap_importance || null,
      shapHistoryJson: parsed.shap_history || null,
      legacyDashboardJson: parsed.legacy_fx?.dashboard || null,
      legacyTimeseriesJson: parsed.legacy_timeseries || null,
      legacyRegimeJson: parsed.legacy_regime || null,
      legacyCyclicalJson: parsed.legacy_cyclical || null,
      status: "completed",
    });

    console.log(
      `[ModelRunner] ARC Macro completed successfully (source: ${source}). Run ID: ${runId}`
    );

    // Generate alerts and changelog entry
    try {
      const alertResult = await generatePostRunAlerts(runId);
      console.log(
        `[ModelRunner] Alert engine: ${alertResult.alerts} alerts, changelog: ${alertResult.changelog}`
      );
    } catch (alertErr) {
      console.error(
        "[ModelRunner] Alert generation failed (non-fatal):",
        alertErr
      );
    }

    return { success: true, runId, source };
  } catch (error) {
    const errMsg = error instanceof Error ? error.message : String(error);
    console.error(`[ModelRunner] Model execution failed: ${errMsg}`);
    return { success: false, error: errMsg };
  } finally {
    isRunning = false;
  }
}

/**
 * Fetch model output JSON from S3 fallback URL.
 */
async function fetchModelOutputFromS3(): Promise<string> {
  console.log(`[ModelRunner] Fetching from: ${MODEL_OUTPUT_S3_URL}`);
  const response = await fetch(MODEL_OUTPUT_S3_URL, { signal: AbortSignal.timeout(60_000) });
  if (!response.ok) {
    throw new Error(
      `S3 fallback fetch failed: ${response.status} ${response.statusText}`
    );
  }
  const text = await response.text();
  if (!text || text.length < 100) {
    throw new Error("S3 fallback returned empty or invalid response");
  }
  console.log(
    `[ModelRunner] S3 fallback loaded: ${(text.length / 1024).toFixed(0)} KB`
  );
  return text;
}

/**
 * Run the Python model script and capture stdout as JSON.
 */
function runPythonModel(pythonBin: string): Promise<string> {
  return new Promise((resolve, reject) => {
    // Clean environment to prevent Python version conflicts
    const cleanEnv = { ...process.env };
    delete cleanEnv.PYTHONPATH;
    delete cleanEnv.PYTHONHOME;
    const extraPaths = [
      "/usr/bin",
      "/usr/local/bin",
      "/usr/sbin",
      "/usr/local/sbin",
    ];
    cleanEnv.PATH = [...extraPaths, cleanEnv.PATH || ""].join(":");

    // Ensure Python dependencies are installed (non-blocking, best-effort)
    try {
      const reqPath = path.join(__dirname, "model", "requirements.txt");
      if (fs.existsSync(reqPath)) {
        execSync(`${pythonBin} -m pip install -q -r ${reqPath}`, {
          timeout: 120_000,
          env: cleanEnv,
          stdio: "pipe",
        });
        console.log("[ModelRunner] Python dependencies verified");
      }
    } catch (pipErr) {
      console.warn(
        "[ModelRunner] pip install failed (non-fatal):",
        pipErr instanceof Error ? pipErr.message : pipErr
      );
    }

    const proc = spawn(pythonBin, [MODEL_SCRIPT], {
      cwd: path.join(__dirname, "model"),
      env: cleanEnv,
      timeout: 1_800_000, // 30 minute timeout
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
        reject(
          new Error(
            `Python process exited with code ${code}. Stderr: ${stderr.slice(-1000)}`
          )
        );
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
  console.log("[ModelRunner] Initializing ARC Macro scheduler...");

  const latest = await getLatestModelRun();
  const today = new Date().toISOString().slice(0, 10);

  if (!latest || latest.runDate !== today) {
    console.log("[ModelRunner] No run for today. Executing ARC Macro now...");
    executeModel().catch((err) => {
      console.error("[ModelRunner] Initial model run failed:", err);
    });
  } else {
    console.log(
      `[ModelRunner] Latest run found: ${latest.runDate} (spot=${latest.currentSpot})`
    );
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
  console.log(
    `[ModelRunner] Next scheduled run at ${next.toISOString()} (in ${Math.round(delay / 60000)} minutes)`
  );

  setTimeout(async () => {
    console.log("[ModelRunner] Scheduled daily run starting...");
    await executeModel();
    scheduleDailyRun();
  }, delay);
}
