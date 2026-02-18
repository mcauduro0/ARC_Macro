/**
 * ModelAlertsPanel — Automatic alerts for regime changes, SHAP shifts, score changes.
 * Shows a notification-style panel with severity indicators and dismiss actions.
 * Design: "Institutional Command Center" dark slate theme.
 */

import { trpc } from '@/lib/trpc';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import {
  Bell, AlertTriangle, AlertCircle, Info, X, Check,
  TrendingUp, BarChart3, Activity, ShieldAlert, Eye, EyeOff,
  ArrowRight, Scale,
} from 'lucide-react';
import { Link } from 'wouter';
import { useState, useMemo } from 'react';
import { useAuth } from '@/_core/hooks/useAuth';

// ============================================================
// Types
// ============================================================

interface ModelAlert {
  id: number;
  modelRunId: number | null;
  alertType: string;
  severity: string;
  title: string;
  message: string;
  previousValue: string | null;
  currentValue: string | null;
  threshold: number | null;
  instrument: string | null;
  feature: string | null;
  detailsJson: Record<string, unknown> | null;
  isRead: boolean;
  isDismissed: boolean;
  createdAt: string;
}

// ============================================================
// Helpers
// ============================================================

const SEVERITY_CONFIG: Record<string, { icon: typeof AlertTriangle; color: string; bg: string; border: string; label: string }> = {
  critical: {
    icon: AlertTriangle,
    color: 'text-red-400',
    bg: 'bg-red-500/10',
    border: 'border-red-500/30',
    label: 'CRÍTICO',
  },
  warning: {
    icon: AlertCircle,
    color: 'text-amber-400',
    bg: 'bg-amber-500/10',
    border: 'border-amber-500/30',
    label: 'ALERTA',
  },
  info: {
    icon: Info,
    color: 'text-cyan-400',
    bg: 'bg-cyan-500/10',
    border: 'border-cyan-500/30',
    label: 'INFO',
  },
};

const ALERT_TYPE_ICONS: Record<string, typeof Activity> = {
  regime_change: Activity,
  shap_shift: BarChart3,
  score_change: TrendingUp,
  drawdown_warning: ShieldAlert,
  model_degradation: AlertTriangle,
  data_quality: AlertCircle,
  feature_stability: Activity,
  rebalancing_deviation: Activity,
};

const ALERT_TYPE_LABELS: Record<string, string> = {
  regime_change: 'Regime',
  shap_shift: 'SHAP',
  score_change: 'Score',
  drawdown_warning: 'Drawdown',
  model_degradation: 'Degradação',
  data_quality: 'Dados',
  feature_stability: 'Estabilidade',
  rebalancing_deviation: 'Rebalanceamento',
};

function timeAgo(dateStr: string): string {
  const now = new Date();
  const date = new Date(dateStr);
  const diffMs = now.getTime() - date.getTime();
  const diffMin = Math.floor(diffMs / 60000);
  const diffHr = Math.floor(diffMin / 60);
  const diffDay = Math.floor(diffHr / 24);

  if (diffMin < 1) return 'agora';
  if (diffMin < 60) return `${diffMin}m atrás`;
  if (diffHr < 24) return `${diffHr}h atrás`;
  if (diffDay < 7) return `${diffDay}d atrás`;
  return date.toLocaleDateString('pt-BR');
}

// ============================================================
// Alert Card Component
// ============================================================

