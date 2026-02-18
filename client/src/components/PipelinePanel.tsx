/**
 * PipelinePanel — Daily automated update pipeline trigger + status UI.
 * Shows: trigger button, step-by-step progress, last run summary, run history.
 */

import { usePipelineStatus, useLatestPipelineRun, usePipelineHistory, useTriggerPipeline } from '@/hooks/useModelData';
import { useAuth } from '@/_core/hooks/useAuth';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { toast } from 'sonner';
import {
  Play,
  Loader2,
  CheckCircle2,
  XCircle,
  Clock,
  Database,
  Cpu,
  Bell,
  Briefcase,
  BarChart3,
  Send,
  ChevronDown,
  ChevronUp,
  Timer,
  CalendarClock,
  Rocket,
} from 'lucide-react';
import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';

const STEP_ICONS: Record<string, React.ReactNode> = {
  data_ingest: <Database className="w-4 h-4" />,
  model_run: <Cpu className="w-4 h-4" />,
  alerts: <Bell className="w-4 h-4" />,
  portfolio: <Briefcase className="w-4 h-4" />,
  backtest: <BarChart3 className="w-4 h-4" />,
  notify: <Send className="w-4 h-4" />,
};

const STATUS_COLORS: Record<string, string> = {
  pending: 'text-muted-foreground',
  running: 'text-cyan-400',
  completed: 'text-emerald-400',
  failed: 'text-rose-400',
  skipped: 'text-amber-400',
};

const STATUS_BG: Record<string, string> = {
  pending: 'bg-muted-foreground/10',
  running: 'bg-cyan-400/10 border-cyan-400/30',
  completed: 'bg-emerald-400/10 border-emerald-400/30',
  failed: 'bg-rose-400/10 border-rose-400/30',
  skipped: 'bg-amber-400/10 border-amber-400/30',
};

function StatusIcon({ status }: { status: string }) {
  switch (status) {
    case 'completed': return <CheckCircle2 className="w-4 h-4 text-emerald-400" />;
    case 'failed': return <XCircle className="w-4 h-4 text-rose-400" />;
    case 'running': return <Loader2 className="w-4 h-4 text-cyan-400 animate-spin" />;
    case 'skipped': return <Clock className="w-4 h-4 text-amber-400" />;
    default: return <Clock className="w-4 h-4 text-muted-foreground/50" />;
  }
}

