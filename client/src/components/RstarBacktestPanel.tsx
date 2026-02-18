/**
 * RstarBacktestPanel — r* Signal Backtesting Comparison
 *
 * Compares portfolio returns using r* composite as signal vs the current model.
 * Shows cumulative returns, alpha measurement, signal transitions, and win rates.
 *
 * KEY FIX: Backtest returns (overlay_return, cash_return, total_return) are
 * DECIMAL FRACTIONS (e.g., 0.01 = 1% monthly), NOT percentages.
 *
 * VISUALIZATION: Uses "Excess over CDI" as default view to make alpha visible,
 * since CDI compounds to ~260 over 10 years while overlay alpha is ~30-40%.
 */

import { useMemo, useState } from 'react';
import { RstarTsPoint, BacktestData, BacktestPoint } from '@/hooks/useModelData';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { Button } from '@/components/ui/button';
import { motion } from 'framer-motion';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  ResponsiveContainer, ReferenceLine, Area, AreaChart,
  Tooltip as RechartsTooltip, Legend, ComposedChart, Bar
} from 'recharts';
import { Info, BarChart3, ArrowUpDown } from 'lucide-react';

interface Props {
  rstarTs: RstarTsPoint[];
  backtest: BacktestData | null;
}

interface SignalTransition {
  date: string;
  from: string;
  to: string;
  rstar: number;
  selicStar: number;
  selicActual: number;
  gap: number;
}

/**
 * Build a synthetic r* signal backtest from rstarTs and actual backtest data.
 *
 * Logic:
 * - The r* signal determines position sizing based on the policy gap (SELIC - SELIC*).
 * - When SELIC > SELIC* + 1.5pp → "restrictive" → model is over-tightening → long BRL (scale up)
 * - When SELIC < SELIC* - 1.5pp → "accommodative" → model is too loose → reduce/short BRL
 * - When gap is within ±1.5pp → "neutral" → keep a small position
 */
