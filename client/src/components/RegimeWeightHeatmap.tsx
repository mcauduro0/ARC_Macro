/**
 * RegimeWeightHeatmap — Model Weight Evolution Across Regimes
 *
 * Displays a matrix heatmap showing how each of the 5 equilibrium models
 * is weighted under different macro regimes (Carry, Risk-Off, Domestic Stress).
 * Highlights the current regime row and shows the active weight allocation.
 */

import { EquilibriumData, MacroDashboard } from '@/hooks/useModelData';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { motion } from 'framer-motion';
import { Info, Grid3X3 } from 'lucide-react';

interface Props {
  dashboard: MacroDashboard;
}

/** Regime display metadata */
const REGIME_META: Record<string, { label: string; description: string; color: string; bgActive: string }> = {
  carry: {
    label: 'Carry',
    description: 'Low volatility, positive carry environment. State-Space and Market-Implied models dominate.',
    color: 'text-emerald-400',
    bgActive: 'bg-emerald-500/15 border-emerald-500/40',
  },
  riskoff: {
    label: 'Risk-Off',
    description: 'Global risk aversion. Parity model gains weight as external factors dominate.',
    color: 'text-blue-400',
    bgActive: 'bg-blue-500/15 border-blue-500/40',
  },
  domestic_stress: {
    label: 'Domestic Stress',
    description: 'Fiscal deterioration or political crisis. Fiscal model dominates with 40% weight.',
    color: 'text-amber-400',
    bgActive: 'bg-amber-500/15 border-amber-500/40',
  },
};

/** Model display metadata (same order as EquilibriumPanel) */
const MODEL_META: Record<string, { label: string; shortLabel: string; color: string }> = {
  fiscal: { label: 'Fiscal r*', shortLabel: 'Fiscal', color: '#f59e0b' },
  parity: { label: 'Parity r*', shortLabel: 'Parity', color: '#60a5fa' },
  market_implied: { label: 'Market-Implied', shortLabel: 'Mkt-Impl', color: '#22d3ee' },
  state_space: { label: 'State-Space', shortLabel: 'Kalman', color: '#a78bfa' },
  regime: { label: 'Regime r*', shortLabel: 'Regime', color: '#34d399' },
};

const REGIME_ORDER = ['carry', 'riskoff', 'domestic_stress'];
const MODEL_ORDER = ['fiscal', 'parity', 'market_implied', 'state_space', 'regime'];

/** Compute heatmap cell color intensity based on weight (0-1) */
function getHeatColor(weight: number): string {
  // Scale from dark (low weight) to bright cyan (high weight)
  const intensity = Math.min(weight / 0.4, 1); // 40% = max intensity
  const alpha = 0.08 + intensity * 0.55;
  return `rgba(34, 211, 238, ${alpha.toFixed(2)})`;
}

/** Get text color based on weight */
function getTextColor(weight: number): string {
  if (weight >= 0.3) return 'text-cyan-300 font-bold';
  if (weight >= 0.2) return 'text-cyan-400/90 font-semibold';
  if (weight >= 0.15) return 'text-foreground/80';
  return 'text-muted-foreground';
}

