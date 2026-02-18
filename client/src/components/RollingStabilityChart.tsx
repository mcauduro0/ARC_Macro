/**
 * RollingStabilityChart — Rolling window visualization of feature stability over time.
 * Shows how composite scores evolve across model runs (6-12 month window).
 * Includes:
 * - Per-instrument stacked area chart (robust/moderate/unstable counts)
 * - Per-feature composite score sparklines
 * - Feature persistence heatmap
 */

import { useMemo, useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Badge } from '@/components/ui/badge';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import {
  TrendingUp,
  TrendingDown,
  Clock,
  BarChart3,
  Info,
  ArrowUpRight,
  ArrowDownRight,
  Minus,
} from 'lucide-react';

// ─── Types ───────────────────────────────────────────────────────

interface FeaturePoint {
  date: string;
  composite_score: number;
  classification: string;
}

interface DateSummary {
  date: string;
  n_robust: number;
  n_moderate: number;
  n_unstable: number;
  pct_robust: number;
}

interface InstrumentRolling {
  feature_series: Record<string, FeaturePoint[]>;
  date_summaries: DateSummary[];
}

interface RollingStabilityData {
  n_snapshots: number;
  dates?: string[];
  instruments: Record<string, InstrumentRolling>;
}

interface FeaturePersistence {
  [instrument: string]: Record<string, number>;
}

interface RollingStabilityChartProps {
  rollingData?: RollingStabilityData | null;
  featurePersistence?: FeaturePersistence | null;
}

// ─── Helpers ─────────────────────────────────────────────────────

const INSTRUMENT_LABELS: Record<string, string> = {
  fx: 'DOL Futuro (Câmbio)',
  front: 'Front (DI1 Curto)',
  belly: 'Belly (DI1 Médio)',
  long: 'Long (DI1 Longo)',
  hard: 'Hard (DDI/CDS)',
};

const CLASS_COLORS: Record<string, string> = {
  robust: '#22c55e',
  moderate: '#f59e0b',
  unstable: '#ef4444',
  unknown: '#6b7280',
};

const CLASS_BG: Record<string, string> = {
  robust: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
  moderate: 'bg-amber-500/20 text-amber-400 border-amber-500/30',
  unstable: 'bg-red-500/20 text-red-400 border-red-500/30',
};

function formatDate(d: string): string {
  if (!d) return '';
  const parts = d.split('-');
  if (parts.length >= 2) return `${parts[1]}/${parts[0]?.slice(2)}`;
  return d;
}

function getTrend(series: FeaturePoint[]): { direction: 'up' | 'down' | 'flat'; delta: number } {
  if (series.length < 2) return { direction: 'flat', delta: 0 };
  const last = series[series.length - 1].composite_score;
  const prev = series[series.length - 2].composite_score;
  const delta = last - prev;
  if (Math.abs(delta) < 0.02) return { direction: 'flat', delta };
  return { direction: delta > 0 ? 'up' : 'down', delta };
}

// ─── Sparkline SVG ───────────────────────────────────────────────

function Sparkline({
  series,
  width = 120,
  height = 28,
  thresholdRobust,
  thresholdModerate,
}: {
  series: FeaturePoint[];
  width?: number;
  height?: number;
  thresholdRobust?: number;
  thresholdModerate?: number;
}) {
  if (series.length === 0) return null;

  const maxScore = Math.max(...series.map(s => s.composite_score), 1);
  const minScore = 0;
  const range = maxScore - minScore || 1;

  const points = series.map((s, i) => {
    const x = series.length === 1 ? width / 2 : (i / (series.length - 1)) * width;
    const y = height - ((s.composite_score - minScore) / range) * (height - 4) - 2;
    return `${x},${y}`;
  });

  const lastPoint = series[series.length - 1];
  const color = CLASS_COLORS[lastPoint.classification] || CLASS_COLORS.unknown;

  return (
    <svg width={width} height={height} className="inline-block">
      {/* Threshold lines */}
      {thresholdRobust !== undefined && (
        <line
          x1={0}
          y1={height - ((thresholdRobust - minScore) / range) * (height - 4) - 2}
          x2={width}
          y2={height - ((thresholdRobust - minScore) / range) * (height - 4) - 2}
          stroke="#22c55e"
          strokeWidth={0.5}
          strokeDasharray="2,2"
          opacity={0.4}
        />
      )}
      {thresholdModerate !== undefined && (
        <line
          x1={0}
          y1={height - ((thresholdModerate - minScore) / range) * (height - 4) - 2}
          x2={width}
          y2={height - ((thresholdModerate - minScore) / range) * (height - 4) - 2}
          stroke="#f59e0b"
          strokeWidth={0.5}
          strokeDasharray="2,2"
          opacity={0.4}
        />
      )}
      {/* Line */}
      <polyline
        points={points.join(' ')}
        fill="none"
        stroke={color}
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {/* Dots */}
      {series.map((s, i) => {
        const x = series.length === 1 ? width / 2 : (i / (series.length - 1)) * width;
        const y = height - ((s.composite_score - minScore) / range) * (height - 4) - 2;
        const dotColor = CLASS_COLORS[s.classification] || CLASS_COLORS.unknown;
        return (
          <circle
            key={i}
            cx={x}
            cy={y}
            r={i === series.length - 1 ? 3 : 1.5}
            fill={dotColor}
            opacity={i === series.length - 1 ? 1 : 0.6}
          />
        );
      })}
    </svg>
  );
}

