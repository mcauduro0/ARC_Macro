import { BacktestData, BacktestPoint, BacktestSummary } from '@/hooks/useModelData';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip as RTooltip,
  ResponsiveContainer, AreaChart, Area, BarChart, Bar, ReferenceLine, Legend, Cell,
  ComposedChart,
} from 'recharts';
import { motion } from 'framer-motion';
import { useMemo, useState } from 'react';
import {
  TrendingUp, TrendingDown, BarChart3, Target, Calendar, Percent,
  Activity, Award, AlertTriangle, Layers, ArrowUpDown,
} from 'lucide-react';

interface Props {
  backtest: BacktestData | null;
}

const COLORS = {
  overlay: '#06b6d4',
  total: '#818cf8',
  drawdown: '#f43f5e',
  positive: '#34d399',
  negative: '#f43f5e',
  fx: '#06b6d4',
  front: '#a78bfa',
  belly: '#f59e0b',
  long: '#818cf8',
  hard: '#34d399',
  ibov: '#f59e0b',
  grid: 'rgba(255,255,255,0.05)',
  text: 'rgba(255,255,255,0.5)',
  zero: 'rgba(255,255,255,0.2)',
};

const INSTRUMENT_LABELS: Record<string, string> = {
  fx: 'FX (NDF)',
  front: 'Front-End (DI 1Y)',
  belly: 'Belly (DI 5Y)',
  long: 'Long-End (DI 10Y)',
  hard: 'Hard Currency (EMBI)',
};

const MONTH_LABELS = ['Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun', 'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez'];

function CustomTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-card/95 backdrop-blur-sm border border-border rounded-lg px-3 py-2 shadow-xl">
      <p className="text-xs text-muted-foreground mb-1 font-data">{label}</p>
      {payload.map((entry: any, i: number) => (
        <div key={i} className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full" style={{ backgroundColor: entry.color }} />
          <span className="text-xs text-muted-foreground">{entry.name}:</span>
          <span className="text-xs font-data font-semibold text-foreground">
            {typeof entry.value === 'number'
              ? `${entry.value.toFixed(2)}%`
              : entry.value}
          </span>
        </div>
      ))}
    </div>
  );
}

type ChartView = 'equity' | 'drawdown' | 'monthly' | 'heatmap' | 'attribution' | 'weights' | 'ic' | 'ensemble' | 'regime' | 'rolling_sharpe';

function MetricCard({
  icon: Icon,
  label,
  value,
  suffix = '',
  color = 'text-foreground',
}: {
  icon: React.ElementType;
  label: string;
  value: string | number;
  suffix?: string;
  color?: string;
}) {
  return (
    <div className="bg-secondary/30 rounded-lg p-3 flex items-start gap-3">
      <div className="p-1.5 rounded-md bg-secondary/50">
        <Icon className="w-4 h-4 text-muted-foreground" />
      </div>
      <div className="min-w-0">
        <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-medium">{label}</p>
        <p className={`text-lg font-data font-bold ${color} leading-tight`}>
          {value}{suffix}
        </p>
      </div>
    </div>
  );
}

function getHeatmapColor(value: number | null): string {
  if (value === null) return 'transparent';
  const clamped = Math.max(-6, Math.min(6, value));
  if (clamped >= 0) {
    const intensity = clamped / 6;
    const r = Math.round(20 + (52 - 20) * (1 - intensity));
    const g = Math.round(30 + (211 - 30) * intensity);
    const b = Math.round(30 + (153 - 30) * intensity * 0.6);
    return `rgb(${r}, ${g}, ${b})`;
  } else {
    const intensity = Math.abs(clamped) / 6;
    const r = Math.round(30 + (244 - 30) * intensity);
    const g = Math.round(30 + (63 - 30) * (1 - intensity));
    const b = Math.round(30 + (94 - 30) * (1 - intensity * 0.5));
    return `rgb(${r}, ${g}, ${b})`;
  }
}

function buildHeatmapData(timeseries: BacktestPoint[]) {
  const yearMap: Record<number, (number | null)[]> = {};
  for (const pt of timeseries) {
    const d = new Date(pt.date + 'T12:00:00Z');
    const year = d.getUTCFullYear();
    const month = d.getUTCMonth();
    if (!yearMap[year]) yearMap[year] = Array(12).fill(null);
    yearMap[year][month] = (pt.overlay_return ?? pt.monthly_return ?? 0) * 100;
  }
  const years = Object.keys(yearMap).map(Number).sort();
  return years.map(year => {
    const months = yearMap[year];
    const validMonths = months.filter((v): v is number => v !== null);
    const yearTotal = validMonths.length > 0
      ? (validMonths.reduce((acc, r) => acc * (1 + r / 100), 1) - 1) * 100
      : null;
    return { year, months, yearTotal };
  });
}

/** Extract overlay or total summary metrics */
function getOverlayMetrics(summary: BacktestSummary) {
  if (summary.overlay) {
    return {
      totalReturn: summary.overlay.total_return,
      annReturn: summary.overlay.annualized_return,
      annVol: summary.overlay.annualized_vol,
      sharpe: summary.overlay.sharpe,
      maxDD: summary.overlay.max_drawdown,
      calmar: summary.overlay.calmar,
      winRate: summary.overlay.win_rate,
      nMonths: summary.n_months ?? summary.total_months ?? 0,
      period: summary.period ?? '',
    };
  }
  // Legacy fallback
  return {
    totalReturn: summary.total_return ?? 0,
    annReturn: summary.annualized_return ?? 0,
    annVol: summary.annualized_vol ?? 0,
    sharpe: summary.sharpe_ratio ?? 0,
    maxDD: summary.max_drawdown ?? 0,
    calmar: (summary.annualized_return ?? 0) / Math.abs(summary.max_drawdown ?? 1),
    winRate: summary.win_rate ?? 0,
    nMonths: summary.total_months ?? 0,
    period: `${summary.start_date ?? ''} → ${summary.end_date ?? ''}`,
  };
}

