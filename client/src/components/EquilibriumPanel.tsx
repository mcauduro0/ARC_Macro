/**
 * EquilibriumPanel — Composite Equilibrium Rate (r*) Breakdown
 * 
 * Displays the 5-model composite real neutral rate with:
 * - Composite r* headline with SELIC* derived from it
 * - Individual model contributions (Fiscal, Parity, Market-Implied, State-Space, Regime)
 * - Regime-dependent weight allocation visualization
 * - Fiscal decomposition (base + fiscal + sovereign)
 * - ACM term premium
 */

import { MacroDashboard, EquilibriumData } from '@/hooks/useModelData';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { motion } from 'framer-motion';
import { Info, Target, TrendingUp, Layers, Scale, Activity } from 'lucide-react';

interface Props {
  dashboard: MacroDashboard;
}

/** Model display metadata */
const MODEL_META: Record<string, { label: string; description: string; color: string; icon: typeof Target }> = {
  fiscal: {
    label: 'Fiscal r*',
    description: 'Fiscal-Augmented r*: base rate + debt/GDP premium + CDS sovereign risk',
    color: 'text-amber-400',
    icon: Scale,
  },
  parity: {
    label: 'Parity r*',
    description: 'Real Rate Parity: US TIPS + country risk premium (CDS + EMBI)',
    color: 'text-blue-400',
    icon: Layers,
  },
  market_implied: {
    label: 'Market-Implied r*',
    description: 'ACM-style term structure decomposition of the DI curve',
    color: 'text-cyan-400',
    icon: TrendingUp,
  },
  state_space: {
    label: 'State-Space r*',
    description: 'Kalman filter with fiscal and external channels',
    color: 'text-purple-400',
    icon: Activity,
  },
  regime: {
    label: 'Regime r*',
    description: 'Regime-conditional r* from HMM state probabilities',
    color: 'text-emerald-400',
    icon: Target,
  },
};

function ModelBar({ name, weight, value, compositeRstar }: {
  name: string;
  weight: number;
  value: number;
  compositeRstar: number;
}) {
  const meta = MODEL_META[name] || { label: name, description: '', color: 'text-foreground', icon: Target };
  const Icon = meta.icon;
  const weightPct = (weight * 100).toFixed(1);
  const contribution = weight * value;

  // Color the value based on whether it's above or below composite
  const valueColor = value > compositeRstar + 0.5 ? 'text-amber-400' : value < compositeRstar - 0.5 ? 'text-cyan-400' : 'text-foreground';

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Icon className={`w-3.5 h-3.5 ${meta.color}`} />
          <Tooltip>
            <TooltipTrigger>
              <span className="text-[10px] text-muted-foreground uppercase tracking-wider cursor-help">
                {meta.label}
              </span>
            </TooltipTrigger>
            <TooltipContent side="right" className="max-w-[280px] text-xs">
              {meta.description}
            </TooltipContent>
          </Tooltip>
        </div>
        <div className="flex items-center gap-3">
          <span className={`font-data text-xs font-semibold ${valueColor}`}>
            {value.toFixed(2)}%
          </span>
          <span className="font-data text-[10px] text-muted-foreground w-12 text-right">
            w={weightPct}%
          </span>
        </div>
      </div>
      {/* Weight bar */}
      <div className="relative h-1.5 bg-secondary rounded-full overflow-hidden">
        <motion.div
          initial={{ width: 0 }}
          animate={{ width: `${Math.min(weight * 100, 100)}%` }}
          transition={{ duration: 0.8, ease: 'easeOut' }}
          className={`absolute inset-y-0 left-0 rounded-full opacity-70`}
          style={{ backgroundColor: `var(--chart-${Object.keys(MODEL_META).indexOf(name) % 5 + 1})` }}
        />
      </div>
      <div className="text-[9px] text-muted-foreground/60 text-right">
        contribution: {contribution.toFixed(2)}%
      </div>
    </div>
  );
}

