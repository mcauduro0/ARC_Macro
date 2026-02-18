/**
 * SovereignRiskPanel — Sovereign Risk Dashboard
 *
 * CDS term structure, EMBI decomposition, rating migration probability,
 * and composite sovereign risk score.
 */

import { useMemo, useState } from 'react';
import { MacroDashboard } from '@/hooks/useModelData';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { Button } from '@/components/ui/button';
import { motion } from 'framer-motion';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  ResponsiveContainer, ReferenceLine, Bar, BarChart,
  Tooltip as RechartsTooltip, Cell
} from 'recharts';
import { Shield, Info, TrendingDown, TrendingUp, AlertTriangle } from 'lucide-react';

interface Props {
  dashboard: MacroDashboard;
}

/** Estimate CDS term structure from available data */
function estimateCDSCurve(dashboard: MacroDashboard) {
  const embi = dashboard.embi_spread;
  const eq = dashboard.equilibrium;
  const fiscalDecomp = eq?.fiscal_decomposition;

  // Base: EMBI spread as anchor for 5Y CDS
  const cds5y = Math.round(embi * 0.85); // CDS typically trades tighter than EMBI
  const fiscalPremium = fiscalDecomp ? (fiscalDecomp.fiscal + fiscalDecomp.sovereign) * 25 : 0;

  // Term structure shape based on credit quality
  // Investment grade: upward sloping. Distressed: inverted
  const isDistressed = cds5y > 300;
  const slope = isDistressed ? -0.15 : 0.12;

  return [
    { tenor: '6M', cds: Math.round(cds5y * (1 - slope * 4.5)), label: '6M' },
    { tenor: '1Y', cds: Math.round(cds5y * (1 - slope * 4)), label: '1Y' },
    { tenor: '2Y', cds: Math.round(cds5y * (1 - slope * 3)), label: '2Y' },
    { tenor: '3Y', cds: Math.round(cds5y * (1 - slope * 2)), label: '3Y' },
    { tenor: '5Y', cds: cds5y, label: '5Y' },
    { tenor: '7Y', cds: Math.round(cds5y * (1 + slope * 2)), label: '7Y' },
    { tenor: '10Y', cds: Math.round(cds5y * (1 + slope * 5)), label: '10Y' },
  ];
}

/** Decompose EMBI spread into components */
function decomposeEMBI(dashboard: MacroDashboard) {
  const embi = dashboard.embi_spread;
  const eq = dashboard.equilibrium;
  const fiscalDecomp = eq?.fiscal_decomposition;

  // Decomposition: sovereign credit + fiscal premium + liquidity + external
  const sovereignBase = Math.round(embi * 0.35); // Pure sovereign credit
  const fiscalPremiumPct = fiscalDecomp ? Math.round((fiscalDecomp.fiscal / (fiscalDecomp.base + fiscalDecomp.fiscal + fiscalDecomp.sovereign)) * embi) : Math.round(embi * 0.25);
  const externalPremium = Math.round(embi * 0.20); // Global risk-off / EM contagion
  const liquidityPremium = embi - sovereignBase - fiscalPremiumPct - externalPremium;

  return [
    { component: 'Crédito Soberano', value: sovereignBase, pct: Math.round(sovereignBase / embi * 100), color: '#3b82f6' },
    { component: 'Prêmio Fiscal', value: fiscalPremiumPct, pct: Math.round(fiscalPremiumPct / embi * 100), color: '#f59e0b' },
    { component: 'Risco Externo', value: externalPremium, pct: Math.round(externalPremium / embi * 100), color: '#ef4444' },
    { component: 'Liquidez', value: liquidityPremium, pct: Math.round(liquidityPremium / embi * 100), color: '#8b5cf6' },
  ];
}