// ─── Stacked Bar Chart ───────────────────────────────────────────

function StackedBarChart({ summaries }: { summaries: DateSummary[] }) {
  if (summaries.length === 0) return null;

  const width = 320;
  const height = 80;
  const barWidth = Math.min(20, (width - 20) / summaries.length - 2);

  const maxTotal = Math.max(...summaries.map(s => s.n_robust + s.n_moderate + s.n_unstable), 1);

  return (
    <div className="flex flex-col items-center">
      <svg width={width} height={height + 20} className="overflow-visible">
        {summaries.map((s, i) => {
          const x = 10 + i * ((width - 20) / summaries.length);
          const total = s.n_robust + s.n_moderate + s.n_unstable;
          const scale = (height - 5) / maxTotal;

          const hRobust = s.n_robust * scale;
          const hModerate = s.n_moderate * scale;
          const hUnstable = s.n_unstable * scale;

          return (
            <g key={i}>
              {/* Unstable (bottom) */}
              <rect
                x={x}
                y={height - hUnstable}
                width={barWidth}
                height={hUnstable}
                fill="#ef4444"
                opacity={0.8}
                rx={1}
              />
              {/* Moderate (middle) */}
              <rect
                x={x}
                y={height - hUnstable - hModerate}
                width={barWidth}
                height={hModerate}
                fill="#f59e0b"
                opacity={0.8}
                rx={1}
              />
              {/* Robust (top) */}
              <rect
                x={x}
                y={height - hUnstable - hModerate - hRobust}
                width={barWidth}
                height={hRobust}
                fill="#22c55e"
                opacity={0.8}
                rx={1}
              />
              {/* Date label */}
              {(i === 0 || i === summaries.length - 1 || summaries.length <= 6) && (
                <text
                  x={x + barWidth / 2}
                  y={height + 14}
                  textAnchor="middle"
                  className="fill-muted-foreground"
                  fontSize={8}
                >
                  {formatDate(s.date)}
                </text>
              )}
            </g>
          );
        })}
      </svg>
      <div className="flex gap-3 mt-1 text-[10px] text-muted-foreground">
        <span className="flex items-center gap-1">
          <span className="w-2 h-2 rounded-sm bg-emerald-500 inline-block" /> Robust
        </span>
        <span className="flex items-center gap-1">
          <span className="w-2 h-2 rounded-sm bg-amber-500 inline-block" /> Moderate
        </span>
        <span className="flex items-center gap-1">
          <span className="w-2 h-2 rounded-sm bg-red-500 inline-block" /> Unstable
        </span>
      </div>
    </div>
  );
}

// ─── Main Component ──────────────────────────────────────────────

