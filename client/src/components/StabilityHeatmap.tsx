/**
 * StabilityHeatmap — v4.4 Bootstrap Stability Selection Visualization
 * Uses composite scoring (Elastic Net freq + Boruta freq + RF importance)
 * with adaptive thresholds calibrated from actual frequency distribution.
 * Shows interactions, instability alerts, and per-instrument breakdown.
 */

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import {
  Shield,
  ShieldAlert,
  ShieldCheck,
  Info,
  AlertTriangle,
  Zap,
  ArrowDownRight,
  ArrowUpRight,
  TrendingUp,
} from 'lucide-react';

const FEATURE_LABELS: Record<string, string> = {
  Z_real_diff: 'Dif. Real',
  Z_infl_surprise: 'Surpresa Infl.',
  Z_fiscal: 'Risco Fiscal',
  Z_tot: 'Termos Troca',
  Z_dxy: 'DXY',
  Z_vix: 'VIX',
  Z_cds_br: 'CDS Brasil',
  Z_beer: 'BEER',
  Z_reer_gap: 'REER Gap',
  Z_term_premium: 'Term Prem.',
  Z_cip_basis: 'CIP Basis',
  Z_iron_ore: 'Minério',
  Z_policy_gap: 'Policy Gap',
  Z_rstar_composite: 'r* Comp.',
  Z_rstar_momentum: 'r* Mom.',
  Z_fiscal_component: 'Comp. Fiscal',
  Z_sovereign_component: 'Comp. Soberano',
  Z_selic_star_gap: 'SELIC* Gap',
  rstar_regime_signal: 'Regime r*',
  Z_rstar_curve_gap: 'r* Curve',
  Z_focus_fx: 'Focus FX',
  Z_ewz: 'EWZ',
  Z_portfolio_flow: 'Fluxo Port.',
  Z_debt_accel: 'Acel. Dívida',
  carry_fx: 'Carry FX',
  carry_front: 'Carry Front',
  carry_belly: 'Carry Belly',
  carry_long: 'Carry Long',
  carry_hard: 'Carry Hard',
  Z_slope: 'Slope',
  Z_ppp_gap: 'PPP Gap',
  Z_hy_spread: 'HY Spread',
  Z_us_real_yield: 'US Real Yield',
  Z_us_breakeven: 'US Breakeven',
  Z_bop: 'BoP',
  Z_cftc_brl: 'CFTC BRL',
  Z_idp_flow: 'IDP Flow',
  Z_pb_momentum: 'PB Mom.',
  Z_surpresa_inflacao: 'Surpresa Infl.',
  Z_diferencial_real: 'Dif. Real',
  Z_termos_de_troca: 'Termos Troca',
  Z_fiscal_risk: 'Risco Fiscal',
  Z_fiscal_premium: 'Prêmio Fiscal',
  Z_tp_5y: 'TP 5Y',
  Z_cds_brasil: 'CDS Brasil',
  mu_fx_val: 'μ FX Val',
  mu_fx_lag1: 'μ FX Lag-1',
  mu_front_lag1: 'μ Front Lag-1',
  mu_belly_lag1: 'μ Belly Lag-1',
  mu_long_lag1: 'μ Long Lag-1',
  mu_hard_lag1: 'μ Hard Lag-1',
};

const INSTRUMENT_SHORT: Record<string, string> = {
  fx: 'FX',
  front: 'Front',
  belly: 'Belly',
  long: 'Long',
  hard: 'Hard',
};

interface StabilityData {
  n_subsamples: number;
  subsample_ratio: number;
  enet_frequency?: Record<string, number>;
  lasso_frequency?: Record<string, number>;
  boruta_frequency?: Record<string, number>;
  composite_score?: Record<string, number>;
  combined_frequency?: Record<string, number>;
  classification: Record<string, string>;
  thresholds?: { robust: number; moderate: number };
}

interface InteractionData {
  tested: string[];
  confirmed: string[];
  rejected: string[];
  n_tested: number;
  n_confirmed: number;
}

interface AlertData {
  type: 'critical' | 'warning' | 'info';
  feature: string;
  instrument: string;
  message: string;
  previous?: string;
  current?: string;
  transition?: string;
}

interface InstrumentData {
  stability?: StabilityData;
  interactions?: InteractionData;
  alerts?: AlertData[];
}

interface StabilityHeatmapProps {
  data: Record<string, InstrumentData> | null | undefined;
}

