/**
 * TemporalSelectionPanel — v4.3 Temporal Feature Selection Comparison
 * Shows how feature selection results change over time, detecting structural
 * shifts in feature importance regimes.
 */

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Clock, ArrowUpRight, ArrowDownRight, Minus, AlertTriangle, TrendingUp } from 'lucide-react';

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

interface TemporalChange {
  instrument: string;
  feature: string;
  change_type: string;
  from_status: string;
  to_status: string;
}

interface TemporalSummary {
  total_features_tracked: number;
  features_gained: string[];
  features_lost: string[];
  features_stable: string[];
  structural_shift_score: number;
}

interface TemporalSelectionPanelProps {
  temporal: {
    changes: TemporalChange[];
    summary: Record<string, TemporalSummary>;
    run_date: string;
    previous_date: string;
  } | null | undefined;
}

function ChangeIcon({ type }: { type: string }) {
  switch (type) {
    case 'gained':
      return <ArrowUpRight className="w-3.5 h-3.5 text-emerald-400" />;
    case 'lost':
      return <ArrowDownRight className="w-3.5 h-3.5 text-red-400" />;
    case 'upgraded':
      return <ArrowUpRight className="w-3.5 h-3.5 text-blue-400" />;
    case 'downgraded':
      return <ArrowDownRight className="w-3.5 h-3.5 text-orange-400" />;
    default:
      return <Minus className="w-3.5 h-3.5 text-slate-400" />;
  }
}

function ChangeTypeBadge({ type }: { type: string }) {
  const styles: Record<string, string> = {
    gained: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/25',
    lost: 'bg-red-500/15 text-red-300 border-red-500/25',
    upgraded: 'bg-blue-500/15 text-blue-300 border-blue-500/25',
    downgraded: 'bg-orange-500/15 text-orange-300 border-orange-500/25',
    stable: 'bg-slate-500/15 text-slate-300 border-slate-500/25',
  };
  const labels: Record<string, string> = {
    gained: 'Ganhou',
    lost: 'Perdeu',
    upgraded: 'Promovida',
    downgraded: 'Rebaixada',
    stable: 'Estável',
  };

  return (
    <Badge variant="outline" className={`text-[10px] ${styles[type] || styles.stable}`}>
      {labels[type] || type}
    </Badge>
  );
}

