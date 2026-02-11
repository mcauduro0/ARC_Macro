/**
 * Standalone script to trigger the Macro Risk OS model and store results in DB.
 * Usage: node scripts/trigger-model.mjs
 */
import { spawn } from "child_process";
import path from "path";
import fs from "fs";
import { fileURLToPath } from "url";
import mysql from "mysql2/promise";
import dotenv from "dotenv";

dotenv.config();

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const MODEL_SCRIPT = path.join(__dirname, "..", "server", "model", "run_model.py");
const OUTPUT_FILE = path.join(__dirname, "..", "server", "model", "output", "macro_risk_os_output.json");

async function main() {
  console.log("[Trigger] Running Macro Risk OS...");

  // Run model and capture stdout
  const stdout = await new Promise((resolve, reject) => {
    const cleanEnv = { ...process.env };
    delete cleanEnv.PYTHONPATH;
    cleanEnv.PYTHONHOME = "/usr";
    cleanEnv.PATH = `/usr/bin:/usr/local/bin:${cleanEnv.PATH || ""}`;

    const proc = spawn("/usr/bin/python3.11", [MODEL_SCRIPT], {
      cwd: path.join(__dirname, "..", "server", "model"),
      env: cleanEnv,
      timeout: 600_000,
      maxBuffer: 100 * 1024 * 1024, // 100MB
    });

    const chunks = [];
    proc.stdout.on("data", (data) => { chunks.push(data); });
    proc.stderr.on("data", (data) => {
      const lines = data.toString().trim().split("\n");
      for (const line of lines) {
        if (line.trim() && (line.includes("[RUNNER]") || line.includes("ERROR") || line.includes("MACRO RISK"))) {
          console.log(`[Python] ${line.trim()}`);
        }
      }
    });

    proc.on("close", (code) => {
      const output = Buffer.concat(chunks).toString("utf-8").trim();
      if (code === 0 && output.length > 0) {
        resolve(output);
      } else {
        reject(new Error(`Exit code ${code}, stdout length: ${output.length}`));
      }
    });
    proc.on("error", (err) => reject(err));
  });

  // Save to file for debugging
  fs.writeFileSync(OUTPUT_FILE, stdout);
  console.log(`[Trigger] Output saved (${(stdout.length / 1024).toFixed(0)} KB)`);

  // Parse JSON
  const parsed = JSON.parse(stdout);
  console.log(`[Trigger] Spot: ${parsed.dashboard?.current_spot}, Regime: ${parsed.dashboard?.current_regime}`);

  // Insert into DB
  const conn = await mysql.createConnection(process.env.DATABASE_URL);

  // Clear isLatest
  await conn.execute("UPDATE model_runs SET isLatest = 0");

  const [result] = await conn.execute(
    `INSERT INTO model_runs (runDate, currentSpot, dashboardJson, timeseriesJson, regimeJson, cyclicalJson, stateVariablesJson, legacyDashboardJson, legacyTimeseriesJson, legacyRegimeJson, legacyCyclicalJson, status, isLatest)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'completed', 1)`,
    [
      parsed.dashboard?.run_date || new Date().toISOString().slice(0, 10),
      parsed.dashboard?.current_spot || 0,
      JSON.stringify(parsed.dashboard),
      JSON.stringify(parsed.timeseries),
      JSON.stringify(parsed.regime),
      JSON.stringify([]),
      JSON.stringify(parsed.state_variables_ts || []),
      JSON.stringify(parsed.legacy_fx?.dashboard || null),
      JSON.stringify(parsed.legacy_timeseries || null),
      JSON.stringify(parsed.legacy_regime || null),
      JSON.stringify(parsed.legacy_cyclical || null),
    ]
  );

  console.log(`[Trigger] Inserted run ID: ${result.insertId}`);
  await conn.end();
  console.log("[Trigger] Done!");
}

main().catch((err) => {
  console.error("[Trigger] Fatal:", err.message);
  process.exit(1);
});