export function RollingStabilityChart({ rollingData, featurePersistence }: RollingStabilityChartProps) {
  const instruments = useMemo(() => {
    if (!rollingData?.instruments) return [];
    return Object.keys(rollingData.instruments).sort();
  }, [rollingData]);

  const [selectedInstrument, setSelectedInstrument] = useState<string>('');

  // Auto-select first instrument
  const activeInst = selectedInstrument || instruments[0] || '';
  const instData = rollingData?.instruments?.[activeInst];

  // Not enough data
  if (!rollingData || rollingData.n_snapshots === 0) {
    return (
      <Card className="border-border/50 bg-card/50">
        <CardContent className="py-12 text-center">
          <Clock className="w-10 h-10 mx-auto mb-3 text-muted-foreground/40" />
          <p className="text-muted-foreground text-sm font-medium">
            Rolling Stability Window
          </p>
          <p className="text-muted-foreground/60 text-xs mt-1 max-w-md mx-auto">
            Dados de estabilidade temporal serão acumulados a cada execução do modelo.
            Após 2+ runs, este painel mostrará a evolução dos composite scores e classificações
            ao longo do tempo (janela de 6-12 meses).
          </p>
        </CardContent>
      </Card>
    );
  }

  const featureEntries = useMemo(() => {
    if (!instData?.feature_series) return [];
    return Object.entries(instData.feature_series)
      .map(([name, series]) => {
        const latest = series[series.length - 1];
        const trend = getTrend(series);
        const persistence = featurePersistence?.[activeInst]?.[name] ?? 0;
        return { name, series, latest, trend, persistence };
      })
      .sort((a, b) => (b.latest?.composite_score ?? 0) - (a.latest?.composite_score ?? 0));
  }, [instData, activeInst, featurePersistence]);

  return (
    <div className="space-y-4">
      {/* Header with instrument selector */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <BarChart3 className="w-4 h-4 text-primary" />
          <h3 className="text-sm font-semibold text-foreground">
            Rolling Stability Window
          </h3>
          <Badge variant="outline" className="text-[10px] px-1.5 py-0">
            {rollingData.n_snapshots} snapshot{rollingData.n_snapshots !== 1 ? 's' : ''}
          </Badge>
        </div>
        {instruments.length > 1 && (
          <Select value={activeInst} onValueChange={setSelectedInstrument}>
            <SelectTrigger className="w-[180px] h-7 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {instruments.map(inst => (
                <SelectItem key={inst} value={inst}>
                  {INSTRUMENT_LABELS[inst] || inst.toUpperCase()}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
      </div>

      {/* Single snapshot message */}
      {rollingData.n_snapshots === 1 && (
        <div className="flex items-start gap-2 p-3 rounded-lg bg-blue-500/10 border border-blue-500/20">
          <Info className="w-4 h-4 text-blue-400 mt-0.5 shrink-0" />
          <div className="text-xs text-blue-300/80">
            <p className="font-medium text-blue-300">Primeiro snapshot registrado</p>
            <p className="mt-0.5">
              A visualização temporal requer pelo menos 2 execuções do modelo.
              Os sparklines e gráficos de evolução serão ativados automaticamente
              após a próxima execução. Abaixo está o snapshot atual com classificações
              e composite scores.
            </p>
          </div>
        </div>
      )}

      {/* Summary stacked bar chart (only if >1 snapshot) */}
      {instData && instData.date_summaries.length > 1 && (
        <Card className="border-border/50 bg-card/50">
          <CardHeader className="pb-2 pt-3 px-4">
            <CardTitle className="text-xs font-medium text-muted-foreground">
              Distribuição de Classificação ao Longo do Tempo — {INSTRUMENT_LABELS[activeInst] || activeInst.toUpperCase()}
            </CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-3">
            <StackedBarChart summaries={instData.date_summaries} />
          </CardContent>
        </Card>
      )}

      {/* Feature sparkline table */}
      {featureEntries.length > 0 && (
        <Card className="border-border/50 bg-card/50">
          <CardHeader className="pb-2 pt-3 px-4">
            <CardTitle className="text-xs font-medium text-muted-foreground">
              Evolução por Feature — {INSTRUMENT_LABELS[activeInst] || activeInst.toUpperCase()}
            </CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-3">
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-border/30">
                    <th className="text-left py-1.5 text-muted-foreground font-medium w-[140px]">Feature</th>
                    <th className="text-center py-1.5 text-muted-foreground font-medium w-[140px]">Evolução</th>
                    <th className="text-center py-1.5 text-muted-foreground font-medium w-[80px]">Score</th>
                    <th className="text-center py-1.5 text-muted-foreground font-medium w-[70px]">Status</th>
                    <th className="text-center py-1.5 text-muted-foreground font-medium w-[60px]">Trend</th>
                    <th className="text-center py-1.5 text-muted-foreground font-medium w-[70px]">
                      <Tooltip>
                        <TooltipTrigger>
                          <span className="flex items-center gap-1 justify-center">
                            Persist.
                            <Info className="w-3 h-3" />
                          </span>
                        </TooltipTrigger>
                        <TooltipContent>
                          <p className="text-xs max-w-[200px]">
                            Fração dos snapshots históricos em que esta feature
                            foi selecionada. 1.0 = sempre presente.
                          </p>
                        </TooltipContent>
                      </Tooltip>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {featureEntries.map(({ name, series, latest, trend, persistence }) => (
                    <tr key={name} className="border-b border-border/10 hover:bg-muted/20 transition-colors">
                      <td className="py-1.5 font-mono text-[11px] text-foreground/80 truncate max-w-[140px]" title={name}>
                        {name}
                      </td>
                      <td className="py-1.5 text-center">
                        <Sparkline series={series} width={120} height={24} />
                      </td>
                      <td className="py-1.5 text-center font-mono text-foreground/70">
                        {latest ? `${(latest.composite_score * 100).toFixed(0)}%` : '—'}
                      </td>
                      <td className="py-1.5 text-center">
                        {latest && (
                          <span className={`inline-flex px-1.5 py-0.5 rounded text-[10px] font-medium border ${CLASS_BG[latest.classification] || ''}`}>
                            {latest.classification === 'robust' ? 'R' : latest.classification === 'moderate' ? 'M' : 'U'}
                          </span>
                        )}
                      </td>
                      <td className="py-1.5 text-center">
                        {trend.direction === 'up' ? (
                          <span className="text-emerald-400 flex items-center justify-center gap-0.5">
                            <ArrowUpRight className="w-3 h-3" />
                            <span className="text-[10px]">+{(trend.delta * 100).toFixed(0)}pp</span>
                          </span>
                        ) : trend.direction === 'down' ? (
                          <span className="text-red-400 flex items-center justify-center gap-0.5">
                            <ArrowDownRight className="w-3 h-3" />
                            <span className="text-[10px]">{(trend.delta * 100).toFixed(0)}pp</span>
                          </span>
                        ) : (
                          <span className="text-muted-foreground flex items-center justify-center">
                            <Minus className="w-3 h-3" />
                          </span>
                        )}
                      </td>
                      <td className="py-1.5 text-center">
                        <div className="flex items-center justify-center gap-1">
                          <div className="w-12 h-1.5 rounded-full bg-muted/30 overflow-hidden">
                            <div
                              className="h-full rounded-full transition-all"
                              style={{
                                width: `${persistence * 100}%`,
                                backgroundColor: persistence >= 0.8 ? '#22c55e' : persistence >= 0.5 ? '#f59e0b' : '#ef4444',
                              }}
                            />
                          </div>
                          <span className="text-[10px] text-muted-foreground font-mono w-8">
                            {(persistence * 100).toFixed(0)}%
                          </span>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Cross-instrument persistence summary */}
      {featurePersistence && Object.keys(featurePersistence).length > 1 && (
        <Card className="border-border/50 bg-card/50">
          <CardHeader className="pb-2 pt-3 px-4">
            <CardTitle className="text-xs font-medium text-muted-foreground">
              Persistência Cross-Instrumento
            </CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-3">
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-3">
              {Object.entries(featurePersistence).map(([inst, features]) => {
                const sorted = Object.entries(features).sort((a, b) => b[1] - a[1]);
                const top3 = sorted.slice(0, 3);
                const avgPersistence = sorted.length > 0
                  ? sorted.reduce((s, [, v]) => s + v, 0) / sorted.length
                  : 0;

                return (
                  <div key={inst} className="p-2 rounded-lg bg-muted/10 border border-border/20">
                    <div className="flex items-center justify-between mb-1.5">
                      <span className="text-[10px] font-semibold text-foreground/70 uppercase">
                        {inst}
                      </span>
                      <span className="text-[10px] text-muted-foreground">
                        avg {(avgPersistence * 100).toFixed(0)}%
                      </span>
                    </div>
                    {top3.map(([feat, pct]) => (
                      <div key={feat} className="flex items-center justify-between text-[10px] py-0.5">
                        <span className="text-muted-foreground truncate max-w-[80px]" title={feat}>
                          {feat}
                        </span>
                        <span className={`font-mono ${pct >= 0.8 ? 'text-emerald-400' : pct >= 0.5 ? 'text-amber-400' : 'text-red-400'}`}>
                          {(pct * 100).toFixed(0)}%
                        </span>
                      </div>
                    ))}
                  </div>
                );
              })}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
