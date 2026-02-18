/**
 * MobileOverviewTab — Hero health gauge + key metrics grid + quick overview
 * Touch-optimized cards with 44px minimum tap targets
 */

import { useMemo } from 'react';
import { motion } from 'framer-motion';
import { Card, CardContent } from '@/components/ui/card';
import {
  TrendingUp,
  TrendingDown,
  Minus,
  Activity,
  Shield,
  Zap,
  AlertTriangle,
  Target,
  BarChart3,
  Gauge,
  ArrowUpRight,
  ArrowDownRight,
  Percent,
  DollarSign,
} from 'lucide-react';
import type { MacroDashboard, AssetPosition } from '@/hooks/useModelData';

interface Props {
  dashboard: MacroDashboard;
}

// ── Health Score Gauge (circular) ──────────────────────────────────────────

function HealthGauge({ data }: { data: Record<string, any> | null | undefined }) {
  const score = useMemo(() => {
    if (!data) return 0;
    const instruments = Object.entries(data).filter(([k]) => !['summary', 'temporal'].includes(k));
    if (instruments.length === 0) return 0;

    let totalRobust = 0, totalModerate = 0, totalUnstable = 0;
    let totalAlertsCritical = 0, totalAlertsWarning = 0, totalAlertsPositive = 0;

    for (const [, inst] of instruments) {
      const cls = inst?.stability?.classification || {};
      for (const status of Object.values(cls)) {
        if (status === 'robust') totalRobust++;
        else if (status === 'moderate') totalModerate++;
        else totalUnstable++;
      }
      const alerts = inst?.alerts || [];
      for (const a of alerts) {
        if (a.type === 'critical') totalAlertsCritical++;
        else if (a.type === 'warning') totalAlertsWarning++;
        else totalAlertsPositive++;
      }
    }

    const total = totalRobust + totalModerate + totalUnstable;
    if (total === 0) return 50;

    const stabilityScore = (totalRobust / total) * 100 + (totalModerate / total) * 60 + (totalUnstable / total) * 20;
    const alertScore = Math.max(0, Math.min(100, 80 - totalAlertsCritical * 15 - totalAlertsWarning * 5 + totalAlertsPositive * 3));

    return Math.round(stabilityScore * 0.55 + alertScore * 0.45);
  }, [data]);

  const circumference = 2 * Math.PI * 52;
  const offset = circumference - (score / 100) * circumference;
  const color = score >= 75 ? '#34d399' : score >= 55 ? '#22d3ee' : score >= 35 ? '#fbbf24' : '#f87171';

  return (
    <motion.div
      initial={{ scale: 0.9, opacity: 0 }}
      animate={{ scale: 1, opacity: 1 }}
      className="relative flex items-center justify-center"
    >
      <svg width="130" height="130" viewBox="0 0 120 120">
        <circle cx="60" cy="60" r="52" fill="none" stroke="currentColor" strokeWidth="6" className="text-secondary" />
        <motion.circle
          cx="60" cy="60" r="52"
          fill="none"
          stroke={color}
          strokeWidth="6"
          strokeLinecap="round"
          strokeDasharray={circumference}
          initial={{ strokeDashoffset: circumference }}
          animate={{ strokeDashoffset: offset }}
          transition={{ duration: 1.2, ease: 'easeOut' }}
          transform="rotate(-90 60 60)"
          style={{ filter: `drop-shadow(0 0 6px ${color}40)` }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="font-data text-3xl font-bold" style={{ color }}>{score}</span>
        <span className="text-[10px] text-muted-foreground uppercase tracking-wider">Health</span>
      </div>
    </motion.div>
  );
}

// ── Metric Card ────────────────────────────────────────────────────────────

function MetricCard({
  label,
  value,
  unit,
  icon: Icon,
  color,
  delay = 0,
}: {
  label: string;
  value: string | number;
  unit?: string;
  icon: typeof Activity;
  color: string;
  delay?: number;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay, duration: 0.3 }}
    >
      <Card className="bg-card/80 border-border/50">
        <CardContent className="p-3">
          <div className="flex items-center gap-2 mb-1.5">
            <div className={`w-7 h-7 rounded-lg flex items-center justify-center ${color}`}>
              <Icon className="w-3.5 h-3.5" />
            </div>
            <span className="text-[10px] text-muted-foreground uppercase tracking-wider leading-tight">
              {label}
            </span>
          </div>
          <div className="font-data text-lg font-bold text-foreground">
            {value}
            {unit && <span className="text-xs text-muted-foreground ml-0.5">{unit}</span>}
          </div>
        </CardContent>
      </Card>
    </motion.div>
  );
}

