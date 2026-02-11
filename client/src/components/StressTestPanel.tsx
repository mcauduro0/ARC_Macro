import { MacroDashboard, StressTest } from '@/hooks/useModelData';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { motion } from 'framer-motion';
import { ShieldAlert, AlertTriangle, TrendingDown } from 'lucide-react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip as RTooltip,
  ResponsiveContainer, Cell, ReferenceLine, Legend
} from 'recharts';

interface Props {
  dashboard: MacroDashboard;
}

const SCENARIO_COLORS: Record<string, string> = {
  'Taper Tantrum 2013': '#f59e0b',
  'BR Fiscal 2015': '#ef4444',
  'Covid 2020': '#8b5cf6',
  'Inflation 2022': '#f97316',
};

const ASSET_COLORS: Record<string, string> = {
  fx: '#06b6d4',
  front: '#34d399',
  long: '#a78bfa',
  hard: '#f472b6',
};

const ASSET_LABELS: Record<string, string> = {
  fx: 'FX',
  front: 'Front-End',
  long: 'Long-End',
  hard: 'Hard Currency',
};

function CustomTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-card/95 backdrop-blur-sm border border-border rounded-lg px-3 py-2 shadow-xl">
      <p className="text-xs font-semibold text-foreground mb-1">{label}</p>
      {payload.map((entry: any, i: number) => (
        <div key={i} className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full" style={{ backgroundColor: entry.color }} />
          <span className="text-xs text-muted-foreground">{entry.name}:</span>
          <span className={`text-xs font-data font-semibold ${entry.value < 0 ? 'text-rose-400' : 'text-emerald-400'}`}>
            {entry.value > 0 ? '+' : ''}{entry.value.toFixed(2)}%
          </span>
        </div>
      ))}
    </div>
  );
}

