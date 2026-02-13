import { MacroDashboard, StressTestV23 } from '@/hooks/useModelData';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { motion } from 'framer-motion';
import { ShieldAlert, TrendingUp, TrendingDown, Activity, Target, AlertTriangle } from 'lucide-react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip as RTooltip,
  ResponsiveContainer, Cell, ReferenceLine, Legend
} from 'recharts';

interface Props {
  dashboard: MacroDashboard;
}

const CATEGORY_COLORS: Record<string, string> = {
  domestic: '#ef4444',
  global: '#f59e0b',
  mixed: '#8b5cf6',
};

const ASSET_COLORS: Record<string, string> = {
  fx: '#06b6d4',
  front: '#34d399',
  belly: '#a78bfa',
  long: '#f472b6',
  hard: '#f59e0b',
};

const ASSET_LABELS: Record<string, string> = {
  fx: 'FX',
  front: 'Front',
  belly: 'Belly',
  long: 'Long',
  hard: 'Hard',
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

function ScenarioCard({ scenario, id }: { scenario: StressTestV23; id: string }) {
  const catColor = CATEGORY_COLORS[scenario.category] || '#6b7280';
  const isPositive = scenario.overlay_return >= 0;

  return (
    <div className="p-4 rounded-lg bg-secondary/30 border border-border/30 hover:border-border/60 transition-colors">
      {/* Header */}
      <div className="flex items-start justify-between mb-3">
        <div className="flex-1">
          <div className="flex items-center gap-2 mb-1">
            <span className="w-2 h-2 rounded-full" style={{ backgroundColor: catColor }} />
            <span className="text-xs font-semibold text-foreground">{scenario.name}</span>
            <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-secondary/50 text-muted-foreground uppercase tracking-wider">
              {scenario.category}
            </span>
          </div>
          <p className="text-[10px] text-muted-foreground/70 leading-relaxed">{scenario.description}</p>
        </div>
        <div className="text-right ml-3">
          <p className={`font-data text-lg font-bold ${isPositive ? 'text-emerald-400' : 'text-rose-400'}`}>
            {isPositive ? '+' : ''}{scenario.overlay_return.toFixed(1)}%
          </p>
          <p className="text-[9px] text-muted-foreground">overlay</p>
        </div>
      </div>

      {/* Metrics Row */}
      <div className="grid grid-cols-5 gap-2 mb-3">
        <div className="text-center">
          <p className="text-[9px] text-muted-foreground uppercase">Período</p>
          <p className="font-data text-[10px] font-semibold text-foreground">{scenario.n_months}m</p>
        </div>
        <div className="text-center">
          <p className="text-[9px] text-muted-foreground uppercase">Max DD</p>
          <p className={`font-data text-[10px] font-semibold ${scenario.max_dd_overlay < -1 ? 'text-rose-400' : 'text-foreground'}`}>
            {scenario.max_dd_overlay.toFixed(1)}%
          </p>
        </div>
        <div className="text-center">
          <p className="text-[9px] text-muted-foreground uppercase">Vol</p>
          <p className="font-data text-[10px] font-semibold text-foreground">{scenario.annualized_vol.toFixed(1)}%</p>
        </div>
        <div className="text-center">
          <p className="text-[9px] text-muted-foreground uppercase">Win Rate</p>
          <p className="font-data text-[10px] font-semibold text-foreground">{scenario.win_rate.toFixed(0)}%</p>
        </div>
        <div className="text-center">
          <p className="text-[9px] text-muted-foreground uppercase">Total</p>
          <p className={`font-data text-[10px] font-semibold ${scenario.total_return >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
            {scenario.total_return >= 0 ? '+' : ''}{scenario.total_return.toFixed(1)}%
          </p>
        </div>
      </div>

      {/* Attribution Mini-Bar */}
      {scenario.attribution && (
        <div className="space-y-1">
          <p className="text-[9px] text-muted-foreground uppercase tracking-wider">Atribuição (%)</p>
          <div className="flex gap-1 h-3">
            {Object.entries(scenario.attribution).map(([asset, val]) => {
              const total = Object.values(scenario.attribution).reduce((s, v) => s + Math.abs(v), 0);
              const width = total > 0 ? (Math.abs(val) / total) * 100 : 20;
              return (
                <div
                  key={asset}
                  className="rounded-sm relative group cursor-default"
                  style={{
                    width: `${Math.max(width, 5)}%`,
                    backgroundColor: ASSET_COLORS[asset] || '#6b7280',
                    opacity: val >= 0 ? 0.7 : 0.4,
                  }}
                  title={`${ASSET_LABELS[asset] || asset}: ${val >= 0 ? '+' : ''}${val.toFixed(1)}%`}
                />
              );
            })}
          </div>
          <div className="flex gap-2 flex-wrap">
            {Object.entries(scenario.attribution).map(([asset, val]) => (
              <span key={asset} className="text-[8px] text-muted-foreground/60">
                <span className="inline-block w-1.5 h-1.5 rounded-full mr-0.5" style={{ backgroundColor: ASSET_COLORS[asset] }} />
                {ASSET_LABELS[asset] || asset}: {val >= 0 ? '+' : ''}{val.toFixed(1)}%
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Period */}
      <div className="mt-2 text-[9px] text-muted-foreground/50">
        {scenario.period}
      </div>
    </div>
  );
}

export function StressTestPanel({ dashboard: d }: Props) {
  // v2.3: stress_tests is a dict keyed by scenario ID
  const stressTestsDict = (d as any).stress_tests as Record<string, StressTestV23> | undefined;

  // Also check legacy format
  const legacyTests = d.risk_metrics?.stress_tests || [];

  if (!stressTestsDict && legacyTests.length === 0) return null;

  // Use v2.3 format if available
  const scenarios = stressTestsDict
    ? Object.entries(stressTestsDict).map(([id, s]) => ({ id, ...s }))
    : [];

  if (scenarios.length === 0 && legacyTests.length === 0) return null;

  // Build attribution chart data
  const attrChartData = scenarios.map(s => {
    const row: Record<string, any> = { name: s.name };
    if (s.attribution) {
      Object.entries(s.attribution).forEach(([asset, val]) => {
        row[asset] = val;
      });
    }
    return row;
  });

  // Build overlay return chart data
  const overlayChartData = scenarios.map(s => ({
    name: s.name,
    overlay: s.overlay_return,
    total: s.total_return,
    max_dd: s.max_dd_overlay,
  }));

  // Worst scenario by overlay
  const worstScenario = scenarios.reduce((worst, s) =>
    s.overlay_return < worst.overlay_return ? s : worst, scenarios[0]);

  // Best scenario by overlay
  const bestScenario = scenarios.reduce((best, s) =>
    s.overlay_return > best.overlay_return ? s : best, scenarios[0]);

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.7, duration: 0.4 }}
    >
      <Card className="bg-card border-border/50">
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between flex-wrap gap-2">
            <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground flex items-center gap-2">
              <ShieldAlert className="w-3.5 h-3.5" />
              Stress Tests — Cenários Históricos (v2.3)
            </CardTitle>
            <div className="flex items-center gap-4 text-xs">
              {worstScenario && worstScenario.overlay_return < 0 && (
                <div className="flex items-center gap-1">
                  <AlertTriangle className="w-3 h-3 text-amber-400" />
                  <span className="text-muted-foreground">Pior:</span>
                  <span className="font-data font-semibold text-rose-400">
                    {worstScenario.name} ({worstScenario.overlay_return.toFixed(1)}%)
                  </span>
                </div>
              )}
              {bestScenario && (
                <div className="flex items-center gap-1">
                  <TrendingUp className="w-3 h-3 text-emerald-400" />
                  <span className="text-muted-foreground">Melhor:</span>
                  <span className="font-data font-semibold text-emerald-400">
                    {bestScenario.name} (+{bestScenario.overlay_return.toFixed(1)}%)
                  </span>
                </div>
              )}
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {/* Charts Row */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
            {/* Overlay Return Chart */}
            <div>
              <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-3 font-semibold">
                Retorno Overlay por Cenário (%)
              </p>
              <div className="h-[240px]">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={overlayChartData} layout="vertical" margin={{ top: 5, right: 30, bottom: 5, left: 120 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" horizontal={false} />
                    <XAxis
                      type="number"
                      tick={{ fontSize: 10, fill: 'rgba(255,255,255,0.5)' }}
                      tickFormatter={(v: number) => `${v > 0 ? '+' : ''}${v.toFixed(0)}%`}
                    />
                    <YAxis
                      type="category"
                      dataKey="name"
                      tick={{ fontSize: 9, fill: 'rgba(255,255,255,0.5)' }}
                      width={115}
                    />
                    <RTooltip content={<CustomTooltip />} />
                    <ReferenceLine x={0} stroke="rgba(255,255,255,0.2)" />
                    <Bar dataKey="overlay" name="Overlay" radius={[0, 4, 4, 0]}>
                      {overlayChartData.map((entry, i) => (
                        <Cell
                          key={i}
                          fill={entry.overlay < 0 ? '#ef4444' : '#34d399'}
                          fillOpacity={0.7}
                        />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* Attribution Stacked Chart */}
            <div>
              <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-3 font-semibold">
                Atribuição por Classe de Ativo (%)
              </p>
              <div className="h-[240px]">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={attrChartData} layout="vertical" margin={{ top: 5, right: 30, bottom: 5, left: 120 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" horizontal={false} />
                    <XAxis
                      type="number"
                      tick={{ fontSize: 10, fill: 'rgba(255,255,255,0.5)' }}
                      tickFormatter={(v: number) => `${v > 0 ? '+' : ''}${v.toFixed(0)}%`}
                    />
                    <YAxis
                      type="category"
                      dataKey="name"
                      tick={{ fontSize: 9, fill: 'rgba(255,255,255,0.5)' }}
                      width={115}
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
          </div>

          {/* Scenario Detail Cards */}
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
            {scenarios.map(s => (
              <ScenarioCard key={s.id} scenario={s} id={s.id} />
            ))}
          </div>

          {/* Summary Stats Row */}
          <div className="mt-4 pt-3 border-t border-border/30">
            <div className="grid grid-cols-3 gap-4 text-center">
              <div>
                <p className="text-[10px] text-muted-foreground uppercase tracking-wider">Cenários Positivos</p>
                <p className="font-data text-lg font-bold text-emerald-400 mt-1">
                  {scenarios.filter(s => s.overlay_return >= 0).length}/{scenarios.length}
                </p>
              </div>
              <div>
                <p className="text-[10px] text-muted-foreground uppercase tracking-wider">Retorno Médio</p>
                <p className={`font-data text-lg font-bold mt-1 ${
                  scenarios.reduce((s, sc) => s + sc.overlay_return, 0) / scenarios.length >= 0 ? 'text-emerald-400' : 'text-rose-400'
                }`}>
                  {(scenarios.reduce((s, sc) => s + sc.overlay_return, 0) / scenarios.length).toFixed(1)}%
                </p>
              </div>
              <div>
                <p className="text-[10px] text-muted-foreground uppercase tracking-wider">Pior Max DD</p>
                <p className="font-data text-lg font-bold text-rose-400 mt-1">
                  {Math.min(...scenarios.map(s => s.max_dd_overlay)).toFixed(1)}%
                </p>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>
    </motion.div>
  );
}
