/**
 * DataSourceHealthPanel — Data source health monitoring dashboard.
 * Shows status, latency, uptime, and historical health for each external data source.
 * Design: "Institutional Command Center" dark slate theme.
 */

import { useDataSourceHealth, useCheckDataSources } from '@/hooks/useModelData';
import { useAuth } from '@/_core/hooks/useAuth';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { toast } from 'sonner';
import {
  Activity,
  RefreshCw,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  HelpCircle,
  Clock,
  Wifi,
  WifiOff,
  Loader2,
  ChevronDown,
  ChevronUp,
  TrendingUp,
} from 'lucide-react';
import { useState, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';

// ============================================================
// Status Helpers
// ============================================================

const STATUS_CONFIG: Record<string, {
  icon: React.ReactNode;
  color: string;
  bg: string;
  label: string;
  dotColor: string;
}> = {
  healthy: {
    icon: <CheckCircle2 className="w-4 h-4" />,
    color: 'text-emerald-400',
    bg: 'bg-emerald-400/10 border-emerald-400/20',
    label: 'Online',
    dotColor: 'bg-emerald-400',
  },
  degraded: {
    icon: <AlertTriangle className="w-4 h-4" />,
    color: 'text-amber-400',
    bg: 'bg-amber-400/10 border-amber-400/20',
    label: 'Degradado',
    dotColor: 'bg-amber-400',
  },
  down: {
    icon: <XCircle className="w-4 h-4" />,
    color: 'text-rose-400',
    bg: 'bg-rose-400/10 border-rose-400/20',
    label: 'Offline',
    dotColor: 'bg-rose-400',
  },
  unknown: {
    icon: <HelpCircle className="w-4 h-4" />,
    color: 'text-muted-foreground',
    bg: 'bg-muted/30 border-border/30',
    label: 'Desconhecido',
    dotColor: 'bg-muted-foreground',
  },
};

function formatLatency(ms: number | null | undefined): string {
  if (ms == null) return '--';
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
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

function getLatencyColor(ms: number | null | undefined): string {
  if (ms == null) return 'text-muted-foreground';
  if (ms < 2000) return 'text-emerald-400';
  if (ms < 5000) return 'text-amber-400';
  return 'text-rose-400';
}

function getUptimeColor(pct: number): string {
  if (pct >= 99) return 'text-emerald-400';
  if (pct >= 95) return 'text-amber-400';
  return 'text-rose-400';
}

// ============================================================
// Uptime Sparkline (last 30 checks)
// ============================================================

function UptimeSparkline({ history }: { history: Array<{ status: string; latencyMs: number }> }) {
  if (!history || history.length === 0) return null;

  // Show last 20 checks as colored dots
  const recent = history.slice(-20);
  return (
    <div className="flex items-center gap-[2px]">
      {recent.map((entry, i) => (
        <div
          key={i}
          className={`w-1.5 h-4 rounded-[1px] ${
            entry.status === 'healthy' ? 'bg-emerald-400/60' :
            entry.status === 'degraded' ? 'bg-amber-400/60' :
            'bg-rose-400/60'
          }`}
          title={`${entry.status} (${entry.latencyMs}ms)`}
        />
      ))}
    </div>
  );
}

// ============================================================
// Source Row
// ============================================================

interface SourceData {
  name: string;
  label: string;
  status: string;
  latencyMs: number | null;
  error?: string | null;
  uptimePercent: number;
  lastSuccessAt?: string | null;
  lastDataDate?: string | null;
  history: Array<{ timestamp: string; status: string; latencyMs: number; error?: string }>;
}

function SourceRow({ source }: { source: SourceData }) {
  const config = STATUS_CONFIG[source.status] || STATUS_CONFIG.unknown;

  return (
    <div className={`flex items-center gap-3 px-3 py-2.5 rounded-lg border ${config.bg} transition-all`}>
      {/* Status dot + icon */}
      <div className="flex items-center gap-2">
        <div className={`w-2 h-2 rounded-full ${config.dotColor} ${source.status === 'healthy' ? 'animate-pulse' : ''}`} />
        <div className={config.color}>
          {config.icon}
        </div>
      </div>

      {/* Source info */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-foreground truncate">
            {source.label}
          </span>
          <span className={`text-[9px] px-1.5 py-0.5 rounded font-data ${config.bg} ${config.color} border`}>
            {config.label}
          </span>
        </div>
        {source.error && (
          <p className="text-[10px] text-rose-400/80 truncate mt-0.5">{source.error}</p>
        )}
      </div>

      {/* Uptime sparkline */}
      <div className="hidden md:block">
        <UptimeSparkline history={source.history} />
      </div>

      {/* Metrics */}
      <div className="flex items-center gap-4 text-xs">
        {/* Latency */}
        <div className="text-right min-w-[50px]">
          <div className="text-[9px] text-muted-foreground uppercase">Latência</div>
          <div className={`font-data font-bold ${getLatencyColor(source.latencyMs)}`}>
            {formatLatency(source.latencyMs)}
          </div>
        </div>

        {/* Uptime */}
        <div className="text-right min-w-[50px]">
          <div className="text-[9px] text-muted-foreground uppercase">Uptime</div>
          <div className={`font-data font-bold ${getUptimeColor(source.uptimePercent)}`}>
            {source.uptimePercent.toFixed(1)}%
          </div>
        </div>

        {/* Last success */}
        <div className="text-right min-w-[60px] hidden sm:block">
          <div className="text-[9px] text-muted-foreground uppercase">Último OK</div>
          <div className="font-data text-muted-foreground">
            {formatTimeAgo(source.lastSuccessAt)}
          </div>
        </div>
      </div>
    </div>
  );
}

// ============================================================
// Main Panel
// ============================================================

export function DataSourceHealthPanel() {
  const { isAuthenticated } = useAuth();
  const { data: healthData, isLoading } = useDataSourceHealth();
  const checkSources = useCheckDataSources();
  const [expanded, setExpanded] = useState(false);

  const handleCheck = () => {
    if (!isAuthenticated) {
      toast.error('Faça login para executar health check');
      return;
    }
    checkSources.mutate(undefined, {
      onSuccess: (data) => {
        const healthy = data.filter(s => s.status === 'healthy').length;
        const total = data.length;
        if (healthy === total) {
          toast.success(`Todas as ${total} fontes estão online`);
        } else {
          toast.warning(`${healthy}/${total} fontes online`);
        }
      },
      onError: (err) => {
        toast.error('Erro no health check: ' + err.message);
      },
    });
  };

  // Summary stats
  const summary = useMemo(() => {
    if (!healthData || healthData.length === 0) return null;
    const healthy = healthData.filter(s => s.status === 'healthy').length;
    const degraded = healthData.filter(s => s.status === 'degraded').length;
    const down = healthData.filter(s => s.status === 'down').length;
    const avgLatency = healthData.reduce((sum, s) => sum + (s.latencyMs || 0), 0) / healthData.length;
    const avgUptime = healthData.reduce((sum, s) => sum + s.uptimePercent, 0) / healthData.length;
    return { healthy, degraded, down, total: healthData.length, avgLatency, avgUptime };
  }, [healthData]);

  const hasData = healthData && healthData.length > 0;

  return (
    <Card className="border-border/50 bg-card/50 backdrop-blur-sm">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-blue-500/10 border border-blue-500/20">
              <Activity className="w-5 h-5 text-blue-400" />
            </div>
            <div>
              <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Saúde dos Data Sources
              </CardTitle>
              {summary && (
                <div className="flex items-center gap-3 mt-1">
                  <span className="flex items-center gap-1 text-xs">
                    <Wifi className="w-3 h-3 text-emerald-400" />
                    <span className="text-emerald-400 font-data font-bold">{summary.healthy}</span>
                  </span>
                  {summary.degraded > 0 && (
                    <span className="flex items-center gap-1 text-xs">
                      <AlertTriangle className="w-3 h-3 text-amber-400" />
                      <span className="text-amber-400 font-data font-bold">{summary.degraded}</span>
                    </span>
                  )}
                  {summary.down > 0 && (
                    <span className="flex items-center gap-1 text-xs">
                      <WifiOff className="w-3 h-3 text-rose-400" />
                      <span className="text-rose-400 font-data font-bold">{summary.down}</span>
                    </span>
                  )}
                  <span className="text-[10px] text-muted-foreground">
                    de {summary.total} fontes
                  </span>
                </div>
              )}
            </div>
          </div>

          <div className="flex items-center gap-2">
            {summary && (
              <div className="hidden sm:flex items-center gap-2 text-xs text-muted-foreground mr-2">
                <TrendingUp className="w-3.5 h-3.5" />
                <span>Uptime médio: <span className={`font-data font-bold ${getUptimeColor(summary.avgUptime)}`}>{summary.avgUptime.toFixed(1)}%</span></span>
              </div>
            )}

            <Button
              onClick={handleCheck}
              disabled={checkSources.isPending || !isAuthenticated}
              size="sm"
              variant="outline"
              className="gap-1.5"
            >
              {checkSources.isPending ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <RefreshCw className="w-3.5 h-3.5" />
              )}
              <span className="hidden sm:inline">Verificar</span>
            </Button>

            {hasData && (
              <Button
                onClick={() => setExpanded(!expanded)}
                size="sm"
                variant="ghost"
                className="gap-1"
              >
                {expanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
              </Button>
            )}
          </div>
        </div>
      </CardHeader>

      <AnimatePresence>
        {(expanded || !hasData) && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.2 }}
          >
            <CardContent className="space-y-2 pt-0">
              {isLoading && (
                <div className="flex items-center justify-center py-6">
                  <Loader2 className="w-5 h-5 animate-spin text-muted-foreground" />
                  <span className="ml-2 text-sm text-muted-foreground">Carregando status...</span>
                </div>
              )}

              {!isLoading && !hasData && (
                <div className="text-center py-6">
                  <HelpCircle className="w-8 h-8 text-muted-foreground/30 mx-auto mb-2" />
                  <p className="text-sm text-muted-foreground">
                    Nenhum health check registrado. Clique em "Verificar" para executar o primeiro check.
                  </p>
                </div>
              )}

              {hasData && healthData!.map((source) => (
                <SourceRow key={source.name} source={source as SourceData} />
              ))}

              {hasData && (
                <p className="text-[10px] text-muted-foreground/60 leading-relaxed pt-2">
                  Health checks verificam a conectividade e latência de cada fonte de dados externa.
                  O uptime é calculado com base no histórico de checks. Fontes com latência {'>'} 10s são marcadas como degradadas.
                  O pipeline executa health checks automaticamente antes de cada coleta de dados.
                </p>
              )}
            </CardContent>
          </motion.div>
        )}
      </AnimatePresence>
    </Card>
  );
}