function AlertCard({ alert, onMarkRead, onDismiss, isAuthenticated }: {
  alert: ModelAlert;
  onMarkRead: (id: number) => void;
  onDismiss: (id: number) => void;
  isAuthenticated: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const config = SEVERITY_CONFIG[alert.severity] || SEVERITY_CONFIG.info;
  const TypeIcon = ALERT_TYPE_ICONS[alert.alertType] || Info;
  const SeverityIcon = config.icon;

  return (
    <div
      className={`rounded-lg border p-3 transition-all ${config.border} ${config.bg} ${
        !alert.isRead ? 'ring-1 ring-offset-0 ring-offset-background' : 'opacity-80'
      } ${!alert.isRead ? config.border.replace('border-', 'ring-') : ''}`}
    >
      {/* Header */}
      <div className="flex items-start gap-2.5">
        <div className={`mt-0.5 flex-shrink-0 ${config.color}`}>
          <SeverityIcon className="w-4 h-4" />
        </div>

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <Badge
              variant="outline"
              className={`text-[9px] px-1.5 py-0 h-4 ${config.border} ${config.color} bg-transparent`}
            >
              {config.label}
            </Badge>
            <span className="inline-flex items-center gap-1 text-[10px] text-muted-foreground">
              <TypeIcon className="w-3 h-3" />
              {ALERT_TYPE_LABELS[alert.alertType] || alert.alertType}
            </span>
            {alert.instrument && (
              <span className="text-[10px] font-mono text-muted-foreground uppercase">
                {alert.instrument}
              </span>
            )}
            <span className="text-[10px] text-muted-foreground ml-auto flex-shrink-0">
              {timeAgo(alert.createdAt)}
            </span>
          </div>

          <h4
            className="text-xs font-semibold text-foreground mt-1 cursor-pointer hover:text-primary transition-colors"
            onClick={() => setExpanded(!expanded)}
          >
            {alert.title}
          </h4>

          {/* Expanded message */}
          {expanded && (
            <div className="mt-2 space-y-2">
              <p className="text-xs text-foreground/70 leading-relaxed">{alert.message}</p>

              {/* Value comparison */}
              {(alert.previousValue || alert.currentValue) && (
                <div className="flex items-center gap-3 text-[10px]">
                  {alert.previousValue && (
                    <span className="text-muted-foreground">
                      Anterior: <span className="font-mono text-foreground/60">{alert.previousValue}</span>
                    </span>
                  )}
                  {alert.previousValue && alert.currentValue && (
                    <span className="text-muted-foreground">→</span>
                  )}
                  {alert.currentValue && (
                    <span className="text-muted-foreground">
                      Atual: <span className={`font-mono ${config.color}`}>{alert.currentValue}</span>
                    </span>
                  )}
                  {alert.threshold !== null && (
                    <span className="text-muted-foreground">
                      (threshold: {alert.threshold})
                    </span>
                  )}
                </div>
              )}

              {/* Actionable buttons for regime change and rebalancing alerts */}
              {(alert.alertType === 'regime_change' || alert.alertType === 'rebalancing_deviation') && (
                <div className="mt-2 flex items-center gap-2">
                  <Link href="/portfolio?tab=rebalance">
                    <Button variant="outline" size="sm" className="h-6 text-[10px] gap-1 border-primary/30 text-primary hover:bg-primary/10">
                      <Scale className="w-3 h-3" />
                      Rebalancear Portfólio
                      <ArrowRight className="w-3 h-3" />
                    </Button>
                  </Link>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Actions */}
        {isAuthenticated && (
          <div className="flex items-center gap-1 flex-shrink-0">
            {!alert.isRead && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-6 w-6"
                    onClick={(e) => { e.stopPropagation(); onMarkRead(alert.id); }}
                  >
                    <Eye className="w-3 h-3" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>Marcar como lido</TooltipContent>
              </Tooltip>
            )}
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-6 w-6"
                  onClick={(e) => { e.stopPropagation(); onDismiss(alert.id); }}
                >
                  <X className="w-3 h-3" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>Dispensar</TooltipContent>
            </Tooltip>
          </div>
        )}
      </div>
    </div>
  );
}

// ============================================================
// Main Panel Component
// ============================================================

export function ModelAlertsPanel() {
  const { data: alerts, isLoading } = trpc.alerts.list.useQuery(undefined, {
    refetchInterval: 60000, // Refresh every minute
  });
  const { data: unreadCount } = trpc.alerts.unreadCount.useQuery(undefined, {
    refetchInterval: 60000,
  });
  const { isAuthenticated } = useAuth();
  const utils = trpc.useUtils();

  const markRead = trpc.alerts.markRead.useMutation({
    onSuccess: () => {
      utils.alerts.list.invalidate();
      utils.alerts.unreadCount.invalidate();
    },
  });

  const dismiss = trpc.alerts.dismiss.useMutation({
    onSuccess: () => {
      utils.alerts.list.invalidate();
      utils.alerts.unreadCount.invalidate();
    },
  });

  const dismissAll = trpc.alerts.dismissAll.useMutation({
    onSuccess: () => {
      utils.alerts.list.invalidate();
      utils.alerts.unreadCount.invalidate();
    },
  });

  const testNotification = trpc.alerts.testNotification.useMutation({
    onSuccess: (data) => {
      console.log('[Alerts] Test notification:', data.message);
    },
    onError: (err) => {
      console.error('[Alerts] Test notification failed:', err.message);
    },
  });

  const [filterType, setFilterType] = useState<string | null>(null);
  const [filterSeverity, setFilterSeverity] = useState<string | null>(null);

  const filteredAlerts = useMemo(() => {
    if (!alerts) return [];
    let result = alerts as unknown as ModelAlert[];
    if (filterType) result = result.filter(a => a.alertType === filterType);
    if (filterSeverity) result = result.filter(a => a.severity === filterSeverity);
    return result.sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime());
  }, [alerts, filterType, filterSeverity]);

  // Count by type for filter badges
  const typeCounts = useMemo(() => {
    if (!alerts) return {};
    const counts: Record<string, number> = {};
    (alerts as unknown as ModelAlert[]).forEach(a => {
      counts[a.alertType] = (counts[a.alertType] || 0) + 1;
    });
    return counts;
  }, [alerts]);

  const severityCounts = useMemo(() => {
    if (!alerts) return {};
    const counts: Record<string, number> = {};
    (alerts as unknown as ModelAlert[]).forEach(a => {
      counts[a.severity] = (counts[a.severity] || 0) + 1;
    });
    return counts;
  }, [alerts]);

  if (isLoading) {
    return (
      <Card className="bg-card border-border/50">
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-semibold tracking-wider uppercase text-muted-foreground flex items-center gap-2">
            <Bell className="w-4 h-4" />
            Alertas do Modelo
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

  return (
    <Card className="bg-card border-border/50">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-semibold tracking-wider uppercase text-muted-foreground flex items-center gap-2">
            <Bell className="w-4 h-4" />
            Alertas do Modelo
            {(unreadCount as number) > 0 && (
              <Badge className="bg-red-500 text-white text-[10px] px-1.5 py-0 h-4 rounded-full">
                {unreadCount as number}
              </Badge>
            )}
          </CardTitle>
          <div className="flex items-center gap-2">
            {isAuthenticated && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-7 text-[10px]"
                    onClick={() => testNotification.mutate()}
                    disabled={testNotification.isPending}
                  >
                    <Bell className="w-3 h-3 mr-1" />
                    {testNotification.isPending ? 'Enviando...' : 'Testar'}
                  </Button>
                </TooltipTrigger>
                <TooltipContent>Enviar notificação de teste via push</TooltipContent>
              </Tooltip>
            )}
            {isAuthenticated && filteredAlerts.length > 0 && (
              <Button
                variant="ghost"
                size="sm"
                className="h-7 text-[10px]"
                onClick={() => dismissAll.mutate()}
                disabled={dismissAll.isPending}
              >
                <EyeOff className="w-3 h-3 mr-1" />
                Dispensar todos
              </Button>
            )}
          </div>
        </div>

        {/* Filters */}
        {filteredAlerts.length > 0 && (
          <div className="flex items-center gap-2 mt-2 flex-wrap">
            {/* Severity filters */}
            {['critical', 'warning', 'info'].map(sev => {
              const count = severityCounts[sev] || 0;
              if (count === 0) return null;
              const config = SEVERITY_CONFIG[sev];
              const isActive = filterSeverity === sev;
              return (
                <button
                  key={sev}
                  onClick={() => setFilterSeverity(isActive ? null : sev)}
                  className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium border transition-colors ${
                    isActive
                      ? `${config.bg} ${config.border} ${config.color}`
                      : 'border-border/30 text-muted-foreground hover:border-border'
                  }`}
                >
                  {config.label} ({count})
                </button>
              );
            })}

            <span className="text-border/50 mx-1">|</span>

            {/* Type filters */}
            {Object.entries(typeCounts).map(([type, count]) => {
              const isActive = filterType === type;
              return (
                <button
                  key={type}
                  onClick={() => setFilterType(isActive ? null : type)}
                  className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium border transition-colors ${
                    isActive
                      ? 'bg-primary/20 border-primary/30 text-primary'
                      : 'border-border/30 text-muted-foreground hover:border-border'
                  }`}
                >
                  {ALERT_TYPE_LABELS[type] || type} ({count})
                </button>
              );
            })}
          </div>
        )}
      </CardHeader>

      <CardContent className="space-y-2">
        {filteredAlerts.length === 0 ? (
          <div className="text-center py-8">
            <Check className="w-8 h-8 text-emerald-400 mx-auto mb-2" />
            <p className="text-sm text-muted-foreground">
              {(alerts as unknown as ModelAlert[])?.length === 0
                ? 'Nenhum alerta ativo. Alertas serão gerados automaticamente após cada execução do modelo.'
                : 'Nenhum alerta corresponde ao filtro selecionado.'}
            </p>
          </div>
        ) : (
          <>
            {filteredAlerts.map(alert => (
              <AlertCard
                key={alert.id}
                alert={alert}
                onMarkRead={(id) => markRead.mutate({ alertId: id })}
                onDismiss={(id) => dismiss.mutate({ alertId: id })}
                isAuthenticated={isAuthenticated}
              />
            ))}
          </>
        )}
      </CardContent>
    </Card>
  );
}

/**
 * Compact alert badge for the status bar — shows unread count with severity color.
 */
export function AlertBadge() {
  const { data: unreadCount } = trpc.alerts.unreadCount.useQuery(undefined, {
    refetchInterval: 60000,
  });
  const { data: alerts } = trpc.alerts.list.useQuery(undefined, {
    refetchInterval: 60000,
  });

  const count = (unreadCount as number) || 0;
  if (count === 0) return null;

  // Determine highest severity
  const alertList = (alerts as unknown as ModelAlert[]) || [];
  const hasCritical = alertList.some(a => !a.isRead && a.severity === 'critical');
  const hasWarning = alertList.some(a => !a.isRead && a.severity === 'warning');

  const color = hasCritical ? 'bg-red-500' : hasWarning ? 'bg-amber-500' : 'bg-cyan-500';

  return (
    <div className="relative">
      <Bell className="w-4 h-4 text-muted-foreground" />
      <span className={`absolute -top-1 -right-1 ${color} text-white text-[8px] font-bold rounded-full w-3.5 h-3.5 flex items-center justify-center`}>
        {count > 9 ? '9+' : count}
      </span>
    </div>
  );
}
