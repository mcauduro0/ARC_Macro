/**
 * MobilePortfolioTab — Full trade details, contracts, rationale, history, risk
 * Institutional-grade portfolio view optimized for mobile
 */

import { useState, useMemo, type ReactNode } from 'react';
import { Link } from 'wouter';
import { motion, AnimatePresence } from 'framer-motion';
import { Card, CardContent } from '@/components/ui/card';
import {
  ChevronDown,
  ChevronRight,
  TrendingUp,
  TrendingDown,
  Minus,
  BarChart3,
  Shield,
  Target,
  Zap,
  ArrowUpRight,
  ArrowDownRight,
  Percent,
  FileText,
  Clock,
  AlertTriangle,
  Activity,
  DollarSign,
  Info,
  Crosshair,
  PieChart,
  Settings,
} from 'lucide-react';
import { BacktestPanel } from '@/components/BacktestPanel';
import { RstarBacktestPanel } from '@/components/RstarBacktestPanel';
import { CombinedStressPanel } from '@/components/CombinedStressPanel';
import { StressTestPanel } from '@/components/StressTestPanel';
import { ActionPanel } from '@/components/ActionPanel';
import type { MacroDashboard, AssetPosition, BacktestData, RstarTsPoint } from '@/hooks/useModelData';

interface Props {
  dashboard: MacroDashboard;
  backtest?: BacktestData | null;
  rstarTs?: RstarTsPoint[];
  shapImportance?: Record<string, Record<string, { mean_abs: number; current: number; rank: number }>> | null;
}

// ── Contract Specifications ───────────────────────────────────────────────

interface ContractSpec {
  ticker: string;
  exchange: string;
  maturity: string;
  type: string;
  currency: string;
  notionalBase: string;
  dv01Approx: string;
}

const CONTRACT_SPECS: Record<string, ContractSpec> = {
  fx: {
    ticker: 'DOL / WDO',
    exchange: 'B3',
    maturity: 'DOL G26 (Fev/26)',
    type: 'Futuro de Dólar',
    currency: 'BRL',
    notionalBase: 'DOL: USD 50k / WDO: USD 10k',
    dv01Approx: '~R$500/pip (DOL)',
  },
  front: {
    ticker: 'DI1F (1Y)',
    exchange: 'B3',
    maturity: 'Jan/27 (F27)',
    type: 'Futuro de DI',
    currency: 'BRL',
    notionalBase: 'R$100k por contrato',
    dv01Approx: '~R$95/bp',
  },
  belly: {
    ticker: 'DI1F (2-5Y)',
    exchange: 'B3',
    maturity: 'Jan/29 (F29)',
    type: 'Futuro de DI',
    currency: 'BRL',
    notionalBase: 'R$100k por contrato',
    dv01Approx: '~R$350/bp',
  },
  long: {
    ticker: 'DI1F (10Y)',
    exchange: 'B3',
    maturity: 'Jan/36 (F36)',
    type: 'Futuro de DI',
    currency: 'BRL',
    notionalBase: 'R$100k por contrato',
    dv01Approx: '~R$800/bp',
  },
  hard: {
    ticker: 'DDI (Cupom Cambial)',
    exchange: 'B3',
    maturity: 'DDI F27 (Jan/27)',
    type: 'Futuro de Cupom Cambial',
    currency: 'USD',
    notionalBase: 'USD 50k por contrato',
    dv01Approx: '~USD 5/bp',
  },
  ntnb: {
    ticker: 'NTN-B (IPCA+)',
    exchange: 'B3 / Tesouro Direto',
    maturity: 'NTN-B 2035',
    type: 'Título Público Indexado',
    currency: 'BRL',
    notionalBase: 'R$1k VNA',
    dv01Approx: '~R$7.5/bp',
  },
};

const INSTRUMENT_LABELS: Record<string, string> = {
  fx: 'DOL Futuro (Câmbio)',
  front: 'DI Front (1Y)',
  belly: 'DI Belly (2-5Y)',
  long: 'DI Long (10Y)',
  hard: 'Cupom Cambial (DDI)',
    ntnb: 'NTN-B (Cupom de Inflação)',
};

