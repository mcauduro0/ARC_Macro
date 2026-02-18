/**
 * RebalancingTab — Side-by-side current vs target positions comparison
 * with visual weight diff bars, contract-level trade orders, and cost estimates.
 * Design: "Institutional Command Center" dark slate theme.
 */
import { trpc } from '@/lib/trpc';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { toast } from 'sonner';
import {
  ArrowRight, ArrowUpDown, Check, ChevronRight, Loader2,
  RefreshCw, Scale, ShieldAlert, TrendingDown, TrendingUp,
  AlertTriangle, BarChart3, DollarSign, Percent, Target,
  Zap, ArrowLeftRight, Minus, Plus, Equal,
} from 'lucide-react';
import { useState, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';

// ============================================================
// Constants
// ============================================================
const INSTRUMENT_LABELS: Record<string, string> = {
  fx: 'FX (NDF)',
  front: 'Front-End (DI 1Y)',
  belly: 'Belly (DI 5Y)',
  long: 'Long-End (DI 10Y)',
  hard: 'Cupom Cambial (DDI)',
  ntnb: 'NTN-B (IPCA+)',
};

const INSTRUMENT_COLORS: Record<string, string> = {
  fx: '#06b6d4',
  front: '#a78bfa',
  belly: '#f59e0b',
  long: '#818cf8',
  hard: '#34d399',
  ntnb: '#fbbf24',
};

const INSTRUMENT_ORDER = ['fx', 'front', 'belly', 'long', 'hard', 'ntnb'];

function fmtBrl(v: number): string {
  return new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL', maximumFractionDigits: 0 }).format(v);
}

function fmtNum(v: number): string {
  return new Intl.NumberFormat('pt-BR').format(v);
}

function fmtPct(v: number, decimals = 1): string {
  return `${v >= 0 ? '+' : ''}${v.toFixed(decimals)}%`;
}

// ============================================================
// Weight Diff Bar
// ============================================================
function WeightDiffBar({ current, target, maxAbs }: { current: number; target: number; maxAbs: number }) {
  const diff = target - current;
  const barWidth = maxAbs > 0 ? Math.abs(diff) / maxAbs * 100 : 0;
  const isPositive = diff >= 0;

  return (
    <div className="flex items-center gap-2 w-full">
      <span className="text-xs font-data w-12 text-right text-muted-foreground">
        {(current * 100).toFixed(0)}%
      </span>
      <div className="flex-1 h-5 bg-secondary/30 rounded relative overflow-hidden">
        {/* Center line */}
        <div className="absolute left-1/2 top-0 bottom-0 w-px bg-border z-10" />
        {/* Diff bar */}
        <motion.div
          initial={{ width: 0 }}
          animate={{ width: `${barWidth / 2}%` }}
          transition={{ duration: 0.5, ease: 'easeOut' }}
          className={`absolute top-0.5 bottom-0.5 rounded ${
            isPositive ? 'left-1/2 bg-emerald-500/60' : 'bg-rose-500/60'
          }`}
          style={!isPositive ? { right: '50%' } : undefined}
        />
      </div>
      <span className="text-xs font-data w-12 text-muted-foreground">
        {(target * 100).toFixed(0)}%
      </span>
      <Badge
        variant="outline"
        className={`text-xs font-data w-16 justify-center ${
          diff > 0.01 ? 'text-emerald-400 border-emerald-500/30' :
          diff < -0.01 ? 'text-rose-400 border-rose-500/30' :
          'text-muted-foreground border-border'
        }`}
      >
        {diff > 0 ? '+' : ''}{(diff * 100).toFixed(0)}%
      </Badge>
    </div>
  );
}

// ============================================================
// Trade Action Badge
// ============================================================
function ActionBadge({ action }: { action: string }) {
  switch (action) {
    case 'BUY':
      return (
        <Badge className="bg-emerald-500/20 text-emerald-400 border-emerald-500/30 gap-1">
          <Plus className="w-3 h-3" /> COMPRAR
        </Badge>
      );
    case 'SELL':
      return (
        <Badge className="bg-rose-500/20 text-rose-400 border-rose-500/30 gap-1">
          <Minus className="w-3 h-3" /> VENDER
        </Badge>
      );
    default:
      return (
        <Badge variant="outline" className="text-muted-foreground gap-1">
          <Equal className="w-3 h-3" /> MANTER
        </Badge>
      );
  }
}

// ============================================================
// Cost Breakdown Card
// ============================================================
function CostBreakdown({ plan }: { plan: any }) {
  if (!plan) return null;
  const trades = plan.trades || [];
  const activeTrades = trades.filter((t: any) => t.action !== 'HOLD');

  return (
    <Card className="bg-card border-border">
      <CardHeader className="pb-3">
        <CardTitle className="text-sm flex items-center gap-2">
          <DollarSign className="w-4 h-4 text-amber-400" />
          Estimativa de Custos de Transação
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div>
            <p className="text-xs text-muted-foreground uppercase tracking-wider">Custo Total</p>
            <p className="text-lg font-data font-bold text-amber-400">{fmtBrl(plan.estimatedCostBrl || 0)}</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground uppercase tracking-wider">Custo (bps)</p>
            <p className="text-lg font-data font-bold">{(plan.estimatedCostBps || 0).toFixed(1)} bps</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground uppercase tracking-wider">Turnover</p>
            <p className="text-lg font-data font-bold">{(plan.turnoverPct || 0).toFixed(1)}%</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground uppercase tracking-wider">Ordens</p>
            <p className="text-lg font-data font-bold">{activeTrades.length}</p>
          </div>
        </div>
        {activeTrades.length > 0 && (
          <div className="mt-4 space-y-2">
            <p className="text-xs text-muted-foreground uppercase tracking-wider">Custo por Instrumento</p>
            {activeTrades.map((trade: any, idx: number) => (
              <div key={idx} className="flex items-center justify-between py-1 border-b border-border/50 last:border-0">
                <div className="flex items-center gap-2">
                  <div className="w-2 h-2 rounded-full" style={{ backgroundColor: INSTRUMENT_COLORS[trade.instrument] || '#888' }} />
                  <span className="text-xs">{INSTRUMENT_LABELS[trade.instrument] || trade.instrument}</span>
                </div>
                <span className="text-xs font-data text-muted-foreground">{fmtBrl(trade.estimatedCostBrl || 0)}</span>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ============================================================
// Main RebalancingTab
// ============================================================
export function RebalancingTab() {
  const { data: computeData, isLoading, refetch } = trpc.portfolio.compute.useQuery();
  const rebalanceMutation = trpc.portfolio.rebalance.useMutation({
    onSuccess: (result) => {
      if (result.success) {
        toast.success(`Rebalanceamento executado! ${result.tradesCount} trades criados.`);
        refetch();
      } else {
        toast.error(result.error || 'Erro ao rebalancear.');
      }
    },
    onError: (err) => {
      toast.error(`Erro: ${err.message}`);
    },
  });

  const [showAllTrades, setShowAllTrades] = useState(false);
  const [confirmRebalance, setConfirmRebalance] = useState(false);

  const d = computeData?.data;
  const error = computeData?.error;

  // Compute position comparison data
  const comparison = useMemo(() => {
    if (!d) return null;

    const targetPositions = d.positions || [];
    const rebalPlan = d.rebalancingPlan;
    const currentPositions = rebalPlan?.currentPositions || [];
    const trades = rebalPlan?.trades || [];

    // Build comparison rows
    const rows = INSTRUMENT_ORDER.map(inst => {
      const target = targetPositions.find((p: any) => p.instrument === inst);
      const current = currentPositions.find((p: any) => p.instrument === inst);
      const trade = trades.find((t: any) => t.instrument === inst);

      return {
        instrument: inst,
        label: INSTRUMENT_LABELS[inst] || inst,
        color: INSTRUMENT_COLORS[inst] || '#888',
        currentWeight: current?.modelWeight || 0,
        targetWeight: target?.modelWeight || 0,
        currentContracts: current?.contracts || 0,
        targetContracts: target?.contracts || 0,
        currentNotional: current?.notionalBrl || 0,
        targetNotional: target?.notionalBrl || 0,
        currentDirection: current?.direction || '—',
        targetDirection: target?.direction || '—',
        b3Ticker: target?.b3Ticker || current?.b3Ticker || '—',
        trade: trade || null,
        hasPosition: !!target || !!current,
      };
    }).filter(r => r.hasPosition || r.targetWeight !== 0);

    const maxWeightAbs = Math.max(
      ...rows.map(r => Math.abs(r.targetWeight - r.currentWeight)),
      0.01
    );

    return { rows, maxWeightAbs, trades, currentPositions, targetPositions };
  }, [d]);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="w-8 h-8 animate-spin text-primary" />
      </div>
    );
  }

  if (error) {
    return (
      <Card className="bg-card border-border">
        <CardContent className="py-12 text-center">
          <ShieldAlert className="w-10 h-10 text-muted-foreground mx-auto mb-4" />
          <p className="text-lg font-medium">Portfólio não configurado</p>
          <p className="text-sm text-muted-foreground mt-2">{error}</p>
        </CardContent>
      </Card>
    );
  }

  if (!d || !comparison) {
    return (
      <Card className="bg-card border-border">
        <CardContent className="py-12 text-center">
          <Scale className="w-10 h-10 text-muted-foreground mx-auto mb-4" />
          <p className="text-lg font-medium">Sem dados de portfólio</p>
          <p className="text-sm text-muted-foreground mt-2">Execute o modelo para gerar recomendações.</p>
        </CardContent>
      </Card>
    );
  }

  const activeTrades = comparison.trades.filter((t: any) => t.action !== 'HOLD');
  const hasChanges = activeTrades.length > 0;
  const plan = d.rebalancingPlan;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold flex items-center gap-2">
            <ArrowLeftRight className="w-5 h-5 text-primary" />
            Rebalanceamento
          </h2>
          <p className="text-sm text-muted-foreground mt-1">
            Comparação posições atuais vs recomendação do modelo
            {d.modelRunDate && <span className="text-primary ml-1">({d.modelRunDate})</span>}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => refetch()} className="gap-1">
            <RefreshCw className="w-3.5 h-3.5" /> Atualizar
          </Button>
          {hasChanges && !confirmRebalance && (
            <Button
              size="sm"
              className="gap-1 bg-primary hover:bg-primary/90"
              onClick={() => setConfirmRebalance(true)}
            >
              <Zap className="w-3.5 h-3.5" /> Executar Rebalanceamento
            </Button>
          )}
        </div>
      </div>

      {/* Confirmation Banner */}
      <AnimatePresence>
        {confirmRebalance && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
          >
            <Card className="bg-amber-500/10 border-amber-500/30">
              <CardContent className="py-4">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <AlertTriangle className="w-5 h-5 text-amber-400" />
                    <div>
                      <p className="text-sm font-medium text-amber-400">Confirmar Rebalanceamento</p>
                      <p className="text-xs text-muted-foreground">
                        {activeTrades.length} ordens serão criadas. Custo estimado: {fmtBrl(plan?.estimatedCostBrl || 0)} ({(plan?.estimatedCostBps || 0).toFixed(1)} bps).
                      </p>
                    </div>
                  </div>
                  <div className="flex gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setConfirmRebalance(false)}
                    >
                      Cancelar
                    </Button>
                    <Button
                      size="sm"
                      className="bg-amber-500 hover:bg-amber-600 text-black"
                      onClick={() => {
                        rebalanceMutation.mutate();
                        setConfirmRebalance(false);
                      }}
                      disabled={rebalanceMutation.isPending}
                    >
                      {rebalanceMutation.isPending ? (
                        <Loader2 className="w-4 h-4 animate-spin" />
                      ) : (
                        <>
                          <Check className="w-4 h-4 mr-1" /> Confirmar
                        </>
                      )}
                    </Button>
                  </div>
                </div>
              </CardContent>
            </Card>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Summary KPIs */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <Card className="bg-card border-border">
          <CardContent className="pt-3 pb-3">
            <p className="text-[10px] text-muted-foreground uppercase tracking-wider">AUM</p>
            <p className="text-base font-data font-bold">{fmtBrl(d.config?.aumBrl || 0)}</p>
          </CardContent>
        </Card>
        <Card className="bg-card border-border">
          <CardContent className="pt-3 pb-3">
            <p className="text-[10px] text-muted-foreground uppercase tracking-wider">Vol Target</p>
            <p className="text-base font-data font-bold">{((d.config?.volTargetAnnual || 0) * 100).toFixed(1)}% a.a.</p>
          </CardContent>
        </Card>
        <Card className="bg-card border-border">
          <CardContent className="pt-3 pb-3">
            <p className="text-[10px] text-muted-foreground uppercase tracking-wider">VaR 95%</p>
            <p className="text-base font-data font-bold text-rose-400">{fmtBrl(d.var?.varDaily95Brl || 0)}</p>
          </CardContent>
        </Card>
        <Card className="bg-card border-border">
          <CardContent className="pt-3 pb-3">
            <p className="text-[10px] text-muted-foreground uppercase tracking-wider">Alavancagem</p>
            <p className="text-base font-data font-bold">{(d.exposure?.grossLeverage || 0).toFixed(1)}x</p>
          </CardContent>
        </Card>
        <Card className="bg-card border-border">
          <CardContent className="pt-3 pb-3">
            <p className="text-[10px] text-muted-foreground uppercase tracking-wider">Status</p>
            <p className={`text-base font-bold ${hasChanges ? 'text-amber-400' : 'text-emerald-400'}`}>
              {hasChanges ? `${activeTrades.length} trades` : 'Alinhado'}
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Weight Comparison */}
      <Card className="bg-card border-border">
        <CardHeader className="pb-3">
          <CardTitle className="text-sm flex items-center gap-2">
            <BarChart3 className="w-4 h-4 text-primary" />
            Comparação de Pesos — Atual vs Alvo
          </CardTitle>
          <CardDescription className="text-xs">
            Barras verdes indicam aumento de peso, vermelhas indicam redução
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            <div className="flex items-center gap-2 text-[10px] text-muted-foreground uppercase tracking-wider mb-2">
              <span className="w-24">Instrumento</span>
              <span className="w-12 text-right">Atual</span>
              <span className="flex-1 text-center">Diferença</span>
              <span className="w-12">Alvo</span>
              <span className="w-16 text-center">Delta</span>
            </div>
            {comparison.rows.map(row => (
              <div key={row.instrument} className="flex items-center gap-2">
                <div className="w-24 flex items-center gap-2">
                  <div className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: row.color }} />
                  <span className="text-xs font-medium truncate">{row.label.split(' (')[0]}</span>
                </div>
                <WeightDiffBar
                  current={row.currentWeight}
                  target={row.targetWeight}
                  maxAbs={comparison.maxWeightAbs}
                />
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Positions Comparison Table */}
      <Card className="bg-card border-border">
        <CardHeader className="pb-3">
          <CardTitle className="text-sm flex items-center gap-2">
            <Target className="w-4 h-4 text-primary" />
            Posições Detalhadas — Atual → Alvo
          </CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Instrumento</TableHead>
                <TableHead>Ticker B3</TableHead>
                <TableHead className="text-center">Direção</TableHead>
                <TableHead className="text-right">Contratos Atual</TableHead>
                <TableHead className="text-center">→</TableHead>
                <TableHead className="text-right">Contratos Alvo</TableHead>
                <TableHead className="text-right">Delta</TableHead>
                <TableHead className="text-right">Notional Alvo</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {comparison.rows.map(row => {
                const delta = row.targetContracts - row.currentContracts;
                return (
                  <TableRow key={row.instrument} className={row.trade?.action !== 'HOLD' ? 'bg-primary/5' : ''}>
                    <TableCell>
                      <div className="flex items-center gap-2">
                        <div className="w-2 h-2 rounded-full" style={{ backgroundColor: row.color }} />
                        <span className="font-medium text-sm">{row.label}</span>
                      </div>
                    </TableCell>
                    <TableCell className="font-data text-primary">{row.b3Ticker}</TableCell>
                    <TableCell className="text-center">
                      <div className="flex items-center justify-center gap-1">
                        <Badge variant="outline" className="text-[10px]">
                          {row.currentDirection === 'long' ? '↑' : row.currentDirection === 'short' ? '↓' : '—'}
                        </Badge>
                        <ArrowRight className="w-3 h-3 text-muted-foreground" />
                        <Badge
                          variant="outline"
                          className={`text-[10px] ${
                            row.targetDirection === 'long' ? 'text-emerald-400 border-emerald-500/30' :
                            row.targetDirection === 'short' ? 'text-rose-400 border-rose-500/30' : ''
                          }`}
                        >
                          {row.targetDirection === 'long' ? '↑ LONG' : row.targetDirection === 'short' ? '↓ SHORT' : '—'}
                        </Badge>
                      </div>
                    </TableCell>
                    <TableCell className="text-right font-data">{fmtNum(row.currentContracts)}</TableCell>
                    <TableCell className="text-center text-muted-foreground">→</TableCell>
                    <TableCell className="text-right font-data font-bold">{fmtNum(row.targetContracts)}</TableCell>
                    <TableCell className="text-right">
                      <span className={`font-data font-bold ${
                        delta > 0 ? 'text-emerald-400' : delta < 0 ? 'text-rose-400' : 'text-muted-foreground'
                      }`}>
                        {delta > 0 ? '+' : ''}{fmtNum(delta)}
                      </span>
                    </TableCell>
                    <TableCell className="text-right font-data text-muted-foreground">
                      {fmtBrl(row.targetNotional)}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {/* Trade Orders */}
      {hasChanges && (
        <Card className="bg-card border-border border-primary/30">
          <CardHeader className="pb-3">
            <CardTitle className="text-sm flex items-center gap-2">
              <ArrowUpDown className="w-4 h-4 text-primary" />
              Ordens de Execução
              <Badge variant="outline" className="ml-2">{activeTrades.length} ordens</Badge>
            </CardTitle>
            <CardDescription className="text-xs">
              Ordens a serem executadas na B3 para alinhar o portfólio com o modelo
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Instrumento</TableHead>
                  <TableHead>Ticker</TableHead>
                  <TableHead>Ação</TableHead>
                  <TableHead className="text-right">Contratos</TableHead>
                  <TableHead className="text-right">Notional</TableHead>
                  <TableHead className="text-right">Custo Est.</TableHead>
                  <TableHead>Motivo</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(showAllTrades ? comparison.trades : activeTrades).map((trade: any, idx: number) => (
                  <TableRow key={idx} className={trade.action !== 'HOLD' ? 'bg-primary/5' : ''}>
                    <TableCell>
                      <div className="flex items-center gap-2">
                        <div className="w-2 h-2 rounded-full" style={{ backgroundColor: INSTRUMENT_COLORS[trade.instrument] || '#888' }} />
                        <span className="font-medium text-sm">{INSTRUMENT_LABELS[trade.instrument] || trade.instrument}</span>
                      </div>
                    </TableCell>
                    <TableCell className="font-data text-primary font-bold">{trade.b3Ticker}</TableCell>
                    <TableCell><ActionBadge action={trade.action} /></TableCell>
                    <TableCell className="text-right">
                      <span className={`font-data font-bold ${
                        trade.contractsDelta > 0 ? 'text-emerald-400' :
                        trade.contractsDelta < 0 ? 'text-rose-400' : 'text-muted-foreground'
                      }`}>
                        {trade.contractsDelta > 0 ? '+' : ''}{fmtNum(trade.contractsDelta)}
                      </span>
                      <span className="text-xs text-muted-foreground ml-1">
                        ({trade.currentContracts} → {trade.targetContracts})
                      </span>
                    </TableCell>
                    <TableCell className="text-right font-data">{fmtBrl(Math.abs(trade.notionalDeltaBrl))}</TableCell>
                    <TableCell className="text-right font-data text-amber-400">{fmtBrl(trade.estimatedCostBrl)}</TableCell>
                    <TableCell className="text-xs text-muted-foreground max-w-[200px] truncate">
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <span className="cursor-help">{trade.reason}</span>
                        </TooltipTrigger>
                        <TooltipContent side="left" className="max-w-[300px]">
                          <p className="text-xs">{trade.reason}</p>
                        </TooltipContent>
                      </Tooltip>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            {comparison.trades.length > activeTrades.length && (
              <Button
                variant="ghost"
                size="sm"
                className="mt-2 text-xs"
                onClick={() => setShowAllTrades(!showAllTrades)}
              >
                {showAllTrades ? 'Ocultar posições mantidas' : `Mostrar todas (${comparison.trades.length} total)`}
              </Button>
            )}
          </CardContent>
        </Card>
      )}

      {/* No changes needed */}
      {!hasChanges && (
        <Card className="bg-emerald-500/5 border-emerald-500/20">
          <CardContent className="py-8 text-center">
            <Check className="w-10 h-10 text-emerald-400 mx-auto mb-3" />
            <p className="text-lg font-medium text-emerald-400">Portfólio Alinhado</p>
            <p className="text-sm text-muted-foreground mt-2">
              As posições atuais estão alinhadas com a recomendação do modelo. Nenhuma ação necessária.
            </p>
          </CardContent>
        </Card>
      )}

      {/* Cost Breakdown */}
      {hasChanges && <CostBreakdown plan={plan} />}

      {/* Interpretation */}
      {d.interpretation && (
        <Card className="bg-card border-border">
          <CardHeader className="pb-3">
            <CardTitle className="text-sm">Racional do Modelo</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {d.interpretation.macroView && (
              <p className="text-sm text-muted-foreground">{d.interpretation.macroView}</p>
            )}
            {d.interpretation.positionRationale && (
              <div className="space-y-2">
                {Object.entries(d.interpretation.positionRationale).map(([inst, rationale]) => (
                  <div key={inst} className="p-2.5 rounded-lg bg-secondary/30 border border-border">
                    <div className="flex items-center gap-2 mb-1">
                      <div className="w-2 h-2 rounded-full" style={{ backgroundColor: INSTRUMENT_COLORS[inst] || '#888' }} />
                      <p className="text-xs text-primary font-semibold uppercase tracking-wider">
                        {INSTRUMENT_LABELS[inst] || inst}
                      </p>
                    </div>
                    <p className="text-xs text-muted-foreground">{rationale as string}</p>
                  </div>
                ))}
              </div>
            )}
            {d.interpretation.actionItems && (
              <div className="mt-3">
                <p className="text-xs text-muted-foreground uppercase tracking-wider mb-2">Checklist de Execução</p>
                <ul className="space-y-1.5">
                  {d.interpretation.actionItems.map((item: string, idx: number) => (
                    <li key={idx} className="flex items-start gap-2 text-xs text-muted-foreground">
                      <ChevronRight className="w-3.5 h-3.5 mt-0.5 text-primary shrink-0" />{item}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