function getScore(stability: StabilityData | undefined, feat: string): number {
  if (!stability) return 0;
  return (
    stability.composite_score?.[feat] ??
    stability.combined_frequency?.[feat] ??
    0
  );
}

function getScoreColor(score: number, thresholds?: { robust: number; moderate: number }): string {
  const robustT = thresholds?.robust ?? 0.8;
  const moderateT = thresholds?.moderate ?? 0.5;
  if (score >= robustT) return 'bg-emerald-500';
  if (score >= (robustT + moderateT) / 2) return 'bg-emerald-500/70';
  if (score >= moderateT) return 'bg-yellow-500/70';
  if (score >= moderateT * 0.6) return 'bg-orange-500/60';
  return 'bg-red-500/50';
}

function getScoreTextColor(score: number, thresholds?: { robust: number; moderate: number }): string {
  const robustT = thresholds?.robust ?? 0.8;
  const moderateT = thresholds?.moderate ?? 0.5;
  if (score >= robustT) return 'text-emerald-100';
  if (score >= moderateT) return 'text-yellow-100';
  return 'text-red-200';
}

function getClassBadge(cls: string) {
  switch (cls) {
    case 'robust':
      return (
        <Badge className="bg-emerald-500/20 text-emerald-300 border-emerald-500/30 text-[10px] px-1">
          <ShieldCheck className="w-2.5 h-2.5 mr-0.5" />
          Robusto
        </Badge>
      );
    case 'moderate':
      return (
        <Badge className="bg-yellow-500/20 text-yellow-300 border-yellow-500/30 text-[10px] px-1">
          <Shield className="w-2.5 h-2.5 mr-0.5" />
          Moderado
        </Badge>
      );
    default:
      return (
        <Badge className="bg-red-500/20 text-red-300 border-red-500/30 text-[10px] px-1">
          <ShieldAlert className="w-2.5 h-2.5 mr-0.5" />
          Instável
        </Badge>
      );
  }
}

function getAlertIcon(type: string) {
  switch (type) {
    case 'critical':
      return <AlertTriangle className="w-3.5 h-3.5 text-red-400" />;
    case 'warning':
      return <ArrowDownRight className="w-3.5 h-3.5 text-yellow-400" />;
    case 'info':
      return <ArrowUpRight className="w-3.5 h-3.5 text-emerald-400" />;
    default:
      return <Info className="w-3.5 h-3.5 text-slate-400" />;
  }
}

