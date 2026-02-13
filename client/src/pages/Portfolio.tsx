/**
 * Portfolio Management — Institutional Trading Console
 *
 * Tabs:
 *   1. Setup       — AUM, vol target, instrument preferences
 *   2. Posições    — Model-recommended positions + trade blotter
 *   3. Trades      — Execute pending trades + record manual trades
 *   4. P&L         — Daily/MTD/YTD tracking with attribution
 *   5. Risco       — VaR, stress tests, DV01, exposure
 *   6. Histórico   — Rebalancing timeline + trade history
 */

import { useState, useMemo } from "react";
import { useAuth } from "@/_core/hooks/useAuth";
import { trpc } from "@/lib/trpc";
import { getLoginUrl } from "@/const";
import { Link } from "wouter";
import { motion } from "framer-motion";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Separator } from "@/components/ui/separator";
import { Switch } from "@/components/ui/switch";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Progress } from "@/components/ui/progress";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";

import {
  Loader2, ArrowLeft, BarChart3, Shield, Target, Wallet, Scale,
  Info, ChevronRight, AlertTriangle, CheckCircle2, Settings,
  RefreshCw, ArrowUpDown, TrendingUp, TrendingDown, Clock,
  DollarSign, Activity, Bell, BellOff, History, FileText,
  Plus, X, Check, Edit3, Send, Minus,
} from "lucide-react";

// ============================================================
// Formatters
// ============================================================

