/**
 * ModelChangelogPanel — Version history with comparative metrics.
 * Shows each model run with key metrics, changes, and delta indicators.
 * Design: "Institutional Command Center" dark slate theme.
 */

import { trpc } from '@/lib/trpc';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { History, TrendingUp, TrendingDown, Minus, ChevronDown, ChevronUp, Info } from 'lucide-react';
import { useState, useMemo } from 'react';

// ============================================================
// Types
// ============================================================

interface ChangelogEntry {
  id: number;
  version: string;
  runDate: string;
  score: number | null;
  regime: string | null;
  regimeCarryProb: number | null;
  regimeRiskoffProb: number | null;
  regimeStressProb: number | null;
  backtestSharpe: number | null;
  backtestReturn: number | null;
  backtestMaxDD: number | null;
  backtestWinRate: number | null;
  backtestMonths: number | null;
  weightFx: number | null;
  weightFront: number | null;
  weightBelly: number | null;
  weightLong: number | null;
  weightHard: number | null;
  trainingWindow: number | null;
  nStressScenarios: number | null;
  changesJson: Array<{ type: string; description: string }> | null;
  metricsJson: Record<string, unknown> | null;
  createdAt: string;
}

// ============================================================
// Helpers
// ============================================================

const REGIME_COLORS: Record<string, string> = {
  carry: 'text-emerald-400',
  riskoff: 'text-amber-400',
  stress_dom: 'text-red-400',
  stress: 'text-red-400',
};

const REGIME_LABELS: Record<string, string> = {
  carry: 'Carry',
  riskoff: 'Risk-Off',
  stress_dom: 'Stress',
  stress: 'Stress',
};

function formatPct(val: number | null, decimals = 1): string {
  if (val === null || val === undefined) return '—';
  return `${(val * 100).toFixed(decimals)}%`;
}

function formatNum(val: number | null, decimals = 2): string {
  if (val === null || val === undefined) return '—';
  return val.toFixed(decimals);
}

function DeltaIndicator({ current, previous, inverted = false, format = 'pct' }: {
  current: number | null;
  previous: number | null;
  inverted?: boolean;
  format?: 'pct' | 'num';
}) {
  if (current === null || previous === null) return null;
  const delta = current - previous;
  if (Math.abs(delta) < 0.001) return <Minus className="w-3 h-3 text-muted-foreground inline" />;

  const isPositive = inverted ? delta < 0 : delta > 0;
  const Icon = isPositive ? TrendingUp : TrendingDown;
  const color = isPositive ? 'text-emerald-400' : 'text-red-400';
  const formatted = format === 'pct'
    ? `${delta > 0 ? '+' : ''}${(delta * 100).toFixed(1)}pp`
    : `${delta > 0 ? '+' : ''}${delta.toFixed(2)}`;

  return (
    <span className={`inline-flex items-center gap-0.5 text-[10px] ${color}`}>
      <Icon className="w-2.5 h-2.5" />
      {formatted}
    </span>
  );
}