/** Calculate rating migration probabilities based on fiscal fundamentals */
function calculateRatingMigration(dashboard: MacroDashboard) {
  const eq = dashboard.equilibrium;
  const embi = dashboard.embi_spread;
  const rstar = eq?.composite_rstar || 4.75;
  const fiscalDecomp = eq?.fiscal_decomposition;

  // Current implied rating based on EMBI spread
  // BB: 150-250, BB+: 100-150, BBB-: 70-100, BBB: 50-70
  let currentRating = 'BB';
  if (embi < 80) currentRating = 'BBB-';
  else if (embi < 120) currentRating = 'BB+';
  else if (embi < 200) currentRating = 'BB';
  else if (embi < 350) currentRating = 'BB-';
  else currentRating = 'B+';

  // Fiscal stress indicator (0-1)
  const fiscalStress = Math.min(1, Math.max(0,
    (rstar - 3) / 6 * 0.4 +
    (embi - 100) / 300 * 0.3 +
    ((fiscalDecomp?.fiscal || 2) / 4) * 0.3
  ));

  // Migration probabilities (1Y horizon)
  const upgradeProb = Math.max(2, Math.round((1 - fiscalStress) * 25));
  const stableProb = Math.round(60 + (1 - fiscalStress) * 15);
  const downgrade1Prob = Math.round(fiscalStress * 20);
  const downgrade2Prob = Math.max(1, Math.round(fiscalStress * 8));
  const defaultProb = Math.max(0.1, Math.round(fiscalStress * 3 * 10) / 10);

  // Normalize to 100
  const total = upgradeProb + stableProb + downgrade1Prob + downgrade2Prob + defaultProb;
  const scale = 100 / total;

  return {
    currentRating,
    fiscalStress: Math.round(fiscalStress * 100),
    transitions: [
      { label: 'Upgrade', prob: Math.round(upgradeProb * scale * 10) / 10, color: '#10b981' },
      { label: 'Estável', prob: Math.round(stableProb * scale * 10) / 10, color: '#3b82f6' },
      { label: 'Down 1 notch', prob: Math.round(downgrade1Prob * scale * 10) / 10, color: '#f59e0b' },
      { label: 'Down 2 notch', prob: Math.round(downgrade2Prob * scale * 10) / 10, color: '#ef4444' },
      { label: 'Default', prob: Math.round(defaultProb * scale * 100) / 100, color: '#991b1b' },
    ],
  };
}

/** Calculate composite sovereign risk score (0-100) */
function calculateSovereignScore(dashboard: MacroDashboard) {
  const embi = dashboard.embi_spread;
  const eq = dashboard.equilibrium;
  const rstar = eq?.composite_rstar || 4.75;
  const vix = dashboard.vix;

  // Components (each 0-25)
  const embiScore = Math.min(25, Math.max(0, (embi - 50) / 400 * 25));
  const rstarScore = Math.min(25, Math.max(0, (rstar - 2) / 8 * 25));
  const vixScore = Math.min(25, Math.max(0, (vix - 12) / 40 * 25));
  const fiscalScore = eq?.fiscal_decomposition
    ? Math.min(25, Math.max(0, (eq.fiscal_decomposition.fiscal / 4) * 25))
    : 12.5;

  const total = Math.round(embiScore + rstarScore + vixScore + fiscalScore);

  return {
    total,
    components: [
      { label: 'EMBI Spread', score: Math.round(embiScore), max: 25 },
      { label: 'r* Composto', score: Math.round(rstarScore), max: 25 },
      { label: 'VIX / Global', score: Math.round(vixScore), max: 25 },
      { label: 'Prêmio Fiscal', score: Math.round(fiscalScore), max: 25 },
    ],
    classification: total < 25 ? 'Baixo' : total < 45 ? 'Moderado' : total < 65 ? 'Elevado' : 'Crítico',
    classColor: total < 25 ? 'text-emerald-400' : total < 45 ? 'text-blue-400' : total < 65 ? 'text-amber-400' : 'text-rose-400',
  };
}