export function StabilityHeatmap({ data }: StabilityHeatmapProps) {
  if (!data) return null;

  const instruments = Object.keys(data).filter(
    (i) => data[i]?.stability?.n_subsamples && data[i].stability!.n_subsamples > 0
  );

  if (instruments.length === 0) {
    return (
      <Card className="bg-slate-800/50 border-slate-700/50">
        <CardContent className="p-6 text-center">
          <Shield className="w-8 h-8 text-slate-500 mx-auto mb-2" />
          <p className="text-sm text-slate-400">
            Stability selection não disponível. Execute o pipeline v4.4 para gerar resultados.
          </p>
        </CardContent>
      </Card>
    );
  }

  // Collect all unique features across instruments
  const allFeatures = new Set<string>();
  instruments.forEach((inst) => {
    const stability = data[inst]?.stability;
    const scoreMap = stability?.composite_score ?? stability?.combined_frequency;
    if (scoreMap) {
      Object.keys(scoreMap).forEach((f) => allFeatures.add(f));
    }
  });

  // Get adaptive thresholds (use first instrument's thresholds as reference)
  const refThresholds = data[instruments[0]]?.stability?.thresholds;

  // Sort features by average composite score (descending)
  const featureList = Array.from(allFeatures).sort((a, b) => {
    const avgA =
      instruments.reduce((s, i) => s + getScore(data[i]?.stability, a), 0) /
      instruments.length;
    const avgB =
      instruments.reduce((s, i) => s + getScore(data[i]?.stability, b), 0) /
      instruments.length;
    return avgB - avgA;
  });

  // Summary stats
  const totalRobust = instruments.reduce((s, inst) => {
    const cls = data[inst]?.stability?.classification || {};
    return s + Object.values(cls).filter((v) => v === 'robust').length;
  }, 0);
  const totalModerate = instruments.reduce((s, inst) => {
    const cls = data[inst]?.stability?.classification || {};
    return s + Object.values(cls).filter((v) => v === 'moderate').length;
  }, 0);
  const totalUnstable = instruments.reduce((s, inst) => {
    const cls = data[inst]?.stability?.classification || {};
    return s + Object.values(cls).filter((v) => v === 'unstable').length;
  }, 0);

  const nSubsamples = data[instruments[0]]?.stability?.n_subsamples || 100;

  // Collect all alerts
  const allAlerts: AlertData[] = [];
  instruments.forEach((inst) => {
    const alerts = data[inst]?.alerts;
    if (alerts) allAlerts.push(...alerts);
  });

  // Collect all interactions
  const totalInteractionsTested = instruments.reduce(
    (s, i) => s + (data[i]?.interactions?.n_tested || 0),
    0
  );
  const totalInteractionsConfirmed = instruments.reduce(
    (s, i) => s + (data[i]?.interactions?.n_confirmed || 0),
    0
  );

  return (
    <div className="space-y-4">
      {/* Instability Alerts */}
      {allAlerts.length > 0 && (
        <Card className="bg-red-500/5 border-red-500/20">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm text-red-300 flex items-center gap-2">
              <AlertTriangle className="w-4 h-4" />
              Alertas de Instabilidade ({allAlerts.length})
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {allAlerts.map((alert, idx) => (
              <div
                key={idx}
                className={`flex items-start gap-2 p-2 rounded text-xs ${
                  alert.type === 'critical'
                    ? 'bg-red-500/10 border border-red-500/20'
                    : alert.type === 'warning'
                      ? 'bg-yellow-500/10 border border-yellow-500/20'
                      : 'bg-emerald-500/10 border border-emerald-500/20'
                }`}
              >
                {getAlertIcon(alert.type)}
                <div>
                  <span className="font-semibold text-slate-200">
                    {FEATURE_LABELS[alert.feature] || alert.feature}
                  </span>
                  <span className="text-slate-400 mx-1">em</span>
                  <span className="font-semibold text-slate-200">
                    {INSTRUMENT_SHORT[alert.instrument] || alert.instrument}
                  </span>
                  <span className="text-slate-400 ml-1">— {alert.message}</span>
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {/* Summary cards */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <Card className="bg-slate-800/50 border-slate-700/50">
          <CardContent className="p-3 text-center">
            <div className="text-2xl font-bold text-slate-200">{nSubsamples}</div>
            <div className="text-xs text-slate-400">Bootstrap Subsamples</div>
          </CardContent>
        </Card>
        <Card className="bg-emerald-500/10 border-emerald-500/20">
          <CardContent className="p-3 text-center">
            <div className="text-2xl font-bold text-emerald-300">{totalRobust}</div>
            <div className="text-xs text-emerald-400">
              Robustas (adaptativo)
            </div>
          </CardContent>
        </Card>
        <Card className="bg-yellow-500/10 border-yellow-500/20">
          <CardContent className="p-3 text-center">
            <div className="text-2xl font-bold text-yellow-300">{totalModerate}</div>
            <div className="text-xs text-yellow-400">
              Moderadas (adaptativo)
            </div>
          </CardContent>
        </Card>
        <Card className="bg-red-500/10 border-red-500/20">
          <CardContent className="p-3 text-center">
            <div className="text-2xl font-bold text-red-300">{totalUnstable}</div>
            <div className="text-xs text-red-400">
              Instáveis (adaptativo)
            </div>
          </CardContent>
        </Card>
        <Card className="bg-blue-500/10 border-blue-500/20">
          <CardContent className="p-3 text-center">
            <div className="text-2xl font-bold text-blue-300">
              {totalInteractionsConfirmed}/{totalInteractionsTested}
            </div>
            <div className="text-xs text-blue-400">Interações Confirmadas</div>
          </CardContent>
        </Card>
      </div>

      {/* Heatmap */}
      <Card className="bg-slate-800/50 border-slate-700/50">
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between">
            <CardTitle className="text-sm text-slate-300 flex items-center gap-2">
              <Shield className="w-4 h-4" />
              Heatmap de Estabilidade — Composite Score (Features × Instrumentos)
            </CardTitle>
            <Tooltip>
              <TooltipTrigger>
                <Info className="w-4 h-4 text-slate-500" />
              </TooltipTrigger>
              <TooltipContent className="max-w-xs">
                <p className="text-xs">
                  Composite Score = 40% Elastic Net freq + 40% Boruta freq + 20% RF importance.
                  Thresholds adaptativos calibrados da distribuição real dos scores (P75 = robust,
                  P40 = moderate). Interações validadas com Boruta antes de inclusão.
                </p>
              </TooltipContent>
            </Tooltip>
          </div>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-slate-700/50">
                  <th className="text-left py-2 px-2 text-slate-400 font-medium min-w-[120px]">
                    Feature
                  </th>
                  {instruments.map((inst) => (
                    <th
                      key={inst}
                      className="text-center py-2 px-2 text-slate-400 font-medium min-w-[60px]"
                    >
                      {INSTRUMENT_SHORT[inst] || inst}
                    </th>
                  ))}
                  <th className="text-center py-2 px-2 text-slate-400 font-medium min-w-[60px]">
                    Média
                  </th>
                  <th className="text-center py-2 px-2 text-slate-400 font-medium min-w-[80px]">
                    Status
                  </th>
                </tr>
              </thead>
              <tbody>
                {featureList.map((feat) => {
                  const scores = instruments.map((i) => getScore(data[i]?.stability, feat));
                  const avg = scores.reduce((s, f) => s + f, 0) / scores.length;
                  const isInteraction = feat.includes('×') || feat.includes('_x_');
                  // Use best per-instrument classification (not averaged)
                  const perInstClasses = instruments.map((i) => {
                    const cls = data[i]?.stability?.classification?.[feat];
                    return cls || 'unstable';
                  });
                  const bestClass = perInstClasses.includes('robust')
                    ? 'robust'
                    : perInstClasses.includes('moderate')
                      ? 'moderate'
                      : 'unstable';
                  // Count how many instruments have this feature as non-zero
                  const activeInstruments = scores.filter((s) => s > 0).length;

                  return (
                    <tr
                      key={feat}
                      className={`border-b border-slate-700/20 hover:bg-slate-700/20 ${isInteraction ? 'bg-blue-500/5' : ''}`}
                    >
                      <td className="py-1.5 px-2 text-slate-300 font-mono text-[11px] flex items-center gap-1">
                        {isInteraction && <Zap className="w-3 h-3 text-blue-400 flex-shrink-0" />}
                        {FEATURE_LABELS[feat] || feat}
                      </td>
                      {instruments.map((inst) => {
                        const score = getScore(data[inst]?.stability, feat);
                        const instThresholds = data[inst]?.stability?.thresholds;
                        return (
                          <td key={inst} className="text-center py-1.5 px-1">
                            <Tooltip>
                              <TooltipTrigger>
                                <div
                                  className={`inline-flex w-10 h-6 rounded-sm items-center justify-center ${getScoreColor(score, instThresholds)}`}
                                >
                                  <span
                                    className={`text-[10px] font-bold ${getScoreTextColor(score, instThresholds)}`}
                                  >
                                    {(score * 100).toFixed(0)}%
                                  </span>
                                </div>
                              </TooltipTrigger>
                              <TooltipContent>
                                <div className="text-xs space-y-1">
                                  <div>
                                    <strong>{FEATURE_LABELS[feat] || feat}</strong> em{' '}
                                    {INSTRUMENT_SHORT[inst]}
                                  </div>
                                  <div>
                                    Elastic Net:{' '}
                                    {(
                                      ((data[inst]?.stability?.enet_frequency?.[feat] ??
                                        data[inst]?.stability?.lasso_frequency?.[feat]) ||
                                        0) * 100
                                    ).toFixed(0)}
                                    %
                                  </div>
                                  <div>
                                    Boruta:{' '}
                                    {(
                                      (data[inst]?.stability?.boruta_frequency?.[feat] || 0) * 100
                                    ).toFixed(0)}
                                    %
                                  </div>
                                  <div>
                                    Composite:{' '}
                                    {(score * 100).toFixed(1)}%
                                  </div>
                                  <div className="text-slate-400 italic">
                                    Threshold: robust ≥{' '}
                                    {((instThresholds?.robust ?? 0.8) * 100).toFixed(0)}%, moderate ≥{' '}
                                    {((instThresholds?.moderate ?? 0.5) * 100).toFixed(0)}%
                                  </div>
                                </div>
                              </TooltipContent>
                            </Tooltip>
                          </td>
                        );
                      })}
                      <td className="text-center py-1.5 px-1">
                        <span
                          className={`text-[11px] font-bold ${bestClass === 'robust' ? 'text-emerald-300' : bestClass === 'moderate' ? 'text-yellow-300' : 'text-red-300'}`}
                        >
                          {(avg * 100).toFixed(0)}%
                        </span>
                      </td>
                      <td className="text-center py-1.5 px-1">
                        <div className="flex flex-col items-center gap-0.5">
                          {getClassBadge(bestClass)}
                          {activeInstruments > 0 && activeInstruments < instruments.length && (
                            <span className="text-[9px] text-slate-500">
                              {activeInstruments}/{instruments.length}
                            </span>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Legend */}
          <div className="flex flex-wrap items-center gap-4 mt-3 pt-3 border-t border-slate-700/30">
            <span className="text-xs text-slate-500">Legenda:</span>
            <div className="flex items-center gap-1">
              <div className="w-3 h-3 rounded-sm bg-emerald-500" />
              <span className="text-xs text-slate-400">Robusto</span>
            </div>
            <div className="flex items-center gap-1">
              <div className="w-3 h-3 rounded-sm bg-yellow-500/70" />
              <span className="text-xs text-slate-400">Moderado</span>
            </div>
            <div className="flex items-center gap-1">
              <div className="w-3 h-3 rounded-sm bg-red-500/50" />
              <span className="text-xs text-slate-400">Instável</span>
            </div>
            <div className="flex items-center gap-1">
              <Zap className="w-3 h-3 text-blue-400" />
              <span className="text-xs text-slate-400">Interação</span>
            </div>
            <span className="text-xs text-slate-500 ml-auto">
              Scoring: 40% ENet + 40% Boruta + 20% RF Imp. | Thresholds adaptativos (P75/P40)
            </span>
          </div>
        </CardContent>
      </Card>

      {/* Per-instrument breakdown with interactions */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        {instruments.map((inst) => {
          const stability = data[inst]?.stability;
          const interactions = data[inst]?.interactions;
          if (!stability) return null;
          const cls = stability.classification || {};
          const robust = Object.entries(cls).filter(([, v]) => v === 'robust');
          const moderate = Object.entries(cls).filter(([, v]) => v === 'moderate');

          return (
            <Card key={inst} className="bg-slate-800/50 border-slate-700/50">
              <CardHeader className="pb-2">
                <CardTitle className="text-xs font-semibold text-slate-200 flex items-center justify-between">
                  <span>{INSTRUMENT_SHORT[inst] || inst}</span>
                  {stability.thresholds && (
                    <span className="text-[10px] text-slate-500 font-normal">
                      T: {(stability.thresholds.robust * 100).toFixed(0)}% /{' '}
                      {(stability.thresholds.moderate * 100).toFixed(0)}%
                    </span>
                  )}
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                <div className="flex gap-2 text-[10px]">
                  <span className="text-emerald-400">{robust.length} robustas</span>
                  <span className="text-yellow-400">{moderate.length} moderadas</span>
                  <span className="text-red-400">
                    {Object.values(cls).filter((v) => v === 'unstable').length} instáveis
                  </span>
                </div>
                {robust.length > 0 && (
                  <div>
                    <div className="text-[10px] text-emerald-400/80 mb-0.5">Robustas:</div>
                    <div className="flex flex-wrap gap-1">
                      {robust.map(([f]) => (
                        <span
                          key={f}
                          className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/15 text-emerald-300 border border-emerald-500/20"
                        >
                          {FEATURE_LABELS[f] || f}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
                {moderate.length > 0 && (
                  <div>
                    <div className="text-[10px] text-yellow-400/80 mb-0.5">Moderadas:</div>
                    <div className="flex flex-wrap gap-1">
                      {moderate.map(([f]) => (
                        <span
                          key={f}
                          className="text-[10px] px-1.5 py-0.5 rounded bg-yellow-500/15 text-yellow-300 border border-yellow-500/20"
                        >
                          {FEATURE_LABELS[f] || f}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
                {interactions && interactions.n_confirmed > 0 && (
                  <div>
                    <div className="text-[10px] text-blue-400/80 mb-0.5 flex items-center gap-1">
                      <Zap className="w-2.5 h-2.5" />
                      Interações Confirmadas ({interactions.n_confirmed}/{interactions.n_tested}):
                    </div>
                    <div className="flex flex-wrap gap-1">
                      {interactions.confirmed.map((ix) => (
                        <span
                          key={ix}
                          className="text-[10px] px-1.5 py-0.5 rounded bg-blue-500/15 text-blue-300 border border-blue-500/20"
                        >
                          {ix}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>
          );
        })}
      </div>
    </div>
  );
}