export function BacktestPanel({ backtest }: Props) {
  const [chartView, setChartView] = useState<ChartView>('equity');

  const equityData = useMemo(() => {
    if (!backtest?.timeseries?.length) return [];
    return backtest.timeseries.map(pt => ({
      ...pt,
      overlay_pct: ((pt.equity_overlay ?? pt.equity ?? 1) - 1) * 100,
      total_pct: ((pt.equity_total ?? 1) - 1) * 100,
      dd_overlay_pct: (pt.drawdown_overlay ?? pt.drawdown ?? 0) * 100,
      dd_total_pct: (pt.drawdown_total ?? 0) * 100,
      ibov_pct: (pt as any).equity_ibov != null ? (((pt as any).equity_ibov ?? 1) - 1) * 100 : null,
    }));
  }, [backtest]);

  const monthlyData = useMemo(() => {
    if (!backtest?.timeseries?.length) return [];
    return backtest.timeseries.map(pt => ({
      date: pt.date,
      overlay_return: (pt.overlay_return ?? pt.monthly_return ?? 0) * 100,
      fx_pnl: (pt.fx_pnl ?? 0) * 100,
      front_pnl: (pt.front_pnl ?? 0) * 100,
      belly_pnl: (pt.belly_pnl ?? 0) * 100,
      long_pnl: (pt.long_pnl ?? 0) * 100,
      hard_pnl: (pt.hard_pnl ?? 0) * 100,
    }));
  }, [backtest]);

  const weightsData = useMemo(() => {
    if (!backtest?.timeseries?.length) return [];
    return backtest.timeseries.map(pt => ({
      date: pt.date,
      fx: pt.weight_fx ?? 0,
      front: pt.weight_front ?? 0,
      belly: pt.weight_belly ?? 0,
      long: pt.weight_long ?? 0,
      hard: pt.weight_hard ?? 0,
    }));
  }, [backtest]);

  const heatmapData = useMemo(() => {
    if (!backtest?.timeseries?.length) return [];
    return buildHeatmapData(backtest.timeseries);
  }, [backtest]);

  const ensembleData = useMemo(() => {
    if (!backtest?.timeseries?.length) return [];
    return backtest.timeseries.map(pt => ({
      date: pt.date,
      w_ridge: ((pt as any).w_ridge_avg ?? 0.25) * 100,
      w_gbm: ((pt as any).w_gbm_avg ?? 0.25) * 100,
      w_rf: ((pt as any).w_rf_avg ?? 0.25) * 100,
      w_xgb: ((pt as any).w_xgb_avg ?? 0.25) * 100,
      raw_score: (pt as any).raw_score ?? 0,
      demeaned_score: (pt as any).demeaned_score ?? 0,
    }));
  }, [backtest]);

  const regimeData = useMemo(() => {
    if (!backtest?.timeseries?.length) return [];
    return backtest.timeseries.map(pt => ({
      date: pt.date,
      P_carry: ((pt as any).P_carry ?? 0) * 100,
      P_riskoff: ((pt as any).P_riskoff ?? 0) * 100,
      P_stress: ((pt as any).P_stress ?? 0) * 100,
      P_domestic_calm: ((pt as any).P_domestic_calm ?? 0) * 100,
      P_domestic_stress: ((pt as any).P_domestic_stress ?? 0) * 100,
    }));
  }, [backtest]);

  const rollingSharpeData = useMemo(() => {
    if (!backtest?.timeseries?.length) return [];
    return backtest.timeseries
      .filter(pt => (pt as any).rolling_sharpe_12m != null)
      .map(pt => ({
        date: pt.date,
        sharpe_12m: (pt as any).rolling_sharpe_12m ?? 0,
      }));
  }, [backtest]);

  const formatDate = (d: string) => d?.slice(0, 7) || '';

  if (!backtest || !backtest.timeseries?.length) {
    return (
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.5, duration: 0.4 }}
      >
        <Card className="bg-card border-border/50">
          <CardHeader className="pb-2">
            <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Backtest — Overlay sobre CDI
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex items-center justify-center h-48 text-muted-foreground text-sm">
              <AlertTriangle className="w-5 h-5 mr-2" />
              Dados de backtest não disponíveis. Execute o modelo para gerar.
            </div>
          </CardContent>
        </Card>
      </motion.div>
    );
  }

  const summary = backtest.summary;
  const m = getOverlayMetrics(summary);
  const totalMetrics = summary.total;
  const sharpeColor = m.sharpe >= 1 ? 'text-emerald-400' : m.sharpe >= 0.5 ? 'text-amber-400' : 'text-red-400';
  const returnColor = m.annReturn >= 0 ? 'text-emerald-400' : 'text-red-400';
  const ddColor = 'text-red-400';

  const chartViews: { value: ChartView; label: string }[] = [
    { value: 'equity', label: 'Equity Overlay vs Total' },
    { value: 'drawdown', label: 'Drawdown' },
    { value: 'monthly', label: 'Retornos' },
    { value: 'heatmap', label: 'Heatmap' },
    { value: 'attribution', label: 'Atribuição' },
    { value: 'weights', label: 'Pesos' },
    { value: 'ic', label: 'IC & Hit Rate' },
    { value: 'ensemble', label: 'Ensemble' },
    { value: 'regime', label: 'Regime' },
    { value: 'rolling_sharpe', label: 'Rolling Sharpe' },
  ];

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.5, duration: 0.4 }}
    >
      <Card className="bg-card border-border/50">
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between flex-wrap gap-2">
            <div className="flex items-center gap-3">
              <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Backtest v3.8 — Overlay sobre CDI
              </CardTitle>
              <span className="text-[10px] text-muted-foreground/60 font-data">
                {m.period} · {m.nMonths} meses
              </span>
            </div>
            <div className="flex items-center gap-1 bg-amber-500/10 border border-amber-500/20 rounded px-2 py-0.5">
              <AlertTriangle className="w-3 h-3 text-amber-500" />
              <span className="text-[9px] text-amber-500 font-medium uppercase tracking-wider">Walk-Forward</span>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Overlay vs Total Summary */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            {/* Overlay metrics */}
            <div className="bg-secondary/20 rounded-lg p-3 border border-cyan-500/10">
              <p className="text-[10px] uppercase tracking-wider text-cyan-400 font-semibold mb-2">Overlay (Excesso sobre CDI)</p>
              <div className="grid grid-cols-3 gap-2">
                <div>
                  <p className="text-[9px] text-muted-foreground">Retorno Total</p>
                  <p className={`text-sm font-data font-bold ${returnColor}`}>{m.totalReturn.toFixed(1)}%</p>
                </div>
                <div>
                  <p className="text-[9px] text-muted-foreground">Ann Return</p>
                  <p className={`text-sm font-data font-bold ${returnColor}`}>{m.annReturn.toFixed(1)}%</p>
                </div>
                <div>
                  <p className="text-[9px] text-muted-foreground">Ann Vol</p>
                  <p className="text-sm font-data font-bold text-foreground">{m.annVol.toFixed(1)}%</p>
                </div>
                <div>
                  <p className="text-[9px] text-muted-foreground">Sharpe</p>
                  <p className={`text-sm font-data font-bold ${sharpeColor}`}>{m.sharpe.toFixed(2)}</p>
                </div>
                <div>
                  <p className="text-[9px] text-muted-foreground">Max DD</p>
                  <p className={`text-sm font-data font-bold ${ddColor}`}>{m.maxDD.toFixed(1)}%</p>
                </div>
                <div>
                  <p className="text-[9px] text-muted-foreground">Calmar</p>
                  <p className={`text-sm font-data font-bold ${sharpeColor}`}>{m.calmar.toFixed(2)}</p>
                </div>
              </div>
            </div>
            {/* Total metrics */}
            {totalMetrics && (
              <div className="bg-secondary/20 rounded-lg p-3 border border-indigo-500/10">
                <p className="text-[10px] uppercase tracking-wider text-indigo-400 font-semibold mb-2">Total (CDI + Overlay)</p>
                <div className="grid grid-cols-3 gap-2">
                  <div>
                    <p className="text-[9px] text-muted-foreground">Retorno Total</p>
                    <p className="text-sm font-data font-bold text-indigo-400">{totalMetrics.total_return.toFixed(1)}%</p>
                  </div>
                  <div>
                    <p className="text-[9px] text-muted-foreground">Ann Return</p>
                    <p className="text-sm font-data font-bold text-indigo-400">{totalMetrics.annualized_return.toFixed(1)}%</p>
                  </div>
                  <div>
                    <p className="text-[9px] text-muted-foreground">Total Sharpe</p>
                    <p className="text-sm font-data font-bold text-indigo-400">{totalMetrics.sharpe.toFixed(2)}</p>
                  </div>
                </div>
              </div>
            )}
            {/* Ibovespa Benchmark */}
            {(summary as any).ibovespa && (
              <div className="bg-secondary/20 rounded-lg p-3 border border-amber-500/10">
                <p className="text-[10px] uppercase tracking-wider text-amber-400 font-semibold mb-2">Ibovespa (Benchmark)</p>
                <div className="grid grid-cols-3 gap-2">
                  <div>
                    <p className="text-[9px] text-muted-foreground">Retorno Total</p>
                    <p className="text-sm font-data font-bold text-amber-400">{((summary as any).ibovespa.total_return ?? 0).toFixed(1)}%</p>
                  </div>
                  <div>
                    <p className="text-[9px] text-muted-foreground">Ann Return</p>
                    <p className="text-sm font-data font-bold text-amber-400">{((summary as any).ibovespa.annualized_return ?? 0).toFixed(1)}%</p>
                  </div>
                  <div>
                    <p className="text-[9px] text-muted-foreground">Sharpe</p>
                    <p className="text-sm font-data font-bold text-amber-400">{((summary as any).ibovespa.sharpe ?? 0).toFixed(2)}</p>
                  </div>
                  <div>
                    <p className="text-[9px] text-muted-foreground">Max DD</p>
                    <p className="text-sm font-data font-bold text-red-400">{((summary as any).ibovespa.max_drawdown ?? 0).toFixed(1)}%</p>
                  </div>
                  <div>
                    <p className="text-[9px] text-muted-foreground">Win Rate</p>
                    <p className="text-sm font-data font-bold text-amber-400">{((summary as any).ibovespa.win_rate ?? 0).toFixed(0)}%</p>
                  </div>
                  <div>
                    <p className="text-[9px] text-muted-foreground">Calmar</p>
                    <p className="text-sm font-data font-bold text-amber-400">{((summary as any).ibovespa.calmar ?? 0).toFixed(2)}</p>
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Key Metrics Row */}
          <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
            <MetricCard icon={Target} label="Win Rate" value={m.winRate.toFixed(0)} suffix="%" color={m.winRate >= 50 ? 'text-emerald-400' : 'text-red-400'} />
            <MetricCard icon={ArrowUpDown} label="Turnover Médio" value={(summary.avg_monthly_turnover ?? 0).toFixed(2)} suffix="x" />
            <MetricCard icon={Layers} label="TC Total" value={(summary.total_tc_pct ?? 0).toFixed(1)} suffix="%" color="text-amber-400" />
            <MetricCard icon={Calendar} label="Melhor Mês" value={summary.best_month ? `+${(summary.best_month.return_pct ?? 0).toFixed(1)}%` : 'N/A'} color="text-emerald-400" />
            <MetricCard icon={Calendar} label="Pior Mês" value={summary.worst_month ? `${(summary.worst_month.return_pct ?? 0).toFixed(1)}%` : 'N/A'} color="text-red-400" />
          </div>

          {/* Chart View Tabs */}
          <div className="flex gap-1 bg-secondary/50 rounded-lg p-1 w-fit flex-wrap">
            {chartViews.map(tab => (
              <button
                key={tab.value}
                onClick={() => setChartView(tab.value)}
                className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
                  chartView === tab.value
                    ? 'bg-background text-foreground shadow-sm'
                    : 'text-muted-foreground hover:text-foreground'
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>

          {/* Charts */}
          {chartView === 'equity' && (
            <div className="h-[320px]">
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={equityData} margin={{ top: 5, right: 20, bottom: 5, left: 10 }}>
                  <defs>
                    <linearGradient id="overlayGradient" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor={COLORS.overlay} stopOpacity={0.15} />
                      <stop offset="95%" stopColor={COLORS.overlay} stopOpacity={0.02} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke={COLORS.grid} />
                  <XAxis dataKey="date" tickFormatter={formatDate} tick={{ fontSize: 10, fill: COLORS.text }} interval="preserveStartEnd" />
                  <YAxis tick={{ fontSize: 10, fill: COLORS.text }} tickFormatter={(v: number) => `${v.toFixed(0)}%`} />
                  <RTooltip content={<CustomTooltip />} />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  <ReferenceLine y={0} stroke={COLORS.zero} strokeWidth={1.5} />
                  <Line
                    type="monotone"
                    dataKey="total_pct"
                    stroke={COLORS.total}
                    strokeWidth={1.5}
                    strokeDasharray="5 3"
                    dot={false}
                    name="Total (CDI + Overlay) %"
                    connectNulls
                    isAnimationActive={false}
                  />
                  <Line
                    type="monotone"
                    dataKey="ibov_pct"
                    stroke={COLORS.ibov}
                    strokeWidth={1.2}
                    strokeDasharray="3 3"
                    dot={false}
                    name="Ibovespa %"
                    connectNulls
                    isAnimationActive={false}
                  />
                  <Area
                    type="monotone"
                    dataKey="overlay_pct"
                    stroke={COLORS.overlay}
                    fill="url(#overlayGradient)"
                    strokeWidth={2}
                    dot={false}
                    name="Overlay (Excesso) %"
                    connectNulls
                    isAnimationActive={false}
                  />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          )}

          {chartView === 'drawdown' && (
            <div className="h-[320px]">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={equityData} margin={{ top: 5, right: 20, bottom: 5, left: 10 }}>
                  <defs>
                    <linearGradient id="ddGradient" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor={COLORS.drawdown} stopOpacity={0.4} />
                      <stop offset="95%" stopColor={COLORS.drawdown} stopOpacity={0.02} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke={COLORS.grid} />
                  <XAxis dataKey="date" tickFormatter={formatDate} tick={{ fontSize: 10, fill: COLORS.text }} interval="preserveStartEnd" />
                  <YAxis tick={{ fontSize: 10, fill: COLORS.text }} tickFormatter={(v: number) => `${v.toFixed(0)}%`} domain={['auto', 0]} />
                  <RTooltip content={<CustomTooltip />} />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  <ReferenceLine y={0} stroke={COLORS.zero} strokeWidth={1} />
                  <ReferenceLine
                    y={m.maxDD}
                    stroke={COLORS.drawdown}
                    strokeDasharray="4 3"
                    label={{
                      value: `Max DD: ${m.maxDD.toFixed(1)}%`,
                      position: 'right',
                      fill: 'rgba(244,63,94,0.7)',
                      fontSize: 9,
                    }}
                  />
                  <Area
                    type="monotone"
                    dataKey="dd_overlay_pct"
                    stroke={COLORS.drawdown}
                    fill="url(#ddGradient)"
                    strokeWidth={1.5}
                    dot={false}
                    name="DD Overlay (%)"
                    connectNulls
                    isAnimationActive={false}
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}

          {chartView === 'monthly' && (
            <div className="h-[320px]">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={monthlyData} margin={{ top: 5, right: 20, bottom: 5, left: 10 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={COLORS.grid} />
                  <XAxis dataKey="date" tickFormatter={formatDate} tick={{ fontSize: 10, fill: COLORS.text }} interval="preserveStartEnd" />
                  <YAxis tick={{ fontSize: 10, fill: COLORS.text }} tickFormatter={(v: number) => `${v.toFixed(1)}%`} />
                  <RTooltip content={<CustomTooltip />} />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  <ReferenceLine y={0} stroke={COLORS.zero} strokeWidth={1} />
                  <Bar dataKey="overlay_return" name="Overlay Return (%)" isAnimationActive={false}>
                    {monthlyData.map((entry, index) => (
                      <Cell
                        key={`cell-${index}`}
                        fill={entry.overlay_return >= 0 ? COLORS.positive : COLORS.negative}
                        fillOpacity={0.7}
                      />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Monthly Returns Heatmap */}
          {chartView === 'heatmap' && (
            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-xs font-data">
                <thead>
                  <tr>
                    <th className="text-left text-muted-foreground font-medium px-2 py-1.5 w-16">Ano</th>
                    {MONTH_LABELS.map(m => (
                      <th key={m} className="text-center text-muted-foreground font-medium px-1 py-1.5 w-14">{m}</th>
                    ))}
                    <th className="text-center text-muted-foreground font-medium px-2 py-1.5 w-16 border-l border-border/30">Ano</th>
                  </tr>
                </thead>
                <tbody>
                  {heatmapData.map(row => (
                    <tr key={row.year} className="border-t border-border/10">
                      <td className="text-muted-foreground font-semibold px-2 py-0.5">{row.year}</td>
                      {row.months.map((val, mi) => (
                        <td
                          key={mi}
                          className="text-center px-1 py-0.5"
                          style={{
                            backgroundColor: getHeatmapColor(val),
                            color: val === null ? 'transparent' : Math.abs(val) > 2 ? '#fff' : 'rgba(255,255,255,0.8)',
                          }}
                          title={val !== null ? `${MONTH_LABELS[mi]} ${row.year}: ${val.toFixed(2)}%` : ''}
                        >
                          {val !== null ? `${val >= 0 ? '+' : ''}${val.toFixed(1)}` : ''}
                        </td>
                      ))}
                      <td
                        className="text-center font-semibold px-2 py-0.5 border-l border-border/30"
                        style={{
                          backgroundColor: row.yearTotal !== null ? getHeatmapColor(row.yearTotal) : 'transparent',
                          color: row.yearTotal === null ? 'transparent' : Math.abs(row.yearTotal) > 2 ? '#fff' : 'rgba(255,255,255,0.8)',
                        }}
                      >
                        {row.yearTotal !== null ? `${row.yearTotal >= 0 ? '+' : ''}${row.yearTotal.toFixed(1)}` : ''}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="flex items-center justify-center gap-2 mt-3 text-[10px] text-muted-foreground">
                <span>-6%</span>
                <div className="flex h-3 rounded-sm overflow-hidden">
                  {Array.from({ length: 13 }, (_, i) => i - 6).map(v => (
                    <div key={v} className="w-4 h-3" style={{ backgroundColor: getHeatmapColor(v) }} />
                  ))}
                </div>
                <span>+6%</span>
              </div>
            </div>
          )}

          {/* Attribution stacked bar */}
          {chartView === 'attribution' && (
            <div className="space-y-4">
              {/* Attribution summary table */}
              {summary.attribution_pct && (
                <div className="grid grid-cols-5 gap-2">
                  {Object.entries(summary.attribution_pct).map(([inst, pct]) => (
                    <div key={inst} className="bg-secondary/30 rounded-lg p-2 text-center">
                      <p className="text-[9px] uppercase tracking-wider text-muted-foreground">{inst}</p>
                      <p className={`text-sm font-data font-bold ${pct >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                        {pct >= 0 ? '+' : ''}{pct.toFixed(1)}%
                      </p>
                    </div>
                  ))}
                </div>
              )}
              <div className="h-[280px]">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={monthlyData} margin={{ top: 5, right: 20, bottom: 5, left: 10 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke={COLORS.grid} />
                    <XAxis dataKey="date" tickFormatter={formatDate} tick={{ fontSize: 10, fill: COLORS.text }} interval="preserveStartEnd" />
                    <YAxis tick={{ fontSize: 10, fill: COLORS.text }} tickFormatter={(v: number) => `${v.toFixed(1)}%`} />
                    <RTooltip content={<CustomTooltip />} />
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                    <ReferenceLine y={0} stroke={COLORS.zero} strokeWidth={1} />
                    <Bar dataKey="fx_pnl" stackId="a" fill={COLORS.fx} fillOpacity={0.7} name="FX (%)" isAnimationActive={false} />
                    <Bar dataKey="front_pnl" stackId="a" fill={COLORS.front} fillOpacity={0.7} name="Front (%)" isAnimationActive={false} />
                    <Bar dataKey="belly_pnl" stackId="a" fill={COLORS.belly} fillOpacity={0.7} name="Belly (%)" isAnimationActive={false} />
                    <Bar dataKey="long_pnl" stackId="a" fill={COLORS.long} fillOpacity={0.7} name="Long (%)" isAnimationActive={false} />
                    <Bar dataKey="hard_pnl" stackId="a" fill={COLORS.hard} fillOpacity={0.7} name="Hard (%)" isAnimationActive={false} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}

          {/* Weights over time */}
          {chartView === 'weights' && (
            <div className="h-[320px]">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={weightsData} margin={{ top: 5, right: 20, bottom: 5, left: 10 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={COLORS.grid} />
                  <XAxis dataKey="date" tickFormatter={formatDate} tick={{ fontSize: 10, fill: COLORS.text }} interval="preserveStartEnd" />
                  <YAxis tick={{ fontSize: 10, fill: COLORS.text }} tickFormatter={(v: number) => v.toFixed(1)} />
                  <RTooltip content={<CustomTooltip />} />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  <ReferenceLine y={0} stroke={COLORS.zero} strokeWidth={1} />
                  <Line type="stepAfter" dataKey="fx" stroke={COLORS.fx} strokeWidth={1.5} dot={false} name="FX" isAnimationActive={false} />
                  <Line type="stepAfter" dataKey="front" stroke={COLORS.front} strokeWidth={1.5} dot={false} name="Front" isAnimationActive={false} />
                  <Line type="stepAfter" dataKey="belly" stroke={COLORS.belly} strokeWidth={1.5} dot={false} name="Belly" isAnimationActive={false} />
                  <Line type="stepAfter" dataKey="long" stroke={COLORS.long} strokeWidth={1.5} dot={false} name="Long" isAnimationActive={false} />
                  <Line type="stepAfter" dataKey="hard" stroke={COLORS.hard} strokeWidth={1.5} dot={false} name="Hard" isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* IC & Hit Rate table */}
          {chartView === 'ic' && (
            <div className="overflow-x-auto">
              <table className="w-full text-xs font-data">
                <thead>
                  <tr className="border-b border-border/30">
                    <th className="text-left py-2 px-3 text-muted-foreground font-medium">Instrumento</th>
                    <th className="text-center py-2 px-3 text-muted-foreground font-medium">IC (Rank Corr)</th>
                    <th className="text-center py-2 px-3 text-muted-foreground font-medium">Hit Rate</th>
                    <th className="text-center py-2 px-3 text-muted-foreground font-medium">Atribuição</th>
                    <th className="text-center py-2 px-3 text-muted-foreground font-medium">Peso Médio</th>
                  </tr>
                </thead>
                <tbody>
                  {['fx', 'front', 'belly', 'long', 'hard'].map(inst => {
                    const ic = summary.ic_per_instrument?.[inst] ?? 0;
                    const hr = summary.hit_rates?.[inst] ?? 0;
                    const attr = summary.attribution_pct?.[inst] ?? 0;
                    const avgW = backtest.timeseries.length > 0
                      ? backtest.timeseries.reduce((sum, pt) => sum + Math.abs((pt as any)[`weight_${inst}`] ?? 0), 0) / backtest.timeseries.length
                      : 0;
                    return (
                      <tr key={inst} className="border-b border-border/10 hover:bg-secondary/20">
                        <td className="py-2 px-3">
                          <div className="flex items-center gap-2">
                            <span className="w-2 h-2 rounded-full" style={{ backgroundColor: (COLORS as any)[inst] }} />
                            <span className="font-medium">{INSTRUMENT_LABELS[inst] || inst}</span>
                          </div>
                        </td>
                        <td className={`text-center py-2 px-3 font-semibold ${ic > 0.05 ? 'text-emerald-400' : ic < -0.05 ? 'text-red-400' : 'text-muted-foreground'}`}>
                          {ic.toFixed(3)}
                        </td>
                        <td className={`text-center py-2 px-3 font-semibold ${hr >= 50 ? 'text-emerald-400' : 'text-red-400'}`}>
                          {hr.toFixed(1)}%
                        </td>
                        <td className={`text-center py-2 px-3 font-semibold ${attr >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                          {attr >= 0 ? '+' : ''}{attr.toFixed(1)}%
                        </td>
                        <td className="text-center py-2 px-3 text-muted-foreground">
                          {avgW.toFixed(3)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          {/* Ensemble Model Weights & Score Demeaning */}
          {chartView === 'ensemble' && (
            <div className="space-y-4">
              {/* Ensemble summary cards */}
              {summary.ensemble && (
                <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                  <div className="bg-secondary/30 rounded-lg p-3 text-center border border-blue-500/10">
                    <p className="text-[9px] uppercase tracking-wider text-muted-foreground">Avg Ridge</p>
                    <p className="text-lg font-data font-bold text-blue-400">{(summary.ensemble!.avg_w_ridge * 100).toFixed(1)}%</p>
                  </div>
                  <div className="bg-secondary/30 rounded-lg p-3 text-center border border-orange-500/10">
                    <p className="text-[9px] uppercase tracking-wider text-muted-foreground">Avg GBM</p>
                    <p className="text-lg font-data font-bold text-orange-400">{(summary.ensemble!.avg_w_gbm * 100).toFixed(1)}%</p>
                  </div>
                  <div className="bg-secondary/30 rounded-lg p-3 text-center border border-green-500/10">
                    <p className="text-[9px] uppercase tracking-wider text-muted-foreground">Avg RF</p>
                    <p className="text-lg font-data font-bold text-green-400">{((summary.ensemble as any)?.avg_w_rf != null ? ((summary.ensemble as any).avg_w_rf * 100).toFixed(1) : 'N/A')}%</p>
                  </div>
                  <div className="bg-secondary/30 rounded-lg p-3 text-center border border-purple-500/10">
                    <p className="text-[9px] uppercase tracking-wider text-muted-foreground">Avg XGBoost</p>
                    <p className="text-lg font-data font-bold text-purple-400">{((summary.ensemble as any)?.avg_w_xgb != null ? ((summary.ensemble as any).avg_w_xgb * 100).toFixed(1) : 'N/A')}%</p>
                  </div>
                </div>
              )}

              {/* Score demeaning stats */}
              {(summary as any).score_demeaning && (
                <div className="bg-secondary/20 rounded-lg p-3 border border-border/30">
                  <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold mb-2">Score Demeaning (Z-Score Rolling 60m)</p>
                  <div className="grid grid-cols-4 gap-3">
                    <div>
                      <p className="text-[9px] text-muted-foreground">Raw Score Mean</p>
                      <p className="text-sm font-data font-bold text-foreground">{(summary as any).score_demeaning.raw_score_mean.toFixed(3)}</p>
                    </div>
                    <div>
                      <p className="text-[9px] text-muted-foreground">Raw Score Std</p>
                      <p className="text-sm font-data font-bold text-foreground">{(summary as any).score_demeaning.raw_score_std.toFixed(3)}</p>
                    </div>
                    <div>
                      <p className="text-[9px] text-muted-foreground">Demeaned Mean</p>
                      <p className="text-sm font-data font-bold text-emerald-400">{(summary as any).score_demeaning.demeaned_score_mean.toFixed(3)}</p>
                    </div>
                    <div>
                      <p className="text-[9px] text-muted-foreground">Demeaned Std</p>
                      <p className="text-sm font-data font-bold text-foreground">{(summary as any).score_demeaning.demeaned_score_std.toFixed(3)}</p>
                    </div>
                  </div>
                </div>
              )}

              {/* Ensemble weights over time chart */}
              <div className="h-[280px]">
                <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold mb-2">Pesos do Ensemble ao Longo do Tempo</p>
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={ensembleData} margin={{ top: 5, right: 20, bottom: 5, left: 10 }}>
                    <defs>
                      <linearGradient id="ridgeGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.4} />
                        <stop offset="95%" stopColor="#3b82f6" stopOpacity={0.05} />
                      </linearGradient>
                      <linearGradient id="gbmGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#f97316" stopOpacity={0.4} />
                        <stop offset="95%" stopColor="#f97316" stopOpacity={0.05} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke={COLORS.grid} />
                    <XAxis dataKey="date" tickFormatter={formatDate} tick={{ fontSize: 10, fill: COLORS.text }} interval="preserveStartEnd" />
                    <YAxis tick={{ fontSize: 10, fill: COLORS.text }} tickFormatter={(v: number) => `${v.toFixed(0)}%`} domain={[0, 100]} />
                    <RTooltip content={<CustomTooltip />} />
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                    <Area type="monotone" dataKey="w_ridge" stackId="1" stroke="#3b82f6" fill="url(#ridgeGrad)" strokeWidth={1.5} name="Ridge (%)" isAnimationActive={false} />
                    <Area type="monotone" dataKey="w_gbm" stackId="1" stroke="#f97316" fill="url(#gbmGrad)" strokeWidth={1.5} name="GBM (%)" isAnimationActive={false} />
                    <Area type="monotone" dataKey="w_rf" stackId="1" stroke="#22c55e" fill="#22c55e" fillOpacity={0.15} strokeWidth={1.5} name="RF (%)" isAnimationActive={false} />
                    <Area type="monotone" dataKey="w_xgb" stackId="1" stroke="#a855f7" fill="#a855f7" fillOpacity={0.15} strokeWidth={1.5} name="XGBoost (%)" isAnimationActive={false} />
                  </AreaChart>
                </ResponsiveContainer>
              </div>

              {/* Score demeaning chart */}
              <div className="h-[220px]">
                <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold mb-2">Score: Raw vs Demeaned</p>
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={ensembleData} margin={{ top: 5, right: 20, bottom: 5, left: 10 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke={COLORS.grid} />
                    <XAxis dataKey="date" tickFormatter={formatDate} tick={{ fontSize: 10, fill: COLORS.text }} interval="preserveStartEnd" />
                    <YAxis tick={{ fontSize: 10, fill: COLORS.text }} />
                    <RTooltip content={<CustomTooltip />} />
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                    <ReferenceLine y={0} stroke={COLORS.zero} strokeWidth={1.5} />
                    <Line type="monotone" dataKey="raw_score" stroke="#94a3b8" strokeWidth={1} strokeDasharray="4 3" dot={false} name="Raw Score" isAnimationActive={false} />
                    <Line type="monotone" dataKey="demeaned_score" stroke="#06b6d4" strokeWidth={2} dot={false} name="Demeaned Score" isAnimationActive={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}

          {/* Regime Probabilities */}
          {chartView === 'regime' && (
            <div className="space-y-4">
              {/* Two-level regime summary */}
              {(summary as any).regime_two_level && (
                <div className="grid grid-cols-2 gap-3">
                  <div className="bg-secondary/20 rounded-lg p-3 border border-emerald-500/10">
                    <p className="text-[10px] uppercase tracking-wider text-emerald-400 font-semibold mb-2">Global Regime</p>
                    <div className="grid grid-cols-3 gap-2">
                      <div>
                        <p className="text-[9px] text-muted-foreground">Carry</p>
                        <p className="text-sm font-data font-bold text-emerald-400">{(summary as any).regime_two_level.global_carry_pct}%</p>
                      </div>
                      <div>
                        <p className="text-[9px] text-muted-foreground">Risk-Off</p>
                        <p className="text-sm font-data font-bold text-amber-400">{(summary as any).regime_two_level.global_riskoff_pct}%</p>
                      </div>
                      <div>
                        <p className="text-[9px] text-muted-foreground">Stress</p>
                        <p className="text-sm font-data font-bold text-red-400">{(summary as any).regime_two_level.global_stress_pct}%</p>
                      </div>
                    </div>
                  </div>
                  <div className="bg-secondary/20 rounded-lg p-3 border border-amber-500/10">
                    <p className="text-[10px] uppercase tracking-wider text-amber-400 font-semibold mb-2">Domestic Regime</p>
                    <div className="grid grid-cols-2 gap-2">
                      <div>
                        <p className="text-[9px] text-muted-foreground">Calm</p>
                        <p className="text-sm font-data font-bold text-emerald-400">{(summary as any).regime_two_level.domestic_calm_pct}%</p>
                      </div>
                      <div>
                        <p className="text-[9px] text-muted-foreground">Stress</p>
                        <p className="text-sm font-data font-bold text-red-400">{(summary as any).regime_two_level.domestic_stress_pct}%</p>
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {/* Global regime probabilities chart */}
              <div className="h-[260px]">
                <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold mb-2">Probabilidades de Regime Global</p>
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={regimeData} margin={{ top: 5, right: 20, bottom: 5, left: 10 }}>
                    <defs>
                      <linearGradient id="carryGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#34d399" stopOpacity={0.4} />
                        <stop offset="95%" stopColor="#34d399" stopOpacity={0.05} />
                      </linearGradient>
                      <linearGradient id="riskoffGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#fbbf24" stopOpacity={0.4} />
                        <stop offset="95%" stopColor="#fbbf24" stopOpacity={0.05} />
                      </linearGradient>
                      <linearGradient id="stressGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#f43f5e" stopOpacity={0.4} />
                        <stop offset="95%" stopColor="#f43f5e" stopOpacity={0.05} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke={COLORS.grid} />
                    <XAxis dataKey="date" tickFormatter={formatDate} tick={{ fontSize: 10, fill: COLORS.text }} interval="preserveStartEnd" />
                    <YAxis tick={{ fontSize: 10, fill: COLORS.text }} tickFormatter={(v: number) => `${v.toFixed(0)}%`} domain={[0, 100]} />
                    <RTooltip content={<CustomTooltip />} />
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                    <Area type="monotone" dataKey="P_carry" stackId="1" stroke="#34d399" fill="url(#carryGrad)" strokeWidth={1.5} name="Carry (%)" isAnimationActive={false} />
                    <Area type="monotone" dataKey="P_riskoff" stackId="1" stroke="#fbbf24" fill="url(#riskoffGrad)" strokeWidth={1.5} name="Risk-Off (%)" isAnimationActive={false} />
                    <Area type="monotone" dataKey="P_stress" stackId="1" stroke="#f43f5e" fill="url(#stressGrad)" strokeWidth={1.5} name="Stress (%)" isAnimationActive={false} />
                  </AreaChart>
                </ResponsiveContainer>
              </div>

              {/* Domestic regime chart */}
              <div className="h-[200px]">
                <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold mb-2">Probabilidades de Regime Doméstico</p>
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={regimeData} margin={{ top: 5, right: 20, bottom: 5, left: 10 }}>
                    <defs>
                      <linearGradient id="domCalmGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#34d399" stopOpacity={0.4} />
                        <stop offset="95%" stopColor="#34d399" stopOpacity={0.05} />
                      </linearGradient>
                      <linearGradient id="domStressGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#f43f5e" stopOpacity={0.4} />
                        <stop offset="95%" stopColor="#f43f5e" stopOpacity={0.05} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke={COLORS.grid} />
                    <XAxis dataKey="date" tickFormatter={formatDate} tick={{ fontSize: 10, fill: COLORS.text }} interval="preserveStartEnd" />
                    <YAxis tick={{ fontSize: 10, fill: COLORS.text }} tickFormatter={(v: number) => `${v.toFixed(0)}%`} domain={[0, 100]} />
                    <RTooltip content={<CustomTooltip />} />
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                    <Area type="monotone" dataKey="P_domestic_calm" stackId="1" stroke="#34d399" fill="url(#domCalmGrad)" strokeWidth={1.5} name="Calm (%)" isAnimationActive={false} />
                    <Area type="monotone" dataKey="P_domestic_stress" stackId="1" stroke="#f43f5e" fill="url(#domStressGrad)" strokeWidth={1.5} name="Stress (%)" isAnimationActive={false} />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}

          {/* Rolling Sharpe 12m */}
          {chartView === 'rolling_sharpe' && (
            <div className="space-y-3">
              <div className="bg-secondary/20 rounded-lg p-3 border border-border/30">
                <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold mb-1">
                  Rolling Sharpe Ratio (12 meses)
                </p>
                <p className="text-[10px] text-muted-foreground/70">
                  Sharpe anualizado calculado sobre janela móvel de 12 meses do overlay return.
                  Valores acima de 1.0 indicam alpha consistente; abaixo de 0 indicam períodos de underperformance.
                </p>
              </div>
              <div className="h-[320px]">
                <ResponsiveContainer width="100%" height="100%">
                  <ComposedChart data={rollingSharpeData} margin={{ top: 5, right: 20, bottom: 5, left: 10 }}>
                    <defs>
                      <linearGradient id="sharpeGradPos" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#06b6d4" stopOpacity={0.25} />
                        <stop offset="95%" stopColor="#06b6d4" stopOpacity={0.02} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke={COLORS.grid} />
                    <XAxis dataKey="date" tickFormatter={formatDate} tick={{ fontSize: 10, fill: COLORS.text }} interval="preserveStartEnd" />
                    <YAxis tick={{ fontSize: 10, fill: COLORS.text }} tickFormatter={(v: number) => v.toFixed(1)} />
                    <RTooltip
                      content={({ active, payload, label }: any) => {
                        if (!active || !payload?.length) return null;
                        const val = payload[0]?.value;
                        return (
                          <div className="bg-card/95 backdrop-blur-sm border border-border rounded-lg px-3 py-2 shadow-xl">
                            <p className="text-xs text-muted-foreground mb-1 font-data">{label}</p>
                            <div className="flex items-center gap-2">
                              <span className="w-2 h-2 rounded-full" style={{ backgroundColor: val >= 0 ? '#06b6d4' : '#f43f5e' }} />
                              <span className="text-xs text-muted-foreground">Sharpe 12m:</span>
                              <span className={`text-xs font-data font-semibold ${val >= 1 ? 'text-emerald-400' : val >= 0 ? 'text-cyan-400' : 'text-red-400'}`}>
                                {typeof val === 'number' ? val.toFixed(2) : val}
                              </span>
                            </div>
                          </div>
                        );
                      }}
                    />
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                    <ReferenceLine y={0} stroke={COLORS.zero} strokeWidth={1.5} />
                    <ReferenceLine y={1} stroke="rgba(52,211,153,0.3)" strokeDasharray="6 3" label={{ value: 'Sharpe = 1.0', position: 'right', fill: 'rgba(52,211,153,0.5)', fontSize: 9 }} />
                    <ReferenceLine y={-1} stroke="rgba(244,63,94,0.3)" strokeDasharray="6 3" label={{ value: 'Sharpe = -1.0', position: 'right', fill: 'rgba(244,63,94,0.5)', fontSize: 9 }} />
                    <Area
                      type="monotone"
                      dataKey="sharpe_12m"
                      stroke="#06b6d4"
                      fill="url(#sharpeGradPos)"
                      strokeWidth={2}
                      dot={false}
                      name="Rolling Sharpe 12m"
                      connectNulls
                      isAnimationActive={false}
                    />
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
              {/* Summary stats */}
              {rollingSharpeData.length > 0 && (
                <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
                  <MetricCard
                    icon={Activity}
                    label="Média"
                    value={(rollingSharpeData.reduce((s, d) => s + d.sharpe_12m, 0) / rollingSharpeData.length).toFixed(2)}
                    color={rollingSharpeData.reduce((s, d) => s + d.sharpe_12m, 0) / rollingSharpeData.length >= 0 ? 'text-emerald-400' : 'text-red-400'}
                  />
                  <MetricCard
                    icon={TrendingUp}
                    label="Máximo"
                    value={Math.max(...rollingSharpeData.map(d => d.sharpe_12m)).toFixed(2)}
                    color="text-emerald-400"
                  />
                  <MetricCard
                    icon={TrendingDown}
                    label="Mínimo"
                    value={Math.min(...rollingSharpeData.map(d => d.sharpe_12m)).toFixed(2)}
                    color="text-red-400"
                  />
                  <MetricCard
                    icon={Percent}
                    label="% > 0"
                    value={((rollingSharpeData.filter(d => d.sharpe_12m > 0).length / rollingSharpeData.length) * 100).toFixed(0)}
                    suffix="%"
                    color="text-cyan-400"
                  />
                  <MetricCard
                    icon={Award}
                    label="% > 1.0"
                    value={((rollingSharpeData.filter(d => d.sharpe_12m > 1).length / rollingSharpeData.length) * 100).toFixed(0)}
                    suffix="%"
                    color="text-emerald-400"
                  />
                </div>
              )}
            </div>
          )}

          {/* Disclaimer */}
          <div className="text-[10px] text-muted-foreground/50 leading-relaxed border-t border-border/30 pt-3">
            <strong>Disclaimer:</strong> Backtest walk-forward out-of-sample. Custos de transação ({(summary.total_tc_pct ?? 0).toFixed(1)}% total) e turnover
            ({(summary.avg_monthly_turnover ?? 0).toFixed(2)}x/mês) incluídos. Resultados hipotéticos não representam performance real.
            Slippage e restrições de liquidez não estão totalmente modelados.
          </div>
        </CardContent>
      </Card>
    </motion.div>
  );
}