export function SovereignRiskPanel({ dashboard }: Props) {
  const [view, setView] = useState<'overview' | 'cds' | 'embi' | 'rating'>('overview');

  const cdsCurve = useMemo(() => estimateCDSCurve(dashboard), [dashboard]);
  const embiDecomp = useMemo(() => decomposeEMBI(dashboard), [dashboard]);
  const ratingMigration = useMemo(() => calculateRatingMigration(dashboard), [dashboard]);
  const sovereignScore = useMemo(() => calculateSovereignScore(dashboard), [dashboard]);

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: 0.25 }}
    >
      <Card className="bg-card border-border/50">
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <CardTitle className="text-xs font-semibold uppercase tracking-wider text-primary flex items-center gap-2">
              <Shield className="w-3.5 h-3.5" />
              Dashboard de Risco Soberano
              <Tooltip>
                <TooltipTrigger>
                  <Info className="w-3 h-3 text-muted-foreground/50" />
                </TooltipTrigger>
                <TooltipContent side="right" className="max-w-[320px] text-xs">
                  Painel integrado de risco soberano: CDS term structure, decomposição EMBI,
                  probabilidade de migração de rating, e score composto de risco.
                  Estimativas baseadas em EMBI, r* composto, e decomposição fiscal.
                </TooltipContent>
              </Tooltip>
            </CardTitle>
            <div className="flex gap-1">
              {(['overview', 'cds', 'embi', 'rating'] as const).map(v => (
                <Button
                  key={v}
                  variant={view === v ? 'default' : 'ghost'}
                  size="sm"
                  onClick={() => setView(v)}
                  className="h-6 text-[9px] px-2"
                >
                  {v === 'overview' ? 'Score' : v === 'cds' ? 'CDS Curve' : v === 'embi' ? 'EMBI' : 'Rating'}
                </Button>
              ))}
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {/* Overview: Sovereign Risk Score */}
          {view === 'overview' && (
            <div className="space-y-4">
              {/* Score Headline */}
              <div className="flex items-center justify-between bg-secondary/30 rounded-lg p-4 border border-border/20">
                <div>
                  <div className="text-[9px] text-muted-foreground uppercase tracking-wider">Sovereign Risk Score</div>
                  <div className="flex items-baseline gap-3 mt-1">
                    <span className={`font-data text-3xl font-bold ${sovereignScore.classColor}`}>
                      {sovereignScore.total}
                    </span>
                    <span className="text-lg text-muted-foreground">/100</span>
                    <span className={`text-xs font-semibold px-2 py-0.5 rounded-full border ${
                      sovereignScore.total < 25 ? 'bg-emerald-400/10 border-emerald-400/30 text-emerald-400' :
                      sovereignScore.total < 45 ? 'bg-blue-400/10 border-blue-400/30 text-blue-400' :
                      sovereignScore.total < 65 ? 'bg-amber-400/10 border-amber-400/30 text-amber-400' :
                      'bg-rose-400/10 border-rose-400/30 text-rose-400'
                    }`}>
                      {sovereignScore.classification}
                    </span>
                  </div>
                </div>
                <div className="text-right">
                  <div className="text-[9px] text-muted-foreground">Rating Implícito</div>
                  <div className="font-data text-2xl font-bold text-foreground">{ratingMigration.currentRating}</div>
                  <div className="text-[9px] text-muted-foreground">EMBI {dashboard.embi_spread}bps</div>
                </div>
              </div>

              {/* Score Components */}
              <div className="grid grid-cols-4 gap-3">
                {sovereignScore.components.map(c => (
                  <div key={c.label} className="text-center">
                    <div className="text-[9px] text-muted-foreground">{c.label}</div>
                    <div className="font-data text-sm font-bold text-foreground mt-0.5">{c.score}/{c.max}</div>
                    <div className="mt-1 h-2 bg-secondary/50 rounded-full overflow-hidden">
                      <div
                        className={`h-full rounded-full transition-all ${
                          c.score / c.max < 0.4 ? 'bg-emerald-400/60' :
                          c.score / c.max < 0.6 ? 'bg-blue-400/60' :
                          c.score / c.max < 0.8 ? 'bg-amber-400/60' :
                          'bg-rose-400/60'
                        }`}
                        style={{ width: `${(c.score / c.max) * 100}%` }}
                      />
                    </div>
                  </div>
                ))}
              </div>

              {/* Quick Stats */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                {[
                  { label: 'CDS 5Y (est.)', value: `${cdsCurve[4].cds}bps`, color: 'text-foreground' },
                  { label: 'EMBI Spread', value: `${dashboard.embi_spread}bps`, color: 'text-foreground' },
                  { label: 'Fiscal Stress', value: `${ratingMigration.fiscalStress}%`, color: ratingMigration.fiscalStress > 50 ? 'text-amber-400' : 'text-emerald-400' },
                  { label: 'P(Downgrade)', value: `${(ratingMigration.transitions[2].prob + ratingMigration.transitions[3].prob).toFixed(1)}%`, color: 'text-rose-400' },
                ].map(s => (
                  <Card key={s.label} className="bg-secondary/20 border-border/20">
                    <CardContent className="pt-2 pb-2 px-3">
                      <div className="text-[9px] text-muted-foreground">{s.label}</div>
                      <div className={`font-data text-sm font-bold ${s.color}`}>{s.value}</div>
                    </CardContent>
                  </Card>
                ))}
              </div>
            </div>
          )}

          {/* CDS Term Structure */}
          {view === 'cds' && (
            <div className="space-y-3">
              <div className="text-[10px] text-muted-foreground">
                Estrutura a termo de CDS estimada a partir do EMBI spread ({dashboard.embi_spread}bps) e decomposição fiscal.
                Curva {cdsCurve[0].cds < cdsCurve[6].cds ? 'normal (upward sloping)' : 'invertida (distressed)'}.
              </div>
              <div className="h-[250px]">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={cdsCurve} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" opacity={0.3} />
                    <XAxis
                      dataKey="label"
                      tick={{ fontSize: 10, fill: 'hsl(var(--muted-foreground))' }}
                    />
                    <YAxis
                      tick={{ fontSize: 9, fill: 'hsl(var(--muted-foreground))' }}
                      tickFormatter={v => `${v}bps`}
                    />
                    <RechartsTooltip
                      contentStyle={{
                        backgroundColor: 'hsl(var(--card))',
                        border: '1px solid hsl(var(--border))',
                        borderRadius: '6px',
                        fontSize: '10px',
                      }}
                      formatter={(value: number) => [`${value}bps`, 'CDS Spread']}
                    />
                    <Bar dataKey="cds" radius={[4, 4, 0, 0]}>
                      {cdsCurve.map((entry, idx) => (
                        <Cell
                          key={idx}
                          fill={entry.cds > 200 ? '#ef4444' : entry.cds > 120 ? '#f59e0b' : '#3b82f6'}
                          fillOpacity={0.7}
                        />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}

          {/* EMBI Decomposition */}
          {view === 'embi' && (
            <div className="space-y-4">
              <div className="text-[10px] text-muted-foreground">
                Decomposição do EMBI spread ({dashboard.embi_spread}bps) em componentes de risco.
              </div>

              {/* Stacked bar visualization */}
              <div className="bg-secondary/30 rounded-lg p-4 border border-border/20">
                <div className="flex h-8 rounded-full overflow-hidden">
                  {embiDecomp.map(c => (
                    <Tooltip key={c.component}>
                      <TooltipTrigger asChild>
                        <div
                          className="h-full transition-all hover:opacity-80 cursor-pointer"
                          style={{ width: `${c.pct}%`, backgroundColor: c.color }}
                        />
                      </TooltipTrigger>
                      <TooltipContent className="text-xs">
                        {c.component}: {c.value}bps ({c.pct}%)
                      </TooltipContent>
                    </Tooltip>
                  ))}
                </div>
              </div>

              {/* Component cards */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                {embiDecomp.map(c => (
                  <Card key={c.component} className="bg-secondary/20 border-border/20">
                    <CardContent className="pt-3 pb-3 px-4">
                      <div className="flex items-center gap-2">
                        <div className="w-2 h-2 rounded-full" style={{ backgroundColor: c.color }} />
                        <div className="text-[9px] text-muted-foreground">{c.component}</div>
                      </div>
                      <div className="flex items-baseline gap-2 mt-1">
                        <span className="font-data text-lg font-bold text-foreground">{c.value}</span>
                        <span className="text-[10px] text-muted-foreground">bps</span>
                        <span className="text-[10px] text-muted-foreground/60">({c.pct}%)</span>
                      </div>
                    </CardContent>
                  </Card>
                ))}
              </div>
            </div>
          )}

          {/* Rating Migration */}
          {view === 'rating' && (
            <div className="space-y-4">
              <div className="flex items-center justify-between bg-secondary/30 rounded-lg p-3 border border-border/20">
                <div>
                  <div className="text-[9px] text-muted-foreground">Rating Atual (Implícito)</div>
                  <div className="font-data text-2xl font-bold text-foreground">{ratingMigration.currentRating}</div>
                </div>
                <div className="text-right">
                  <div className="text-[9px] text-muted-foreground">Fiscal Stress Index</div>
                  <div className={`font-data text-2xl font-bold ${
                    ratingMigration.fiscalStress < 30 ? 'text-emerald-400' :
                    ratingMigration.fiscalStress < 50 ? 'text-blue-400' :
                    ratingMigration.fiscalStress < 70 ? 'text-amber-400' :
                    'text-rose-400'
                  }`}>{ratingMigration.fiscalStress}%</div>
                </div>
              </div>

              <div className="text-[10px] text-muted-foreground">
                Probabilidade de migração de rating (horizonte 1 ano) baseada em r* composto, EMBI, e decomposição fiscal.
              </div>

              {/* Migration probability bars */}
              <div className="space-y-2">
                {ratingMigration.transitions.map(t => (
                  <div key={t.label} className="flex items-center gap-3">
                    <div className="w-24 text-[10px] text-muted-foreground text-right">{t.label}</div>
                    <div className="flex-1 h-6 bg-secondary/30 rounded-full overflow-hidden relative">
                      <motion.div
                        className="h-full rounded-full"
                        style={{ backgroundColor: t.color }}
                        initial={{ width: 0 }}
                        animate={{ width: `${Math.max(2, t.prob)}%` }}
                        transition={{ duration: 0.6, delay: 0.1 }}
                      />
                      <span className="absolute inset-0 flex items-center justify-center text-[9px] font-data font-semibold text-foreground">
                        {t.prob.toFixed(1)}%
                      </span>
                    </div>
                  </div>
                ))}
              </div>

              {/* Interpretation */}
              <div className="bg-secondary/20 rounded-lg p-3 border border-border/10 text-[10px] text-muted-foreground">
                <div className="flex items-start gap-2">
                  <AlertTriangle className="w-3.5 h-3.5 text-amber-400 mt-0.5 flex-shrink-0" />
                  <div>
                    Probabilidade combinada de downgrade (1-2 notches):
                    <span className="font-data font-semibold text-amber-400 ml-1">
                      {(ratingMigration.transitions[2].prob + ratingMigration.transitions[3].prob).toFixed(1)}%
                    </span>
                    . Probabilidade de upgrade:
                    <span className="font-data font-semibold text-emerald-400 ml-1">
                      {ratingMigration.transitions[0].prob.toFixed(1)}%
                    </span>
                    . Risco de default (1Y):
                    <span className="font-data font-semibold text-rose-400 ml-1">
                      {ratingMigration.transitions[4].prob.toFixed(2)}%
                    </span>
                  </div>
                </div>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </motion.div>
  );
}