function buildRstarBacktest(rstarTs: RstarTsPoint[], backtest: BacktestData | null) {
  if (!backtest || !rstarTs.length) return null;

  const btMap = new Map<string, BacktestPoint>();
  backtest.timeseries.forEach(pt => {
    const key = pt.date.substring(0, 7);
    btMap.set(key, pt);
  });

  let rstarEquity = 100;
  let modelEquity = 100;
  let cdiEquity = 100;
  // Excess over CDI: starts at 0, tracks cumulative alpha
  let rstarExcess = 100;
  let modelExcess = 100;

  const combined: Array<{
    date: string;
    rstarEquity: number;
    modelEquity: number;
    cdiEquity: number;
    rstarExcess: number;
    modelExcess: number;
    rstarReturn: number;
    modelReturn: number;
    cdiReturn: number;
    rstarSignal: string;
    gap: number;
    monthlyAlpha: number;
  }> = [];

  let rstarWins = 0;
  let modelWins = 0;
  let totalMonths = 0;
  let rstarMaxDD = 0;
  let modelMaxDD = 0;
  let rstarPeak = 100;
  let modelPeak = 100;
  const transitions: SignalTransition[] = [];
  let prevSignal = '';

  for (const pt of rstarTs) {
    const key = pt.date.substring(0, 7);
    const btPt = btMap.get(key);
    if (!btPt) continue;
    if (pt.composite_rstar === null || pt.selic_actual === null || pt.selic_star === null) continue;

    const gap = pt.selic_actual - pt.selic_star;
    const signal = gap > 1.5 ? 'restrictive' : gap < -1.5 ? 'accommodative' : 'neutral';

    let rstarScaling: number;
    if (signal === 'restrictive') {
      rstarScaling = Math.min(1.5, 0.5 + gap / 5);
    } else if (signal === 'accommodative') {
      rstarScaling = Math.max(-0.5, gap / 5);
    } else {
      rstarScaling = 0.3;
    }

    const modelReturn = btPt.overlay_return || 0;
    const cdiReturn = btPt.cash_return || 0;
    const rstarReturn = modelReturn * rstarScaling;

    // Compound total equity curves
    rstarEquity *= (1 + rstarReturn + cdiReturn);
    modelEquity *= (1 + modelReturn + cdiReturn);
    cdiEquity *= (1 + cdiReturn);

    // Excess over CDI (pure alpha)
    rstarExcess *= (1 + rstarReturn);
    modelExcess *= (1 + modelReturn);

    // Track drawdowns on excess
    rstarPeak = Math.max(rstarPeak, rstarExcess);
    modelPeak = Math.max(modelPeak, modelExcess);
    rstarMaxDD = Math.min(rstarMaxDD, (rstarExcess / rstarPeak - 1) * 100);
    modelMaxDD = Math.min(modelMaxDD, (modelExcess / modelPeak - 1) * 100);

    if (rstarReturn > 0) rstarWins++;
    if (modelReturn > 0) modelWins++;
    totalMonths++;

    if (prevSignal && signal !== prevSignal) {
      transitions.push({
        date: pt.date,
        from: prevSignal,
        to: signal,
        rstar: pt.composite_rstar,
        selicStar: pt.selic_star,
        selicActual: pt.selic_actual,
        gap: Math.round(gap * 100) / 100,
      });
    }
    prevSignal = signal;

    combined.push({
      date: pt.date,
      rstarEquity: Math.round(rstarEquity * 100) / 100,
      modelEquity: Math.round(modelEquity * 100) / 100,
      cdiEquity: Math.round(cdiEquity * 100) / 100,
      rstarExcess: Math.round(rstarExcess * 100) / 100,
      modelExcess: Math.round(modelExcess * 100) / 100,
      rstarReturn: Math.round(rstarReturn * 10000) / 10000,
      modelReturn: Math.round(modelReturn * 10000) / 10000,
      cdiReturn: Math.round(cdiReturn * 10000) / 10000,
      rstarSignal: signal,
      gap: Math.round(gap * 100) / 100,
      monthlyAlpha: Math.round((rstarReturn - modelReturn) * 10000) / 100, // in bps
    });
  }

  if (totalMonths < 6) return null;

  const years = totalMonths / 12;
  const rstarTotalReturn = (rstarEquity / 100 - 1) * 100;
  const modelTotalReturn = (modelEquity / 100 - 1) * 100;
  const cdiTotalReturn = (cdiEquity / 100 - 1) * 100;
  const rstarExcessReturn = (rstarExcess / 100 - 1) * 100;
  const modelExcessReturn = (modelExcess / 100 - 1) * 100;
  const rstarAnnReturn = (Math.pow(rstarEquity / 100, 1 / years) - 1) * 100;
  const modelAnnReturn = (Math.pow(modelEquity / 100, 1 / years) - 1) * 100;
  const rstarAnnExcess = (Math.pow(rstarExcess / 100, 1 / years) - 1) * 100;
  const modelAnnExcess = (Math.pow(modelExcess / 100, 1 / years) - 1) * 100;

  const rstarReturns = combined.map(c => c.rstarReturn);
  const modelReturns = combined.map(c => c.modelReturn);
  const rstarMean = rstarReturns.reduce((s, r) => s + r, 0) / rstarReturns.length;
  const modelMean = modelReturns.reduce((s, r) => s + r, 0) / modelReturns.length;
  const rstarVar = rstarReturns.reduce((s, r) => s + (r - rstarMean) ** 2, 0) / rstarReturns.length;
  const modelVar = modelReturns.reduce((s, r) => s + (r - modelMean) ** 2, 0) / modelReturns.length;
  const rstarVol = Math.sqrt(rstarVar) * Math.sqrt(12) * 100;
  const modelVol = Math.sqrt(modelVar) * Math.sqrt(12) * 100;

  return {
    timeseries: combined,
    transitions: transitions.slice(-20),
    metrics: {
      rstar: {
        totalReturn: Math.round(rstarTotalReturn * 100) / 100,
        excessReturn: Math.round(rstarExcessReturn * 100) / 100,
        annReturn: Math.round(rstarAnnReturn * 100) / 100,
        annExcess: Math.round(rstarAnnExcess * 100) / 100,
        annVol: Math.round(rstarVol * 100) / 100,
        sharpe: rstarVol > 0 ? Math.round((rstarAnnExcess / rstarVol) * 100) / 100 : 0,
        maxDD: Math.round(rstarMaxDD * 100) / 100,
        winRate: Math.round((rstarWins / totalMonths) * 10000) / 100,
      },
      model: {
        totalReturn: Math.round(modelTotalReturn * 100) / 100,
        excessReturn: Math.round(modelExcessReturn * 100) / 100,
        annReturn: Math.round(modelAnnReturn * 100) / 100,
        annExcess: Math.round(modelAnnExcess * 100) / 100,
        annVol: Math.round(modelVol * 100) / 100,
        sharpe: modelVol > 0 ? Math.round((modelAnnExcess / modelVol) * 100) / 100 : 0,
        maxDD: Math.round(modelMaxDD * 100) / 100,
        winRate: Math.round((modelWins / totalMonths) * 10000) / 100,
      },
      cdi: {
        totalReturn: Math.round(cdiTotalReturn * 100) / 100,
      },
      alpha: Math.round((rstarAnnExcess - modelAnnExcess) * 100) / 100,
      totalMonths,
    },
  };
}