export function RegimeWeightHeatmap({ dashboard: d }: Props) {
  const eq = d.equilibrium;
  if (!eq?.regime_weights || !eq?.model_contributions) return null;

  const regimeWeights = eq.regime_weights;
  const currentRegime = d.current_regime?.toLowerCase()?.replace(/\s+/g, '_') || '';

  // Determine which regime is active
  const activeRegime = REGIME_ORDER.find(r =>
    currentRegime.includes(r) || currentRegime.includes(r.replace('_', ''))
  ) || 'carry';

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: 0.15 }}
    >
      <Card className="bg-card border-border/50">
        <CardHeader className="pb-3">
          <CardTitle className="text-xs font-semibold uppercase tracking-wider text-primary flex items-center gap-2">
            <Grid3X3 className="w-3.5 h-3.5" />
            Regime Weight Matrix
            <Tooltip>
              <TooltipTrigger>
                <Info className="w-3 h-3 text-muted-foreground/50" />
              </TooltipTrigger>
              <TooltipContent side="right" className="max-w-[320px] text-xs">
                How each equilibrium model is weighted under different macro regimes.
                The active regime row is highlighted. Weights determine the composite r*.
              </TooltipContent>
            </Tooltip>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {/* Heatmap Table */}
          <div className="overflow-x-auto">
            <table className="w-full border-collapse">
              {/* Header: Model names */}
              <thead>
                <tr>
                  <th className="text-left text-[10px] text-muted-foreground uppercase tracking-wider pb-2 pr-3 w-28">
                    Regime
                  </th>
                  {MODEL_ORDER.map(model => {
                    const meta = MODEL_META[model];
                    const contribution = eq.model_contributions[model];
                    return (
                      <th key={model} className="text-center pb-2 px-1">
                        <Tooltip>
                          <TooltipTrigger>
                            <div className="flex flex-col items-center gap-0.5">
                              <span
                                className="text-[10px] font-semibold uppercase tracking-wider cursor-help"
                                style={{ color: meta.color }}
                              >
                                {meta.shortLabel}
                              </span>
                              {contribution && (
                                <span className="text-[9px] text-muted-foreground/60 font-data">
                                  {contribution.current_value.toFixed(1)}%
                                </span>
                              )}
                            </div>
                          </TooltipTrigger>
                          <TooltipContent side="top" className="text-xs">
                            {meta.label}: Current r* = {contribution?.current_value?.toFixed(2) ?? 'N/A'}%
                          </TooltipContent>
                        </Tooltip>
                      </th>
                    );
                  })}
                  <th className="text-center text-[10px] text-muted-foreground uppercase tracking-wider pb-2 pl-2 w-16">
                    Sum
                  </th>
                </tr>
              </thead>
              <tbody>
                {REGIME_ORDER.map((regime, ri) => {
                  const regimeMeta = REGIME_META[regime];
                  const weights = regimeWeights[regime] || {};
                  const isActive = regime === activeRegime;
                  const rowSum = MODEL_ORDER.reduce((s, m) => s + (weights[m] || 0), 0);

                  return (
                    <motion.tr
                      key={regime}
                      initial={{ opacity: 0, x: -10 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ duration: 0.3, delay: ri * 0.08 }}
                      className={`border-t border-border/20 ${
                        isActive ? `${regimeMeta.bgActive} border rounded-lg` : ''
                      }`}
                    >
                      {/* Regime label */}
                      <td className="py-2.5 pr-3">
                        <div className="flex items-center gap-2">
                          {isActive && (
                            <span className="relative flex h-2 w-2">
                              <span className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${
                                regime === 'carry' ? 'bg-emerald-400' :
                                regime === 'riskoff' ? 'bg-blue-400' : 'bg-amber-400'
                              }`} />
                              <span className={`relative inline-flex rounded-full h-2 w-2 ${
                                regime === 'carry' ? 'bg-emerald-400' :
                                regime === 'riskoff' ? 'bg-blue-400' : 'bg-amber-400'
                              }`} />
                            </span>
                          )}
                          <Tooltip>
                            <TooltipTrigger>
                              <span className={`text-xs font-semibold cursor-help ${
                                isActive ? regimeMeta.color : 'text-muted-foreground'
                              }`}>
                                {regimeMeta.label}
                              </span>
                            </TooltipTrigger>
                            <TooltipContent side="left" className="max-w-[260px] text-xs">
                              {regimeMeta.description}
                            </TooltipContent>
                          </Tooltip>
                          {isActive && (
                            <span className="text-[9px] text-muted-foreground/60 uppercase tracking-wider">
                              active
                            </span>
                          )}
                        </div>
                      </td>

                      {/* Weight cells */}
                      {MODEL_ORDER.map(model => {
                        const w = weights[model] || 0;
                        const pct = (w * 100).toFixed(0);
                        return (
                          <td key={model} className="text-center py-2.5 px-1">
                            <Tooltip>
                              <TooltipTrigger className="w-full">
                                <motion.div
                                  initial={{ scale: 0.8, opacity: 0 }}
                                  animate={{ scale: 1, opacity: 1 }}
                                  transition={{ duration: 0.3, delay: ri * 0.08 + 0.1 }}
                                  className="mx-auto rounded-md px-2 py-1.5 min-w-[48px] cursor-help transition-all duration-200 hover:ring-1 hover:ring-primary/30"
                                  style={{ backgroundColor: getHeatColor(w) }}
                                >
                                  <span className={`font-data text-xs ${getTextColor(w)}`}>
                                    {pct}%
                                  </span>
                                </motion.div>
                              </TooltipTrigger>
                              <TooltipContent side="top" className="text-xs">
                                <div className="space-y-1">
                                  <div className="font-semibold">{MODEL_META[model].label} in {regimeMeta.label}</div>
                                  <div>Weight: {(w * 100).toFixed(1)}%</div>
                                  {eq.model_contributions[model] && (
                                    <div>
                                      Contribution: {(w * eq.model_contributions[model].current_value).toFixed(2)}% to composite
                                    </div>
                                  )}
                                </div>
                              </TooltipContent>
                            </Tooltip>
                          </td>
                        );
                      })}

                      {/* Row sum */}
                      <td className="text-center py-2.5 pl-2">
                        <span className={`font-data text-[10px] ${
                          Math.abs(rowSum - 1) < 0.01 ? 'text-muted-foreground' : 'text-destructive'
                        }`}>
                          {(rowSum * 100).toFixed(0)}%
                        </span>
                      </td>
                    </motion.tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Legend / Interpretation */}
          <div className="mt-4 pt-3 border-t border-border/20">
            <div className="flex flex-wrap items-center gap-4 text-[10px] text-muted-foreground">
              <div className="flex items-center gap-2">
                <span className="text-muted-foreground/60">Intensity:</span>
                <div className="flex items-center gap-1">
                  <div className="w-4 h-3 rounded-sm" style={{ backgroundColor: getHeatColor(0.05) }} />
                  <span>5%</span>
                </div>
                <div className="flex items-center gap-1">
                  <div className="w-4 h-3 rounded-sm" style={{ backgroundColor: getHeatColor(0.15) }} />
                  <span>15%</span>
                </div>
                <div className="flex items-center gap-1">
                  <div className="w-4 h-3 rounded-sm" style={{ backgroundColor: getHeatColor(0.25) }} />
                  <span>25%</span>
                </div>
                <div className="flex items-center gap-1">
                  <div className="w-4 h-3 rounded-sm" style={{ backgroundColor: getHeatColor(0.35) }} />
                  <span>35%</span>
                </div>
                <div className="flex items-center gap-1">
                  <div className="w-4 h-3 rounded-sm" style={{ backgroundColor: getHeatColor(0.4) }} />
                  <span>40%+</span>
                </div>
              </div>
              <div className="flex items-center gap-1.5">
                <span className="relative flex h-2 w-2">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-primary opacity-75" />
                  <span className="relative inline-flex rounded-full h-2 w-2 bg-primary" />
                </span>
                <span>Current regime</span>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>
    </motion.div>
  );
}