const FEATURE_LABELS: Record<string, string> = {
  Z_dxy: 'Dólar Index',
  Z_vix: 'VIX',
  Z_cds_br: 'CDS Brasil',
  Z_real_diff: 'Diferencial Real',
  Z_tot: 'Termos de Troca',
  Z_fiscal: 'Risco Fiscal',
  Z_beer: 'BEER FV',
  Z_ewz: 'EWZ',
  Z_iron_ore: 'Minério de Ferro',
  Z_policy_gap: 'Gap de Política',
  Z_term_premium: 'Term Premium',
  Z_infl_surprise: 'Surpresa Inflação',
  Z_hy_spread: 'HY Spread',
  Z_bop: 'Balança Pagamentos',
  Z_cip_basis: 'CIP Basis',
  Z_reer_gap: 'REER Gap',
  carry_fx: 'Carry FX',
  carry_front: 'Carry Front',
  carry_belly: 'Carry Belly',
  carry_long: 'Carry Long',
  carry_hard: 'Carry DDI',
  rstar_regime_signal: 'Sinal Regime r*',
  mu_fx_val: 'Valor Justo FX',
};

// ── Collapsible Section ────────────────────────────────────────────────────

function MobileSection({
  title,
  icon: Icon,
  children,
  defaultOpen = false,
  badge,
}: {
  title: string;
  icon: typeof Shield;
  children: ReactNode;
  defaultOpen?: boolean;
  badge?: string;
}) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className="border-b border-border/30 last:border-b-0">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-4 py-3.5 active:bg-accent/30 transition-colors"
      >
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center">
            <Icon className="w-4 h-4 text-primary" />
          </div>
          <span className="text-sm font-medium text-foreground">{title}</span>
          {badge && (
            <span className="px-1.5 py-0.5 rounded-md bg-primary/10 text-primary text-[10px] font-semibold">
              {badge}
            </span>
          )}
        </div>
        <motion.div
          animate={{ rotate: open ? 180 : 0 }}
          transition={{ duration: 0.2 }}
        >
          <ChevronDown className="w-4 h-4 text-muted-foreground" />
        </motion.div>
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.25 }}
            className="overflow-hidden"
          >
            <div className="px-2 pb-4">
              {children}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// ── Trade Detail Card ─────────────────────────────────────────────────────

