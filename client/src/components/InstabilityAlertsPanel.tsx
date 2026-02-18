/**
 * InstabilityAlertsPanel — v4.4 Feature Stability Transition Alerts
 * Detects and displays when features change stability classification
 * between runs (Robust→Unstable = regime change signal).
 */

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import {
  AlertTriangle,
  ArrowDownRight,
  ArrowUpRight,
  Bell,
  Info,
  ShieldAlert,
  ShieldCheck,
  TrendingDown,
  TrendingUp,
} from 'lucide-react';

const FEATURE_LABELS: Record<string, string> = {
  Z_real_diff: 'Diferencial Real',
  Z_infl_surprise: 'Surpresa Inflação',
  Z_fiscal: 'Risco Fiscal',
  Z_tot: 'Termos de Troca',
  Z_dxy: 'Dólar Global (DXY)',
  Z_vix: 'VIX',
  Z_cds_br: 'CDS Brasil',
  Z_beer: 'BEER Misalignment',
  Z_reer_gap: 'REER Gap',
  Z_term_premium: 'Term Premium',
  Z_cip_basis: 'CIP Basis',
  Z_iron_ore: 'Minério de Ferro',
  Z_policy_gap: 'Policy Gap',
  Z_rstar_composite: 'r* Composto',
  Z_rstar_momentum: 'r* Momentum',
  Z_fiscal_component: 'Comp. Fiscal',
  Z_sovereign_component: 'Comp. Soberano',
  Z_selic_star_gap: 'SELIC* Gap',
  rstar_regime_signal: 'Sinal Regime r*',
  Z_rstar_curve_gap: 'r* Curve Gap',
  Z_focus_fx: 'Focus FX',
  Z_ewz: 'EWZ',
  Z_portfolio_flow: 'Fluxo Portfólio',
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
};

const INSTRUMENT_SHORT: Record<string, string> = {
  fx: 'FX',
  front: 'Front',
  belly: 'Belly',
  long: 'Long',
  hard: 'Hard',
};

interface AlertData {
  type: 'critical' | 'warning' | 'info';
  feature: string;
  instrument: string;
  transition?: string;
  message: string;
}

interface InstabilityAlertsPanelProps {
  data: Record<string, { alerts?: AlertData[] }> | null | undefined;
}

function getAlertConfig(type: string) {
  switch (type) {
    case 'critical':
      return {
        icon: <AlertTriangle className="w-4 h-4 text-red-400" />,
        bg: 'bg-red-500/10 border-red-500/20',
        badge: 'bg-red-500/20 text-red-300 border-red-500/30',
        label: 'Crítico',
        arrow: <TrendingDown className="w-3.5 h-3.5 text-red-400" />,
      };
    case 'warning':
      return {
        icon: <ArrowDownRight className="w-4 h-4 text-yellow-400" />,
        bg: 'bg-yellow-500/10 border-yellow-500/20',
        badge: 'bg-yellow-500/20 text-yellow-300 border-yellow-500/30',
        label: 'Atenção',
        arrow: <ArrowDownRight className="w-3.5 h-3.5 text-yellow-400" />,
      };
    case 'info':
      return {
        icon: <ArrowUpRight className="w-4 h-4 text-emerald-400" />,
        bg: 'bg-emerald-500/10 border-emerald-500/20',
        badge: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30',
        label: 'Positivo',
        arrow: <TrendingUp className="w-3.5 h-3.5 text-emerald-400" />,
      };
    default:
      return {
        icon: <Info className="w-4 h-4 text-slate-400" />,
        bg: 'bg-slate-500/10 border-slate-500/20',
        badge: 'bg-slate-500/20 text-slate-300 border-slate-500/30',
        label: 'Info',
        arrow: <Info className="w-3.5 h-3.5 text-slate-400" />,
      };
  }
}

export function InstabilityAlertsPanel({ data }: InstabilityAlertsPanelProps) {
  if (!data) return null;

  // Collect all alerts across instruments
  const allAlerts: AlertData[] = [];
  Object.keys(data).forEach((inst) => {
    const alerts = data[inst]?.alerts;
    if (alerts && alerts.length > 0) {
      allAlerts.push(...alerts);
    }
  });

  if (allAlerts.length === 0) return null;

  // Sort: critical first, then warning, then info
  const sortOrder = { critical: 0, warning: 1, info: 2 };
  allAlerts.sort(
    (a, b) =>
      (sortOrder[a.type] ?? 3) - (sortOrder[b.type] ?? 3)
  );

  const criticalCount = allAlerts.filter((a) => a.type === 'critical').length;
  const warningCount = allAlerts.filter((a) => a.type === 'warning').length;
  const infoCount = allAlerts.filter((a) => a.type === 'info').length;

  return (
    <Card className="bg-slate-800/50 border-slate-700/50">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm text-slate-300 flex items-center gap-2">
            <Bell className="w-4 h-4 text-amber-400" />
            Alertas de Instabilidade — Transições de Estabilidade
          </CardTitle>
          <div className="flex items-center gap-2">
            {criticalCount > 0 && (
              <Badge className="bg-red-500/20 text-red-300 border-red-500/30 text-xs">
                <ShieldAlert className="w-3 h-3 mr-1" />
                {criticalCount} crítico{criticalCount > 1 ? 's' : ''}
              </Badge>
            )}
            {warningCount > 0 && (
              <Badge className="bg-yellow-500/20 text-yellow-300 border-yellow-500/30 text-xs">
                {warningCount} atenção
              </Badge>
            )}
            {infoCount > 0 && (
              <Badge className="bg-emerald-500/20 text-emerald-300 border-emerald-500/30 text-xs">
                <ShieldCheck className="w-3 h-3 mr-1" />
                {infoCount} positivo{infoCount > 1 ? 's' : ''}
              </Badge>
            )}
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-2">
        {allAlerts.map((alert, idx) => {
          const config = getAlertConfig(alert.type);
          return (
            <div
              key={idx}
              className={`flex items-start gap-3 p-3 rounded-md border ${config.bg}`}
            >
              {config.icon}
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-0.5">
                  <span className="text-xs font-semibold text-slate-200">
                    {FEATURE_LABELS[alert.feature] || alert.feature}
                  </span>
                  <span className="text-[10px] text-slate-500">em</span>
                  <Badge
                    variant="outline"
                    className="text-[10px] px-1.5 py-0 border-slate-600 text-slate-300"
                  >
                    {INSTRUMENT_SHORT[alert.instrument] || alert.instrument}
                  </Badge>
                  <Badge className={`text-[10px] px-1.5 py-0 ${config.badge}`}>
                    {config.label}
                  </Badge>
                </div>
                <p className="text-xs text-slate-400 leading-relaxed">
                  {alert.message}
                </p>
                {alert.transition && (
                  <div className="flex items-center gap-1 mt-1">
                    {config.arrow}
                    <span className="text-[10px] text-slate-500 font-mono">
                      {alert.transition}
                    </span>
                  </div>
                )}
              </div>
            </div>
          );
        })}

        {/* Explanation footer */}
        <div className="pt-2 border-t border-slate-700/30">
          <p className="text-[10px] text-slate-500 leading-relaxed">
            Alertas são gerados comparando a classificação de estabilidade atual com a execução anterior.
            Transições Robusto→Instável indicam possível mudança de regime. Transições Instável→Robusto
            indicam novos sinais emergentes.
          </p>
        </div>
      </CardContent>
    </Card>
  );
}