export function RstarBacktestPanel({ rstarTs, backtest }: Props) {
  const [view, setView] = useState<'excess' | 'total' | 'signal' | 'transitions'>('excess');

  const result = useMemo(() => buildRstarBacktest(rstarTs, backtest), [rstarTs, backtest]);

  if (!result || result.timeseries.length < 12) {
    return null;
  }

  const { timeseries, transitions, metrics } = result;
  const alphaPositive = metrics.alpha > 0;

  const formatDate = (d: string) => {
    const [y, m] = d.split('-');
    return `${m}/${y.slice(2)}`;
  };

  // Y-axis domains
  const excessValues = timeseries.flatMap(t => [t.rstarExcess, t.modelExcess]);
  const minExcess = Math.floor(Math.min(...excessValues, 100) * 0.95);
  const maxExcess = Math.ceil(Math.max(...excessValues, 100) * 1.05);

  const totalValues = timeseries.flatMap(t => [t.rstarEquity, t.modelEquity, t.cdiEquity]);
  const minTotal = Math.floor(Math.min(...totalValues) * 0.95);
  const maxTotal = Math.ceil(Math.max(...totalValues) * 1.05);

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: 0.2 }}
    >
      <Card className="bg-card border-border/50">
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <CardTitle className="text-xs font-semibold uppercase tracking-wider text-primary flex items-center gap-2">
              <BarChart3 className="w-3.5 h-3.5" />
              Backtest r* Signal vs Modelo Atual
              <Tooltip>
                <TooltipTrigger>
                  <Info className="w-3 h-3 text-muted-foreground/50" />
                </TooltipTrigger>
                <TooltipContent side="right" className="max-w-[320px] text-xs">
                  <p className="mb-1"><strong>Lógica do sinal r*:</strong></p>
                  <p className="mb-1">O gap de política (SELIC - SELIC*) determina o sizing da posição.</p>
                  <p className="mb-1">• <strong>Restritivo</strong> (gap &gt; 1.5pp): BCB apertou demais → BRL deve fortalecer → escala posição long BRL até 1.5x</p>
                  <p className="mb-1">• <strong>Acomodatício</strong> (gap &lt; -1.5pp): BCB frouxo demais → BRL deve enfraquecer → reduz/inverte posição</p>
                  <p>• <strong>Neutro</strong> (|gap| &lt; 1.5pp): posição moderada (0.3x)</p>
                </TooltipContent>
              </Tooltip>
            </CardTitle>
            <div className="flex gap-1">
              {(['excess', 'total', 'signal', 'transitions'] as const).map(v => (
                <Button
                  key={v}
                  variant={view === v ? 'default' : 'ghost'}
                  size="sm"
                  onClick={() => setView(v)}
                  className="h-6 text-[9px] px-2"
                >
                  {v === 'excess' ? 'Alpha (Excesso)' : v === 'total' ? 'Retorno Total' : v === 'signal' ? 'Policy Gap' : 'Transições'}
                </Button>
              ))}
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {/* Metrics Comparison */}
          <div className="grid grid-cols-4 sm:grid-cols-8 gap-3 mb-5">
            {[
              { label: 'ALPHA (ANN.)', value: `${metrics.alpha > 0 ? '+' : ''}${metrics.alpha.toFixed(2)}%`, color: alphaPositive ? 'text-emerald-400' : 'text-red-400' },
              { label: 'SHARPE R*', value: metrics.rstar.sharpe.toFixed(2), color: metrics.rstar.sharpe > metrics.model.sharpe ? 'text-emerald-400' : 'text-amber-400' },
              { label: 'SHARPE MODELO', value: metrics.model.sharpe.toFixed(2), color: 'text-purple-400' },
              { label: 'EXCESS R*', value: `${metrics.rstar.excessReturn > 0 ? '+' : ''}${metrics.rstar.excessReturn.toFixed(1)}%`, color: metrics.rstar.excessReturn > 0 ? 'text-emerald-400' : 'text-red-400' },
              { label: 'EXCESS MODELO', value: `${metrics.model.excessReturn > 0 ? '+' : ''}${metrics.model.excessReturn.toFixed(1)}%`, color: metrics.model.excessReturn > 0 ? 'text-purple-400' : 'text-red-400' },
              { label: 'MAXDD R*', value: `${metrics.rstar.maxDD.toFixed(1)}%`, color: 'text-red-400' },
              { label: 'MAXDD MODELO', value: `${metrics.model.maxDD.toFixed(1)}%`, color: 'text-red-400' },
              { label: 'WIN RATE R*', value: `${metrics.rstar.winRate.toFixed(0)}%`, color: metrics.rstar.winRate > 50 ? 'text-emerald-400' : 'text-amber-400' },
            ].map(m => (
              <div key={m.label} className="text-center">
                <div className="text-[8px] text-muted-foreground/70 uppercase tracking-wider mb-0.5">{m.label}</div>
                <div className={`text-sm font-mono font-bold ${m.color}`}>{m.value}</div>
              </div>
            ))}
          </div>

          {/* Excess over CDI Chart (DEFAULT VIEW - shows alpha clearly) */}
          {view === 'excess' && (
            <div className="h-[300px]">
              <div className="text-[9px] text-muted-foreground/60 mb-2 text-center">
                Retorno acumulado do overlay (excesso sobre CDI) — base 100. Mostra o alpha puro de cada estratégia.
              </div>
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={timeseries} margin={{ top: 5, right: 10, left: 5, bottom: 5 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" opacity={0.3} />
                  <XAxis
                    dataKey="date"
                    tickFormatter={formatDate}
                    tick={{ fontSize: 9, fill: 'hsl(var(--muted-foreground))' }}
                    interval={Math.floor(timeseries.length / 8)}
                  />
                  <YAxis
                    domain={[minExcess, maxExcess]}
                    tick={{ fontSize: 9, fill: 'hsl(var(--muted-foreground))' }}
                    tickFormatter={v => v.toFixed(0)}
                  />
                  <RechartsTooltip
                    contentStyle={{
                      backgroundColor: 'hsl(var(--card))',
                      border: '1px solid hsl(var(--border))',
                      borderRadius: '6px',
                      fontSize: '10px',
                    }}
                    labelFormatter={formatDate}
                    formatter={(value: number, name: string) => {
                      const label = name === 'rstarExcess' ? 'r* Signal (Excess)' : 'Modelo Atual (Excess)';
                      return [`${value.toFixed(2)} (${value > 100 ? '+' : ''}${(value - 100).toFixed(1)}%)`, label];
                    }}
                  />
                  <Legend
                    formatter={(value: string) =>
                      value === 'rstarExcess' ? 'r* Signal (Overlay)' : 'Modelo Atual (Overlay)'
                    }
                    wrapperStyle={{ fontSize: '10px' }}
                  />
                  <ReferenceLine y={100} stroke="hsl(var(--muted-foreground))" strokeDasharray="3 3" opacity={0.5} label={{ value: 'CDI (base)', position: 'left', fontSize: 8, fill: 'hsl(var(--muted-foreground))' }} />
                  <Line
                    type="monotone"
                    dataKey="rstarExcess"
                    stroke="#22d3ee"
                    strokeWidth={2.5}
                    dot={false}
                    isAnimationActive={false}
                  />
                  <Line
                    type="monotone"
                    dataKey="modelExcess"
                    stroke="#a78bfa"
                    strokeWidth={2}
                    dot={false}
                    isAnimationActive={false}
                  />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Total Return Chart (includes CDI compounding) */}
          {view === 'total' && (
            <div className="h-[300px]">
              <div className="text-[9px] text-muted-foreground/60 mb-2 text-center">
                Retorno total acumulado (CDI + overlay) — base 100. O CDI domina o retorno total (~{metrics.cdi.totalReturn.toFixed(0)}% em {(metrics.totalMonths / 12).toFixed(1)} anos).
              </div>
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={timeseries} margin={{ top: 5, right: 10, left: 5, bottom: 5 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" opacity={0.3} />
                  <XAxis
                    dataKey="date"
                    tickFormatter={formatDate}
                    tick={{ fontSize: 9, fill: 'hsl(var(--muted-foreground))' }}
                    interval={Math.floor(timeseries.length / 8)}
                  />
                  <YAxis
                    domain={[minTotal, maxTotal]}
                    tick={{ fontSize: 9, fill: 'hsl(var(--muted-foreground))' }}
                    tickFormatter={v => v.toFixed(0)}
                  />
                  <RechartsTooltip
                    contentStyle={{
                      backgroundColor: 'hsl(var(--card))',
                      border: '1px solid hsl(var(--border))',
                      borderRadius: '6px',
                      fontSize: '10px',
                    }}
                    labelFormatter={formatDate}
                    formatter={(value: number, name: string) => {
                      const label = name === 'rstarEquity' ? 'r* Signal (Total)' :
                                    name === 'modelEquity' ? 'Modelo Atual (Total)' : 'CDI (Buy & Hold)';
                      return [`${value.toFixed(2)} (${value > 100 ? '+' : ''}${(value - 100).toFixed(1)}%)`, label];
                    }}
                  />
                  <Legend
                    formatter={(value: string) =>
                      value === 'rstarEquity' ? 'r* Signal' :
                      value === 'modelEquity' ? 'Modelo Atual' : 'CDI'
                    }
                    wrapperStyle={{ fontSize: '10px' }}
                  />
                  <ReferenceLine y={100} stroke="hsl(var(--muted-foreground))" strokeDasharray="3 3" opacity={0.3} />
                  <Line type="monotone" dataKey="cdiEquity" stroke="#fbbf24" strokeWidth={1.5} dot={false} strokeDasharray="6 3" isAnimationActive={false} />
                  <Line type="monotone" dataKey="modelEquity" stroke="#a78bfa" strokeWidth={2} dot={false} isAnimationActive={false} />
                  <Line type="monotone" dataKey="rstarEquity" stroke="#22d3ee" strokeWidth={2.5} dot={false} isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Policy Gap Chart */}
          {view === 'signal' && (
            <div className="h-[300px]">
              <div className="text-[9px] text-muted-foreground/60 mb-2 text-center">
                Gap de política monetária (SELIC - SELIC*). Positivo = BCB restritivo, Negativo = BCB acomodatício.
              </div>
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={timeseries} margin={{ top: 5, right: 10, left: 5, bottom: 5 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" opacity={0.3} />
                  <XAxis
                    dataKey="date"
                    tickFormatter={formatDate}
                    tick={{ fontSize: 9, fill: 'hsl(var(--muted-foreground))' }}
                    interval={Math.floor(timeseries.length / 8)}
                  />
                  <YAxis
                    tick={{ fontSize: 9, fill: 'hsl(var(--muted-foreground))' }}
                    tickFormatter={v => `${v.toFixed(1)}pp`}
                  />
                  <RechartsTooltip
                    contentStyle={{
                      backgroundColor: 'hsl(var(--card))',
                      border: '1px solid hsl(var(--border))',
                      borderRadius: '6px',
                      fontSize: '10px',
                    }}
                    labelFormatter={formatDate}
                    formatter={(value: number) => [`${value.toFixed(2)}pp`, 'Policy Gap (SELIC - SELIC*)']}
                  />
                  <ReferenceLine y={0} stroke="hsl(var(--muted-foreground))" strokeWidth={1} />
                  <ReferenceLine y={1.5} stroke="#f59e0b" strokeDasharray="3 3" opacity={0.5} label={{ value: 'Restritivo', position: 'right', fontSize: 8, fill: '#f59e0b' }} />
                  <ReferenceLine y={-1.5} stroke="#10b981" strokeDasharray="3 3" opacity={0.5} label={{ value: 'Acomodatício', position: 'right', fontSize: 8, fill: '#10b981' }} />
                  <defs>
                    <linearGradient id="gapGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#f59e0b" stopOpacity={0.4} />
                      <stop offset="50%" stopColor="transparent" stopOpacity={0} />
                      <stop offset="100%" stopColor="#10b981" stopOpacity={0.4} />
                    </linearGradient>
                  </defs>
                  <Area
                    type="monotone"
                    dataKey="gap"
                    stroke="hsl(var(--primary))"
                    fill="url(#gapGrad)"
                    strokeWidth={1.5}
                    isAnimationActive={false}
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Signal Transitions Table */}
          {view === 'transitions' && (
            <div className="max-h-[320px] overflow-y-auto">
              <table className="w-full text-[10px]">
                <thead className="sticky top-0 bg-card">
                  <tr className="text-muted-foreground border-b border-border/30">
                    <th className="text-left py-1.5 px-2">Data</th>
                    <th className="text-left py-1.5 px-2">Transição</th>
                    <th className="text-right py-1.5 px-2">r*</th>
                    <th className="text-right py-1.5 px-2">SELIC*</th>
                    <th className="text-right py-1.5 px-2">SELIC</th>
                    <th className="text-right py-1.5 px-2">Gap</th>
                  </tr>
                </thead>
                <tbody>
                  {transitions.length === 0 ? (
                    <tr><td colSpan={6} className="text-center py-4 text-muted-foreground">Sem transições de sinal no período</td></tr>
                  ) : transitions.map((t, i) => {
                    const signalColor = (s: string) =>
                      s === 'restrictive' ? 'text-amber-400' :
                      s === 'accommodative' ? 'text-emerald-400' : 'text-muted-foreground';
                    const signalLabel = (s: string) =>
                      s === 'restrictive' ? 'Restritivo' :
                      s === 'accommodative' ? 'Acomodatício' : 'Neutro';
                    return (
                      <tr key={i} className="border-b border-border/10 hover:bg-muted/20">
                        <td className="py-1.5 px-2 font-mono">{formatDate(t.date)}</td>
                        <td className="py-1.5 px-2">
                          <span className={signalColor(t.from)}>{signalLabel(t.from)}</span>
                          <span className="text-muted-foreground mx-1">→</span>
                          <span className={signalColor(t.to)}>{signalLabel(t.to)}</span>
                        </td>
                        <td className="text-right py-1.5 px-2 font-mono">{t.rstar.toFixed(2)}%</td>
                        <td className="text-right py-1.5 px-2 font-mono">{t.selicStar.toFixed(2)}%</td>
                        <td className="text-right py-1.5 px-2 font-mono">{t.selicActual.toFixed(2)}%</td>
                        <td className={`text-right py-1.5 px-2 font-mono ${t.gap > 0 ? 'text-amber-400' : 'text-emerald-400'}`}>
                          {t.gap > 0 ? '+' : ''}{t.gap.toFixed(2)}pp
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          {/* Interpretation footer */}
          <div className="mt-4 pt-3 border-t border-border/20">
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-[9px] text-muted-foreground/70">
              <div>
                <span className="inline-block w-3 h-0.5 bg-[#22d3ee] mr-1.5 align-middle rounded"></span>
                <strong className="text-[#22d3ee]">r* Signal</strong>: Posição escalada pelo gap SELIC vs SELIC* (r* composite). Restritivo → long BRL 1.5x, Neutro → 0.3x, Acomodatício → short 0.5x.
              </div>
              <div>
                <span className="inline-block w-3 h-0.5 bg-[#a78bfa] mr-1.5 align-middle rounded"></span>
                <strong className="text-[#a78bfa]">Modelo Atual</strong>: Posição baseada no score composto do ARC Macro (Ridge+GBM ensemble com 7 features).
              </div>
              <div>
                <span className="inline-block w-3 h-0.5 bg-[#fbbf24] mr-1.5 align-middle rounded"></span>
                <strong className="text-[#fbbf24]">CDI</strong>: Benchmark passivo — retorno acumulado da SELIC/CDI sem exposição a risco.
              </div>
            </div>
          </div>
        </CardContent>
      </Card>
    </motion.div>
  );
}
