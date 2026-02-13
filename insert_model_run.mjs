/**
 * Insert model run output into the database.
 * Usage: npx tsx insert_model_run.mjs
 */
import { readFileSync } from 'fs';
import { insertModelRun } from './server/db.ts';

const data = JSON.parse(readFileSync('./server/model/output_final.json', 'utf8'));
const dash = data.dashboard;

console.log('[Insert] Dashboard run_date:', dash.run_date);
console.log('[Insert] Dashboard current_spot:', dash.current_spot);
console.log('[Insert] Dashboard current_regime:', dash.current_regime);
console.log('[Insert] Timeseries points:', data.timeseries?.length);
console.log('[Insert] Regime points:', data.regime?.length);
console.log('[Insert] State vars points:', data.state_variables_ts?.length);

try {
  const runId = await insertModelRun({
    runDate: dash.run_date || '2026-02-28',
    currentSpot: dash.current_spot || 5.212,
    dashboardJson: dash,
    timeseriesJson: data.timeseries,
    regimeJson: data.regime,
    stateVariablesJson: data.state_variables_ts,
    scoreJson: data.score_ts,
    backtestJson: data.backtest_ts,
    cyclicalJson: data.cyclical_factors_ts || [],
    status: 'completed',
  });
  console.log('[Insert] Success! Run ID:', runId);
} catch (err) {
  console.error('[Insert] Error:', err.message || err);
}

// Give the connection time to close
setTimeout(() => process.exit(0), 2000);
