import { MacroDashboard } from '@/hooks/useModelData';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { motion } from 'framer-motion';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { Info, TrendingUp, TrendingDown, Minus, ArrowUpRight, ArrowDownRight } from 'lucide-react';

interface Props {
  dashboard: MacroDashboard;
}

function MetricRow({ label, value, unit, tooltip, color }: {
  label: string;
  value: string | number;
  unit?: string;
  tooltip?: string;
  color?: string;
}) {
  return (
    <div className="flex items-center justify-between py-1">
      <div className="flex items-center gap-1.5">
        <span className="text-[10px] text-muted-foreground uppercase tracking-wider">{label}</span>
        {tooltip && (
          <Tooltip>
            <TooltipTrigger>
              <Info className="w-3 h-3 text-muted-foreground/50" />
            </TooltipTrigger>
            <TooltipContent side="right" className="max-w-[240px] text-xs">
              {tooltip}
            </TooltipContent>
          </Tooltip>
        )}
      </div>
      <span className={`font-data text-xs font-semibold ${color || 'text-foreground'}`}>
        {value}{unit || ''}
      </span>
    </div>
  );
}

function ZScoreBar({ value, label }: { value: number; label: string }) {
  const clampedValue = Math.max(-3, Math.min(3, value));
  const pct = ((clampedValue + 3) / 6) * 100;
  const color = value > 1 ? 'bg-emerald-400' : value > 0 ? 'bg-emerald-400/60' : value > -1 ? 'bg-amber-400' : 'bg-rose-400';

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between">
        <span className="text-[10px] text-muted-foreground uppercase tracking-wider">{label}</span>
        <span className="font-data text-[10px] font-semibold text-foreground">
          {value > 0 ? '+' : ''}{value.toFixed(2)}σ
        </span>
      </div>
      <div className="relative h-1.5 bg-secondary rounded-full overflow-hidden">
        <div className="absolute inset-y-0 left-1/2 w-px bg-muted-foreground/30" />
        <motion.div
          initial={{ width: '50%' }}
          animate={{ width: `${pct}%` }}
          transition={{ duration: 0.8 }}
          className={`absolute inset-y-0 left-0 ${color} rounded-full`}
        />
      </div>
    </div>
  );
}

function DirectionBadge({ direction, er }: { direction: string; er: number }) {
  const isLong = direction?.includes('LONG') ?? false;
  const isShort = direction?.includes('SHORT') ?? false;
  const color = isLong ? 'text-emerald-400' : isShort ? 'text-rose-400' : 'text-amber-400';
  const Icon = isLong ? ArrowUpRight : isShort ? ArrowDownRight : Minus;
  return (
    <div className={`flex items-center gap-1 ${color}`}>
      <Icon className="w-3.5 h-3.5" />
      <span className="font-data text-xs font-bold">{direction}</span>
      <span className="font-data text-[10px] text-muted-foreground ml-1">
        E[r]={er > 0 ? '+' : ''}{er.toFixed(2)}%
      </span>
    </div>
  );
}

const cardVariants = {
  hidden: { opacity: 0, y: 20 },
  visible: (i: number) => ({
    opacity: 1,
    y: 0,
    transition: { delay: i * 0.08, duration: 0.4 },
  }),
};