function TradeDetailCard({
  instrumentKey,
  position,
  spec,
  shapDrivers,
  regime,
  attribution,
  ic,
  hitRate,
  delay = 0,
}: {
  instrumentKey: string;
  position: AssetPosition;
  spec: ContractSpec;
  shapDrivers: Array<{ name: string; label: string; value: number; direction: string }>;
  regime: string;
  attribution?: number;
  ic?: number;
  hitRate?: number;
  delay?: number;
}) {
  const [expanded, setExpanded] = useState(false);
  const isLong = position.direction?.toLowerCase().includes('long');
  const isShort = position.direction?.toLowerCase().includes('short');
  const isFlat = position.weight === 0;

  const dirLabel = isFlat ? 'FLAT' : position.direction || 'N/A';
  const dirIcon = isFlat ? <Minus className="w-3.5 h-3.5" /> : isLong ? <ArrowUpRight className="w-3.5 h-3.5" /> : <ArrowDownRight className="w-3.5 h-3.5" />;

  // Use static Tailwind classes to avoid purge issues
  const borderClass = isFlat ? 'border-amber-400/20' : isLong ? 'border-emerald-400/20' : isShort ? 'border-rose-400/20' : 'border-amber-400/20';
  const badgeBg = isFlat ? 'bg-amber-400/10 text-amber-400' : isLong ? 'bg-emerald-400/10 text-emerald-400' : isShort ? 'bg-rose-400/10 text-rose-400' : 'bg-amber-400/10 text-amber-400';
  const weightColor = isFlat ? 'text-amber-400' : isLong ? 'text-emerald-400' : isShort ? 'text-rose-400' : 'text-amber-400';
  const barBg = isFlat ? 'bg-amber-400/60' : isLong ? 'bg-emerald-400/60' : isShort ? 'bg-rose-400/60' : 'bg-amber-400/60';

  // Estimate notional from risk_unit (simplified)
  const estimatedContracts = Math.abs(position.weight) > 0
    ? Math.max(1, Math.round(Math.abs(position.weight) * 100))
    : 0;

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay, duration: 0.3 }}
    >
      <Card className={`bg-card/90 ${borderClass} border overflow-hidden`}>
        {/* Header — always visible */}
        <button
          onClick={() => setExpanded(!expanded)}
          className="w-full text-left"
        >
          <CardContent className="p-3.5">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                <span className="text-sm font-semibold text-foreground">
                  {INSTRUMENT_LABELS[instrumentKey] || instrumentKey}
                </span>
                <span className={`text-[10px] font-mono text-muted-foreground`}>
                  {spec.ticker}
                </span>
              </div>
              <div className={`flex items-center gap-1 px-2 py-0.5 rounded-full ${badgeBg} text-[11px] font-bold`}>
                {dirIcon}
                {dirLabel}
              </div>
            </div>

            {/* Key metrics row */}
            <div className="grid grid-cols-4 gap-2 mb-2">
              <div>
                <span className="text-[9px] text-muted-foreground uppercase block">Peso</span>
                <span className={`font-data text-sm font-bold ${weightColor}`}>
                  {(position.weight * 100).toFixed(1)}%
                </span>
              </div>
              <div>
                <span className="text-[9px] text-muted-foreground uppercase block">E[R] 6M</span>
                <span className={`font-data text-sm font-bold ${position.expected_return_6m > 0 ? 'text-emerald-400' : position.expected_return_6m < 0 ? 'text-rose-400' : 'text-foreground'}`}>
                  {position.expected_return_6m > 0 ? '+' : ''}{position.expected_return_6m.toFixed(2)}%
                </span>
              </div>
              <div>
                <span className="text-[9px] text-muted-foreground uppercase block">Sharpe</span>
                <span className={`font-data text-sm font-bold ${position.sharpe > 0.5 ? 'text-emerald-400' : position.sharpe > 0 ? 'text-amber-400' : 'text-rose-400'}`}>
                  {position.sharpe.toFixed(2)}
                </span>
              </div>
              <div>
                <span className="text-[9px] text-muted-foreground uppercase block">Vol</span>
                <span className="font-data text-sm font-bold text-foreground">
                  {position.annualized_vol.toFixed(1)}%
                </span>
              </div>
            </div>

            {/* Risk contribution bar */}
            <div className="flex items-center gap-2">
              <span className="text-[9px] text-muted-foreground w-16">Risk Contrib</span>
              <div className="flex-1 h-1.5 bg-muted/30 rounded-full overflow-hidden">
                <div
                  className={`h-full ${barBg} rounded-full transition-all`}
                  style={{ width: `${Math.min(100, position.risk_contribution * 100)}%` }}
                />
              </div>
              <span className="font-data text-[10px] text-muted-foreground w-10 text-right">
                {(position.risk_contribution * 100).toFixed(1)}%
              </span>
            </div>

            {/* Expand indicator */}
            <div className="flex items-center justify-center mt-2 text-muted-foreground/50">
              <motion.div animate={{ rotate: expanded ? 180 : 0 }} transition={{ duration: 0.2 }}>
                <ChevronDown className="w-3.5 h-3.5" />
              </motion.div>
            </div>
          </CardContent>
        </button>

        {/* Expanded Details */}
        <AnimatePresence initial={false}>
          {expanded && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.25 }}
              className="overflow-hidden"
            >
              <div className="px-3.5 pb-4 space-y-4 border-t border-border/20 pt-3">
                {/* Contract Specifications */}
                <div>
                  <h4 className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider mb-2 flex items-center gap-1.5">
                    <FileText className="w-3 h-3" />
                    Especificação do Contrato
                  </h4>
                  <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 bg-muted/10 rounded-lg p-2.5">
                    <div>
                      <span className="text-[9px] text-muted-foreground">Ticker</span>
                      <p className="font-data text-[11px] text-foreground font-medium">{spec.ticker}</p>
                    </div>
                    <div>
                      <span className="text-[9px] text-muted-foreground">Exchange</span>
                      <p className="font-data text-[11px] text-foreground font-medium">{spec.exchange}</p>
                    </div>
                    <div>
                      <span className="text-[9px] text-muted-foreground">Maturidade</span>
                      <p className="font-data text-[11px] text-foreground font-medium">{spec.maturity}</p>
                    </div>
                    <div>
                      <span className="text-[9px] text-muted-foreground">Tipo</span>
                      <p className="font-data text-[11px] text-foreground font-medium">{spec.type}</p>
                    </div>
                    <div>
                      <span className="text-[9px] text-muted-foreground">Notional Base</span>
                      <p className="font-data text-[11px] text-foreground font-medium">{spec.notionalBase}</p>
                    </div>
                    <div>
                      <span className="text-[9px] text-muted-foreground">DV01 Aprox</span>
                      <p className="font-data text-[11px] text-foreground font-medium">{spec.dv01Approx}</p>
                    </div>
                  </div>
                </div>

                {/* Sizing Estimativa */}
                <div>
                  <h4 className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider mb-2 flex items-center gap-1.5">
                    <DollarSign className="w-3 h-3" />
                    Sizing Estimativa
                  </h4>
                  <div className="grid grid-cols-3 gap-2">
                    <div className="bg-muted/10 rounded-lg p-2 text-center">
                      <span className="text-[9px] text-muted-foreground block">Contratos Est.</span>
                      <span className="font-data text-sm font-bold text-foreground">{estimatedContracts}</span>
                    </div>
                    <div className="bg-muted/10 rounded-lg p-2 text-center">
                      <span className="text-[9px] text-muted-foreground block">Risk Unit</span>
                      <span className="font-data text-sm font-bold text-foreground">{position.risk_unit.toFixed(4)}</span>
                    </div>
                    <div className="bg-muted/10 rounded-lg p-2 text-center">
                      <span className="text-[9px] text-muted-foreground block">E[R] 3M</span>
                      <span className={`font-data text-sm font-bold ${position.expected_return_3m > 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                        {position.expected_return_3m > 0 ? '+' : ''}{position.expected_return_3m.toFixed(2)}%
                      </span>
                    </div>
                  </div>
                </div>

                {/* Trade Rationale — SHAP Drivers */}
                <div>
                  <h4 className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider mb-2 flex items-center gap-1.5">
                    <Crosshair className="w-3 h-3" />
                    Racional do Trade
                  </h4>
                  <div className="bg-muted/10 rounded-lg p-2.5 space-y-2">
                    <div className="flex items-center gap-2 mb-1.5">
                      <span className="text-[9px] text-muted-foreground">Regime:</span>
                      <span className="px-1.5 py-0.5 rounded bg-primary/10 text-primary text-[10px] font-semibold">
                        {regime}
                      </span>
                    </div>
                    <p className="text-[10px] text-muted-foreground mb-2">
                      Top 3 drivers SHAP (contribuição atual para o score):
                    </p>
                    {shapDrivers.map((driver, i) => (
                      <div key={driver.name} className="flex items-center gap-2">
                        <span className="text-[10px] text-muted-foreground w-4">{i + 1}.</span>
                        <span className="text-[11px] text-foreground flex-1 truncate">{driver.label}</span>
                        <div className="flex items-center gap-1">
                          {driver.value > 0 ? (
                            <ArrowUpRight className="w-3 h-3 text-emerald-400" />
                          ) : (
                            <ArrowDownRight className="w-3 h-3 text-rose-400" />
                          )}
                          <span className={`font-data text-[11px] font-semibold ${driver.value > 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                            {driver.value > 0 ? '+' : ''}{(driver.value * 100).toFixed(3)}
                          </span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Backtest Performance */}
                {(attribution != null || ic != null || hitRate != null) && (
                  <div>
                    <h4 className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider mb-2 flex items-center gap-1.5">
                      <Activity className="w-3 h-3" />
                      Performance Histórica
                    </h4>
                    <div className="grid grid-cols-3 gap-2">
                      {attribution != null && (
                        <div className="bg-muted/10 rounded-lg p-2 text-center">
                          <span className="text-[9px] text-muted-foreground block">Attribution</span>
                          <span className={`font-data text-sm font-bold ${attribution > 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                            {attribution > 0 ? '+' : ''}{attribution.toFixed(1)}%
                          </span>
                        </div>
                      )}
                      {ic != null && (
                        <div className="bg-muted/10 rounded-lg p-2 text-center">
                          <span className="text-[9px] text-muted-foreground block">IC</span>
                          <span className={`font-data text-sm font-bold ${ic > 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                            {ic > 0 ? '+' : ''}{ic.toFixed(3)}
                          </span>
                        </div>
                      )}
                      {hitRate != null && (
                        <div className="bg-muted/10 rounded-lg p-2 text-center">
                          <span className="text-[9px] text-muted-foreground block">Hit Rate</span>
                          <span className={`font-data text-sm font-bold ${hitRate > 50 ? 'text-emerald-400' : 'text-rose-400'}`}>
                            {hitRate.toFixed(1)}%
                          </span>
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </Card>
    </motion.div>
  );
}

// ── Overlay Summary Card ──────────────────────────────────────────────────

function OverlaySummary({ dashboard, backtest }: { dashboard: MacroDashboard; backtest?: BacktestData | null }) {
  const metrics = backtest?.summary?.overlay ?? dashboard.overlay_metrics;
  if (!metrics) return null;

  return (
    <Card className="bg-card/90 border-primary/20 border mx-4 mb-4">
      <CardContent className="p-3.5">
        <div className="flex items-center gap-2 mb-3">
          <PieChart className="w-4 h-4 text-primary" />
          <span className="text-xs font-semibold text-foreground uppercase tracking-wider">
            Overlay Portfolio Summary
          </span>
        </div>
        <div className="grid grid-cols-3 gap-3 mb-3">
          <div className="text-center">
            <span className="text-[9px] text-muted-foreground uppercase block">Return</span>
            <span className={`font-data text-base font-bold ${(metrics.total_return || 0) > 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
              {metrics.total_return > 0 ? '+' : ''}{metrics.total_return?.toFixed(1)}%
            </span>
          </div>
          <div className="text-center">
            <span className="text-[9px] text-muted-foreground uppercase block">Sharpe</span>
            <span className={`font-data text-base font-bold ${(metrics.sharpe || 0) > 0.5 ? 'text-emerald-400' : (metrics.sharpe || 0) > 0 ? 'text-amber-400' : 'text-rose-400'}`}>
              {metrics.sharpe?.toFixed(2)}
            </span>
          </div>
          <div className="text-center">
            <span className="text-[9px] text-muted-foreground uppercase block">Max DD</span>
            <span className="font-data text-base font-bold text-rose-400">
              {metrics.max_drawdown?.toFixed(1)}%
            </span>
          </div>
        </div>
        <div className="grid grid-cols-4 gap-2">
          <div className="text-center bg-muted/10 rounded-lg p-1.5">
            <span className="text-[8px] text-muted-foreground block">Ann. Ret</span>
            <span className="font-data text-[11px] font-semibold text-foreground">
              {metrics.annualized_return?.toFixed(1)}%
            </span>
          </div>
          <div className="text-center bg-muted/10 rounded-lg p-1.5">
            <span className="text-[8px] text-muted-foreground block">Ann. Vol</span>
            <span className="font-data text-[11px] font-semibold text-foreground">
              {metrics.annualized_vol?.toFixed(1)}%
            </span>
          </div>
          <div className="text-center bg-muted/10 rounded-lg p-1.5">
            <span className="text-[8px] text-muted-foreground block">Calmar</span>
            <span className="font-data text-[11px] font-semibold text-foreground">
              {metrics.calmar?.toFixed(2)}
            </span>
          </div>
          <div className="text-center bg-muted/10 rounded-lg p-1.5">
            <span className="text-[8px] text-muted-foreground block">Win Rate</span>
            <span className={`font-data text-[11px] font-semibold ${(metrics.win_rate || 0) > 50 ? 'text-emerald-400' : 'text-rose-400'}`}>
              {metrics.win_rate?.toFixed(0)}%
            </span>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

// ── Trade History Mini-Chart ──────────────────────────────────────────────

function TradeHistoryMini({ backtest, instrumentKey }: { backtest?: BacktestData | null; instrumentKey: string }) {
  const pnlKey = `${instrumentKey}_pnl` as keyof (typeof backtest extends { timeseries: (infer T)[] } ? T : never);
  const weightKey = `weight_${instrumentKey}` as string;

  const recentTrades = useMemo(() => {
    if (!backtest?.timeseries) return [];
    const ts = backtest.timeseries as any[];
    // Get last 12 months of data
    const recent = ts.slice(-12);
    return recent.map((point: any) => ({
      date: point.date,
      pnl: point[pnlKey] || 0,
      weight: point[weightKey] || 0,
    }));
  }, [backtest?.timeseries, pnlKey, weightKey]);

  if (recentTrades.length === 0) return null;

  const maxAbs = Math.max(...recentTrades.map(t => Math.abs(t.pnl as number)), 0.01);

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between">
        <span className="text-[9px] text-muted-foreground uppercase">Últimos 12M P&L</span>
        <span className="text-[9px] text-muted-foreground">
          Total: <span className={`font-data font-semibold ${recentTrades.reduce((s, t) => s + (t.pnl as number), 0) > 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
            {(recentTrades.reduce((s, t) => s + (t.pnl as number), 0) * 100).toFixed(2)}%
          </span>
        </span>
      </div>
      <div className="flex items-end gap-0.5 h-10">
        {recentTrades.map((trade, i) => {
          const pnl = trade.pnl as number;
          const height = Math.max(2, (Math.abs(pnl) / maxAbs) * 100);
          return (
            <div
              key={i}
              className="flex-1 flex flex-col items-center justify-end"
              title={`${trade.date}: ${(pnl * 100).toFixed(2)}%`}
            >
              <div
                className={`w-full rounded-sm ${pnl >= 0 ? 'bg-emerald-400/60' : 'bg-rose-400/60'}`}
                style={{ height: `${height}%` }}
              />
            </div>
          );
        })}
      </div>
      <div className="flex justify-between text-[8px] text-muted-foreground/50">
        <span>{recentTrades[0]?.date?.slice(0, 7)}</span>
        <span>{recentTrades[recentTrades.length - 1]?.date?.slice(0, 7)}</span>
      </div>
    </div>
  );
}

// ── Attribution Waterfall ─────────────────────────────────────────────────

function AttributionWaterfall({ backtest, dashboard }: { backtest?: BacktestData | null; dashboard: MacroDashboard }) {
  const attribution = backtest?.summary?.attribution_pct ?? dashboard.attribution;
  if (!attribution) return null;

  const items = Object.entries(attribution)
    .map(([key, value]) => ({
      key,
      label: INSTRUMENT_LABELS[key] || key,
      value: value as number,
    }))
    .sort((a, b) => b.value - a.value);

  const maxAbs = Math.max(...items.map(i => Math.abs(i.value)), 1);
  const total = items.reduce((s, i) => s + i.value, 0);

  return (
    <div className="space-y-2">
      {items.map((item) => (
        <div key={item.key} className="flex items-center gap-2">
          <span className="text-[10px] text-muted-foreground w-20 truncate">{item.label}</span>
          <div className="flex-1 h-4 bg-muted/20 rounded-full overflow-hidden relative">
            <div
              className={`h-full rounded-full ${item.value >= 0 ? 'bg-emerald-400/50' : 'bg-rose-400/50'}`}
              style={{
                width: `${(Math.abs(item.value) / maxAbs) * 100}%`,
                marginLeft: item.value < 0 ? 'auto' : 0,
              }}
            />
          </div>
          <span className={`font-data text-[11px] font-semibold w-12 text-right ${item.value >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
            {item.value >= 0 ? '+' : ''}{item.value.toFixed(1)}%
          </span>
        </div>
      ))}
      <div className="flex items-center gap-2 border-t border-border/30 pt-1.5">
        <span className="text-[10px] font-semibold text-foreground w-20">Total</span>
        <div className="flex-1" />
        <span className={`font-data text-[11px] font-bold w-12 text-right ${total >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
          {total >= 0 ? '+' : ''}{total.toFixed(1)}%
        </span>
      </div>
    </div>
  );
}

// ── Main Component ─────────────────────────────────────────────────────────

export function MobilePortfolioTab({ dashboard, backtest, rstarTs, shapImportance }: Props) {
  const positions = dashboard.positions;
  const regime = dashboard.dominant_regime || Object.keys(dashboard.regime_probs || {})[0] || 'carry';

  // Build SHAP drivers per instrument
  const shapDriversMap = useMemo(() => {
    const map: Record<string, Array<{ name: string; label: string; value: number; direction: string }>> = {};
    if (!shapImportance) return map;

    for (const [inst, features] of Object.entries(shapImportance)) {
      const sorted = Object.entries(features)
        .map(([name, data]) => ({
          name,
          label: FEATURE_LABELS[name] || name,
          value: data.current,
          direction: data.current > 0 ? 'positive' : 'negative',
        }))
        .sort((a, b) => Math.abs(b.value) - Math.abs(a.value))
        .slice(0, 3);
      map[inst] = sorted;
    }
    return map;
  }, [shapImportance]);

  // Get attribution, IC, hit rates from backtest summary
  const attribution = backtest?.summary?.attribution_pct ?? dashboard.attribution;
  const icPerInst = backtest?.summary?.ic_per_instrument ?? dashboard.ic_per_instrument;
  const hitRates = backtest?.summary?.hit_rates ?? dashboard.hit_rates;

  const instrumentOrder = ['fx', 'front', 'belly', 'long', 'hard', 'ntnb'];

  return (
    <div className="py-2">
      {/* Header */}
      <div className="px-4 py-2 mb-1">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold text-foreground">Portfólio & Trades</h2>
            <p className="text-xs text-muted-foreground">Posições, contratos, racional e histórico</p>
          </div>
          <Link
            href="/portfolio"
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-primary/30 bg-primary/5 text-primary text-xs font-semibold hover:bg-primary/10 transition-all"
          >
            <Settings className="w-3.5 h-3.5" />
            Gerenciar
          </Link>
        </div>
      </div>

      {/* Overlay Summary */}
      <OverlaySummary dashboard={dashboard} backtest={backtest} />

      {/* Signal Direction Hero */}
      <div className="px-4 mb-4">
        <Card className={`border ${
          dashboard.direction?.includes('LONG') && dashboard.direction?.includes('BRL')
            ? 'bg-emerald-400/5 border-emerald-400/20'
            : dashboard.direction?.includes('SHORT') && dashboard.direction?.includes('BRL')
            ? 'bg-rose-400/5 border-rose-400/20'
            : 'bg-amber-400/5 border-amber-400/20'
        }`}>
          <CardContent className="p-3 flex items-center justify-between">
            <div>
              <span className="text-[10px] text-muted-foreground uppercase">Sinal Composto</span>
              <p className={`text-base font-bold font-data ${
                dashboard.direction?.includes('LONG') && dashboard.direction?.includes('BRL')
                  ? 'text-emerald-400'
                  : dashboard.direction?.includes('SHORT') && dashboard.direction?.includes('BRL')
                  ? 'text-rose-400'
                  : 'text-amber-400'
              }`}>
                {dashboard.direction || 'NEUTRAL'}
              </p>
            </div>
            <div className="text-right">
              <span className="text-[10px] text-muted-foreground uppercase">Score</span>
              <p className={`text-base font-bold font-data ${
                (dashboard.score_total || 0) > 0 ? 'text-emerald-400' : 'text-rose-400'
              }`}>
                {dashboard.score_total != null ? (dashboard.score_total > 0 ? '+' : '') + dashboard.score_total.toFixed(2) : 'N/A'}
              </p>
            </div>
            <div className="text-right">
              <span className="text-[10px] text-muted-foreground uppercase">Regime</span>
              <p className="text-sm font-semibold text-primary capitalize">{regime}</p>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Trade Cards — Detailed per instrument */}
      <div className="px-4 mb-2">
        <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3 flex items-center gap-2">
          <Target className="w-3.5 h-3.5" />
          Trades Recomendados
        </h3>
        <div className="space-y-3">
          {instrumentOrder.map((key, i) => {
            const pos = positions?.[key as keyof typeof positions];
            if (!pos) return null;
            return (
              <TradeDetailCard
                key={key}
                instrumentKey={key}
                position={pos}
                spec={CONTRACT_SPECS[key]}
                shapDrivers={shapDriversMap[key] || []}
                regime={regime}
                attribution={(attribution as any)?.[key]}
                ic={(icPerInst as any)?.[key]}
                hitRate={(hitRates as any)?.[key]}
                delay={0.05 * i}
              />
            );
          })}
        </div>
      </div>

      {/* Attribution Waterfall */}
      <MobileSection title="Attribution por Instrumento" icon={PieChart} defaultOpen={true}>
        <div className="px-2">
          <AttributionWaterfall backtest={backtest} dashboard={dashboard} />
        </div>
      </MobileSection>

      {/* Trade History per instrument */}
      <MobileSection title="Histórico de P&L (12M)" icon={Clock} defaultOpen={false}>
        <div className="space-y-4 px-2">
          {instrumentOrder.map(key => (
            <div key={key}>
              <span className="text-[10px] font-semibold text-foreground mb-1 block">
                {INSTRUMENT_LABELS[key]}
              </span>
              <TradeHistoryMini backtest={backtest} instrumentKey={key} />
            </div>
          ))}
        </div>
      </MobileSection>

      {/* Backtest P&L */}
      <MobileSection title="Backtest Completo" icon={BarChart3}>
        <div className="overflow-x-auto -mx-2">
          <BacktestPanel backtest={backtest || null} />
        </div>
      </MobileSection>

      {/* r* Signal Backtest */}
      <MobileSection title="r* Signal Backtest" icon={TrendingUp}>
        <div className="overflow-x-auto -mx-2">
          <RstarBacktestPanel rstarTs={rstarTs || []} backtest={backtest || null} />
        </div>
      </MobileSection>

      {/* Stress Tests */}
      <MobileSection title="Stress Tests" icon={Shield}>
        <div className="overflow-x-auto -mx-2">
          <CombinedStressPanel dashboard={dashboard} />
        </div>
      </MobileSection>

      {/* Stress Histórico */}
      <MobileSection title="Stress Histórico" icon={Zap}>
        <div className="overflow-x-auto -mx-2">
          <StressTestPanel dashboard={dashboard} />
        </div>
      </MobileSection>

      {/* Action Panel */}
      <MobileSection title="Sizing & Action" icon={Target}>
        <div className="overflow-x-auto -mx-2">
          <ActionPanel dashboard={dashboard} backtest={backtest || null} />
        </div>
      </MobileSection>
    </div>
  );
}