function ShiftScoreBar({ score }: { score: number }) {
  // Score 0-1: 0 = no change, 1 = complete turnover
  const pct = Math.min(score * 100, 100);
  const color =
    score < 0.1
      ? 'bg-emerald-500'
      : score < 0.3
        ? 'bg-yellow-500'
        : score < 0.5
          ? 'bg-orange-500'
          : 'bg-red-500';
  const label =
    score < 0.1
      ? 'Estável'
      : score < 0.3
        ? 'Mudança Leve'
        : score < 0.5
          ? 'Mudança Moderada'
          : 'Mudança Estrutural';

  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs">
        <span className="text-slate-400">Structural Shift Score</span>
        <span className={score < 0.3 ? 'text-emerald-400' : score < 0.5 ? 'text-orange-400' : 'text-red-400'}>
          {(score * 100).toFixed(1)}% — {label}
        </span>
      </div>
      <div className="w-full h-2 bg-slate-700/50 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

export function TemporalSelectionPanel({ temporal }: TemporalSelectionPanelProps) {
  if (!temporal || !temporal.summary) {
    return (
      <Card className="bg-slate-800/50 border-slate-700/50">
        <CardContent className="p-6 text-center">
          <Clock className="w-8 h-8 text-slate-500 mx-auto mb-2" />
          <p className="text-sm text-slate-400">
            Comparação temporal não disponível. Necessário pelo menos 2 execuções do pipeline para
            comparar mudanças na seleção de features.
          </p>
        </CardContent>
      </Card>
    );
  }

  const instruments = Object.keys(temporal.summary);
  const changes = temporal.changes || [];
  const totalGained = instruments.reduce(
    (s, i) => s + (temporal.summary[i]?.features_gained?.length || 0),
    0
  );
  const totalLost = instruments.reduce(
    (s, i) => s + (temporal.summary[i]?.features_lost?.length || 0),
    0
  );
  const totalStable = instruments.reduce(
    (s, i) => s + (temporal.summary[i]?.features_stable?.length || 0),
    0
  );
  const avgShift =
    instruments.reduce((s, i) => s + (temporal.summary[i]?.structural_shift_score || 0), 0) /
    instruments.length;

  return (
    <div className="space-y-4">
      {/* Header with dates */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <Clock className="w-4 h-4 text-slate-400" />
          <span className="text-xs text-slate-400">
            Comparando: <span className="text-slate-300">{temporal.previous_date || 'N/A'}</span>
            {' → '}
            <span className="text-slate-200 font-medium">{temporal.run_date || 'Atual'}</span>
          </span>
        </div>
        {avgShift > 0.3 && (
          <Badge className="bg-orange-500/15 text-orange-300 border-orange-500/25 text-xs">
            <AlertTriangle className="w-3 h-3 mr-1" />
            Mudança Estrutural Detectada
          </Badge>
        )}
      </div>

      {/* Global summary */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Card className="bg-emerald-500/10 border-emerald-500/20">
          <CardContent className="p-3 text-center">
            <div className="text-2xl font-bold text-emerald-300">+{totalGained}</div>
            <div className="text-xs text-emerald-400">Features Ganhas</div>
          </CardContent>
        </Card>
        <Card className="bg-red-500/10 border-red-500/20">
          <CardContent className="p-3 text-center">
            <div className="text-2xl font-bold text-red-300">-{totalLost}</div>
            <div className="text-xs text-red-400">Features Perdidas</div>
          </CardContent>
        </Card>
        <Card className="bg-slate-700/30 border-slate-600/30">
          <CardContent className="p-3 text-center">
            <div className="text-2xl font-bold text-slate-200">{totalStable}</div>
            <div className="text-xs text-slate-400">Features Estáveis</div>
          </CardContent>
        </Card>
        <Card className="bg-slate-800/50 border-slate-700/50">
          <CardContent className="p-3 text-center">
            <div className={`text-2xl font-bold ${avgShift < 0.3 ? 'text-emerald-300' : avgShift < 0.5 ? 'text-orange-300' : 'text-red-300'}`}>
              {(avgShift * 100).toFixed(0)}%
            </div>
            <div className="text-xs text-slate-400">Shift Score Médio</div>
          </CardContent>
        </Card>
      </div>

      {/* Per-instrument shift scores */}
      <Card className="bg-slate-800/50 border-slate-700/50">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm text-slate-300 flex items-center gap-2">
            <TrendingUp className="w-4 h-4" />
            Structural Shift Score por Instrumento
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {instruments.map((inst) => {
            const summary = temporal.summary[inst];
            if (!summary) return null;
            return (
              <div key={inst}>
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-xs font-medium text-slate-300 w-12">
                    {INSTRUMENT_SHORT[inst] || inst}
                  </span>
                  <div className="flex-1">
                    <ShiftScoreBar score={summary.structural_shift_score} />
                  </div>
                </div>
                <div className="flex gap-2 ml-14 text-[10px]">
                  {summary.features_gained.length > 0 && (
                    <span className="text-emerald-400">
                      +{summary.features_gained.map((f) => FEATURE_LABELS[f] || f).join(', ')}
                    </span>
                  )}
                  {summary.features_lost.length > 0 && (
                    <span className="text-red-400">
                      -{summary.features_lost.map((f) => FEATURE_LABELS[f] || f).join(', ')}
                    </span>
                  )}
                </div>
              </div>
            );
          })}
        </CardContent>
      </Card>

      {/* Detailed changes table */}
      {changes.length > 0 && (
        <Card className="bg-slate-800/50 border-slate-700/50">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm text-slate-300">
              Mudanças Detalhadas ({changes.length})
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-slate-700/50">
                    <th className="text-left py-2 text-slate-400 font-medium">Instrumento</th>
                    <th className="text-left py-2 text-slate-400 font-medium">Feature</th>
                    <th className="text-center py-2 text-slate-400 font-medium">Tipo</th>
                    <th className="text-center py-2 text-slate-400 font-medium">De</th>
                    <th className="text-center py-2 text-slate-400 font-medium">Para</th>
                  </tr>
                </thead>
                <tbody>
                  {changes.map((ch, idx) => (
                    <tr key={idx} className="border-b border-slate-700/20 hover:bg-slate-700/20">
                      <td className="py-1.5 text-slate-300 font-medium">
                        {INSTRUMENT_SHORT[ch.instrument] || ch.instrument}
                      </td>
                      <td className="py-1.5 text-slate-200 font-mono text-[11px]">
                        <div className="flex items-center gap-1">
                          <ChangeIcon type={ch.change_type} />
                          {FEATURE_LABELS[ch.feature] || ch.feature}
                        </div>
                      </td>
                      <td className="text-center py-1.5">
                        <ChangeTypeBadge type={ch.change_type} />
                      </td>
                      <td className="text-center py-1.5 text-slate-400 text-[11px]">
                        {ch.from_status || '—'}
                      </td>
                      <td className="text-center py-1.5 text-slate-300 text-[11px]">
                        {ch.to_status || '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Explanation */}
      <Card className="bg-amber-500/5 border-amber-500/20">
        <CardContent className="p-3">
          <div className="flex items-center gap-2 mb-1">
            <Clock className="w-4 h-4 text-amber-400" />
            <span className="text-sm font-semibold text-amber-300">Comparação Temporal</span>
          </div>
          <p className="text-xs text-slate-400 leading-relaxed">
            Compara os resultados de feature selection entre execuções consecutivas do pipeline.
            Um Structural Shift Score alto (&gt;30%) indica que o regime de importância das features
            mudou significativamente — pode sinalizar uma mudança estrutural no mercado ou nos
            drivers macro. Features que entram/saem consistentemente entre runs devem ser
            investigadas.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