export function OverviewGrid({ dashboard: d }: Props) {
  const isMROS = 'positions' in d && d.positions;
  const fmtPct = (v: number | undefined | null) => v != null ? `${v > 0 ? '+' : ''}${v.toFixed(1)}%` : 'N/A';
  const fmtNum = (v: number | undefined | null, dec = 2) => v != null ? v.toFixed(dec) : 'N/A';
  const misColor = (v: number | undefined | null) => v == null ? 'text-foreground' : v > 0 ? 'text-emerald-400' : v < 0 ? 'text-rose-400' : 'text-foreground';

  return (
    <div className="space-y-4">
      {/* Row 1: Cross-Asset Positions (Macro Risk OS) */}
      {isMROS && (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
          {/* FX Position */}
          <motion.div custom={0} variants={cardVariants} initial="hidden" animate="visible">
            <Card className="card-indicator card-indicator-cyan h-full bg-card border-border/50">
              <CardHeader className="pb-1">
                <CardTitle className="text-xs font-semibold uppercase tracking-wider text-primary flex items-center gap-2">
                  <span className="w-1.5 h-1.5 rounded-full bg-primary" />
                  FX (USDBRL)
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-1">
                <DirectionBadge
                  direction={d.positions?.fx?.direction || d.direction}
                  er={d.positions?.fx?.expected_return_6m || 0}
                />
                <MetricRow label="Fair Value (BEER)" value={fmtNum(d.fx_fair_value)} tooltip="BEER equilibrium model (REER-based, institutional standard — primary fair value)" />
                <MetricRow label="Misalignment" value={fmtPct(d.fx_misalignment)} color={misColor(d.fx_misalignment)} tooltip="Spot vs BEER fair value" />
                <MetricRow label="PPP-BS" value={fmtNum(d.ppp_bs_fair)} tooltip="PPP ajustado por Balassa-Samuelson (β=0.35): corrige o viés de produtividade para EM" />
                <MetricRow label="FEER" value={fmtNum(d.feer_fair)} tooltip="Fundamental Equilibrium ER: câmbio consistente com conta corrente sustentável (-2.0% PIB)" />
                <MetricRow label="PPP Raw" value={fmtNum(d.ppp_fair)} tooltip="PPP conversion factor bruto (referência estrutural de longo prazo, não é fair value)" />
                <MetricRow label="Sharpe" value={fmtNum(d.positions?.fx?.sharpe)} />
                <MetricRow label="Weight" value={fmtNum(d.positions?.fx?.weight, 3)} />
              </CardContent>
            </Card>
          </motion.div>

          {/* Front-End Rates */}
          <motion.div custom={1} variants={cardVariants} initial="hidden" animate="visible">
            <Card className="card-indicator card-indicator-cyan h-full bg-card border-border/50">
              <CardHeader className="pb-1">
                <CardTitle className="text-xs font-semibold uppercase tracking-wider text-primary flex items-center gap-2">
                  <span className="w-1.5 h-1.5 rounded-full bg-cyan-400" />
                  Front-End (DI 1Y)
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-1">
                <DirectionBadge
                  direction={d.positions?.front?.direction || 'N/A'}
                  er={d.positions?.front?.expected_return_6m || 0}
                />
                <MetricRow label="DI 1Y" value={`${fmtNum(d.di_1y)}%`} />
                <MetricRow label="SELIC" value={`${fmtNum(d.selic_target)}%`} />
                <MetricRow label="Fair Value" value={`${fmtNum(d.front_fair)}%`} tooltip="Front-end fair rate from model" />
                <MetricRow label="Sharpe" value={fmtNum(d.positions?.front?.sharpe)} />
                <MetricRow label="Weight" value={fmtNum(d.positions?.front?.weight, 3)} />
                <MetricRow label="Risk Unit" value={fmtNum(d.positions?.front?.risk_unit, 4)} />
              </CardContent>
            </Card>
          </motion.div>

          {/* Long-End Rates */}
          <motion.div custom={2} variants={cardVariants} initial="hidden" animate="visible">
            <Card className="card-indicator card-indicator-neutral h-full bg-card border-border/50">
              <CardHeader className="pb-1">
                <CardTitle className="text-xs font-semibold uppercase tracking-wider text-amber-400 flex items-center gap-2">
                  <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
                  Long-End (DI 5Y)
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-1">
                <DirectionBadge
                  direction={d.positions?.long?.direction || 'N/A'}
                  er={d.positions?.long?.expected_return_6m || 0}
                />
                <MetricRow label="DI 5Y" value={`${fmtNum(d.di_5y)}%`} />
                <MetricRow label="DI 10Y" value={`${fmtNum(d.di_10y)}%`} />
                <MetricRow label="Fair Value" value={`${fmtNum(d.long_fair)}%`} />
                <MetricRow label="Term Premium" value={`${fmtNum(d.term_premium)}%`} />
                <MetricRow label="Sharpe" value={fmtNum(d.positions?.long?.sharpe)} />
                <MetricRow label="Weight" value={fmtNum(d.positions?.long?.weight, 3)} />
              </CardContent>
            </Card>
          </motion.div>

          {/* Hard Currency Sovereign */}
          <motion.div custom={3} variants={cardVariants} initial="hidden" animate="visible">
            <Card className="card-indicator h-full bg-card border-border/50 card-indicator-bearish">
              <CardHeader className="pb-1">
                <CardTitle className="text-xs font-semibold uppercase tracking-wider text-rose-400 flex items-center gap-2">
                  <span className="w-1.5 h-1.5 rounded-full bg-rose-400" />
                  Hard Currency
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-1">
                <DirectionBadge
                  direction={d.positions?.hard?.direction || 'N/A'}
                  er={d.positions?.hard?.expected_return_6m || 0}
                />
                <MetricRow label="EMBI Spread" value={`${fmtNum(d.embi_spread, 0)} bps`} />
                <MetricRow label="UST 2Y" value={`${fmtNum(d.ust_2y)}%`} />
                <MetricRow label="UST 10Y" value={`${fmtNum(d.ust_10y)}%`} />
                <MetricRow label="Sharpe" value={fmtNum(d.positions?.hard?.sharpe)} />
                <MetricRow label="Weight" value={fmtNum(d.positions?.hard?.weight, 3)} />
                <MetricRow label="Risk Unit" value={fmtNum(d.positions?.hard?.risk_unit, 4)} />
              </CardContent>
            </Card>
          </motion.div>
        </div>
      )}

      {/* Row 2: State Variables + Regime */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        {/* State Variables X1-X7 */}
        <motion.div custom={4} variants={cardVariants} initial="hidden" animate="visible" className="xl:col-span-2">
          <Card className="h-full bg-card border-border/50">
            <CardHeader className="pb-2">
              <CardTitle className="text-xs font-semibold uppercase tracking-wider text-primary flex items-center gap-2">
                <span className="w-1.5 h-1.5 rounded-full bg-primary" />
                Variáveis de Estado (Z-Scores Rolling 5Y)
              </CardTitle>
            </CardHeader>
            <CardContent>
              {isMROS && d.state_variables ? (
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-2">
                  {Object.entries(d.state_variables).map(([key, value]) => {
                    const v = value as number;
                    const labels: Record<string, string> = {
                      'X1_diferencial_real': 'Diferencial Real',
                      'X2_surpresa_inflacao': 'Surpresa Inflação',
                      'X3_fiscal_risk': 'Risco Fiscal',
                      'X4_termos_de_troca': 'Termos de Troca',
                      'X5_dolar_global': 'Dólar Global (DXY)',
                      'X6_risk_global': 'Risco Global (VIX)',
                      'X7_cds_brasil': 'CDS Brasil',
                      'X8_beer_misalignment': 'BEER Misalignment',
                      'X9_reer_gap': 'REER Gap',
                      'X10_term_premium': 'Term Premium',
                      'X11_cip_basis': 'CIP Basis',
                      'X12_iron_ore': 'Iron Ore',
                    };
                    return (
                      <ZScoreBar key={key} value={v || 0} label={labels[key] || key.replace(/^X\d+_/, '')} />
                    );
                  })}
                </div>
              ) : (
                // Legacy: cyclical weights
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-2">
                  {d.z_cycle != null && <ZScoreBar value={d.z_cycle} label="Z-Score Cíclico Composto" />}
                  {d.cyclical_weights && Object.entries(d.cyclical_weights).map(([key, weight]) => (
                    <div key={key} className="flex items-center justify-between py-1">
                      <span className="text-[10px] text-muted-foreground uppercase tracking-wider">{key.replace('Z_', '')}</span>
                      <span className="font-data text-[10px] text-muted-foreground">w={(weight as number).toFixed(2)}</span>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </motion.div>

        {/* Regime */}
        <motion.div custom={5} variants={cardVariants} initial="hidden" animate="visible">
          <Card className={`h-full bg-card border-border/50 card-indicator ${
            (d.current_regime || d.dominant_regime) === 'Carry' ? 'card-indicator-bullish' :
            (d.current_regime || d.dominant_regime) === 'StressDom' ? 'card-indicator-neutral' :
            'card-indicator-bearish'
          }`}>
            <CardHeader className="pb-2">
              <CardTitle className={`text-xs font-semibold uppercase tracking-wider flex items-center gap-2 ${
                (d.current_regime || d.dominant_regime) === 'Carry' ? 'text-emerald-400' :
                (d.current_regime || d.dominant_regime) === 'StressDom' ? 'text-amber-400' :
                'text-rose-400'
              }`}>
                <span className={`w-1.5 h-1.5 rounded-full ${
                  (d.current_regime || d.dominant_regime) === 'Carry' ? 'bg-emerald-400' :
                  (d.current_regime || d.dominant_regime) === 'StressDom' ? 'bg-amber-400' :
                  'bg-rose-400'
                }`} />
                Regime Macro (3-State)
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              <MetricRow
                label="Regime Dominante"
                value={d.current_regime || d.dominant_regime || 'N/A'}
                color={
                  (d.current_regime || d.dominant_regime) === 'Carry' ? 'text-emerald-400' :
                  (d.current_regime || d.dominant_regime) === 'StressDom' ? 'text-amber-400' :
                  'text-rose-400'
                }
              />
              {/* Regime probabilities */}
              {d.regime_probabilities && Object.entries(d.regime_probabilities)
                .filter(([key]) => key.startsWith('P_'))
                .map(([regime, prob]) => {
                const p = prob as number;
                const regimeColors: Record<string, string> = {
                  'P_Carry': 'bg-emerald-400',
                  'P_RiskOff': 'bg-rose-400',
                  'P_StressDom': 'bg-amber-400',
                };
                return (
                  <div key={regime} className="space-y-1">
                    <div className="flex items-center justify-between">
                      <span className="text-[10px] text-muted-foreground uppercase tracking-wider">
                        {regime.replace('P_', '')}
                      </span>
                      <span className="font-data text-xs font-semibold text-foreground">
                        {(p * 100).toFixed(1)}%
                      </span>
                    </div>
                    <div className="h-1.5 bg-secondary rounded-full overflow-hidden">
                      <motion.div
                        initial={{ width: 0 }}
                        animate={{ width: `${p * 100}%` }}
                        transition={{ duration: 0.8 }}
                        className={`h-full rounded-full ${regimeColors[regime] || 'bg-cyan-400'}`}
                      />
                    </div>
                  </div>
                );
              })}
              {/* Legacy regime probs */}
              {!d.regime_probabilities && d.regime_probs && Object.entries(d.regime_probs).map(([regime, prob]) => {
                const p = prob as number;
                return (
                  <div key={regime} className="space-y-1">
                    <div className="flex items-center justify-between">
                      <span className="text-[10px] text-muted-foreground uppercase tracking-wider">{regime}</span>
                      <span className="font-data text-xs font-semibold text-foreground">{(p * 100).toFixed(1)}%</span>
                    </div>
                    <div className="h-1.5 bg-secondary rounded-full overflow-hidden">
                      <motion.div
                        initial={{ width: 0 }}
                        animate={{ width: `${p * 100}%` }}
                        transition={{ duration: 0.8 }}
                        className={`h-full rounded-full ${regime === 'Carry' ? 'bg-emerald-400' : 'bg-rose-400'}`}
                      />
                    </div>
                  </div>
                );
              })}
              {/* Risk metrics */}
              {isMROS && d.risk_metrics && (
                <>
                  <div className="border-t border-border/30 pt-2 mt-2">
                    <MetricRow label="Portfolio Vol" value={`${d.risk_metrics.portfolio_vol < 1 ? (d.risk_metrics.portfolio_vol * 100).toFixed(2) : d.risk_metrics.portfolio_vol.toFixed(2)}%`} tooltip="Volatilidade anualizada do portfólio cross-asset" />
                    <MetricRow label="VIX" value={fmtNum(d.vix)} />
                    <MetricRow label="DXY" value={fmtNum(d.dxy)} />
                  </div>
                </>
              )}
            </CardContent>
          </Card>
        </motion.div>
      </div>
    </div>
  );
}
