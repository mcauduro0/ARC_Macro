import { MacroDashboard } from '@/hooks/useModelData';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { motion } from 'framer-motion';
import { ChevronDown, Database, FlaskConical } from 'lucide-react';
import { useState } from 'react';

interface Props {
  dashboard: MacroDashboard;
}

function StatRow({ label, value, highlight }: { label: string; value: string; highlight?: boolean }) {
  return (
    <div className="flex items-center justify-between py-1">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className={`font-data text-xs ${highlight ? 'text-primary font-semibold' : 'text-foreground/80'}`}>
        {value}
      </span>
    </div>
  );
}

export function ModelDetails({ dashboard: d }: Props) {
  const [open, setOpen] = useState(false);
  const isMROS = 'model_details' in d && d.model_details;

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.8, duration: 0.4 }}
    >
      <Collapsible open={open} onOpenChange={setOpen}>
        <Card className="bg-card border-border/50">
          <CollapsibleTrigger className="w-full">
            <CardHeader className="pb-2">
              <div className="flex items-center justify-between">
                <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground flex items-center gap-2">
                  <FlaskConical className="w-3.5 h-3.5" />
                  Detalhes do Modelo
                </CardTitle>
                <ChevronDown className={`w-4 h-4 text-muted-foreground transition-transform ${open ? 'rotate-180' : ''}`} />
              </div>
            </CardHeader>
          </CollapsibleTrigger>
          <CollapsibleContent>
            <CardContent>
              {isMROS ? (
                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-6">
                  {Object.entries(d.model_details).map(([asset, detail]) => {
                    const labels: Record<string, string> = {
                      fx: 'FX (USDBRL)', front: 'Front-End (DI 1Y)',
                      long: 'Long-End (DI 5Y)', hard: 'Hard Currency',
                    };
                    const md = detail as { r_squared: number; coefficients: Record<string, number>; p_values: Record<string, number>; n_obs: number };
                    return (
                      <div key={asset} className="space-y-2">
                        <h4 className="text-xs font-semibold text-primary uppercase tracking-wider flex items-center gap-1.5">
                          <Database className="w-3 h-3" />
                          {labels[asset] || asset}
                        </h4>
                        <div className="bg-secondary/30 rounded-lg p-3 space-y-0.5">
                          <StatRow label="R²" value={md.r_squared?.toFixed(4) || 'N/A'} highlight />
                          <StatRow label="N obs" value={String(md.n_obs || 'N/A')} />
                          {md.coefficients && Object.entries(md.coefficients).map(([k, v]) => (
                            <StatRow
                              key={k}
                              label={`β ${k}`}
                              value={(v as number).toFixed(4)}
                              highlight={md.p_values?.[k] != null && (md.p_values[k] as number) < 0.05}
                            />
                          ))}
                        </div>
                      </div>
                    );
                  })}
                </div>
              ) : (
                <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                  {/* Legacy BEER */}
                  <div className="space-y-2">
                    <h4 className="text-xs font-semibold text-primary uppercase tracking-wider flex items-center gap-1.5">
                      <Database className="w-3 h-3" />
                      Regressão BEER
                    </h4>
                    <div className="bg-secondary/30 rounded-lg p-3 space-y-0.5">
                      <StatRow label="R²" value={((d.beer_regression as Record<string, unknown>)?.r_squared as number)?.toFixed(4) || 'N/A'} highlight />
                      <StatRow label="Variáveis" value={((d.beer_regression as Record<string, unknown>)?.variables as string[] || []).join(', ')} />
                      <StatRow label="Método" value="OLS + HAC" />
                    </div>
                  </div>
                  {/* Legacy Regime */}
                  <div className="space-y-2">
                    <h4 className="text-xs font-semibold text-primary uppercase tracking-wider flex items-center gap-1.5">
                      <Database className="w-3 h-3" />
                      Modelo de Regime
                    </h4>
                    <div className="bg-secondary/30 rounded-lg p-3 space-y-0.5">
                      <StatRow label="Tipo" value={(d.regime_model as Record<string, unknown>)?.type as string || 'N/A'} />
                      <StatRow label="Log-Likelihood" value={((d.regime_model as Record<string, unknown>)?.log_likelihood as number)?.toFixed(2) || 'N/A'} />
                      <StatRow label="AIC" value={((d.regime_model as Record<string, unknown>)?.aic as number)?.toFixed(2) || 'N/A'} />
                    </div>
                  </div>
                  {/* Legacy Return */}
                  <div className="space-y-2">
                    <h4 className="text-xs font-semibold text-primary uppercase tracking-wider flex items-center gap-1.5">
                      <Database className="w-3 h-3" />
                      Regressão de Retorno
                    </h4>
                    <div className="bg-secondary/30 rounded-lg p-3 space-y-0.5">
                      <StatRow label="R² (6m)" value={((d.return_regression_6m as Record<string, unknown>)?.r_squared as number)?.toFixed(4) || 'N/A'} />
                      <StatRow label="Delta (6m)" value={((d.return_regression_6m as Record<string, unknown>)?.delta as number)?.toFixed(4) || 'N/A'} highlight />
                      <StatRow label="R² (3m)" value={((d.return_regression_3m as Record<string, unknown>)?.r_squared as number)?.toFixed(4) || 'N/A'} />
                    </div>
                  </div>
                </div>
              )}

              {/* Methodology Note */}
              <div className="mt-4 p-3 bg-secondary/20 rounded-lg border border-border/30">
                <p className="text-[10px] text-muted-foreground leading-relaxed">
                  <strong className="text-foreground/70">Macro Risk OS:</strong> Sistema cross-asset integrado para BRL. 7 variáveis de estado unificadas (X1-X7) alimentam modelos de expected return para 4 classes: FX (USDBRL), Front-End (DI 1Y), Long-End (DI 5Y), Hard Currency (EMBI). Regime Markov 3-estados (Carry, RiskOff, StressDom) ajusta expected returns. Sizing ótimo via Half-Kelly + target vol 8% ann. Agregação de risco com matriz de covariância e stress tests históricos.
                </p>
              </div>
            </CardContent>
          </CollapsibleContent>
        </Card>
      </Collapsible>
    </motion.div>
  );
}