function FiscalDecomp({ decomp }: { decomp: { base: number; fiscal: number; sovereign: number } }) {
  const total = decomp.base + decomp.fiscal + decomp.sovereign;
  const segments = [
    { label: 'Base', value: decomp.base, color: 'bg-slate-500', pct: (decomp.base / total) * 100 },
    { label: 'Fiscal', value: decomp.fiscal, color: 'bg-amber-500', pct: (decomp.fiscal / total) * 100 },
    { label: 'Sovereign', value: decomp.sovereign, color: decomp.sovereign >= 0 ? 'bg-rose-500' : 'bg-emerald-500', pct: (Math.abs(decomp.sovereign) / total) * 100 },
  ];

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-1.5">
        <span className="text-[10px] text-muted-foreground uppercase tracking-wider">Fiscal Decomposition</span>
        <Tooltip>
          <TooltipTrigger>
            <Info className="w-3 h-3 text-muted-foreground/50" />
          </TooltipTrigger>
          <TooltipContent side="right" className="max-w-[260px] text-xs">
            Fiscal r* = Base (4%) + Debt/GDP premium + Sovereign CDS risk
          </TooltipContent>
        </Tooltip>
      </div>
      {/* Stacked bar */}
      <div className="flex h-2 rounded-full overflow-hidden">
        {segments.map((seg) => (
          <motion.div
            key={seg.label}
            initial={{ width: 0 }}
            animate={{ width: `${seg.pct}%` }}
            transition={{ duration: 0.8 }}
            className={`${seg.color} opacity-80`}
          />
        ))}
      </div>
      <div className="flex items-center justify-between text-[10px]">
        {segments.map((seg) => (
          <div key={seg.label} className="flex items-center gap-1">
            <span className={`w-2 h-2 rounded-sm ${seg.color}`} />
            <span className="text-muted-foreground">{seg.label}</span>
            <span className="font-data font-semibold text-foreground">
              {seg.value >= 0 ? '+' : ''}{seg.value.toFixed(2)}%
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

export function EquilibriumPanel({ dashboard: d }: Props) {
  const eq = d.equilibrium;
  if (!eq || eq.composite_rstar == null) return null;

  const compositeRstar = eq.composite_rstar;
  const selicStar = eq.selic_star ?? d.selic_star ?? null;
  const taylorGap = d.taylor_gap;
  const selicTarget = d.selic_target;

  // Sort models by weight descending
  const models = Object.entries(eq.model_contributions || {})
    .sort(([, a], [, b]) => b.weight - a.weight);

  // Determine if r* is restrictive or accommodative relative to historical
  const rstarSignal = compositeRstar > 5.5 ? 'restrictive' : compositeRstar < 3.5 ? 'accommodative' : 'neutral';
  const rstarColor = rstarSignal === 'restrictive' ? 'text-amber-400' : rstarSignal === 'accommodative' ? 'text-emerald-400' : 'text-cyan-400';
  const rstarGlow = rstarSignal === 'restrictive' ? 'glow-red' : rstarSignal === 'accommodative' ? 'glow-green' : 'glow-cyan';

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Main: Composite r* headline */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4 }}
        >
          <Card className="h-full bg-card border-border/50 card-indicator card-indicator-cyan">
            <CardHeader className="pb-2">
              <CardTitle className="text-xs font-semibold uppercase tracking-wider text-primary flex items-center gap-2">
                <span className="w-1.5 h-1.5 rounded-full bg-primary" />
                Composite r* (Real Neutral Rate)
                <Tooltip>
                  <TooltipTrigger>
                    <Info className="w-3 h-3 text-muted-foreground/50" />
                  </TooltipTrigger>
                  <TooltipContent side="right" className="max-w-[300px] text-xs">
                    Regime-weighted composite of 5 equilibrium models: Fiscal-Augmented, Real Rate Parity, Market-Implied (ACM), State-Space (Kalman), and Regime-Conditional.
                  </TooltipContent>
                </Tooltip>
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {/* Headline r* */}
              <div className="text-center py-2">
                <div className={`font-data text-3xl font-bold ${rstarColor} ${rstarGlow}`}>
                  {compositeRstar.toFixed(2)}%
                </div>
                <div className="text-[10px] text-muted-foreground uppercase tracking-wider mt-1">
                  Real Neutral Rate
                </div>
              </div>

              {/* Derived metrics */}
              <div className="border-t border-border/30 pt-2 space-y-1">
                {selicStar != null && (
                  <div className="flex items-center justify-between py-0.5">
                    <div className="flex items-center gap-1.5">
                      <span className="text-[10px] text-muted-foreground uppercase tracking-wider">SELIC*</span>
                      <Tooltip>
                        <TooltipTrigger>
                          <Info className="w-3 h-3 text-muted-foreground/50" />
                        </TooltipTrigger>
                        <TooltipContent side="right" className="max-w-[240px] text-xs">
                          Equilibrium nominal policy rate = r* + IPCA expectations
                        </TooltipContent>
                      </Tooltip>
                    </div>
                    <span className="font-data text-sm font-bold text-foreground">
                      {selicStar.toFixed(2)}%
                    </span>
                  </div>
                )}
                <div className="flex items-center justify-between py-0.5">
                  <span className="text-[10px] text-muted-foreground uppercase tracking-wider">SELIC Target</span>
                  <span className="font-data text-xs font-semibold text-foreground">
                    {selicTarget?.toFixed(2) ?? 'N/A'}%
                  </span>
                </div>
                {selicStar != null && selicTarget != null && (
                  <div className="flex items-center justify-between py-0.5">
                    <span className="text-[10px] text-muted-foreground uppercase tracking-wider">Policy Gap</span>
                    <span className={`font-data text-xs font-bold ${
                      selicTarget - selicStar > 1 ? 'text-amber-400' :
                      selicTarget - selicStar < -1 ? 'text-emerald-400' :
                      'text-foreground'
                    }`}>
                      {(selicTarget - selicStar) > 0 ? '+' : ''}{(selicTarget - selicStar).toFixed(2)}%
                    </span>
                  </div>
                )}
                <div className="flex items-center justify-between py-0.5">
                  <span className="text-[10px] text-muted-foreground uppercase tracking-wider">Taylor Gap</span>
                  <span className={`font-data text-xs font-semibold ${
                    taylorGap > 1 ? 'text-amber-400' : taylorGap < -1 ? 'text-emerald-400' : 'text-foreground'
                  }`}>
                    {taylorGap > 0 ? '+' : ''}{taylorGap?.toFixed(1) ?? 'N/A'}%
                  </span>
                </div>
                {eq.acm_term_premium_5y != null && (
                  <div className="flex items-center justify-between py-0.5">
                    <div className="flex items-center gap-1.5">
                      <span className="text-[10px] text-muted-foreground uppercase tracking-wider">ACM TP 5Y</span>
                      <Tooltip>
                        <TooltipTrigger>
                          <Info className="w-3 h-3 text-muted-foreground/50" />
                        </TooltipTrigger>
                        <TooltipContent side="right" className="max-w-[240px] text-xs">
                          ACM-style term premium for 5Y maturity
                        </TooltipContent>
                      </Tooltip>
                    </div>
                    <span className="font-data text-xs font-semibold text-foreground">
                      {eq.acm_term_premium_5y.toFixed(2)}%
                    </span>
                  </div>
                )}
              </div>

              {/* Signal interpretation */}
              <div className="border-t border-border/30 pt-2">
                <div className={`text-[10px] uppercase tracking-wider text-center ${rstarColor}`}>
                  {rstarSignal === 'restrictive' && 'Elevated r* — Fiscal risk premia dominant'}
                  {rstarSignal === 'accommodative' && 'Low r* — Favorable external conditions'}
                  {rstarSignal === 'neutral' && 'Neutral r* — Balanced macro conditions'}
                </div>
              </div>
            </CardContent>
          </Card>
        </motion.div>

        {/* Model Contributions */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, delay: 0.1 }}
          className="lg:col-span-2"
        >
          <Card className="h-full bg-card border-border/50">
            <CardHeader className="pb-2">
              <CardTitle className="text-xs font-semibold uppercase tracking-wider text-primary flex items-center gap-2">
                <span className="w-1.5 h-1.5 rounded-full bg-primary" />
                Model Contributions ({models.length} Models)
                <Tooltip>
                  <TooltipTrigger>
                    <Info className="w-3 h-3 text-muted-foreground/50" />
                  </TooltipTrigger>
                  <TooltipContent side="right" className="max-w-[300px] text-xs">
                    Weights are regime-dependent: in domestic stress, fiscal model dominates; in risk-off, parity model gains weight.
                  </TooltipContent>
                </Tooltip>
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {models.map(([name, contrib]) => (
                <ModelBar
                  key={name}
                  name={name}
                  weight={contrib.weight}
                  value={contrib.current_value}
                  compositeRstar={compositeRstar}
                />
              ))}

              {/* Fiscal decomposition */}
              {eq.fiscal_decomposition && (
                <div className="border-t border-border/30 pt-3 mt-2">
                  <FiscalDecomp decomp={eq.fiscal_decomposition} />
                </div>
              )}
            </CardContent>
          </Card>
        </motion.div>
      </div>
    </div>
  );
}
