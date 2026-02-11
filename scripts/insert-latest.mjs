import fs from 'fs';
import mysql from 'mysql2/promise';

const data = JSON.parse(fs.readFileSync('/tmp/latest_mros_output.json', 'utf-8'));
const dash = data.dashboard;
const ts = data.timeseries || [];
const regime = data.regime || [];
const stateVars = data.state_variables_ts || [];

const conn = await mysql.createConnection(process.env.DATABASE_URL);

// Clear isLatest on all existing runs
await conn.execute('UPDATE model_runs SET isLatest = 0');

// Insert new run
const [result] = await conn.execute(
  `INSERT INTO model_runs (runDate, currentSpot, dashboardJson, timeseriesJson, regimeJson, cyclicalJson, stateVariablesJson, status, isLatest)
   VALUES (?, ?, ?, ?, ?, ?, ?, 'completed', 1)`,
  [
    dash.run_date || new Date().toISOString().slice(0, 10),
    dash.current_spot || 0,
    JSON.stringify(dash),
    JSON.stringify(ts),
    JSON.stringify(regime),
    JSON.stringify([]),
    JSON.stringify(stateVars),
  ]
);

console.log('Inserted run ID:', result.insertId);
console.log('Spot:', dash.current_spot);
console.log('Regime:', dash.current_regime);
console.log('DI 5Y:', dash.di_5y);
console.log('DI 10Y:', dash.di_10y);

await conn.end();
