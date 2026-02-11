import { MacroDashboard } from '@/hooks/useModelData';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { motion } from 'framer-motion';
import { TrendingUp, TrendingDown, Minus, Target, BarChart3, ShieldAlert, Gauge } from 'lucide-react';

interface Props {
  dashboard: MacroDashboard;
}

function getDirectionStyle(direction: string) {
  if (direction.includes('LONG') && direction.includes('BRL')) {
    return {
      bg: 'bg-emerald-400/10', border: 'border-emerald-400/30', text: 'text-emerald-400',
      icon: <TrendingDown className="w-6 h-6" />, label: 'LONG BRL', sublabel: 'Vender USD / Comprar BRL',
    };
  }
  if (direction.includes('SHORT') && direction.includes('BRL')) {
    return {
      bg: 'bg-rose-400/10', border: 'border-rose-400/30', text: 'text-rose-400',
      icon: <TrendingUp className="w-6 h-6" />, label: 'SHORT BRL', sublabel: 'Comprar USD / Vender BRL',
    };
  }
  return {
    bg: 'bg-amber-400/10', border: 'border-amber-400/30', text: 'text-amber-400',
    icon: <Minus className="w-6 h-6" />, label: 'NEUTRAL', sublabel: 'Sem sinal direcional',
  };
}

export function ActionPanel({ dashboard: d }: Props) {
  const style = getDirectionStyle(d.direction);
  const isMROS = 'positions' in d && d.positions;
  const fmtPct = (v: number | undefined | null) => v != null ? `${v > 0 ? '+' : ''}${v.toFixed(2)}%` : 'N/A';
  const fmtNum = (v: number | undefined | null, dec = 2) => v != null ? v.toFixed(dec) : 'N/A';
  const erColor = (v: number | undefined | null) => v == null ? 'text-foreground' : v > 0 ? 'text-emerald-400' : 'text-rose-400';

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.6, duration: 0.4 }}
    >
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Direction Signal */}
        <Card className={`${style.bg} border ${style.border}`}>
          <CardContent className="pt-6 flex flex-col items-center text-center gap-3">
            <div className={`${style.text}`}>{style.icon}</div>
            <div>
              <p className={`text-2xl font-bold font-data ${style.text}`}>{style.label}</p>
              <p className="text-xs text-muted-foreground mt-1">{style.sublabel}</p>
            </div>
            <p className="text-xs text-muted-foreground/80 mt-2 max-w-[280px]">
              {d.interpretation || `Score total: ${d.score_total?.toFixed(2) || 'N/A'}`}
            </p>
          </CardContent>
        </Card>

        {/* Cross-Asset Expected Returns */}
        <Card className="bg-card border-border/50">
          <CardHeader className="pb-2">
            <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground flex items-center gap-2">
              <Target className="w-3.5 h-3.5" />
              Expected Returns (6m)
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {isMROS ? (
              <>
                {(['fx', 'front', 'long', 'hard'] as const).map(asset => {
                  const pos = d.positions?.[asset];
                  const labels: Record<string, string> = { fx: 'FX (USDBRL)', front: 'Front-End (DI 1Y)', long: 'Long-End (DI 5Y)', hard: 'Hard Currency' };
                  return (
                    <div key={asset} className="flex items-center justify-between">
                      <span className="text-xs text-muted-foreground">{labels[asset]}</span>
                      <div className="flex items-center gap-3">
                        <span className={`font-data text-sm font-bold ${erColor(pos?.expected_return_6m)}`}>
                          {fmtPct(pos?.expected_return_6m)}
                        </span>
                        <span className="font-data text-[10px] text-muted-foreground">
                          S={fmtNum(pos?.sharpe)}
                        </span>
                      </div>
                    </div>
                  );
                })}
              </>
            ) : (
              <>
                <div className="flex items-center justify-between">
                  <span className="text-xs text-muted-foreground">FX 3m</span>
                  <span className={`font-data text-lg font-bold ${erColor(d.expected_return_3m_pct)}`}>
                    {fmtPct(d.expected_return_3m_pct)}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-xs text-muted-foreground">FX 6m</span>
                  <span className={`font-data text-lg font-bold ${erColor(d.expected_return_6m_pct)}`}>
                    {fmtPct(d.expected_return_6m_pct)}
                  </span>
                </div>
              </>
            )}
          </CardContent>
        </Card>

        {/* Risk Metrics & Sizing */}
        <Card className="bg-card border-border/50">
          <CardHeader className="pb-2">
            <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground flex items-center gap-2">
              <ShieldAlert className="w-3.5 h-3.5" />
              Risco & Sizing
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {isMROS && d.risk_metrics ? (
              <>
                <div className="flex items-center justify-between">
                  <span className="text-xs text-muted-foreground">Portfolio Vol (ann)</span>
                  <span className="font-data text-sm font-bold text-foreground">
                    {(d.risk_metrics.portfolio_vol * 100).toFixed(2)}%
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-xs text-muted-foreground">Max Drawdown</span>
                  <span className="font-data text-sm font-bold text-rose-400">
                    {(d.risk_metrics.max_drawdown * 100).toFixed(2)}%
                  </span>
                </div>
                {/* Stress Tests */}
                {d.risk_metrics.stress_tests?.length > 0 && (
                  <div className="border-t border-border/30 pt-2 space-y-1">
                    <span className="text-[10px] text-muted-foreground uppercase tracking-wider">Stress Tests</span>
                    {d.risk_metrics.stress_tests.map((st, i) => (
                      <div key={i} className="flex items-center justify-between">
                        <span className="text-[10px] text-muted-foreground">{st.name}</span>
                        <span className={`font-data text-[10px] font-semibold ${st.return_pct < 0 ? 'text-rose-400' : 'text-emerald-400'}`}>
                          {st.return_pct > 0 ? '+' : ''}{st.return_pct.toFixed(2)}%
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </>
            ) : (
              <>
                <div className="flex items-center justify-between">
                  <span className="text-xs text-muted-foreground">Vol Anualizada</span>
                  <span className="font-data text-sm font-bold text-foreground">
                    {d.current_vol_ann_pct?.toFixed(1) || 'N/A'}%
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-xs text-muted-foreground">Posição 6m</span>
                  <span className={`font-data text-lg font-bold ${
                    (d.recommended_position_6m || 0) > 0 ? 'text-emerald-400' : 'text-rose-400'
                  }`}>
                    {d.recommended_position_6m != null ? `${d.recommended_position_6m > 0 ? '+' : ''}${d.recommended_position_6m.toFixed(2)}x` : 'N/A'}
                  </span>
                </div>
              </>
            )}
          </CardContent>
        </Card>
      </div>
    </motion.div>
  );
}
