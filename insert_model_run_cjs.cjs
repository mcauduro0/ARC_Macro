const fs = require('fs');
const mysql = require('mysql2/promise');

async function main() {
  const data = JSON.parse(fs.readFileSync('./server/model/output_final.json', 'utf8'));
  const dash = data.dashboard;
  
  console.log('[Insert] Dashboard run_date:', dash.run_date);
  console.log('[Insert] Dashboard current_spot:', dash.current_spot);
  
  const dbUrl = process.env.DATABASE_URL;
  if (!dbUrl) {
    console.error('DATABASE_URL not set in environment');
    process.exit(1);
  }
  console.log('[Insert] Connecting to DB...');
  
  const connection = await mysql.createConnection(dbUrl);
  
  // Clear isLatest
  await connection.execute('UPDATE model_runs SET isLatest = 0');
  console.log('[Insert] Cleared isLatest flags');
  
  // Insert new run
  const sql = `INSERT INTO model_runs (runDate, currentSpot, dashboardJson, timeseriesJson, regimeJson, stateVariablesJson, scoreJson, backtestJson, cyclicalJson, status, isLatest) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`;
  
  const [result] = await connection.execute(sql, [
    dash.run_date || '2026-02-28',
    dash.current_spot || 5.212,
    JSON.stringify(dash),
    JSON.stringify(data.timeseries),
    JSON.stringify(data.regime),
    JSON.stringify(data.state_variables_ts),
    JSON.stringify(data.score_ts),
    JSON.stringify(data.backtest_ts),
    JSON.stringify(data.cyclical_factors_ts || []),
    'completed',
    true,
  ]);
  
  console.log('[Insert] Success! Run ID:', result.insertId);
  
  await connection.end();
}

main().catch(err => {
  console.error('[Insert] Error:', err.message);
  process.exit(1);
});