const fmtBrl = (v: number) => v.toLocaleString("pt-BR", { style: "currency", currency: "BRL", maximumFractionDigits: 0 });
const fmtBrlFull = (v: number) => v.toLocaleString("pt-BR", { style: "currency", currency: "BRL", minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fmtUsd = (v: number) => `$ ${v.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
const fmtPct = (v: number) => `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`;
const fmtNum = (v: number) => v.toLocaleString("pt-BR");

function instrumentLabel(inst: string) {
  const map: Record<string, string> = {
    fx: "FX (Câmbio)", front: "Front-End (DI 1Y)", belly: "Belly (DI 5Y)",
    long: "Long-End (DI 10Y)", hard: "Hard Currency",
  };
  return map[inst] || inst;
}

function instrumentShort(inst: string) {
  const map: Record<string, string> = { fx: "FX", front: "Front", belly: "Belly", long: "Long", hard: "Hard" };
  return map[inst] || inst;
}

function directionBadge(dir: string) {
  if (dir === "long") return <Badge className="bg-emerald-500/20 text-emerald-400 border-emerald-500/30 text-xs">LONG</Badge>;
  if (dir === "short") return <Badge className="bg-rose-500/20 text-rose-400 border-rose-500/30 text-xs">SHORT</Badge>;
  return <Badge variant="outline" className="text-xs">FLAT</Badge>;
}

function actionBadge(action: string) {
  if (action === "BUY") return <Badge className="bg-emerald-500/20 text-emerald-400 border-emerald-500/30 text-xs">COMPRA</Badge>;
  if (action === "SELL") return <Badge className="bg-rose-500/20 text-rose-400 border-rose-500/30 text-xs">VENDA</Badge>;
  return <Badge variant="outline" className="text-xs">{action}</Badge>;
}

function statusBadge(status: string) {
  if (status === "pending") return <Badge className="bg-amber-500/20 text-amber-400 border-amber-500/30 text-xs">PENDENTE</Badge>;
  if (status === "executed") return <Badge className="bg-emerald-500/20 text-emerald-400 border-emerald-500/30 text-xs">EXECUTADO</Badge>;
  if (status === "cancelled") return <Badge className="bg-zinc-500/20 text-zinc-400 border-zinc-500/30 text-xs">CANCELADO</Badge>;
  if (status === "partial") return <Badge className="bg-blue-500/20 text-blue-400 border-blue-500/30 text-xs">PARCIAL</Badge>;
  return <Badge variant="outline" className="text-xs">{status}</Badge>;
}

function severityBadge(sev: string) {
  if (sev === "critical") return <Badge className="bg-rose-500/20 text-rose-400 border-rose-500/30 text-xs">CRÍTICO</Badge>;
  if (sev === "warning") return <Badge className="bg-amber-500/20 text-amber-400 border-amber-500/30 text-xs">ATENÇÃO</Badge>;
  return <Badge className="bg-blue-500/20 text-blue-400 border-blue-500/30 text-xs">INFO</Badge>;
}

function pnlColor(v: number) {
  if (v > 0) return "text-emerald-400";
  if (v < 0) return "text-rose-400";
  return "text-muted-foreground";
}

// ============================================================
// Setup Tab
// ============================================================

function SetupTab() {
  const utils = trpc.useUtils();
  const { data: existingConfig, isLoading: configLoading } = trpc.portfolio.config.get.useQuery();
  const saveConfig = trpc.portfolio.config.save.useMutation({
    onSuccess: (data) => {
      if (data.success) {
        toast.success(`Portfólio configurado! Risk Budget: ${fmtBrl(data.riskBudgetBrl)}`);
        utils.portfolio.invalidate();
      }
    },
    onError: (err) => toast.error(err.message),
  });

  const [aumInput, setAumInput] = useState("");
  const [volTarget, setVolTarget] = useState("10");
  const [fxInstrument, setFxInstrument] = useState<"DOL" | "WDO">("WDO");
  const [maxDrawdown, setMaxDrawdown] = useState("-10");
  const [maxLeverage, setMaxLeverage] = useState("5");
  const [enableFx, setEnableFx] = useState(true);
  const [enableFront, setEnableFront] = useState(true);
  const [enableBelly, setEnableBelly] = useState(true);
  const [enableLong, setEnableLong] = useState(true);
  const [enableHard, setEnableHard] = useState(true);
  const [initialized, setInitialized] = useState(false);

  // Populate from existing config
  if (existingConfig && !initialized) {
    setAumInput(String(existingConfig.aumBrl));
    setVolTarget(String(existingConfig.volTargetAnnual * 100));
    setFxInstrument(existingConfig.fxInstrument as "DOL" | "WDO");
    setMaxDrawdown(String((existingConfig.maxDrawdownPct || -10)));
    setMaxLeverage(String(existingConfig.maxLeverageGross || 5));
    setEnableFx(existingConfig.enableFx ?? true);
    setEnableFront(existingConfig.enableFront ?? true);
    setEnableBelly(existingConfig.enableBelly ?? true);
    setEnableLong(existingConfig.enableLong ?? true);
    setEnableHard(existingConfig.enableHard ?? true);
    setInitialized(true);
  }

  const aumValue = parseFloat(aumInput) || 0;
  const volValue = parseFloat(volTarget) / 100;
  const riskBudget = aumValue * volValue;

  const handleSave = () => {
    saveConfig.mutate({
      aumBrl: aumValue,
      volTargetAnnual: volValue,
      fxInstrument,
      enableFx, enableFront, enableBelly, enableLong, enableHard,
      maxDrawdownPct: parseFloat(maxDrawdown),
      maxLeverageGross: parseFloat(maxLeverage),
    });
  };

  if (configLoading) {
    return <div className="flex items-center justify-center py-20"><Loader2 className="w-8 h-8 animate-spin text-primary" /></div>;
  }

  return (
    <div className="max-w-2xl mx-auto space-y-6">
      <Card className="bg-card border-border">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Settings className="w-5 h-5 text-primary" />
            Configuração do Portfólio
          </CardTitle>
          <CardDescription>Defina os parâmetros de risco e instrumentos habilitados.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          {/* AUM */}
          <div className="space-y-2">
            <Label className="text-sm font-semibold">AUM (R$)</Label>
            <Input
              type="number"
              placeholder="100000000"
              value={aumInput}
              onChange={(e) => setAumInput(e.target.value)}
              className="font-data text-lg"
            />
            <p className="text-xs text-muted-foreground">Patrimônio sob gestão em Reais.</p>
          </div>

          {/* Vol Target */}
          <div className="space-y-2">
            <Label className="text-sm font-semibold">Vol Target Anual (%)</Label>
            <Input
              type="number"
              placeholder="10"
              value={volTarget}
              onChange={(e) => setVolTarget(e.target.value)}
              className="font-data"
              min="1" max="50" step="0.5"
            />
            <p className="text-xs text-muted-foreground">Volatilidade alvo anualizada do overlay (ex: 10% = conservador, 15% = moderado).</p>
          </div>

          {/* Risk Budget Preview */}
          <div className="p-4 rounded-lg bg-primary/10 border border-primary/20">
            <p className="text-xs text-muted-foreground uppercase tracking-wider mb-1">Risk Budget Anual</p>
            <p className="font-data text-2xl font-bold text-primary">{fmtBrl(riskBudget)}</p>
            <p className="text-xs text-muted-foreground mt-1">= AUM × Vol Target = {fmtBrl(aumValue)} × {volTarget}%</p>
          </div>

          {/* Limits */}
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label className="text-sm font-semibold">Max Drawdown (%)</Label>
              <Input type="number" value={maxDrawdown} onChange={(e) => setMaxDrawdown(e.target.value)} className="font-data" min="-50" max="-1" step="1" />
            </div>
            <div className="space-y-2">
              <Label className="text-sm font-semibold">Max Alavancagem (x)</Label>
              <Input type="number" value={maxLeverage} onChange={(e) => setMaxLeverage(e.target.value)} className="font-data" min="1" max="20" step="0.5" />
            </div>
          </div>

          {/* FX Instrument */}
          <div className="space-y-2">
            <Label className="text-sm font-semibold">Instrumento FX</Label>
            <Select value={fxInstrument} onValueChange={(v) => setFxInstrument(v as "DOL" | "WDO")}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="DOL">DOL (USD 50.000 / contrato)</SelectItem>
                <SelectItem value="WDO">WDO (USD 10.000 / contrato)</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {/* Instrument Toggles */}
          <div className="space-y-3">
            <Label className="text-sm font-semibold">Instrumentos Habilitados</Label>
            <div className="grid grid-cols-2 gap-3">
              {[
                { label: "FX (Câmbio)", value: enableFx, set: setEnableFx, desc: "DOL/WDO" },
                { label: "Front-End", value: enableFront, set: setEnableFront, desc: "DI1F (1Y)" },
                { label: "Belly", value: enableBelly, set: setEnableBelly, desc: "DI1F (5Y)" },
                { label: "Long-End", value: enableLong, set: setEnableLong, desc: "DI1F (10Y)" },
                { label: "Hard Currency", value: enableHard, set: setEnableHard, desc: "DDI/NTN-B" },
              ].map((item) => (
                <div key={item.label} className="flex items-center justify-between p-3 rounded-lg bg-secondary/30 border border-border">
                  <div>
                    <p className="text-sm font-medium">{item.label}</p>
                    <p className="text-xs text-muted-foreground">{item.desc}</p>
                  </div>
                  <Switch checked={item.value} onCheckedChange={item.set} />
                </div>
              ))}
            </div>
          </div>
        </CardContent>
      </Card>

      <Button onClick={handleSave} disabled={saveConfig.isPending || aumValue < 10000} className="w-full h-12 text-base font-semibold" size="lg">
        {saveConfig.isPending ? <Loader2 className="w-5 h-5 animate-spin mr-2" /> : <CheckCircle2 className="w-5 h-5 mr-2" />}
        {existingConfig ? "Atualizar Configuração" : "Iniciar Portfólio"}
      </Button>
    </div>
  );
}

// ============================================================
// Positions Tab — Model-Recommended Positions + Trade Blotter
// ============================================================

function PositionsTab() {
  const { data: computeResult, isLoading } = trpc.portfolio.compute.useQuery(undefined, { refetchInterval: 60_000 });

  if (isLoading) return <div className="flex items-center justify-center py-20"><Loader2 className="w-8 h-8 animate-spin text-primary" /></div>;

  if (computeResult?.error || !computeResult?.data) {
    return (
      <Card className="bg-card border-border">
        <CardContent className="py-12 text-center">
          <AlertTriangle className="w-10 h-10 text-amber-400 mx-auto mb-4" />
          <p className="text-lg font-medium">{computeResult?.error || "Erro ao computar portfólio"}</p>
          <p className="text-sm text-muted-foreground mt-2">Configure o portfólio na aba Setup primeiro.</p>
        </CardContent>
      </Card>
    );
  }

  const d = computeResult.data;
  const positions = d.positions || [];
  const varResult = d.var;
  const exposure = d.exposure;
  const interp = d.interpretation;
  const plan = d.rebalancingPlan;
  const activeTrades = plan?.trades?.filter((t: any) => t.action !== "HOLD") || [];

  return (
    <div className="space-y-6">
      {/* Top KPI Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <KpiCard label="AUM" value={fmtBrl(d.config.aumBrl)} icon={<Wallet className="w-4 h-4" />} color="text-primary" />
        <KpiCard label="Risk Budget" value={fmtBrl(d.config.riskBudgetBrl)} icon={<Target className="w-4 h-4" />} color="text-amber-400" />
        <KpiCard label="VaR 95% (1d)" value={fmtBrl(varResult.varDaily95Brl)} subtitle={fmtPct(varResult.varDaily95Pct) + " AUM"} icon={<Shield className="w-4 h-4" />} color="text-rose-400" />
        <KpiCard label="Alavancagem" value={`${exposure.grossLeverage.toFixed(1)}x`} subtitle={`Margem: ${exposure.marginUtilizationPct.toFixed(1)}%`} icon={<Scale className="w-4 h-4" />} color="text-cyan-400" />
      </div>

      {/* Interpretation Card */}
      {interp && (
        <Card className="bg-card border-border">
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-base"><Info className="w-4 h-4 text-primary" /> Interpretação Macro</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground leading-relaxed">{interp.macroView}</p>
            <div className="mt-3 p-3 rounded-lg bg-secondary/30 border border-border">
              <p className="text-xs text-muted-foreground uppercase tracking-wider mb-2">Avaliação de Risco</p>
              <p className="text-sm text-foreground/80">{interp.riskAssessment}</p>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Target Positions Table */}
      <Card className="bg-card border-border">
        <CardHeader>
          <CardTitle className="text-base">Posições Alvo do Modelo</CardTitle>
          <CardDescription>Alocação calculada pelo Macro Risk OS para o portfólio configurado.</CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Instrumento</TableHead>
                <TableHead>Direção</TableHead>
                <TableHead>Ticker B3</TableHead>
                <TableHead className="text-right">Contratos</TableHead>
                <TableHead className="text-right">Notional</TableHead>
                <TableHead className="text-right">DV01 / Delta</TableHead>
                <TableHead className="text-right">Risco %</TableHead>
                <TableHead className="text-right">Margem</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {positions.map((pos: any) => (
                <TableRow key={pos.instrument}>
                  <TableCell className="font-medium">{instrumentLabel(pos.instrument)}</TableCell>
                  <TableCell>{directionBadge(pos.direction)}</TableCell>
                  <TableCell className="font-data text-primary">{pos.b3Ticker}</TableCell>
                  <TableCell className="text-right font-data font-bold">{fmtNum(pos.contracts)}</TableCell>
                  <TableCell className="text-right font-data">
                    {pos.instrument === "fx" || pos.instrument === "hard" ? fmtUsd(pos.notionalUsd) : fmtBrl(pos.notionalBrl)}
                  </TableCell>
                  <TableCell className="text-right font-data">
                    {pos.dv01Brl ? `R$ ${pos.dv01Brl.toFixed(0)}/bp` : pos.fxDeltaBrl ? fmtBrl(pos.fxDeltaBrl) : pos.spreadDv01Usd ? `$ ${pos.spreadDv01Usd.toFixed(0)}/bp` : "—"}
                  </TableCell>
                  <TableCell className="text-right font-data">
                    {d.riskBudget?.riskBudgetBrl ? `${((pos.riskAllocationBrl / d.riskBudget.riskBudgetBrl) * 100).toFixed(1)}%` : "—"}
                  </TableCell>
                  <TableCell className="text-right font-data text-muted-foreground">{fmtBrl(pos.marginRequiredBrl)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {/* Trades Recomendados */}
      {activeTrades.length > 0 && (
        <Card className="bg-card border-border border-primary/30">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <ArrowUpDown className="w-5 h-5 text-primary" />
              Trades Recomendados para Execução
            </CardTitle>
            <CardDescription>
              {activeTrades.length} ordens a executar na B3. Custo estimado: {plan?.estimatedCostBps?.toFixed(1)} bps ({fmtBrl(plan?.estimatedCostBrl || 0)}).
              Vá para a aba "Trades" para registrar as execuções.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Instrumento</TableHead>
                  <TableHead>Ticker B3</TableHead>
                  <TableHead>Ação</TableHead>
                  <TableHead className="text-right">Contratos</TableHead>
                  <TableHead className="text-right">Atual → Alvo</TableHead>
                  <TableHead className="text-right">Notional</TableHead>
                  <TableHead>Motivo</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {activeTrades.map((trade: any, idx: number) => (
                  <TableRow key={idx} className="bg-primary/5">
                    <TableCell className="font-medium">{instrumentLabel(trade.instrument)}</TableCell>
                    <TableCell className="font-data text-primary font-bold">{trade.b3Ticker}</TableCell>
                    <TableCell>{actionBadge(trade.action)}</TableCell>
                    <TableCell className="text-right font-data font-bold">
                      {trade.contractsDelta > 0 ? "+" : ""}{trade.contractsDelta}
                    </TableCell>
                    <TableCell className="text-right font-data text-muted-foreground">
                      {trade.currentContracts} → {trade.targetContracts}
                    </TableCell>
                    <TableCell className="text-right font-data">{fmtBrl(trade.notionalDeltaBrl)}</TableCell>
                    <TableCell className="text-xs text-muted-foreground max-w-[200px] truncate">{trade.reason}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      {/* Position Rationale */}
      {interp?.positionRationale && (
        <Card className="bg-card border-border">
          <CardHeader><CardTitle className="text-base">Racional das Posições</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            {Object.entries(interp.positionRationale).map(([inst, rationale]) => (
              <div key={inst} className="p-3 rounded-lg bg-secondary/30 border border-border">
                <p className="text-xs text-primary font-semibold uppercase tracking-wider mb-1">{instrumentLabel(inst)}</p>
                <p className="text-sm text-muted-foreground">{rationale as string}</p>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {/* Action Items */}
      {interp?.actionItems && (
        <Card className="bg-card border-border">
          <CardHeader><CardTitle className="text-sm">Checklist de Execução</CardTitle></CardHeader>
          <CardContent>
            <ul className="space-y-2">
              {interp.actionItems.map((item: string, idx: number) => (
                <li key={idx} className="flex items-start gap-2 text-sm text-muted-foreground">
                  <ChevronRight className="w-4 h-4 mt-0.5 text-primary shrink-0" />{item}
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

// ============================================================
// Trades Tab — Execute Pending + Record Manual Trades
// ============================================================

function TradesTab() {
  const utils = trpc.useUtils();
  const { data: pendingTrades, isLoading: pendingLoading } = trpc.portfolio.trades.pending.useQuery();
  const { data: tradeHistory, isLoading: historyLoading } = trpc.portfolio.trades.history.useQuery({ limit: 50 });
  const { data: computeResult } = trpc.portfolio.compute.useQuery();

  const executeTrade = trpc.portfolio.trades.execute.useMutation({
    onSuccess: () => { toast.success("Trade registrado como executado!"); utils.portfolio.invalidate(); },
    onError: (err) => toast.error(err.message),
  });
  const cancelTrade = trpc.portfolio.trades.cancel.useMutation({
    onSuccess: () => { toast.success("Trade cancelado."); utils.portfolio.invalidate(); },
    onError: (err) => toast.error(err.message),
  });
  const recordTrade = trpc.portfolio.trades.record.useMutation({
    onSuccess: () => { toast.success("Trade manual registrado!"); utils.portfolio.invalidate(); setShowManualForm(false); },
    onError: (err) => toast.error(err.message),
  });
  const rebalance = trpc.portfolio.rebalance.useMutation({
    onSuccess: (data) => {
      if (data.success) { toast.success(`Rebalanceamento: ${data.tradesCount} trades criados.`); utils.portfolio.invalidate(); }
      else toast.error(data.error || "Erro");
    },
    onError: (err) => toast.error(err.message),
  });

  // Trade workflow: approve → fill
  const approveTrade = trpc.portfolio.tradeWorkflow.approve.useMutation({
    onSuccess: (data) => {
      if (data.success) { toast.success("Trade aprovado! Pronto para execução."); utils.portfolio.invalidate(); }
      else toast.error(data.error || "Erro");
    },
    onError: (err) => toast.error(err.message),
  });
  const fillTrade = trpc.portfolio.tradeWorkflow.fill.useMutation({
    onSuccess: (data) => {
      if (data.success) {
        const sl = data.slippage;
        toast.success(`Trade executado! Slippage: ${sl?.slippageBps?.toFixed(1) ?? 0}bps (R$ ${sl?.slippageBrl?.toFixed(2) ?? 0})`);
        utils.portfolio.invalidate();
        setFillDialogTradeId(null);
      } else toast.error(data.error || "Erro");
    },
    onError: (err) => toast.error(err.message),
  });

  const [showManualForm, setShowManualForm] = useState(false);
  const [executeDialogTradeId, setExecuteDialogTradeId] = useState<number | null>(null);
  const [executePrice, setExecutePrice] = useState("");
  const [executeContracts, setExecuteContracts] = useState("");
  const [executeNotes, setExecuteNotes] = useState("");
  // Fill dialog state
  const [fillDialogTradeId, setFillDialogTradeId] = useState<number | null>(null);
  const [fillPrice, setFillPrice] = useState("");
  const [fillContracts, setFillContracts] = useState("");
  const [fillCommission, setFillCommission] = useState("");
  const [fillNotes, setFillNotes] = useState("");

  // Manual trade form state
  const [manualInstrument, setManualInstrument] = useState<string>("fx");
  const [manualTicker, setManualTicker] = useState("");
  const [manualType, setManualType] = useState("WDO");
  const [manualAction, setManualAction] = useState<"BUY" | "SELL">("BUY");
  const [manualContracts, setManualContracts] = useState("");
  const [manualPrice, setManualPrice] = useState("");
  const [manualNotional, setManualNotional] = useState("");
  const [manualNotes, setManualNotes] = useState("");
  const [manualTradeType, setManualTradeType] = useState<string>("manual_adjustment");

  const handleExecute = () => {
    if (executeDialogTradeId === null) return;
    executeTrade.mutate({
      tradeId: executeDialogTradeId,
      executedPrice: parseFloat(executePrice) || 0,
      contracts: executeContracts ? parseInt(executeContracts) : undefined,
      notes: executeNotes || undefined,
    });
    setExecuteDialogTradeId(null);
    setExecutePrice("");
    setExecuteContracts("");
    setExecuteNotes("");
  };

  const handleRecordManual = () => {
    recordTrade.mutate({
      instrument: manualInstrument as any,
      b3Ticker: manualTicker,
      b3InstrumentType: manualType,
      action: manualAction,
      contracts: parseInt(manualContracts) || 1,
      executedPrice: parseFloat(manualPrice) || 0,
      notionalBrl: parseFloat(manualNotional) || 0,
      tradeType: manualTradeType as any,
      notes: manualNotes || undefined,
    });
  };

  // Recommended trades from model (not yet saved as pending)
  const modelTrades = computeResult?.data?.rebalancingPlan?.trades?.filter((t: any) => t.action !== "HOLD") || [];
  const hasPendingInDb = (pendingTrades?.length || 0) > 0;

  return (
    <div className="space-y-6">
      {/* Action Bar */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">Gestão de Trades</h2>
          <p className="text-sm text-muted-foreground">Execute trades recomendados pelo modelo ou registre trades manuais.</p>
        </div>
        <div className="flex gap-2">
          {!hasPendingInDb && modelTrades.length > 0 && (
            <Button onClick={() => rebalance.mutate()} disabled={rebalance.isPending} variant="default" size="sm">
              {rebalance.isPending ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : <Send className="w-4 h-4 mr-1" />}
              Gerar Ordens ({modelTrades.length})
            </Button>
          )}
          <Button onClick={() => setShowManualForm(!showManualForm)} variant="outline" size="sm">
            <Plus className="w-4 h-4 mr-1" /> Trade Manual
          </Button>
        </div>
      </div>

      {/* Manual Trade Form */}
      {showManualForm && (
        <Card className="bg-card border-primary/30">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base"><Edit3 className="w-4 h-4 text-primary" /> Registrar Trade Manual</CardTitle>
            <CardDescription>Registre um trade executado fora do modelo (ajuste, stop loss, take profit, roll).</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div className="space-y-1">
                <Label className="text-xs">Instrumento</Label>
                <Select value={manualInstrument} onValueChange={setManualInstrument}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="fx">FX (Câmbio)</SelectItem>
                    <SelectItem value="front">Front-End (DI 1Y)</SelectItem>
                    <SelectItem value="belly">Belly (DI 5Y)</SelectItem>
                    <SelectItem value="long">Long-End (DI 10Y)</SelectItem>
                    <SelectItem value="hard">Hard Currency</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1">
                <Label className="text-xs">Ticker B3</Label>
                <Input placeholder="WDOH26" value={manualTicker} onChange={(e) => setManualTicker(e.target.value)} className="font-data" />
              </div>
              <div className="space-y-1">
                <Label className="text-xs">Tipo Instrumento</Label>
                <Select value={manualType} onValueChange={setManualType}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="WDO">WDO (Mini Dólar)</SelectItem>
                    <SelectItem value="DOL">DOL (Dólar Cheio)</SelectItem>
                    <SelectItem value="DI1">DI1 (Futuro DI)</SelectItem>
                    <SelectItem value="FRA">FRA (DI Spread)</SelectItem>
                    <SelectItem value="DDI">DDI (Cupom Cambial)</SelectItem>
                    <SelectItem value="NTNB">NTN-B (Tesouro IPCA+)</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1">
                <Label className="text-xs">Tipo de Trade</Label>
                <Select value={manualTradeType} onValueChange={setManualTradeType}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="manual_adjustment">Ajuste Manual</SelectItem>
                    <SelectItem value="stop_loss">Stop Loss</SelectItem>
                    <SelectItem value="take_profit">Take Profit</SelectItem>
                    <SelectItem value="roll">Roll (Vencimento)</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div className="space-y-1">
                <Label className="text-xs">Ação</Label>
                <Select value={manualAction} onValueChange={(v) => setManualAction(v as "BUY" | "SELL")}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="BUY">COMPRA</SelectItem>
                    <SelectItem value="SELL">VENDA</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1">
                <Label className="text-xs">Contratos</Label>
                <Input type="number" placeholder="10" value={manualContracts} onChange={(e) => setManualContracts(e.target.value)} className="font-data" />
              </div>
              <div className="space-y-1">
                <Label className="text-xs">Preço Executado</Label>
                <Input type="number" placeholder="5.8500" value={manualPrice} onChange={(e) => setManualPrice(e.target.value)} className="font-data" step="0.0001" />
              </div>
              <div className="space-y-1">
                <Label className="text-xs">Notional (R$)</Label>
                <Input type="number" placeholder="580000" value={manualNotional} onChange={(e) => setManualNotional(e.target.value)} className="font-data" />
              </div>
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Notas</Label>
              <Textarea placeholder="Observações sobre o trade..." value={manualNotes} onChange={(e) => setManualNotes(e.target.value)} className="h-16" />
            </div>
            <div className="flex gap-2">
              <Button onClick={handleRecordManual} disabled={recordTrade.isPending || !manualTicker || !manualContracts}>
                {recordTrade.isPending ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : <Check className="w-4 h-4 mr-1" />}
                Registrar Trade
              </Button>
              <Button variant="outline" onClick={() => setShowManualForm(false)}><X className="w-4 h-4 mr-1" /> Cancelar</Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Pending Trades */}
      {hasPendingInDb && (
        <Card className="bg-card border-amber-500/30">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Clock className="w-5 h-5 text-amber-400" />
              Trades Pendentes ({pendingTrades?.length})
            </CardTitle>
            <CardDescription>Ordens recomendadas pelo modelo. Fluxo: <span className="text-amber-400 font-semibold">Pendente</span> → <span className="text-blue-400 font-semibold">Aprovado</span> → <span className="text-emerald-400 font-semibold">Executado</span></CardDescription>
          </CardHeader>
          <CardContent>
            {pendingLoading ? <Loader2 className="w-6 h-6 animate-spin mx-auto" /> : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Instrumento</TableHead>
                    <TableHead>Ticker B3</TableHead>
                    <TableHead>Ação</TableHead>
                    <TableHead className="text-right">Contratos</TableHead>
                    <TableHead className="text-right">Notional</TableHead>
                    <TableHead>Motivo</TableHead>
                    <TableHead className="text-right">Ações</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {pendingTrades?.map((trade: any) => (
                    <TableRow key={trade.id} className="bg-amber-500/5">
                      <TableCell className="font-medium">{instrumentLabel(trade.instrument)}</TableCell>
                      <TableCell className="font-data text-primary font-bold">{trade.b3Ticker}</TableCell>
                      <TableCell>{actionBadge(trade.action)}</TableCell>
                      <TableCell className="text-right font-data font-bold">{trade.contracts}</TableCell>
                      <TableCell className="text-right font-data">{fmtBrl(trade.notionalBrl)}</TableCell>
                      <TableCell className="text-xs text-muted-foreground max-w-[150px] truncate">{trade.notes}</TableCell>
                      <TableCell className="text-right">
                        <div className="flex gap-1 justify-end">
                          {/* Step 1: Approve */}
                          {trade.status === "pending" && (
                            <>
                              <Button size="sm" variant="default" className="h-7 text-xs bg-blue-600 hover:bg-blue-700" onClick={() => approveTrade.mutate({ tradeId: trade.id })} disabled={approveTrade.isPending}>
                                {approveTrade.isPending ? <Loader2 className="w-3 h-3 animate-spin mr-1" /> : <Check className="w-3 h-3 mr-1" />} Aprovar
                              </Button>
                              <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => cancelTrade.mutate({ tradeId: trade.id })} disabled={cancelTrade.isPending}>
                                <X className="w-3 h-3" />
                              </Button>
                            </>
                          )}
                          {/* Step 2: Fill (after approval) */}
                          {trade.status === "executed" && trade.notes?.includes("APROVADO") && (
                            <Dialog>
                              <DialogTrigger asChild>
                                <Button size="sm" variant="default" className="h-7 text-xs bg-emerald-600 hover:bg-emerald-700" onClick={() => { setFillDialogTradeId(trade.id); setFillPrice(""); setFillContracts(String(trade.contracts)); setFillCommission(""); setFillNotes(""); }}>
                                  <ArrowUpDown className="w-3 h-3 mr-1" /> Preencher Execução
                                </Button>
                              </DialogTrigger>
                              <DialogContent>
                                <DialogHeader>
                                  <DialogTitle>Registrar Execução Real</DialogTitle>
                                  <DialogDescription>
                                    {trade.action} {trade.contracts}x {trade.b3Ticker} ({instrumentLabel(trade.instrument)})
                                    <br /><span className="text-xs text-muted-foreground">Preço alvo: {trade.targetPrice || trade.executedPrice || "N/A"}</span>
                                  </DialogDescription>
                                </DialogHeader>
                                <div className="space-y-4 py-4">
                                  <div className="space-y-2">
                                    <Label>Preço de Execução Real</Label>
                                    <Input type="number" placeholder="5.8500" value={fillPrice} onChange={(e) => setFillPrice(e.target.value)} className="font-data" step="0.0001" autoFocus />
                                  </div>
                                  <div className="space-y-2">
                                    <Label>Contratos Executados</Label>
                                    <Input type="number" value={fillContracts} onChange={(e) => setFillContracts(e.target.value)} className="font-data" />
                                  </div>
                                  <div className="space-y-2">
                                    <Label>Comissão (R$)</Label>
                                    <Input type="number" placeholder="0.00" value={fillCommission} onChange={(e) => setFillCommission(e.target.value)} className="font-data" step="0.01" />
                                  </div>
                                  <div className="space-y-2">
                                    <Label>Notas</Label>
                                    <Textarea placeholder="Broker, horário, observações..." value={fillNotes} onChange={(e) => setFillNotes(e.target.value)} className="h-16" />
                                  </div>
                                </div>
                                <DialogFooter>
                                  <Button onClick={() => { if (fillDialogTradeId) fillTrade.mutate({ tradeId: fillDialogTradeId, executedPrice: parseFloat(fillPrice) || 0, executedContracts: parseInt(fillContracts) || trade.contracts, commissionBrl: parseFloat(fillCommission) || 0, notes: fillNotes }); }} disabled={fillTrade.isPending || !fillPrice}>
                                    {fillTrade.isPending ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : <Check className="w-4 h-4 mr-1" />}
                                    Confirmar Execução
                                  </Button>
                                </DialogFooter>
                              </DialogContent>
                            </Dialog>
                          )}
                          {/* Direct execute (legacy) */}
                          {trade.status === "pending" && (
                            <Dialog>
                              <DialogTrigger asChild>
                                <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => { setExecuteDialogTradeId(trade.id); setExecutePrice(""); setExecuteContracts(String(trade.contracts)); }}>
                                  Exec. Direto
                                </Button>
                              </DialogTrigger>
                              <DialogContent>
                                <DialogHeader>
                                  <DialogTitle>Execução Direta</DialogTitle>
                                  <DialogDescription>
                                    {trade.action} {trade.contracts}x {trade.b3Ticker} ({instrumentLabel(trade.instrument)})
                                  </DialogDescription>
                                </DialogHeader>
                                <div className="space-y-4 py-4">
                                  <div className="space-y-2">
                                    <Label>Preço de Execução</Label>
                                    <Input type="number" placeholder="5.8500" value={executePrice} onChange={(e) => setExecutePrice(e.target.value)} className="font-data" step="0.0001" autoFocus />
                                  </div>
                                  <div className="space-y-2">
                                    <Label>Contratos</Label>
                                    <Input type="number" value={executeContracts} onChange={(e) => setExecuteContracts(e.target.value)} className="font-data" />
                                  </div>
                                  <div className="space-y-2">
                                    <Label>Notas</Label>
                                    <Textarea placeholder="Observações..." value={executeNotes} onChange={(e) => setExecuteNotes(e.target.value)} className="h-16" />
                                  </div>
                                </div>
                                <DialogFooter>
                                  <Button onClick={handleExecute} disabled={executeTrade.isPending || !executePrice}>
                                    {executeTrade.isPending ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : <Check className="w-4 h-4 mr-1" />}
                                    Confirmar
                                  </Button>
                                </DialogFooter>
                              </DialogContent>
                            </Dialog>
                          )}
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      )}

      {/* No Pending Trades + Model Recommendations */}
      {!hasPendingInDb && modelTrades.length > 0 && (
        <Card className="bg-card border-border">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <ArrowUpDown className="w-5 h-5 text-primary" />
              Trades Recomendados pelo Modelo
            </CardTitle>
            <CardDescription>
              O modelo recomenda {modelTrades.length} trades. Clique em "Gerar Ordens" para criar as ordens pendentes.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Instrumento</TableHead>
                  <TableHead>Ticker B3</TableHead>
                  <TableHead>Ação</TableHead>
                  <TableHead className="text-right">Δ Contratos</TableHead>
                  <TableHead className="text-right">Atual → Alvo</TableHead>
                  <TableHead className="text-right">Notional</TableHead>
                  <TableHead>Motivo</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {modelTrades.map((trade: any, idx: number) => (
                  <TableRow key={idx}>
                    <TableCell className="font-medium">{instrumentLabel(trade.instrument)}</TableCell>
                    <TableCell className="font-data text-primary">{trade.b3Ticker}</TableCell>
                    <TableCell>{actionBadge(trade.action)}</TableCell>
                    <TableCell className="text-right font-data font-bold">{trade.contractsDelta > 0 ? "+" : ""}{trade.contractsDelta}</TableCell>
                    <TableCell className="text-right font-data text-muted-foreground">{trade.currentContracts} → {trade.targetContracts}</TableCell>
                    <TableCell className="text-right font-data">{fmtBrl(trade.notionalDeltaBrl)}</TableCell>
                    <TableCell className="text-xs text-muted-foreground max-w-[200px] truncate">{trade.reason}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      {/* Trade History */}
      <Card className="bg-card border-border">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base"><History className="w-4 h-4 text-muted-foreground" /> Histórico de Trades</CardTitle>
          <CardDescription>Últimos 50 trades registrados (executados, cancelados, pendentes).</CardDescription>
        </CardHeader>
        <CardContent>
          {historyLoading ? <Loader2 className="w-6 h-6 animate-spin mx-auto" /> : (
            (tradeHistory?.length || 0) === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-8">Nenhum trade registrado ainda. Execute um rebalanceamento ou registre trades manuais.</p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Data</TableHead>
                    <TableHead>Instrumento</TableHead>
                    <TableHead>Ticker</TableHead>
                    <TableHead>Tipo</TableHead>
                    <TableHead>Ação</TableHead>
                    <TableHead className="text-right">Contratos</TableHead>
                    <TableHead className="text-right">Preço</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Notas</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {tradeHistory?.map((trade: any) => (
                    <TableRow key={trade.id}>
                      <TableCell className="font-data text-xs">{new Date(trade.createdAt).toLocaleDateString("pt-BR")}</TableCell>
                      <TableCell className="text-xs">{instrumentShort(trade.instrument)}</TableCell>
                      <TableCell className="font-data text-primary text-xs">{trade.b3Ticker}</TableCell>
                      <TableCell className="text-xs text-muted-foreground">{trade.tradeType}</TableCell>
                      <TableCell>{actionBadge(trade.action)}</TableCell>
                      <TableCell className="text-right font-data">{trade.contracts}</TableCell>
                      <TableCell className="text-right font-data">{trade.executedPrice ? trade.executedPrice.toFixed(4) : "—"}</TableCell>
                      <TableCell>{statusBadge(trade.status)}</TableCell>
                      <TableCell className="text-xs text-muted-foreground max-w-[120px] truncate">{trade.notes || "—"}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )
          )}
        </CardContent>
      </Card>
    </div>
  );
}

// ============================================================
// P&L Tab — Daily/MTD/YTD Tracking
// ============================================================

function PnlTab() {
  const utils = trpc.useUtils();
  const { data: pnlSummary, isLoading: summaryLoading } = trpc.portfolio.pnl.summary.useQuery();
  const { data: pnlHistory, isLoading: historyLoading } = trpc.portfolio.pnl.history.useQuery({ limit: 252 });
  const recordPnl = trpc.portfolio.pnl.record.useMutation({
    onSuccess: (data) => {
      if (data.success) {
        toast.success(`P&L registrado: ${fmtBrlFull(data.totalPnl ?? 0)} (overlay: ${fmtBrlFull(data.overlayPnl ?? 0)}, CDI: ${fmtBrlFull(data.cdiPnl ?? 0)})`);
        utils.portfolio.invalidate();
        setShowPnlForm(false);
      } else {
        toast.error(data.error || "Erro ao registrar P&L");
      }
    },
    onError: (err) => toast.error(err.message),
  });

  // Auto MTM recording
  const autoMtm = trpc.portfolio.market.recordMtm.useMutation({
    onSuccess: (data) => {
      if (data.success) {
        toast.success(`MTM registrado! P&L: ${fmtBrlFull(data.pnl?.total ?? 0)} | Overlay: ${fmtBrlFull(data.pnl?.overlay ?? 0)} | CDI: ${fmtBrlFull(data.pnl?.cdi ?? 0)} | DD: ${(data.pnl?.drawdown ?? 0).toFixed(2)}%`);
        utils.portfolio.invalidate();
      } else {
        toast.error(data.error || "Erro no MTM");
      }
    },
    onError: (err) => toast.error(err.message),
  });

  // Fetch live market prices
  const [fetchingPrices, setFetchingPrices] = useState(false);
  const marketPricesQuery = trpc.portfolio.market.prices.useQuery({ forceRefresh: true }, { enabled: false });
  const handleFetchPrices = async () => {
    setFetchingPrices(true);
    try {
      const result = await marketPricesQuery.refetch();
      const data = result.data;
      if (data?.error) { toast.error(data.error); return; }
      const p = data?.data;
      if (p) {
        setSpotUsdbrl(p.spotUsdbrl?.toFixed(4) || "");
        setDi1y(p.di1y?.toFixed(2) || "");
        setDi5y(p.di5y?.toFixed(2) || "");
        setDi10y(p.di10y?.toFixed(2) || "");
        setEmbiSpread(p.embiSpread?.toFixed(0) || "");
        toast.success(`Preços atualizados: USD/BRL ${p.spotUsdbrl?.toFixed(4)} | DI1Y ${p.di1y?.toFixed(2)}% | DI5Y ${p.di5y?.toFixed(2)}% | Fonte: ${p.source}`);
      }
    } catch (err: any) {
      toast.error(err.message || "Erro ao buscar preços");
    } finally {
      setFetchingPrices(false);
    }
  };

  const [showPnlForm, setShowPnlForm] = useState(false);
  const [pnlDate, setPnlDate] = useState(new Date().toISOString().slice(0, 10));
  const [pnlMode, setPnlMode] = useState<"prices" | "auto" | "direct">("auto");
  // Market prices
  const [spotUsdbrl, setSpotUsdbrl] = useState("");
  const [di1y, setDi1y] = useState("");
  const [di5y, setDi5y] = useState("");
  const [di10y, setDi10y] = useState("");
  const [embiSpread, setEmbiSpread] = useState("");
  // Direct P&L
  const [fxPnl, setFxPnl] = useState("");
  const [frontPnl, setFrontPnl] = useState("");
  const [bellyPnl, setBellyPnl] = useState("");
  const [longPnl, setLongPnl] = useState("");
  const [hardPnl, setHardPnl] = useState("");

  const handleRecordPnl = () => {
    const input: any = { pnlDate };
    if (pnlMode === "prices") {
      if (spotUsdbrl) input.spotUsdbrl = parseFloat(spotUsdbrl);
      if (di1y) input.di1y = parseFloat(di1y);
      if (di5y) input.di5y = parseFloat(di5y);
      if (di10y) input.di10y = parseFloat(di10y);
      if (embiSpread) input.embiSpread = parseFloat(embiSpread);
    } else {
      if (fxPnl) input.fxPnlBrl = parseFloat(fxPnl);
      if (frontPnl) input.frontPnlBrl = parseFloat(frontPnl);
      if (bellyPnl) input.bellyPnlBrl = parseFloat(bellyPnl);
      if (longPnl) input.longPnlBrl = parseFloat(longPnl);
      if (hardPnl) input.hardPnlBrl = parseFloat(hardPnl);
    }
    recordPnl.mutate(input);
  };

  return (
    <div className="space-y-6">
      {/* P&L Summary Cards */}
      {summaryLoading ? (
        <div className="flex items-center justify-center py-20"><Loader2 className="w-8 h-8 animate-spin text-primary" /></div>
      ) : pnlSummary ? (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <Card className="bg-card border-border">
              <CardContent className="pt-4 pb-4">
                <p className="text-xs text-muted-foreground uppercase tracking-wider mb-1">P&L Diário</p>
                <p className={`font-data text-xl font-bold ${pnlColor(pnlSummary.daily.pnl)}`}>{fmtBrlFull(pnlSummary.daily.pnl)}</p>
                <p className="text-xs text-muted-foreground">{fmtPct(pnlSummary.daily.pnlPct)} AUM</p>
              </CardContent>
            </Card>
            <Card className="bg-card border-border">
              <CardContent className="pt-4 pb-4">
                <p className="text-xs text-muted-foreground uppercase tracking-wider mb-1">P&L MTD</p>
                <p className={`font-data text-xl font-bold ${pnlColor(pnlSummary.mtd.pnl)}`}>{fmtBrlFull(pnlSummary.mtd.pnl)}</p>
                <p className="text-xs text-muted-foreground">{fmtPct(pnlSummary.mtd.pnlPct)} AUM | CDI: {fmtBrlFull(pnlSummary.mtd.cdi)}</p>
              </CardContent>
            </Card>
            <Card className="bg-card border-border">
              <CardContent className="pt-4 pb-4">
                <p className="text-xs text-muted-foreground uppercase tracking-wider mb-1">P&L YTD</p>
                <p className={`font-data text-xl font-bold ${pnlColor(pnlSummary.ytd.pnl)}`}>{fmtBrlFull(pnlSummary.ytd.pnl)}</p>
                <p className="text-xs text-muted-foreground">{fmtPct(pnlSummary.ytd.pnlPct)} AUM | CDI: {fmtBrlFull(pnlSummary.ytd.cdi)}</p>
              </CardContent>
            </Card>
            <Card className="bg-card border-border">
              <CardContent className="pt-4 pb-4">
                <p className="text-xs text-muted-foreground uppercase tracking-wider mb-1">Desde Início</p>
                <p className={`font-data text-xl font-bold ${pnlColor(pnlSummary.inception.pnl)}`}>{fmtBrlFull(pnlSummary.inception.pnl)}</p>
                <p className="text-xs text-muted-foreground">{fmtPct(pnlSummary.inception.pnlPct)} AUM | CDI: {fmtBrlFull(pnlSummary.inception.cdi)}</p>
              </CardContent>
            </Card>
          </div>

          {/* AUM & Drawdown */}
          <div className="grid grid-cols-3 gap-4">
            <MetricBox label="AUM Atual" value={fmtBrl(pnlSummary.aumCurrent)} />
            <MetricBox label="High Water Mark" value={fmtBrl(pnlSummary.hwm)} />
            <MetricBox label="Drawdown Atual" value={`${pnlSummary.currentDrawdown.toFixed(2)}%`} />
          </div>
        </>
      ) : (
        <Card className="bg-card border-border">
          <CardContent className="py-12 text-center">
            <DollarSign className="w-10 h-10 text-muted-foreground mx-auto mb-4" />
            <p className="text-lg font-medium">Sem dados de P&L</p>
            <p className="text-sm text-muted-foreground mt-2">Registre o P&L diário para acompanhar a performance.</p>
          </CardContent>
        </Card>
      )}

      {/* Record P&L Buttons */}
      <div className="flex justify-between items-center">
        <h3 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">Registro de P&L</h3>
        <div className="flex gap-2">
          <Button
            onClick={() => autoMtm.mutate({ pnlDate: new Date().toISOString().slice(0, 10), useAutoMtm: true })}
            variant="default"
            size="sm"
            disabled={autoMtm.isPending}
          >
            {autoMtm.isPending ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : <Activity className="w-4 h-4 mr-1" />}
            MTM Automático (ANBIMA/BCB)
          </Button>
          <Button onClick={() => setShowPnlForm(!showPnlForm)} variant="outline" size="sm">
            <Plus className="w-4 h-4 mr-1" /> Registrar Manual
          </Button>
        </div>
      </div>

      {/* P&L Input Form */}
      {showPnlForm && (
        <Card className="bg-card border-primary/30">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base"><Activity className="w-4 h-4 text-primary" /> Registrar P&L</CardTitle>
            <CardDescription>Insira preços de mercado (MTM automático) ou P&L direto por instrumento.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center gap-4">
              <div className="space-y-1">
                <Label className="text-xs">Data</Label>
                <Input type="date" value={pnlDate} onChange={(e) => setPnlDate(e.target.value)} className="font-data w-40" />
              </div>
              <div className="space-y-1">
                <Label className="text-xs">Modo</Label>
                <Select value={pnlMode} onValueChange={(v) => setPnlMode(v as "prices" | "auto" | "direct")}>
                  <SelectTrigger className="w-48"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="auto">Auto MTM (ANBIMA/BCB/Polygon)</SelectItem>
                    <SelectItem value="prices">Preços Manuais (MTM)</SelectItem>
                    <SelectItem value="direct">P&L Direto (R$)</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              {pnlMode === "prices" && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleFetchPrices}
                  disabled={fetchingPrices}
                  className="mt-4"
                >
                  {fetchingPrices ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : <RefreshCw className="w-4 h-4 mr-1" />}
                  Buscar Preços (ANBIMA/BCB/Polygon)
                </Button>
              )}
            </div>

            {pnlMode === "auto" ? (
              <div className="p-4 rounded-lg bg-primary/10 border border-primary/20">
                <p className="text-sm text-foreground font-medium mb-2">MTM Automático</p>
                <p className="text-xs text-muted-foreground">O sistema buscará preços automaticamente da ANBIMA (curva DI), BCB (PTAX, CDI), e Polygon.io (FX spot) para calcular o P&L de cada posição.</p>
                <div className="mt-3 flex gap-2">
                  <Button
                    onClick={() => autoMtm.mutate({ pnlDate, useAutoMtm: true })}
                    disabled={autoMtm.isPending}
                  >
                    {autoMtm.isPending ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : <Activity className="w-4 h-4 mr-1" />}
                    Calcular MTM Automático
                  </Button>
                  <Button variant="outline" onClick={() => setShowPnlForm(false)}><X className="w-4 h-4 mr-1" /> Cancelar</Button>
                </div>
              </div>
            ) : pnlMode === "prices" ? (
              <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
                <div className="space-y-1">
                  <Label className="text-xs">USD/BRL Spot</Label>
                  <Input type="number" placeholder="5.8500" value={spotUsdbrl} onChange={(e) => setSpotUsdbrl(e.target.value)} className="font-data" step="0.0001" />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">DI 1Y (%)</Label>
                  <Input type="number" placeholder="14.90" value={di1y} onChange={(e) => setDi1y(e.target.value)} className="font-data" step="0.01" />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">DI 5Y (%)</Label>
                  <Input type="number" placeholder="13.50" value={di5y} onChange={(e) => setDi5y(e.target.value)} className="font-data" step="0.01" />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">DI 10Y (%)</Label>
                  <Input type="number" placeholder="13.00" value={di10y} onChange={(e) => setDi10y(e.target.value)} className="font-data" step="0.01" />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">EMBI Spread (bps)</Label>
                  <Input type="number" placeholder="200" value={embiSpread} onChange={(e) => setEmbiSpread(e.target.value)} className="font-data" step="1" />
                </div>
              </div>
            ) : (
              <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
                <div className="space-y-1">
                  <Label className="text-xs">FX P&L (R$)</Label>
                  <Input type="number" placeholder="0" value={fxPnl} onChange={(e) => setFxPnl(e.target.value)} className="font-data" />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Front P&L (R$)</Label>
                  <Input type="number" placeholder="0" value={frontPnl} onChange={(e) => setFrontPnl(e.target.value)} className="font-data" />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Belly P&L (R$)</Label>
                  <Input type="number" placeholder="0" value={bellyPnl} onChange={(e) => setBellyPnl(e.target.value)} className="font-data" />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Long P&L (R$)</Label>
                  <Input type="number" placeholder="0" value={longPnl} onChange={(e) => setLongPnl(e.target.value)} className="font-data" />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Hard P&L (R$)</Label>
                  <Input type="number" placeholder="0" value={hardPnl} onChange={(e) => setHardPnl(e.target.value)} className="font-data" />
                </div>
              </div>
            )}

            <div className="flex gap-2">
              <Button onClick={handleRecordPnl} disabled={recordPnl.isPending}>
                {recordPnl.isPending ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : <Check className="w-4 h-4 mr-1" />}
                Registrar P&L
              </Button>
              <Button variant="outline" onClick={() => setShowPnlForm(false)}><X className="w-4 h-4 mr-1" /> Cancelar</Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* P&L History Table */}
      <Card className="bg-card border-border">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base"><History className="w-4 h-4 text-muted-foreground" /> Histórico de P&L Diário</CardTitle>
        </CardHeader>
        <CardContent>
          {historyLoading ? <Loader2 className="w-6 h-6 animate-spin mx-auto" /> : (
            (pnlHistory?.length || 0) === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-8">Nenhum registro de P&L. Use o botão acima para registrar o P&L diário.</p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Data</TableHead>
                    <TableHead className="text-right">Total</TableHead>
                    <TableHead className="text-right">Overlay</TableHead>
                    <TableHead className="text-right">CDI</TableHead>
                    <TableHead className="text-right">FX</TableHead>
                    <TableHead className="text-right">Front</TableHead>
                    <TableHead className="text-right">Belly</TableHead>
                    <TableHead className="text-right">Long</TableHead>
                    <TableHead className="text-right">Hard</TableHead>
                    <TableHead className="text-right">Acum.</TableHead>
                    <TableHead className="text-right">DD</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {pnlHistory?.map((row: any) => (
                    <TableRow key={row.id}>
                      <TableCell className="font-data text-xs">{row.pnlDate}</TableCell>
                      <TableCell className={`text-right font-data font-bold ${pnlColor(row.totalPnlBrl)}`}>{fmtBrlFull(row.totalPnlBrl)}</TableCell>
                      <TableCell className={`text-right font-data ${pnlColor(row.overlayPnlBrl)}`}>{fmtBrlFull(row.overlayPnlBrl)}</TableCell>
                      <TableCell className="text-right font-data text-emerald-400">{fmtBrlFull(row.cdiPnlBrl || row.cdiDailyPnlBrl || 0)}</TableCell>
                      <TableCell className={`text-right font-data text-xs ${pnlColor(row.fxPnlBrl)}`}>{fmtBrlFull(row.fxPnlBrl)}</TableCell>
                      <TableCell className={`text-right font-data text-xs ${pnlColor(row.frontPnlBrl)}`}>{fmtBrlFull(row.frontPnlBrl)}</TableCell>
                      <TableCell className={`text-right font-data text-xs ${pnlColor(row.bellyPnlBrl)}`}>{fmtBrlFull(row.bellyPnlBrl)}</TableCell>
                      <TableCell className={`text-right font-data text-xs ${pnlColor(row.longPnlBrl)}`}>{fmtBrlFull(row.longPnlBrl)}</TableCell>
                      <TableCell className={`text-right font-data text-xs ${pnlColor(row.hardPnlBrl)}`}>{fmtBrlFull(row.hardPnlBrl)}</TableCell>
                      <TableCell className={`text-right font-data ${pnlColor(row.cumulativePnlBrl)}`}>{fmtBrlFull(row.cumulativePnlBrl)}</TableCell>
                      <TableCell className="text-right font-data text-xs text-rose-400">{row.drawdownPct?.toFixed(2)}%</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )
          )}
        </CardContent>
      </Card>
    </div>
  );
}

// ============================================================
// Risk Tab
// ============================================================

function RiskTab() {
  const utils = trpc.useUtils();
  const { data: riskResult, isLoading } = trpc.portfolio.risk.useQuery(undefined, { refetchInterval: 60_000 });
  const { data: computeResult } = trpc.portfolio.compute.useQuery();
  const { data: alerts } = trpc.portfolio.alerts.active.useQuery();
  const dismissAlert = trpc.portfolio.alerts.dismiss.useMutation({
    onSuccess: () => { toast.success("Alerta dispensado."); utils.portfolio.invalidate(); },
  });
  const checkAlerts = trpc.portfolio.alerts.check.useMutation({
    onSuccess: (data) => {
      if (data.alerts.length > 0) toast.warning(`${data.alerts.length} novos alertas detectados.`);
      else toast.success("Nenhum alerta novo.");
      utils.portfolio.invalidate();
    },
  });

  if (isLoading) return <div className="flex items-center justify-center py-20"><Loader2 className="w-8 h-8 animate-spin text-primary" /></div>;

  if (riskResult?.error || !riskResult?.data) {
    return (
      <Card className="bg-card border-border">
        <CardContent className="py-12 text-center">
          <AlertTriangle className="w-10 h-10 text-amber-400 mx-auto mb-4" />
          <p className="text-lg font-medium">{riskResult?.error || "Sem dados de risco."}</p>
          <p className="text-sm text-muted-foreground mt-2">Execute um rebalanceamento primeiro.</p>
        </CardContent>
      </Card>
    );
  }

  const risk = riskResult.data;
  const varData = risk.var;
  const exp = risk.exposure;
  const stressTests = computeResult?.data?.var?.stressTests || varData.stressTests || [];

  return (
    <div className="space-y-6">
      {/* Alerts */}
      {(alerts?.length || 0) > 0 && (
        <Card className="bg-card border-rose-500/30">
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle className="flex items-center gap-2 text-base"><Bell className="w-5 h-5 text-rose-400" /> Alertas Ativos ({alerts?.length})</CardTitle>
              <Button size="sm" variant="outline" onClick={() => checkAlerts.mutate()} disabled={checkAlerts.isPending}>
                <RefreshCw className={`w-3 h-3 mr-1 ${checkAlerts.isPending ? "animate-spin" : ""}`} /> Verificar
              </Button>
            </div>
          </CardHeader>
          <CardContent className="space-y-2">
            {alerts?.map((alert: any) => (
              <div key={alert.id} className="flex items-start justify-between p-3 rounded-lg bg-rose-500/5 border border-rose-500/20">
                <div className="flex-1">
                  <div className="flex items-center gap-2 mb-1">
                    {severityBadge(alert.severity)}
                    <span className="text-sm font-medium">{alert.title}</span>
                  </div>
                  <p className="text-xs text-muted-foreground">{alert.message}</p>
                  <p className="text-xs text-muted-foreground mt-1">{new Date(alert.createdAt).toLocaleString("pt-BR")}</p>
                </div>
                <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={() => dismissAlert.mutate({ alertId: alert.id })}>
                  <BellOff className="w-3 h-3" />
                </Button>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {/* VaR Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <KpiCard label="VaR 95% (1d)" value={fmtBrl(varData.varDaily95Brl)} subtitle={fmtPct(varData.varDaily95Pct) + " AUM"} icon={<Shield className="w-4 h-4" />} color="text-rose-400" />
        <KpiCard label="VaR 99% (1d)" value={fmtBrl(varData.varDaily99Brl)} subtitle={fmtPct(varData.varDaily99Pct) + " AUM"} icon={<Shield className="w-4 h-4" />} color="text-rose-500" />
        <KpiCard label="VaR 95% (1m)" value={fmtBrl(varData.varMonthly95Brl)} icon={<Shield className="w-4 h-4" />} color="text-amber-400" />
        <KpiCard label="VaR 99% (1m)" value={fmtBrl(varData.varMonthly99Brl)} icon={<Shield className="w-4 h-4" />} color="text-amber-500" />
      </div>

      {/* Factor Exposure */}
      <Card className="bg-card border-border">
        <CardHeader>
          <CardTitle className="text-base">Exposição por Fator</CardTitle>
          <CardDescription>Decomposição do risco por fator macro: câmbio, juros e crédito.</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            {/* FX Factor */}
            <div className="space-y-3 p-4 rounded-lg bg-blue-500/5 border border-blue-500/20">
              <div className="flex items-center gap-2">
                <DollarSign className="w-5 h-5 text-blue-400" />
                <h4 className="font-semibold text-sm">Câmbio (FX)</h4>
              </div>
              <div className="space-y-1 text-sm">
                <div className="flex justify-between"><span className="text-muted-foreground">FX Delta</span><span className="font-data">{fmtBrl(exp.fxDeltaTotalBrl)}</span></div>
                <div className="flex justify-between"><span className="text-muted-foreground">VaR Contrib.</span><span className="font-data">{varData.componentVar?.find((c: any) => c.instrument === 'fx')?.varContributionPct?.toFixed(1) || '0.0'}%</span></div>
                <div className="flex justify-between"><span className="text-muted-foreground">Direção</span>{directionBadge(exp.fxDeltaTotalBrl > 0 ? 'LONG' : exp.fxDeltaTotalBrl < 0 ? 'SHORT' : 'FLAT')}</div>
              </div>
            </div>
            {/* Rates Factor */}
            <div className="space-y-3 p-4 rounded-lg bg-emerald-500/5 border border-emerald-500/20">
              <div className="flex items-center gap-2">
                <TrendingUp className="w-5 h-5 text-emerald-400" />
                <h4 className="font-semibold text-sm">Juros (Rates)</h4>
              </div>
              <div className="space-y-1 text-sm">
                <div className="flex justify-between"><span className="text-muted-foreground">DV01 Total</span><span className="font-data">R$ {exp.dv01TotalBrl.toFixed(0)}/bp</span></div>
                <div className="flex justify-between"><span className="text-muted-foreground">VaR Contrib.</span><span className="font-data">{((varData.componentVar?.filter((c: any) => ['front','belly','long'].includes(c.instrument)).reduce((s: number, c: any) => s + (c.varContributionPct || 0), 0)) || 0).toFixed(1)}%</span></div>
                <div className="flex justify-between"><span className="text-muted-foreground">Direção</span>{directionBadge(exp.dv01TotalBrl > 0 ? 'LONG' : exp.dv01TotalBrl < 0 ? 'SHORT' : 'FLAT')}</div>
              </div>
            </div>
            {/* Credit Factor */}
            <div className="space-y-3 p-4 rounded-lg bg-amber-500/5 border border-amber-500/20">
              <div className="flex items-center gap-2">
                <Shield className="w-5 h-5 text-amber-400" />
                <h4 className="font-semibold text-sm">Crédito (Hard Currency)</h4>
              </div>
              <div className="space-y-1 text-sm">
                <div className="flex justify-between"><span className="text-muted-foreground">Spread DV01</span><span className="font-data">{fmtBrl(exp.dv01Ladder?.find((d: any) => d.instrument === 'hard')?.dv01Brl || 0)}/bp</span></div>
                <div className="flex justify-between"><span className="text-muted-foreground">VaR Contrib.</span><span className="font-data">{varData.componentVar?.find((c: any) => c.instrument === 'hard')?.varContributionPct?.toFixed(1) || '0.0'}%</span></div>
                <div className="flex justify-between"><span className="text-muted-foreground">Direção</span>{directionBadge(exp.dv01Ladder?.find((d: any) => d.instrument === 'hard')?.direction || 'FLAT')}</div>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Limits Check */}
      <Card className="bg-card border-border">
        <CardHeader><CardTitle className="text-base">Limites de Risco</CardTitle></CardHeader>
        <CardContent>
          <div className="space-y-4">
            <LimitBar label="VaR 95% / AUM" current={varData.varDaily95Pct} limit={1.5} unit="%" />
            <LimitBar label="Alavancagem Bruta" current={exp.grossLeverage} limit={risk.config.maxLeverageGross} unit="x" />
            <LimitBar label="Margem / AUM" current={exp.marginUtilizationPct} limit={30} unit="%" />
            <LimitBar label="Maior Posição" current={exp.largestPositionPct} limit={50} unit="%" />
          </div>
        </CardContent>
      </Card>

      {/* Component VaR */}
      <Card className="bg-card border-border">
        <CardHeader>
          <CardTitle className="text-base">Component VaR (Decomposição)</CardTitle>
          <CardDescription>Contribuição de cada instrumento para o VaR total.</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            {varData.componentVar.map((cv: any) => (
              <div key={cv.instrument} className="flex items-center gap-4">
                <span className="text-sm font-medium w-32">{instrumentLabel(cv.instrument)}</span>
                <div className="flex-1"><Progress value={Math.min(cv.varContributionPct, 100)} className="h-2" /></div>
                <span className="font-data text-sm w-20 text-right">{fmtBrl(cv.varContributionBrl)}</span>
                <span className="font-data text-sm w-16 text-right text-muted-foreground">{cv.varContributionPct.toFixed(1)}%</span>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Exposure Analytics */}
      <Card className="bg-card border-border">
        <CardHeader><CardTitle className="text-base">Exposição do Portfólio</CardTitle></CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
            <MetricBox label="Exposição Bruta" value={fmtBrl(exp.grossExposureBrl)} />
            <MetricBox label="Exposição Líquida" value={fmtBrl(exp.netExposureBrl)} />
            <MetricBox label="Alavancagem Bruta" value={`${exp.grossLeverage.toFixed(1)}x`} />
            <MetricBox label="FX Delta Total" value={fmtBrl(exp.fxDeltaTotalBrl)} />
            <MetricBox label="DV01 Total" value={`R$ ${exp.dv01TotalBrl.toFixed(0)}/bp`} />
            <MetricBox label="Margem Total" value={fmtBrl(exp.totalMarginBrl)} />
            <MetricBox label="Margem / AUM" value={`${exp.marginUtilizationPct.toFixed(1)}%`} />
            <MetricBox label="Concentração (HHI)" value={exp.herfindahlIndex.toFixed(3)} />
            <MetricBox label="Maior Posição" value={`${exp.largestPositionPct.toFixed(1)}%`} />
          </div>
        </CardContent>
      </Card>

      {/* DV01 Ladder */}
      {exp.dv01Ladder && exp.dv01Ladder.length > 0 && (
        <Card className="bg-card border-border">
          <CardHeader>
            <CardTitle className="text-base">DV01 Ladder</CardTitle>
            <CardDescription>Sensibilidade por vértice da curva de juros.</CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Tenor</TableHead>
                  <TableHead>Instrumento</TableHead>
                  <TableHead>Ticker B3</TableHead>
                  <TableHead>Direção</TableHead>
                  <TableHead className="text-right">DV01 (R$/bp)</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {exp.dv01Ladder.map((entry: any, idx: number) => (
                  <TableRow key={idx}>
                    <TableCell className="font-data font-bold">{entry.tenor}</TableCell>
                    <TableCell>{instrumentLabel(entry.instrument)}</TableCell>
                    <TableCell className="font-data text-primary">{entry.b3Ticker}</TableCell>
                    <TableCell>{directionBadge(entry.direction)}</TableCell>
                    <TableCell className="text-right font-data">
                      <span className={entry.dv01Brl >= 0 ? "text-emerald-400" : "text-rose-400"}>R$ {entry.dv01Brl.toFixed(0)}</span>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      {/* Stress Tests */}
      {stressTests.length > 0 && (
        <Card className="bg-card border-border">
          <CardHeader>
            <CardTitle className="text-base">Stress Tests</CardTitle>
            <CardDescription>Impacto estimado do portfólio em cenários históricos.</CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Cenário</TableHead>
                  <TableHead>Descrição</TableHead>
                  <TableHead className="text-right">P&L (R$)</TableHead>
                  <TableHead className="text-right">P&L (% AUM)</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {stressTests.map((st: any, idx: number) => (
                  <TableRow key={idx}>
                    <TableCell className="font-medium">{st.name}</TableCell>
                    <TableCell className="text-xs text-muted-foreground max-w-[300px]">{st.description}</TableCell>
                    <TableCell className="text-right font-data">
                      <span className={st.portfolioPnlBrl >= 0 ? "text-emerald-400" : "text-rose-400"}>{fmtBrl(st.portfolioPnlBrl)}</span>
                    </TableCell>
                    <TableCell className="text-right font-data">
                      <span className={st.portfolioPnlPct >= 0 ? "text-emerald-400" : "text-rose-400"}>{fmtPct(st.portfolioPnlPct)}</span>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

// ============================================================
// History Tab — Rebalancing Timeline
// ============================================================

function HistoryTab() {
  const { data: snapshots, isLoading } = trpc.portfolio.snapshots.useQuery();

  if (isLoading) return <div className="flex items-center justify-center py-20"><Loader2 className="w-8 h-8 animate-spin text-primary" /></div>;

  if (!snapshots || snapshots.length === 0) {
    return (
      <Card className="bg-card border-border">
        <CardContent className="py-12 text-center">
          <History className="w-10 h-10 text-muted-foreground mx-auto mb-4" />
          <p className="text-lg font-medium">Sem histórico</p>
          <p className="text-sm text-muted-foreground mt-2">Execute um rebalanceamento para criar o primeiro snapshot.</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Timeline de Rebalanceamentos</h2>
        <Badge variant="outline">{snapshots.length} snapshots</Badge>
      </div>

      <div className="space-y-4">
        {snapshots.map((snap: any, idx: number) => {
          const trades = (snap.tradesJson as any[]) || [];
          const activeTrades = trades.filter((t: any) => t.action !== "HOLD");

          return (
            <Card key={snap.id} className={`bg-card border-border ${idx === 0 ? "border-primary/30" : ""}`}>
              <CardHeader className="pb-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className={`w-3 h-3 rounded-full ${idx === 0 ? "bg-primary" : "bg-muted-foreground/30"}`} />
                    <div>
                      <CardTitle className="text-sm">{snap.snapshotDate}</CardTitle>
                      <CardDescription className="text-xs">
                        {snap.snapshotType === "rebalance" ? "Rebalanceamento" : snap.snapshotType} | Model Run #{snap.modelRunId}
                      </CardDescription>
                    </div>
                  </div>
                  <div className="flex gap-3 text-right">
                    <div>
                      <p className="text-xs text-muted-foreground">VaR 95%</p>
                      <p className="font-data text-sm text-rose-400">{fmtBrl(snap.varDaily95Brl)}</p>
                    </div>
                    <div>
                      <p className="text-xs text-muted-foreground">Alavancagem</p>
                      <p className="font-data text-sm">{snap.grossLeverage?.toFixed(1)}x</p>
                    </div>
                  </div>
                </div>
              </CardHeader>
              {activeTrades.length > 0 && (
                <CardContent className="pt-0">
                  <div className="flex flex-wrap gap-2">
                    {activeTrades.map((trade: any, tidx: number) => (
                      <Badge key={tidx} variant="outline" className="text-xs font-data">
                        {trade.action} {Math.abs(trade.contractsDelta)}x {trade.b3Ticker}
                      </Badge>
                    ))}
                  </div>
                  <div className="mt-2 grid grid-cols-3 gap-2">
                    <div className="text-xs text-muted-foreground">
                      <span className="uppercase tracking-wider">Trades:</span> {activeTrades.length}
                    </div>
                    <div className="text-xs text-muted-foreground">
                      <span className="uppercase tracking-wider">Exposição Bruta:</span> {fmtBrl(snap.grossExposureBrl)}
                    </div>
                    <div className="text-xs text-muted-foreground">
                      <span className="uppercase tracking-wider">AUM:</span> {fmtBrl(snap.aumBrl)}
                    </div>
                  </div>
                </CardContent>
              )}
            </Card>
          );
        })}
      </div>
    </div>
  );
}

// ============================================================
// Shared Components
// ============================================================

function KpiCard({ label, value, subtitle, icon, color }: { label: string; value: string; subtitle?: string; icon: React.ReactNode; color: string }) {
  return (
    <Card className="bg-card border-border">
      <CardContent className="pt-4 pb-4">
        <div className="flex items-center gap-2 mb-2">
          <span className={color}>{icon}</span>
          <span className="text-xs text-muted-foreground uppercase tracking-wider">{label}</span>
        </div>
        <p className={`font-data text-xl font-bold ${color}`}>{value}</p>
        {subtitle && <p className="text-xs text-muted-foreground mt-1">{subtitle}</p>}
      </CardContent>
    </Card>
  );
}

function MetricBox({ label, value }: { label: string; value: string }) {
  return (
    <div className="p-3 rounded-lg bg-secondary/30 border border-border">
      <p className="text-xs text-muted-foreground uppercase tracking-wider mb-1">{label}</p>
      <p className="font-data text-sm font-bold text-foreground">{value}</p>
    </div>
  );
}

function LimitBar({ label, current, limit, unit }: { label: string; current: number; limit: number; unit: string }) {
  const pct = Math.min((current / limit) * 100, 100);
  const isBreached = current > limit;
  const isWarning = pct > 75;

  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs">
        <span className="text-muted-foreground">{label}</span>
        <span className={`font-data font-bold ${isBreached ? "text-rose-400" : isWarning ? "text-amber-400" : "text-emerald-400"}`}>
          {current.toFixed(1)}{unit} / {limit}{unit}
        </span>
      </div>
      <div className="h-2 rounded-full bg-secondary/50 overflow-hidden">
        <div
          className={`h-full rounded-full transition-all ${isBreached ? "bg-rose-500" : isWarning ? "bg-amber-500" : "bg-emerald-500"}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

// ============================================================
// Main Portfolio Page
// ============================================================

export default function Portfolio() {
  const { user, loading: authLoading } = useAuth();

  if (authLoading) {
    return <div className="min-h-screen flex items-center justify-center bg-background"><Loader2 className="w-8 h-8 animate-spin text-primary" /></div>;
  }

  if (!user) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <Card className="bg-card border-border max-w-md w-full mx-4">
          <CardContent className="py-12 text-center">
            <Shield className="w-12 h-12 text-primary mx-auto mb-4" />
            <h2 className="text-xl font-semibold mb-2">Acesso Restrito</h2>
            <p className="text-sm text-muted-foreground mb-6">O módulo de Portfolio Management requer autenticação.</p>
            <Button asChild><a href={getLoginUrl()}>Fazer Login</a></Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <motion.header
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        className="sticky top-0 z-50 border-b border-border/50 bg-background/95 backdrop-blur-sm"
      >
        <div className="container">
          <div className="flex items-center justify-between h-14">
            <div className="flex items-center gap-4">
              <Link href="/" className="flex items-center gap-2 text-muted-foreground hover:text-foreground transition-colors">
                <ArrowLeft className="w-4 h-4" />
                <span className="text-xs uppercase tracking-wider">Dashboard</span>
              </Link>
              <Separator orientation="vertical" className="h-6" />
              <div className="flex items-center gap-2">
                <BarChart3 className="w-5 h-5 text-primary" />
                <h1 className="text-sm font-semibold tracking-wide uppercase">Portfolio Management</h1>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <Badge variant="outline" className="text-xs">B3/BMF</Badge>
              <span className="text-xs text-muted-foreground font-data">{new Date().toLocaleDateString("pt-BR")}</span>
            </div>
          </div>
        </div>
      </motion.header>

      {/* Main Content */}
      <main className="container py-6">
        <Tabs defaultValue="positions" className="space-y-6">
          <TabsList className="grid w-full grid-cols-6 lg:w-auto lg:inline-grid">
            <TabsTrigger value="setup" className="gap-1.5">
              <Settings className="w-4 h-4" />
              <span className="hidden sm:inline">Setup</span>
            </TabsTrigger>
            <TabsTrigger value="positions" className="gap-1.5">
              <BarChart3 className="w-4 h-4" />
              <span className="hidden sm:inline">Posições</span>
            </TabsTrigger>
            <TabsTrigger value="trades" className="gap-1.5">
              <ArrowUpDown className="w-4 h-4" />
              <span className="hidden sm:inline">Trades</span>
            </TabsTrigger>
            <TabsTrigger value="pnl" className="gap-1.5">
              <DollarSign className="w-4 h-4" />
              <span className="hidden sm:inline">P&L</span>
            </TabsTrigger>
            <TabsTrigger value="risk" className="gap-1.5">
              <Shield className="w-4 h-4" />
              <span className="hidden sm:inline">Risco</span>
            </TabsTrigger>
            <TabsTrigger value="history" className="gap-1.5">
              <History className="w-4 h-4" />
              <span className="hidden sm:inline">Histórico</span>
            </TabsTrigger>
          </TabsList>

          <TabsContent value="setup"><SetupTab /></TabsContent>
          <TabsContent value="positions"><PositionsTab /></TabsContent>
          <TabsContent value="trades"><TradesTab /></TabsContent>
          <TabsContent value="pnl"><PnlTab /></TabsContent>
          <TabsContent value="risk"><RiskTab /></TabsContent>
          <TabsContent value="history"><HistoryTab /></TabsContent>
        </Tabs>
      </main>
    </div>
  );
}