function ChangeTypeBadge({ type }: { type: string }) {
  const colors: Record<string, string> = {
    regime: 'bg-amber-500/20 text-amber-400 border-amber-500/30',
    score: 'bg-cyan-500/20 text-cyan-400 border-cyan-500/30',
    position: 'bg-purple-500/20 text-purple-400 border-purple-500/30',
    initial: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
    update: 'bg-muted text-muted-foreground border-border',
  };

  return (
    <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium border ${colors[type] || colors.update}`}>
      {type.toUpperCase()}
    </span>
  );
}

// ============================================================
// Component
// ============================================================

export function ModelChangelogPanel() {
  const { data: changelog, isLoading } = trpc.changelog.list.useQuery();
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [showAll, setShowAll] = useState(false);

  const entries = useMemo(() => {
    if (!changelog) return [];
    return (changelog as unknown as ChangelogEntry[]).sort(
      (a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime()
    );
  }, [changelog]);

  const displayEntries = showAll ? entries : entries.slice(0, 10);

  if (isLoading) {
    return (
      <Card className="bg-card border-border/50">
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-semibold tracking-wider uppercase text-muted-foreground flex items-center gap-2">
            <History className="w-4 h-4" />
            Model Changelog
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="animate-pulse space-y-3">
            {[1, 2, 3].map(i => (
              <div key={i} className="h-16 bg-muted/30 rounded" />
            ))}
          </div>
        </CardContent>
      </Card>
    );
  }

  if (!entries.length) {
    return (
      <Card className="bg-card border-border/50">
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-semibold tracking-wider uppercase text-muted-foreground flex items-center gap-2">
            <History className="w-4 h-4" />
            Model Changelog
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-muted-foreground text-sm text-center py-8">
            Nenhum registro de changelog ainda. Será gerado automaticamente após a próxima execução do modelo.
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="bg-card border-border/50">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-semibold tracking-wider uppercase text-muted-foreground flex items-center gap-2">
            <History className="w-4 h-4" />
            Model Changelog
          </CardTitle>
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <span>{entries.length} versões</span>
            <Tooltip>
              <TooltipTrigger>
                <Info className="w-3.5 h-3.5" />
              </TooltipTrigger>
              <TooltipContent side="left" className="max-w-xs">
                <p>Histórico de versões do modelo com métricas comparativas. Deltas mostram a variação em relação à versão anterior.</p>
              </TooltipContent>
            </Tooltip>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-0">
        {/* Header row */}
        <div className="grid grid-cols-12 gap-2 px-3 py-2 text-[10px] font-semibold tracking-wider uppercase text-muted-foreground border-b border-border/30">
          <div className="col-span-2">Versão</div>
          <div className="col-span-1 text-center">Regime</div>
          <div className="col-span-1 text-right">Score</div>
          <div className="col-span-1 text-right">Sharpe</div>
          <div className="col-span-1 text-right">Retorno</div>
          <div className="col-span-1 text-right">Max DD</div>
          <div className="col-span-1 text-right">Win Rate</div>
          <div className="col-span-1 text-right">Meses</div>
          <div className="col-span-3">Mudanças</div>
        </div>

        {/* Data rows */}
        {displayEntries.map((entry, idx) => {
          const prev = idx < entries.length - 1 ? entries[idx + 1] : null;
          const isExpanded = expandedId === entry.id;
          const rawChanges = entry.changesJson;
          const changes: Array<{ type: string; description: string }> = Array.isArray(rawChanges)
            ? rawChanges
            : typeof rawChanges === 'string'
              ? (() => { try { return JSON.parse(rawChanges); } catch { return []; } })()
              : [];

          return (
            <div key={entry.id} className="border-b border-border/20 last:border-0">
              {/* Main row */}
              <div
                className="grid grid-cols-12 gap-2 px-3 py-2.5 hover:bg-muted/20 cursor-pointer transition-colors items-center"
                onClick={() => setExpandedId(isExpanded ? null : entry.id)}
              >
                {/* Version + Date */}
                <div className="col-span-2">
                  <div className="flex items-center gap-1.5">
                    <span className="text-xs font-mono font-semibold text-foreground">{entry.version}</span>
                    {idx === 0 && (
                      <Badge variant="outline" className="text-[9px] px-1 py-0 h-4 border-primary/50 text-primary">
                        LATEST
                      </Badge>
                    )}
                  </div>
                  <span className="text-[10px] text-muted-foreground">{entry.runDate}</span>
                </div>

                {/* Regime */}
                <div className="col-span-1 text-center">
                  <span className={`text-xs font-semibold ${REGIME_COLORS[entry.regime || ''] || 'text-muted-foreground'}`}>
                    {REGIME_LABELS[entry.regime || ''] || entry.regime || '—'}
                  </span>
                </div>

                {/* Score */}
                <div className="col-span-1 text-right">
                  <div className="text-xs font-mono text-foreground">{formatNum(entry.score)}</div>
                  <DeltaIndicator current={entry.score} previous={prev?.score ?? null} format="num" />
                </div>

                {/* Sharpe */}
                <div className="col-span-1 text-right">
                  <div className="text-xs font-mono text-foreground">{formatNum(entry.backtestSharpe)}</div>
                  <DeltaIndicator current={entry.backtestSharpe} previous={prev?.backtestSharpe ?? null} format="num" />
                </div>

                {/* Return */}
                <div className="col-span-1 text-right">
                  <div className={`text-xs font-mono ${(entry.backtestReturn || 0) >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                    {formatPct(entry.backtestReturn)}
                  </div>
                  <DeltaIndicator current={entry.backtestReturn} previous={prev?.backtestReturn ?? null} />
                </div>

                {/* Max DD */}
                <div className="col-span-1 text-right">
                  <div className="text-xs font-mono text-red-400">{formatPct(entry.backtestMaxDD)}</div>
                  <DeltaIndicator current={entry.backtestMaxDD} previous={prev?.backtestMaxDD ?? null} inverted />
                </div>

                {/* Win Rate */}
                <div className="col-span-1 text-right">
                  <div className="text-xs font-mono text-foreground">{formatPct(entry.backtestWinRate)}</div>
                </div>

                {/* Months */}
                <div className="col-span-1 text-right">
                  <div className="text-xs font-mono text-muted-foreground">{entry.backtestMonths ?? '—'}</div>
                </div>

                {/* Changes summary */}
                <div className="col-span-3 flex items-center gap-1 overflow-hidden">
                  <div className="flex-1 flex flex-wrap gap-1">
                    {changes.slice(0, 2).map((c, i) => (
                      <ChangeTypeBadge key={i} type={c.type} />
                    ))}
                    {changes.length > 2 && (
                      <span className="text-[10px] text-muted-foreground">+{changes.length - 2}</span>
                    )}
                  </div>
                  {isExpanded ? (
                    <ChevronUp className="w-3.5 h-3.5 text-muted-foreground flex-shrink-0" />
                  ) : (
                    <ChevronDown className="w-3.5 h-3.5 text-muted-foreground flex-shrink-0" />
                  )}
                </div>
              </div>

              {/* Expanded details */}
              {isExpanded && (
                <div className="px-3 pb-3 space-y-3">
                  {/* Changes list */}
                  {changes.length > 0 && (
                    <div className="bg-muted/20 rounded-lg p-3">
                      <p className="text-[10px] font-semibold tracking-wider uppercase text-muted-foreground mb-2">Mudanças</p>
                      <div className="space-y-1.5">
                        {changes.map((c, i) => (
                          <div key={i} className="flex items-start gap-2">
                            <ChangeTypeBadge type={c.type} />
                            <span className="text-xs text-foreground/80">{c.description}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Position weights */}
                  <div className="bg-muted/20 rounded-lg p-3">
                    <p className="text-[10px] font-semibold tracking-wider uppercase text-muted-foreground mb-2">Pesos por Instrumento</p>
                    <div className="grid grid-cols-5 gap-3">
                      {[
                        { label: 'FX', val: entry.weightFx, prev: prev?.weightFx },
                        { label: 'Front', val: entry.weightFront, prev: prev?.weightFront },
                        { label: 'Belly', val: entry.weightBelly, prev: prev?.weightBelly },
                        { label: 'Long', val: entry.weightLong, prev: prev?.weightLong },
                        { label: 'Hard', val: entry.weightHard, prev: prev?.weightHard },
                      ].map(({ label, val, prev: prevVal }) => (
                        <div key={label} className="text-center">
                          <p className="text-[10px] text-muted-foreground">{label}</p>
                          <p className="text-xs font-mono text-foreground">{formatPct(val, 0)}</p>
                          <DeltaIndicator current={val ?? null} previous={prevVal ?? null} />
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* Regime probabilities */}
                  <div className="bg-muted/20 rounded-lg p-3">
                    <p className="text-[10px] font-semibold tracking-wider uppercase text-muted-foreground mb-2">Probabilidades de Regime</p>
                    <div className="grid grid-cols-3 gap-3">
                      {[
                        { label: 'Carry', val: entry.regimeCarryProb, color: 'text-emerald-400' },
                        { label: 'Risk-Off', val: entry.regimeRiskoffProb, color: 'text-amber-400' },
                        { label: 'Stress', val: entry.regimeStressProb, color: 'text-red-400' },
                      ].map(({ label, val, color }) => (
                        <div key={label} className="text-center">
                          <p className="text-[10px] text-muted-foreground">{label}</p>
                          <p className={`text-sm font-mono font-semibold ${color}`}>{formatPct(val)}</p>
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* Config info */}
                  <div className="flex items-center gap-4 text-[10px] text-muted-foreground">
                    <span>Training Window: {entry.trainingWindow || '—'}m</span>
                    <span>Stress Scenarios: {entry.nStressScenarios || '—'}</span>
                    <span>Criado: {new Date(entry.createdAt).toLocaleString('pt-BR')}</span>
                  </div>
                </div>
              )}
            </div>
          );
        })}

        {/* Show more button */}
        {entries.length > 10 && (
          <div className="pt-3 text-center">
            <button
              onClick={() => setShowAll(!showAll)}
              className="text-xs text-primary hover:text-primary/80 transition-colors"
            >
              {showAll ? 'Mostrar menos' : `Ver todas as ${entries.length} versões`}
            </button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