// ── Instrument Row ─────────────────────────────────────────────────────────

function InstrumentRow({
  name,
  score,
  direction,
  delay = 0,
}: {
  name: string;
  score: number;
  direction: string;
  delay?: number;
}) {
  const isPositive = score > 0;
  const color = isPositive ? 'text-emerald-400' : score < 0 ? 'text-rose-400' : 'text-amber-400';
  const bg = isPositive ? 'bg-emerald-400/10' : score < 0 ? 'bg-rose-400/10' : 'bg-amber-400/10';

  return (
    <motion.div
      initial={{ opacity: 0, x: -10 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ delay, duration: 0.25 }}
      className="flex items-center justify-between py-2.5 px-3 rounded-lg bg-card/50 border border-border/30"
    >
      <div className="flex items-center gap-2.5">
        <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${bg}`}>
          {isPositive ? (
            <ArrowUpRight className={`w-4 h-4 ${color}`} />
          ) : score < 0 ? (
            <ArrowDownRight className={`w-4 h-4 ${color}`} />
          ) : (
            <Minus className={`w-4 h-4 ${color}`} />
          )}
        </div>
        <div>
          <span className="text-xs font-medium text-foreground">{name}</span>
          <p className="text-[10px] text-muted-foreground capitalize">{direction}</p>
        </div>
      </div>
      <span className={`font-data text-sm font-bold ${color}`}>
        {score > 0 ? '+' : ''}{score.toFixed(2)}
      </span>
    </motion.div>
  );
}

// ── Main Component ─────────────────────────────────────────────────────────

export function MobileOverviewTab({ dashboard }: Props) {
  const d = dashboard;
  const positions = d.positions || {} as any;

  const instrumentList = useMemo(() => {
    const list: { name: string; score: number; direction: string }[] = [];
    const nameMap: Record<string, string> = {
      fx: 'DOL Futuro (Câmbio)',
      front: 'DI Front (1Y)',
      belly: 'DI Belly (2-5Y)',
      long: 'DI Long (10Y)',
      hard: 'Cupom Cambial (DDI)',
      ntnb: 'NTN-B (Cupom de Inflação)',
    };
    for (const [key, pos] of Object.entries(positions)) {
      if (pos && typeof pos === 'object') {
        list.push({
          name: nameMap[key] || key,
          score: (pos as AssetPosition).expected_return_3m || 0,
          direction: (pos as AssetPosition).direction || 'neutral',
        });
      }
    }
    if (list.length === 0) {
      list.push({ name: 'DOL Futuro (Câmbio)', score: d.score_total || 0, direction: d.direction || 'neutral' });
    }
    return list;
  }, [positions, d]);

  return (
    <div className="px-4 py-4 space-y-4">
      {/* Hero: Health Gauge + Score */}
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        className="flex items-center justify-between"
      >
        <div className="flex-1">
          <h2 className="text-lg font-semibold text-foreground mb-1">ARC Macro</h2>
          <p className="text-xs text-muted-foreground mb-3">
            Dashboard consolidado do modelo
          </p>
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <span className="text-[10px] text-muted-foreground uppercase w-16">Score</span>
              <span className={`font-data text-xl font-bold ${
                (d.score_total || 0) > 0 ? 'text-emerald-400' : (d.score_total || 0) < 0 ? 'text-rose-400' : 'text-amber-400'
              }`}>
                {d.score_total != null ? ((d.score_total > 0 ? '+' : '') + d.score_total.toFixed(2)) : '--'}
              </span>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-[10px] text-muted-foreground uppercase w-16">Sinal</span>
              <span className={`text-xs font-semibold uppercase ${
                d.direction?.includes('LONG') && d.direction?.includes('BRL') ? 'text-emerald-400' :
                d.direction?.includes('SHORT') && d.direction?.includes('BRL') ? 'text-rose-400' : 'text-amber-400'
              }`}>
                {d.direction || 'NEUTRAL'}
              </span>
            </div>
          </div>
        </div>
        <HealthGauge data={d.feature_selection} />
      </motion.div>

      {/* Key Metrics Grid — 2x2 */}
      <div className="grid grid-cols-2 gap-2.5">
        <MetricCard
          label="Equilíbrio r*"
          value={d.equilibrium?.composite_rstar?.toFixed(2) || d.selic_star?.toFixed(2) || '--'}
          unit="%"
          icon={Target}
          color="bg-cyan-400/10 text-cyan-400"
          delay={0.1}
        />
        <MetricCard
          label="Misalignment"
          value={d.fx_misalignment?.toFixed(1) || d.beer_misalignment_pct?.toFixed(1) || '--'}
          unit="%"
          icon={Gauge}
          color="bg-amber-400/10 text-amber-400"
          delay={0.15}
        />
        <MetricCard
          label="Carry (1M)"
          value={d.positions?.fx?.expected_return_3m?.toFixed(2) || '--'}
          unit="%"
          icon={DollarSign}
          color="bg-emerald-400/10 text-emerald-400"
          delay={0.2}
        />
        <MetricCard
          label="VIX"
          value={d.vix?.toFixed(1) ?? '--'}
          icon={Activity}
          color="bg-rose-400/10 text-rose-400"
          delay={0.25}
        />
      </div>

      {/* Instruments List */}
      <div>
        <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2.5 px-1">
          Instrumentos
        </h3>
        <div className="space-y-2">
          {instrumentList.map((inst, i) => (
            <InstrumentRow
              key={inst.name}
              name={inst.name}
              score={inst.score}
              direction={inst.direction}
              delay={0.1 + i * 0.05}
            />
          ))}
        </div>
      </div>

      {/* Regime Card */}
      <Card className="bg-card/80 border-border/50 overflow-hidden">
        <CardContent className="p-3">
          <div className="flex items-center justify-between mb-2">
            <span className="text-[10px] text-muted-foreground uppercase tracking-wider">Regime Atual</span>
            <div className={`flex items-center gap-1 px-2 py-0.5 rounded-full border text-[10px] font-semibold ${
              (d.current_regime || d.dominant_regime) === 'Carry' ? 'text-emerald-400 bg-emerald-400/10 border-emerald-400/30' :
              (d.current_regime || d.dominant_regime) === 'RiskOff' ? 'text-rose-400 bg-rose-400/10 border-rose-400/30' :
              (d.current_regime || d.dominant_regime) === 'StressDom' ? 'text-amber-400 bg-amber-400/10 border-amber-400/30' :
              'text-cyan-400 bg-cyan-400/10 border-cyan-400/30'
            }`}>
              {getRegimeIcon(d.current_regime || d.dominant_regime || '')}
              <span className="uppercase">{d.current_regime || d.dominant_regime || 'N/A'}</span>
            </div>
          </div>
          {/* Regime probability bars */}
          {d.regime_probs && (
            <div className="space-y-1.5 mt-2">
              {Object.entries(d.regime_probs).map(([regime, prob]) => (
                <div key={regime} className="flex items-center gap-2">
                  <span className="text-[10px] text-muted-foreground w-20 truncate">{regime}</span>
                  <div className="flex-1 h-1.5 bg-secondary rounded-full overflow-hidden">
                    <motion.div
                      initial={{ width: 0 }}
                      animate={{ width: `${((prob as number) * 100)}%` }}
                      transition={{ duration: 0.8, delay: 0.3 }}
                      className={`h-full rounded-full ${
                        regime === 'Carry' ? 'bg-emerald-400' :
                        regime === 'RiskOff' ? 'bg-rose-400' :
                        regime === 'StressDom' ? 'bg-amber-400' : 'bg-cyan-400'
                      }`}
                    />
                  </div>
                  <span className="font-data text-[10px] text-foreground w-8 text-right">
                    {((prob as number) * 100).toFixed(0)}%
                  </span>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function getRegimeIcon(regime: string) {
  if (regime === 'Carry') return <Zap className="w-3 h-3" />;
  if (regime === 'RiskOff') return <Shield className="w-3 h-3" />;
  if (regime === 'StressDom') return <AlertTriangle className="w-3 h-3" />;
  return <Activity className="w-3 h-3" />;
}
