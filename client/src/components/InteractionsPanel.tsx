/**
 * InteractionsPanel — v4.4 Feature Interaction Terms Visualization
 * Shows which cross-feature products (VIX×CDS, carry×regime, etc.)
 * were tested and validated by Boruta across instruments.
 */

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import {
  Zap,
  CheckCircle2,
  XCircle,
  Info,
} from 'lucide-react';

const INSTRUMENT_SHORT: Record<string, string> = {
  fx: 'FX',
  front: 'Front',
  belly: 'Belly',
  long: 'Long',
  hard: 'Hard',
};

const INTERACTION_LABELS: Record<string, string> = {
  IX_vix_x_cds: 'VIX × CDS',
  IX_vix_x_cds_br: 'VIX × CDS BR',
  IX_carry_x_regime: 'Carry FX × Regime',
  IX_carry_front_x_regime: 'Carry Front × Regime',
  IX_carry_long_x_regime: 'Carry Long × Regime',
  IX_carry_belly_x_regime: 'Carry Belly × Regime',
  IX_carry_hard_x_regime: 'Carry Hard × Regime',
  IX_fiscal_x_cds: 'Fiscal × CDS',
  IX_fiscal_x_cds_br: 'Fiscal × CDS BR',
  IX_fiscal_prem_x_sovereign: 'Prêmio Fiscal × Soberano',
  IX_policy_x_dxy: 'Policy Gap × DXY',
  IX_policy_x_vix: 'Policy Gap × VIX',
  IX_beer_x_momentum: 'BEER × Momentum',
  IX_reer_x_momentum: 'REER × Momentum',
  IX_term_prem_x_vix: 'Term Prem × VIX',
  IX_term_prem_x_cds: 'Term Prem × CDS',
  IX_term_prem_x_cds_br: 'Term Prem × CDS BR',
  IX_rstar_x_dxy: 'r* × DXY',
  IX_rstar_x_vix: 'r* × VIX',
  IX_selic_gap_x_regime: 'SELIC Gap × Regime',
};

interface InteractionData {
  tested: string[];
  confirmed: string[];
  rejected: string[];
  n_tested: number;
  n_confirmed: number;
}

interface InteractionsPanelProps {
  data: Record<string, { interactions?: InteractionData }> | null | undefined;
}

export function InteractionsPanel({ data }: InteractionsPanelProps) {
  if (!data) return null;

  const instruments = Object.keys(data).filter(
    (i) => data[i]?.interactions && data[i].interactions!.n_tested > 0
  );

  if (instruments.length === 0) return null;

  // Build a matrix: interaction × instrument → confirmed/rejected
  const allInteractions = new Set<string>();
  instruments.forEach((inst) => {
    const ix = data[inst]?.interactions;
    if (ix) {
      ix.tested.forEach((t) => allInteractions.add(t));
    }
  });

  const interactionList = Array.from(allInteractions).sort();

  // Summary
  const totalTested = instruments.reduce(
    (s, i) => s + (data[i]?.interactions?.n_tested || 0),
    0
  );
  const totalConfirmed = instruments.reduce(
    (s, i) => s + (data[i]?.interactions?.n_confirmed || 0),
    0
  );
  const confirmRate = totalTested > 0 ? ((totalConfirmed / totalTested) * 100).toFixed(0) : '0';

  return (
    <Card className="bg-slate-800/50 border-slate-700/50">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm text-slate-300 flex items-center gap-2">
            <Zap className="w-4 h-4 text-blue-400" />
            Interações de Features — Validação Boruta
          </CardTitle>
          <div className="flex items-center gap-2">
            <Badge
              variant="outline"
              className="text-xs border-blue-500/30 text-blue-400 bg-blue-500/10"
            >
              {totalConfirmed}/{totalTested} confirmadas ({confirmRate}%)
            </Badge>
            <Tooltip>
              <TooltipTrigger>
                <Info className="w-4 h-4 text-slate-500" />
              </TooltipTrigger>
              <TooltipContent className="max-w-xs">
                <p className="text-xs">
                  Termos de interação são produtos cruzados entre features (ex: VIX × CDS).
                  Cada interação é testada com Boruta (30 iterações) para confirmar poder preditivo
                  genuíno. Apenas interações que superam shadow features são incluídas no modelo.
                </p>
              </TooltipContent>
            </Tooltip>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {interactionList.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-slate-700/50">
                  <th className="text-left py-2 px-2 text-slate-400 font-medium min-w-[150px]">
                    Interação
                  </th>
                  {instruments.map((inst) => (
                    <th
                      key={inst}
                      className="text-center py-2 px-2 text-slate-400 font-medium min-w-[60px]"
                    >
                      {INSTRUMENT_SHORT[inst] || inst}
                    </th>
                  ))}
                  <th className="text-center py-2 px-2 text-slate-400 font-medium min-w-[80px]">
                    Taxa
                  </th>
                </tr>
              </thead>
              <tbody>
                {interactionList.map((ix) => {
                  const confirmedCount = instruments.filter((inst) =>
                    data[inst]?.interactions?.confirmed.includes(ix)
                  ).length;
                  const testedCount = instruments.filter((inst) =>
                    data[inst]?.interactions?.tested.includes(ix)
                  ).length;

                  return (
                    <tr
                      key={ix}
                      className="border-b border-slate-700/20 hover:bg-slate-700/20"
                    >
                      <td className="py-1.5 px-2 text-slate-300 font-mono text-[11px] flex items-center gap-1">
                        <Zap className="w-3 h-3 text-blue-400 flex-shrink-0" />
                        {INTERACTION_LABELS[ix] || ix.replace('IX_', '').replace(/_/g, ' ')}
                      </td>
                      {instruments.map((inst) => {
                        const instIx = data[inst]?.interactions;
                        if (!instIx || !instIx.tested.includes(ix)) {
                          return (
                            <td key={inst} className="text-center py-1.5 px-1">
                              <span className="text-slate-600 text-[10px]">—</span>
                            </td>
                          );
                        }
                        const isConfirmed = instIx.confirmed.includes(ix);
                        return (
                          <td key={inst} className="text-center py-1.5 px-1">
                            {isConfirmed ? (
                              <CheckCircle2 className="w-4 h-4 text-emerald-400 mx-auto" />
                            ) : (
                              <XCircle className="w-4 h-4 text-red-400/50 mx-auto" />
                            )}
                          </td>
                        );
                      })}
                      <td className="text-center py-1.5 px-1">
                        <span
                          className={`text-[11px] font-bold ${
                            confirmedCount > 0 ? 'text-emerald-300' : 'text-red-300'
                          }`}
                        >
                          {confirmedCount}/{testedCount}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-xs text-slate-500 text-center py-4">
            Nenhuma interação testada nesta execução.
          </p>
        )}

        {/* Legend */}
        <div className="flex items-center gap-4 mt-3 pt-3 border-t border-slate-700/30">
          <span className="text-xs text-slate-500">Legenda:</span>
          <div className="flex items-center gap-1">
            <CheckCircle2 className="w-3 h-3 text-emerald-400" />
            <span className="text-xs text-slate-400">Confirmada (Boruta)</span>
          </div>
          <div className="flex items-center gap-1">
            <XCircle className="w-3 h-3 text-red-400/50" />
            <span className="text-xs text-slate-400">Rejeitada</span>
          </div>
          <div className="flex items-center gap-1">
            <span className="text-xs text-slate-600">—</span>
            <span className="text-xs text-slate-400">Não testada</span>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