function formatDuration(ms: number | null | undefined): string {
  if (!ms) return '--';
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.floor(ms / 60000)}m ${Math.round((ms % 60000) / 1000)}s`;
}

function formatTimeAgo(dateStr: string | null | undefined): string {
  if (!dateStr) return 'Nunca';
  const date = new Date(dateStr);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMin = Math.floor(diffMs / 60000);
  const diffHr = Math.floor(diffMs / 3600000);
  const diffDay = Math.floor(diffMs / 86400000);

  if (diffMin < 1) return 'Agora';
  if (diffMin < 60) return `${diffMin}m atrás`;
  if (diffHr < 24) return `${diffHr}h atrás`;
  return `${diffDay}d atrás`;
}

export function PipelinePanel() {
  const { isAuthenticated } = useAuth();
  const { data: pipelineStatus } = usePipelineStatus();
  const { data: latestRun } = useLatestPipelineRun();
  const { data: history } = usePipelineHistory();
  const triggerPipeline = useTriggerPipeline();
  const [showHistory, setShowHistory] = useState(false);

  const isRunning = pipelineStatus?.isRunning || false;
  const progress = pipelineStatus?.progress || 0;
  const steps = pipelineStatus?.steps || [];

  const handleTrigger = () => {
    if (!isAuthenticated) {
      toast.error('Faça login para executar o pipeline');
      return;
    }
    triggerPipeline.mutate(undefined, {
      onSuccess: (data) => {
        if (data.success) {
          toast.success('Pipeline diário iniciado! Acompanhe o progresso abaixo.');
        } else {
          toast.error('Erro: Pipeline já em execução');
        }
      },
      onError: (err) => {
        toast.error('Erro ao iniciar pipeline: ' + err.message);
      },
    });
  };

  const lastRunSteps = (latestRun?.stepsJson as Array<{ name: string; label: string; status: string; durationMs?: number; message?: string; error?: string }>) || [];
  const lastRunSummary = latestRun?.summaryJson as Record<string, unknown> | null;

  return (
    <Card className="border-border/50 bg-card/50 backdrop-blur-sm">
      <CardHeader className="pb-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-primary/10 border border-primary/20">
              <Rocket className="w-5 h-5 text-primary" />
            </div>
            <div>
              <CardTitle className="text-base font-semibold tracking-wide uppercase">
                Pipeline Diário
              </CardTitle>
              <p className="text-xs text-muted-foreground mt-0.5">
                Ingestão → Modelo → Alertas → Portfólio → Backtest → Notificação
              </p>
            </div>
          </div>

          <div className="flex items-center gap-3">
            {/* Schedule info */}
            <div className="hidden sm:flex items-center gap-1.5 text-xs text-muted-foreground">
              <CalendarClock className="w-3.5 h-3.5" />
              <span>Agendado: 07:00 BRT</span>
            </div>

            {/* Trigger button */}
            <Button
              onClick={handleTrigger}
              disabled={isRunning || triggerPipeline.isPending || !isAuthenticated}
              size="sm"
              className="gap-2"
              variant={isRunning ? "outline" : "default"}
            >
              {isRunning ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  <span className="hidden sm:inline">Executando... {progress}%</span>
                  <span className="sm:hidden">{progress}%</span>
                </>
              ) : (
                <>
                  <Play className="w-4 h-4" />
                  <span className="hidden sm:inline">Executar Pipeline</span>
                  <span className="sm:hidden">Run</span>
                </>
              )}
            </Button>
          </div>
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        {/* ---- Live Progress (when running) ---- */}
        <AnimatePresence>
          {isRunning && steps.length > 0 && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              className="space-y-3"
            >
              {/* Progress bar */}
              <div className="relative h-2 rounded-full bg-muted overflow-hidden">
                <motion.div
                  className="absolute inset-y-0 left-0 rounded-full bg-gradient-to-r from-primary to-cyan-400"
                  initial={{ width: 0 }}
                  animate={{ width: `${progress}%` }}
                  transition={{ duration: 0.5 }}
                />
              </div>

              {/* Step list */}
              <div className="grid gap-2">
                {steps.map((step, i) => (
                  <div
                    key={step.name}
                    className={`flex items-center gap-3 px-3 py-2 rounded-lg border ${STATUS_BG[step.status] || 'border-border/30'} transition-all`}
                  >
                    <div className={STATUS_COLORS[step.status]}>
                      {STEP_ICONS[step.name] || <Clock className="w-4 h-4" />}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className={`text-sm font-medium ${STATUS_COLORS[step.status]}`}>
                          {step.label}
                        </span>
                        <StatusIcon status={step.status} />
                      </div>
                      {step.message && (
                        <p className="text-xs text-muted-foreground truncate mt-0.5">{step.message}</p>
                      )}
                      {step.error && (
                        <p className="text-xs text-rose-400 truncate mt-0.5">{step.error}</p>
                      )}
                    </div>
                    <div className="flex items-center gap-2">
                      {/* Retry badge */}
                      {(step as any).retryCount > 0 && (
                        <span className="text-[9px] px-1.5 py-0.5 rounded bg-amber-400/15 text-amber-400 font-data border border-amber-400/20">
                          ⟳{(step as any).retryCount}
                        </span>
                      )}
                      <div className="text-xs text-muted-foreground font-data">
                        {step.durationMs ? formatDuration(step.durationMs) : step.status === 'running' ? '...' : ''}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* ---- Last Run Summary (when not running) ---- */}
        {!isRunning && latestRun && (
          <div className="space-y-3">
            {/* Summary row */}
            <div className="flex items-center justify-between px-3 py-2.5 rounded-lg border border-border/30 bg-muted/30">
              <div className="flex items-center gap-3">
                <div className={`p-1.5 rounded-md ${
                  latestRun.status === 'completed' ? 'bg-emerald-400/10' :
                  latestRun.status === 'failed' ? 'bg-rose-400/10' : 'bg-amber-400/10'
                }`}>
                  {latestRun.status === 'completed' ? (
                    <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                  ) : latestRun.status === 'failed' ? (
                    <XCircle className="w-4 h-4 text-rose-400" />
                  ) : (
                    <Clock className="w-4 h-4 text-amber-400" />
                  )}
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium">
                      Último run: {latestRun.status === 'completed' ? 'Sucesso' : latestRun.status === 'failed' ? 'Falhou' : latestRun.status}
                    </span>
                    <span className="text-xs px-1.5 py-0.5 rounded bg-muted text-muted-foreground">
                      {latestRun.triggerType === 'manual' ? 'Manual' : latestRun.triggerType === 'scheduled' ? 'Agendado' : 'Startup'}
                    </span>
                  </div>
                  <div className="flex items-center gap-3 text-xs text-muted-foreground mt-0.5">
                    <span className="flex items-center gap-1">
                      <Timer className="w-3 h-3" />
                      {formatDuration(latestRun.durationMs)}
                    </span>
                    <span>{formatTimeAgo(latestRun.completedAt ? String(latestRun.completedAt) : null)}</span>
                    <span>{latestRun.completedSteps}/{latestRun.totalSteps} steps</span>
                  </div>
                </div>
              </div>

              {/* Summary metrics */}
              {lastRunSummary && (
                <div className="hidden md:flex items-center gap-4 text-xs">
                  {'spot' in lastRunSummary && lastRunSummary.spot != null && (
                    <div className="text-center">
                      <div className="text-muted-foreground uppercase tracking-wider">Spot</div>
                      <div className="font-data font-bold text-primary">{Number(lastRunSummary.spot).toFixed(4)}</div>
                    </div>
                  )}
                  {'score' in lastRunSummary && lastRunSummary.score != null && (
                    <div className="text-center">
                      <div className="text-muted-foreground uppercase tracking-wider">Score</div>
                      <div className="font-data font-bold">{Number(lastRunSummary.score).toFixed(2)}</div>
                    </div>
                  )}
                  {'regime' in lastRunSummary && lastRunSummary.regime != null && (
                    <div className="text-center">
                      <div className="text-muted-foreground uppercase tracking-wider">Regime</div>
                      <div className="font-data font-bold">{String(lastRunSummary.regime)}</div>
                    </div>
                  )}
                  {'alertsGenerated' in lastRunSummary && lastRunSummary.alertsGenerated != null && (
                    <div className="text-center">
                      <div className="text-muted-foreground uppercase tracking-wider">Alertas</div>
                      <div className="font-data font-bold">{String(lastRunSummary.alertsGenerated)}</div>
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* Last run steps (collapsed by default) */}
            {lastRunSteps.length > 0 && (
              <div>
                <button
                  onClick={() => setShowHistory(!showHistory)}
                  className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
                >
                  {showHistory ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
                  {showHistory ? 'Ocultar detalhes' : 'Ver detalhes dos steps'}
                </button>

                <AnimatePresence>
                  {showHistory && (
                    <motion.div
                      initial={{ opacity: 0, height: 0 }}
                      animate={{ opacity: 1, height: 'auto' }}
                      exit={{ opacity: 0, height: 0 }}
                      className="mt-2 grid gap-1.5"
                    >
                      {lastRunSteps.map((step) => (
                        <div
                          key={step.name}
                          className="flex items-center gap-2.5 px-2.5 py-1.5 rounded-md border border-border/20 bg-muted/20"
                        >
                          <StatusIcon status={step.status} />
                          <span className="text-xs font-medium flex-1">{step.label}</span>
                          {step.message && (
                            <span className="text-[10px] text-muted-foreground truncate max-w-[200px]">{step.message}</span>
                          )}
                          {step.error && (
                            <span className="text-[10px] text-rose-400 truncate max-w-[200px]">{step.error}</span>
                          )}
                          <span className="text-[10px] text-muted-foreground font-data">
                            {formatDuration(step.durationMs)}
                          </span>
                        </div>
                      ))}
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>
            )}

            {/* Run history */}
            {history && history.length > 1 && (
              <div className="pt-2 border-t border-border/30">
                <p className="text-xs text-muted-foreground mb-2 uppercase tracking-wider">Histórico Recente</p>
                <div className="grid gap-1">
                  {history.slice(0, 5).map((run) => (
                    <div key={run.id} className="flex items-center gap-2 text-xs py-1">
                      <div className={`w-1.5 h-1.5 rounded-full ${
                        run.status === 'completed' ? 'bg-emerald-400' :
                        run.status === 'failed' ? 'bg-rose-400' : 'bg-amber-400'
                      }`} />
                      <span className="text-muted-foreground font-data">
                        {new Date(run.startedAt).toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' })}
                      </span>
                      <span className="text-muted-foreground font-data">
                        {new Date(run.startedAt).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })}
                      </span>
                      <span className={`px-1.5 py-0.5 rounded text-[10px] ${
                        run.triggerType === 'manual' ? 'bg-primary/10 text-primary' : 'bg-muted text-muted-foreground'
                      }`}>
                        {run.triggerType}
                      </span>
                      <span className="flex-1" />
                      <span className="font-data">{formatDuration(run.durationMs)}</span>
                      <span>{run.completedSteps}/{run.totalSteps}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* ---- Empty state ---- */}
        {!isRunning && !latestRun && (
          <div className="text-center py-6">
            <Rocket className="w-8 h-8 text-muted-foreground/30 mx-auto mb-2" />
            <p className="text-sm text-muted-foreground">Nenhum pipeline executado ainda</p>
            <p className="text-xs text-muted-foreground/70 mt-1">
              Clique "Executar Pipeline" ou aguarde o agendamento diário (07:00 BRT)
            </p>
          </div>
        )}

        {/* Footer info */}
        <div className="pt-2 border-t border-border/20">
          <p className="text-[10px] text-muted-foreground/60 leading-relaxed">
            O pipeline executa automaticamente todos os dias às 07:00 BRT: ingestão de dados (BCB, Yahoo, Bloomberg) →
            modelo ARC Macro (Ridge+GBM+Regime) → alertas (score, regime, SHAP, r*) → portfólio → backtest → notificação.
            Duração típica: 3-8 minutos.
          </p>
        </div>
      </CardContent>
    </Card>
  );
}