export function StressTestPanel({ dashboard: d }: Props) {
  const stressTests = d.risk_metrics?.stress_tests || [];

  if (stressTests.length === 0) return null;

  // Build chart data: each scenario as a row with per-asset breakdown
  const chartData = stressTests.map((st: any) => {
    const row: Record<string, any> = { name: st.name };
    row.total = st.return_pct || 0;

    // Per-asset breakdown if available
    if (st.per_asset) {
      Object.entries(st.per_asset).forEach(([asset, val]) => {
        row[asset] = val;
      });
    }
    return row;
  });

  // Check if we have per-asset data
  const hasPerAsset = stressTests.some((st: any) => st.per_asset && Object.keys(st.per_asset).length > 0);

  // Summary chart data (total portfolio impact per scenario)
  const summaryData = stressTests.map((st: any) => ({
    name: st.name.replace(' 2013', '\n2013').replace(' 2015', '\n2015').replace(' 2020', '\n2020').replace(' 2022', '\n2022'),
    fullName: st.name,
    return_pct: st.return_pct || 0,
    max_dd_pct: st.max_dd_pct || 0,
  }));

  // Worst scenario
  const worstScenario = stressTests.reduce((worst: any, st: any) =>
    (st.return_pct || 0) < (worst.return_pct || 0) ? st : worst, stressTests[0]);

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.7, duration: 0.4 }}
    >
      <Card className="bg-card border-border/50">
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between">
            <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground flex items-center gap-2">
              <ShieldAlert className="w-3.5 h-3.5" />
              Stress Tests — Cenários Históricos
            </CardTitle>
            {worstScenario && (
              <div className="flex items-center gap-2 text-xs">
                <AlertTriangle className="w-3 h-3 text-amber-400" />
                <span className="text-muted-foreground">Pior cenário:</span>
                <span className="font-data font-semibold text-rose-400">
                  {worstScenario.name} ({worstScenario.return_pct > 0 ? '+' : ''}{worstScenario.return_pct?.toFixed(2)}%)
                </span>
              </div>
            )}
          </div>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Portfolio Impact Chart */}
            <div>
              <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-3 font-semibold">
                Impacto no Portfólio (%)
              </p>
              <div className="h-[280px]">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={summaryData} layout="vertical" margin={{ top: 5, right: 30, bottom: 5, left: 100 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" horizontal={false} />
                    <XAxis
                      type="number"
                      tick={{ fontSize: 10, fill: 'rgba(255,255,255,0.5)' }}
                      tickFormatter={(v: number) => `${v > 0 ? '+' : ''}${v.toFixed(1)}%`}
                    />
                    <YAxis
                      type="category"
                      dataKey="fullName"
                      tick={{ fontSize: 10, fill: 'rgba(255,255,255,0.5)' }}
                      width={95}
                    />
                    <RTooltip content={<CustomTooltip />} />
                    <ReferenceLine x={0} stroke="rgba(255,255,255,0.2)" />
                    <Bar dataKey="return_pct" name="Retorno" radius={[0, 4, 4, 0]}>
                      {summaryData.map((entry, i) => (
                        <Cell
                          key={i}
                          fill={entry.return_pct < 0 ? '#ef4444' : '#34d399'}
                          fillOpacity={0.7}
                        />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* Per-Asset Breakdown Chart */}
            {hasPerAsset ? (
              <div>
                <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-3 font-semibold">
                  Breakdown por Classe de Ativo (%)
                </p>
                <div className="h-[280px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={chartData} layout="vertical" margin={{ top: 5, right: 30, bottom: 5, left: 100 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" horizontal={false} />
                      <XAxis
                        type="number"
                        tick={{ fontSize: 10, fill: 'rgba(255,255,255,0.5)' }}
                        tickFormatter={(v: number) => `${v > 0 ? '+' : ''}${v.toFixed(1)}%`}
                      />
                      <YAxis
                        type="category"
                        dataKey="name"
                        tick={{ fontSize: 10, fill: 'rgba(255,255,255,0.5)' }}
                        width={95}
                      />
                      <RTooltip content={<CustomTooltip />} />
                      <Legend wrapperStyle={{ fontSize: 10 }} />
                      <ReferenceLine x={0} stroke="rgba(255,255,255,0.2)" />
                      {Object.entries(ASSET_COLORS).map(([asset, color]) => (
                        <Bar key={asset} dataKey={asset} name={ASSET_LABELS[asset]} fill={color} fillOpacity={0.7} stackId="assets" />
                      ))}
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>
            ) : (
              <div>
                <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-3 font-semibold">
                  Detalhes por Cenário
                </p>
                <div className="space-y-3">
                  {stressTests.map((st: any, i: number) => {
                    const color = SCENARIO_COLORS[st.name] || '#6b7280';
                    return (
                      <div key={i} className="p-3 rounded-lg bg-secondary/30 border border-border/30">
                        <div className="flex items-center justify-between mb-2">
                          <div className="flex items-center gap-2">
                            <span className="w-2 h-2 rounded-full" style={{ backgroundColor: color }} />
                            <span className="text-xs font-semibold text-foreground">{st.name}</span>
                          </div>
                          <span className={`font-data text-sm font-bold ${(st.return_pct || 0) < 0 ? 'text-rose-400' : 'text-emerald-400'}`}>
                            {(st.return_pct || 0) > 0 ? '+' : ''}{(st.return_pct || 0).toFixed(2)}%
                          </span>
                        </div>
                        <div className="flex items-center gap-4">
                          <div className="flex items-center gap-1">
                            <TrendingDown className="w-3 h-3 text-rose-400/70" />
                            <span className="text-[10px] text-muted-foreground">Max DD:</span>
                            <span className="font-data text-[10px] font-semibold text-rose-400">
                              {(st.max_dd_pct || 0).toFixed(2)}%
                            </span>
                          </div>
                          {/* Duration bar */}
                          <div className="flex-1 h-1.5 bg-secondary/50 rounded-full overflow-hidden">
                            <div
                              className="h-full rounded-full"
                              style={{
                                width: `${Math.min(100, Math.abs(st.return_pct || 0) * 10)}%`,
                                backgroundColor: color,
                                opacity: 0.7,
                              }}
                            />
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
          </div>

          {/* Summary Stats */}
          <div className="mt-4 pt-3 border-t border-border/30 grid grid-cols-2 sm:grid-cols-4 gap-3">
            {stressTests.map((st: any, i: number) => (
              <div key={i} className="text-center">
                <p className="text-[10px] text-muted-foreground uppercase tracking-wider">{st.name}</p>
                <p className={`font-data text-lg font-bold mt-1 ${(st.return_pct || 0) < 0 ? 'text-rose-400' : 'text-emerald-400'}`}>
                  {(st.return_pct || 0) > 0 ? '+' : ''}{(st.return_pct || 0).toFixed(2)}%
                </p>
                <p className="text-[10px] text-muted-foreground/70">
                  DD: {(st.max_dd_pct || 0).toFixed(2)}%
                </p>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </motion.div>
  );
}
