/**
 * FeatureSelectionPanel — v4.4 Elastic Net + Boruta Feature Selection Visualization
 * Shows which features were selected by Elastic Net (structural/linear) and Boruta (non-linear)
 * per instrument, with reduction metrics, stability heatmap, interactions, and instability alerts.
 */

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Progress } from '@/components/ui/progress';
import {
  Filter,
  TrendingDown,
  TreePine,
  CheckCircle2,
  XCircle,
  HelpCircle,
  BarChart3,
  Layers,
  Shield,
  Clock,
  Zap,
  Bell,
} from 'lucide-react';
import { StabilityHeatmap } from './StabilityHeatmap';
import { LassoPathChart } from './LassoPathChart';
import { TemporalSelectionPanel } from './TemporalSelectionPanel';
import { InteractionsPanel } from './InteractionsPanel';
import { InstabilityAlertsPanel } from './InstabilityAlertsPanel';
import { RollingStabilityChart } from './RollingStabilityChart';

// Feature label mapping
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
  Z_policy_gap: 'Policy Gap (SELIC-SELIC*)',
  Z_rstar_composite: 'r* Composto',
  Z_rstar_momentum: 'r* Momentum',
  Z_fiscal_component: 'Componente Fiscal',
  Z_sovereign_component: 'Componente Soberano',
  Z_selic_star_gap: 'SELIC* Gap',
  rstar_regime_signal: 'Sinal Regime r*',
  Z_rstar_curve_gap: 'r* Curve Gap',
  Z_focus_fx: 'Focus FX',
  Z_ewz: 'EWZ',
  Z_portfolio_flow: 'Fluxo Portfólio',
  Z_debt_accel: 'Aceleração Dívida',
  carry_fx: 'Carry FX',
  carry_front: 'Carry Front',
  carry_belly: 'Carry Belly',
  carry_long: 'Carry Long',
  carry_hard: 'Carry Hard',
  Z_slope: 'Slope',
  Z_ppp_gap: 'PPP Gap',
  mu_fx_lag1: 'μ FX Lag-1',
  mu_front_lag1: 'μ Front Lag-1',
  mu_belly_lag1: 'μ Belly Lag-1',
  mu_long_lag1: 'μ Long Lag-1',
  mu_hard_lag1: 'μ Hard Lag-1',
};

const INSTRUMENT_LABELS: Record<string, string> = {
  fx: 'DOL Futuro (Câmbio)',
  front: 'Front (DI 1Y)',
  belly: 'Belly (DI 5Y)',
  long: 'Long (DI 10Y)',
  hard: 'Hard (CDS)',
};

interface FeatureSelectionResult {
  total_features: number;
  lasso: {
    n_selected: number;
    alpha: number;
    l1_ratio?: number;
    method?: string;
    selected: string[];
    coefficients: Record<string, number>;
    path?: unknown[] | Record<string, unknown>;
  };
  boruta: {
    n_confirmed: number;
    n_tentative: number;
    n_rejected: number;
    confirmed: string[];
    tentative: string[];
    rejected: string[];
    n_iterations: number;
  };
  interactions?: {
    tested: string[];
    confirmed: string[];
    rejected: string[];
    n_tested: number;
    n_confirmed: number;
  };
  alerts?: Array<{
    type: 'critical' | 'warning' | 'info';
    feature: string;
    instrument: string;
    transition?: string;
    message: string;
  }>;
  stability?: {
    n_subsamples: number;
    subsample_ratio: number;
    enet_frequency?: Record<string, number>;
    lasso_frequency?: Record<string, number>;
    boruta_frequency?: Record<string, number>;
    composite_score?: Record<string, number>;
    combined_frequency?: Record<string, number>;
    classification: Record<string, string>;
    thresholds?: { robust: number; moderate: number };
  };
  final: {
    n_features: number;
    features: string[];
    reduction_pct: number;
    method: string;
  };
}

interface FeatureSelectionPanelProps {
  data: Record<string, FeatureSelectionResult> | null | undefined;
  temporal?: unknown;
}

function FeatureTag({
  name,
  status,
}: {
  name: string;
  status: 'lasso' | 'boruta' | 'both' | 'tentative' | 'rejected' | 'interaction';
}) {
  const label = FEATURE_LABELS[name] || name;
  const colorMap = {
    lasso: 'bg-blue-500/20 text-blue-300 border-blue-500/30',
    boruta: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30',
    both: 'bg-amber-500/20 text-amber-300 border-amber-500/30',
    tentative: 'bg-yellow-500/15 text-yellow-400/70 border-yellow-500/20',
    rejected: 'bg-red-500/10 text-red-400/50 border-red-500/15 line-through',
    interaction: 'bg-blue-500/15 text-blue-300 border-blue-500/25',
  };
  const iconMap = {
    lasso: <TrendingDown className="w-3 h-3" />,
    boruta: <TreePine className="w-3 h-3" />,
    both: <CheckCircle2 className="w-3 h-3" />,
    tentative: <HelpCircle className="w-3 h-3" />,
    rejected: <XCircle className="w-3 h-3" />,
    interaction: <Zap className="w-3 h-3" />,
  };

  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs font-mono border ${colorMap[status]}`}
    >
      {iconMap[status]}
      {label}
    </span>
  );
}

function InstrumentCard({ inst, result }: { inst: string; result: FeatureSelectionResult }) {
  const label = INSTRUMENT_LABELS[inst] || inst;
  const reductionPct = result.final.reduction_pct;
  const isElasticNet = result.lasso?.method === 'elastic_net' || (result.lasso?.l1_ratio !== undefined && result.lasso.l1_ratio < 1.0);

  // Classify features
  const lassoSet = new Set(result.lasso.selected);
  const borutaSet = new Set(result.boruta.confirmed);
  const tentativeSet = new Set(result.boruta.tentative);
  const rejectedSet = new Set(result.boruta.rejected);

  // All features sorted by status
  const allFeatures = Array.from(
    new Set([
      ...result.lasso.selected,
      ...result.boruta.confirmed,
      ...result.boruta.tentative,
      ...result.boruta.rejected,
    ])
  );

  const bothFeatures = allFeatures.filter((f) => lassoSet.has(f) && borutaSet.has(f));
  const lassoOnly = allFeatures.filter((f) => lassoSet.has(f) && !borutaSet.has(f));
  const borutaOnly = allFeatures.filter((f) => borutaSet.has(f) && !lassoSet.has(f));
  const tentativeFeatures = allFeatures.filter(
    (f) => tentativeSet.has(f) && !lassoSet.has(f) && !borutaSet.has(f)
  );
  const rejectedFeatures = allFeatures.filter(
    (f) => rejectedSet.has(f) && !lassoSet.has(f) && !borutaSet.has(f)
  );

  return (
    <Card className="bg-slate-800/50 border-slate-700/50">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-semibold text-slate-200">{label}</CardTitle>
          <div className="flex items-center gap-2">
            <Badge
              variant="outline"
              className="text-xs border-emerald-500/30 text-emerald-400 bg-emerald-500/10"
            >
              {result.final.n_features}/{result.total_features} features
            </Badge>
            <Badge
              variant="outline"
              className="text-xs border-red-500/30 text-red-400 bg-red-500/10"
            >
              -{reductionPct.toFixed(0)}%
            </Badge>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {/* Progress bar */}
        <div className="space-y-1">
          <div className="flex justify-between text-xs text-slate-400">
            <span>Features retidas</span>
            <span>{(100 - reductionPct).toFixed(0)}%</span>
          </div>
          <Progress value={100 - reductionPct} className="h-1.5" />
        </div>

        {/* Method comparison */}
        <div className="grid grid-cols-2 gap-2">
          <div className="bg-blue-500/10 rounded-md p-2 border border-blue-500/20">
            <div className="flex items-center gap-1 mb-1">
              <TrendingDown className="w-3 h-3 text-blue-400" />
              <span className="text-xs font-medium text-blue-300">
                {isElasticNet ? 'Elastic Net' : 'LASSO'}
              </span>
            </div>
            <div className="text-lg font-bold text-blue-200">{result.lasso.n_selected}</div>
            <div className="text-xs text-slate-400">
              α = {result.lasso.alpha.toFixed(4)}
              {isElasticNet && result.lasso.l1_ratio !== undefined && (
                <span className="ml-1">| L1 = {result.lasso.l1_ratio.toFixed(2)}</span>
              )}
            </div>
          </div>
          <div className="bg-emerald-500/10 rounded-md p-2 border border-emerald-500/20">
            <div className="flex items-center gap-1 mb-1">
              <TreePine className="w-3 h-3 text-emerald-400" />
              <span className="text-xs font-medium text-emerald-300">Boruta</span>
            </div>
            <div className="text-lg font-bold text-emerald-200">{result.boruta.n_confirmed}</div>
            <div className="text-xs text-slate-400">
              +{result.boruta.n_tentative} tentative
            </div>
          </div>
        </div>

        {/* Interactions summary */}
        {result.interactions && result.interactions.n_tested > 0 && (
          <div className="bg-blue-500/5 rounded-md p-2 border border-blue-500/15">
            <div className="flex items-center gap-1 mb-1">
              <Zap className="w-3 h-3 text-blue-400" />
              <span className="text-xs font-medium text-blue-300">Interações</span>
            </div>
            <div className="text-xs text-slate-400">
              {result.interactions.n_confirmed}/{result.interactions.n_tested} confirmadas
              {result.interactions.confirmed.length > 0 && (
                <span className="text-emerald-400 ml-1">
                  ({result.interactions.confirmed.join(', ')})
                </span>
              )}
            </div>
          </div>
        )}

        {/* Feature tags */}
        <div className="space-y-2">
          {bothFeatures.length > 0 && (
            <div>
              <div className="text-xs text-amber-400/80 mb-1 font-medium">
                Ambos ({isElasticNet ? 'ENet' : 'LASSO'} + Boruta)
              </div>
              <div className="flex flex-wrap gap-1">
                {bothFeatures.map((f) => (
                  <FeatureTag key={f} name={f} status="both" />
                ))}
              </div>
            </div>
          )}
          {lassoOnly.length > 0 && (
            <div>
              <div className="text-xs text-blue-400/80 mb-1 font-medium">
                Apenas {isElasticNet ? 'Elastic Net' : 'LASSO'}
              </div>
              <div className="flex flex-wrap gap-1">
                {lassoOnly.map((f) => (
                  <FeatureTag key={f} name={f} status="lasso" />
                ))}
              </div>
            </div>
          )}
          {borutaOnly.length > 0 && (
            <div>
              <div className="text-xs text-emerald-400/80 mb-1 font-medium">Apenas Boruta</div>
              <div className="flex flex-wrap gap-1">
                {borutaOnly.map((f) => (
                  <FeatureTag key={f} name={f} status="boruta" />
                ))}
              </div>
            </div>
          )}
          {tentativeFeatures.length > 0 && (
            <div>
              <div className="text-xs text-yellow-400/60 mb-1 font-medium">Tentativas</div>
              <div className="flex flex-wrap gap-1">
                {tentativeFeatures.map((f) => (
                  <FeatureTag key={f} name={f} status="tentative" />
                ))}
              </div>
            </div>
          )}
          {rejectedFeatures.length > 0 && (
            <div>
              <div className="text-xs text-red-400/40 mb-1 font-medium">
                Rejeitadas ({rejectedFeatures.length})
              </div>
              <div className="flex flex-wrap gap-1">
                {rejectedFeatures.slice(0, 8).map((f) => (
                  <FeatureTag key={f} name={f} status="rejected" />
                ))}
                {rejectedFeatures.length > 8 && (
                  <span className="text-xs text-slate-500">
                    +{rejectedFeatures.length - 8} mais
                  </span>
                )}
              </div>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function SummaryView({ data }: { data: Record<string, FeatureSelectionResult> }) {
  const instruments = Object.keys(data);
  const totalOriginal = instruments.reduce((s, i) => s + data[i].total_features, 0);
  const totalFinal = instruments.reduce((s, i) => s + data[i].final.n_features, 0);
  const totalReduction = ((1 - totalFinal / totalOriginal) * 100).toFixed(0);

  // Count features by method across all instruments
  const allLasso = new Set(instruments.flatMap((i) => data[i].lasso.selected));
  const allBoruta = new Set(instruments.flatMap((i) => data[i].boruta.confirmed));
  const overlap = Array.from(allLasso).filter((f) => allBoruta.has(f));

  // Detect if using Elastic Net
  const isElasticNet = instruments.some(
    (i) => data[i].lasso?.method === 'elastic_net' || (data[i].lasso?.l1_ratio !== undefined && data[i].lasso.l1_ratio! < 1.0)
  );

  // Interactions summary
  const totalInteractions = instruments.reduce(
    (s, i) => s + (data[i].interactions?.n_confirmed || 0),
    0
  );

  return (
    <div className="space-y-4">
      {/* Global summary */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <Card className="bg-slate-800/50 border-slate-700/50">
          <CardContent className="p-3 text-center">
            <div className="text-2xl font-bold text-slate-100">{totalOriginal}</div>
            <div className="text-xs text-slate-400">Features Originais</div>
          </CardContent>
        </Card>
        <Card className="bg-emerald-500/10 border-emerald-500/20">
          <CardContent className="p-3 text-center">
            <div className="text-2xl font-bold text-emerald-300">{totalFinal}</div>
            <div className="text-xs text-emerald-400">Features Retidas</div>
          </CardContent>
        </Card>
        <Card className="bg-red-500/10 border-red-500/20">
          <CardContent className="p-3 text-center">
            <div className="text-2xl font-bold text-red-300">-{totalReduction}%</div>
            <div className="text-xs text-red-400">Redução Total</div>
          </CardContent>
        </Card>
        <Card className="bg-amber-500/10 border-amber-500/20">
          <CardContent className="p-3 text-center">
            <div className="text-2xl font-bold text-amber-300">{overlap.length}</div>
            <div className="text-xs text-amber-400">
              Consenso {isElasticNet ? 'ENet' : 'LASSO'}∩Boruta
            </div>
          </CardContent>
        </Card>
        <Card className="bg-blue-500/10 border-blue-500/20">
          <CardContent className="p-3 text-center">
            <div className="text-2xl font-bold text-blue-300">{totalInteractions}</div>
            <div className="text-xs text-blue-400">Interações Validadas</div>
          </CardContent>
        </Card>
      </div>

      {/* Per-instrument comparison table */}
      <Card className="bg-slate-800/50 border-slate-700/50">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm text-slate-300 flex items-center gap-2">
            <BarChart3 className="w-4 h-4" />
            Comparação por Instrumento
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-slate-700/50">
                  <th className="text-left py-2 text-slate-400 font-medium">Instrumento</th>
                  <th className="text-center py-2 text-slate-400 font-medium">Total</th>
                  <th className="text-center py-2 text-blue-400 font-medium">
                    {isElasticNet ? 'ENet' : 'LASSO'}
                  </th>
                  <th className="text-center py-2 text-emerald-400 font-medium">Boruta</th>
                  <th className="text-center py-2 text-blue-400 font-medium">Interações</th>
                  <th className="text-center py-2 text-amber-400 font-medium">Final</th>
                  <th className="text-center py-2 text-red-400 font-medium">Redução</th>
                </tr>
              </thead>
              <tbody>
                {instruments.map((inst) => {
                  const r = data[inst];
                  return (
                    <tr key={inst} className="border-b border-slate-700/30">
                      <td className="py-2 text-slate-200 font-medium">
                        {INSTRUMENT_LABELS[inst] || inst}
                      </td>
                      <td className="text-center py-2 text-slate-300">{r.total_features}</td>
                      <td className="text-center py-2 text-blue-300">{r.lasso.n_selected}</td>
                      <td className="text-center py-2 text-emerald-300">
                        {r.boruta.n_confirmed}
                        {r.boruta.n_tentative > 0 && (
                          <span className="text-yellow-400/60">+{r.boruta.n_tentative}</span>
                        )}
                      </td>
                      <td className="text-center py-2 text-blue-300">
                        {r.interactions ? `${r.interactions.n_confirmed}/${r.interactions.n_tested}` : '—'}
                      </td>
                      <td className="text-center py-2 text-amber-300 font-bold">
                        {r.final.n_features}
                      </td>
                      <td className="text-center py-2 text-red-300">
                        -{r.final.reduction_pct.toFixed(0)}%
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>

      {/* Method explanation */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <Card className="bg-blue-500/5 border-blue-500/20">
          <CardContent className="p-3">
            <div className="flex items-center gap-2 mb-2">
              <TrendingDown className="w-4 h-4 text-blue-400" />
              <span className="text-sm font-semibold text-blue-300">
                {isElasticNet ? 'Elastic Net (L1+L2)' : 'LASSO (L1)'}
              </span>
              <Badge variant="outline" className="text-xs border-blue-500/30 text-blue-400">
                → Ridge
              </Badge>
            </div>
            <p className="text-xs text-slate-400 leading-relaxed">
              {isElasticNet
                ? 'Regularização L1+L2 que combina esparsidade (L1) com agrupamento (L2). Features correlacionadas (Z_fiscal, Z_cds_br) são mantidas juntas ao invés de descartadas arbitrariamente. CV-otimizado para alpha e l1_ratio.'
                : 'Regularização L1 que força coeficientes a zero. Ideal para o bloco estrutural linear: PPP gap, carry, slope, termos de troca. Features selecionadas alimentam o modelo Ridge.'}
            </p>
          </CardContent>
        </Card>
        <Card className="bg-emerald-500/5 border-emerald-500/20">
          <CardContent className="p-3">
            <div className="flex items-center gap-2 mb-2">
              <TreePine className="w-4 h-4 text-emerald-400" />
              <span className="text-sm font-semibold text-emerald-300">Boruta</span>
              <Badge variant="outline" className="text-xs border-emerald-500/30 text-emerald-400">
                → GBM/RF/XGB
              </Badge>
            </div>
            <p className="text-xs text-slate-400 leading-relaxed">
              Cria shadow features embaralhadas e compara importância via Random Forest. Se a
              feature real não supera o ruído consistentemente, é descartada. Captura relações
              não-lineares e interações complexas.
            </p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

export function FeatureSelectionPanel({ data, temporal }: FeatureSelectionPanelProps) {
  if (!data || Object.keys(data).length === 0) {
    return (
      <Card className="bg-slate-800/50 border-slate-700/50">
        <CardContent className="p-6 text-center">
          <Filter className="w-8 h-8 text-slate-500 mx-auto mb-2" />
          <p className="text-sm text-slate-400">
            Feature selection não disponível. Execute o pipeline v4.2+ para gerar resultados.
          </p>
        </CardContent>
      </Card>
    );
  }

  const instruments = Object.keys(data);

  // Detect if using Elastic Net
  const isElasticNet = instruments.some(
    (i) => data[i].lasso?.method === 'elastic_net' || (data[i].lasso?.l1_ratio !== undefined && data[i].lasso.l1_ratio! < 1.0)
  );

  // Check if we have interactions or alerts
  const hasInteractions = instruments.some((i) => data[i].interactions && data[i].interactions!.n_tested > 0);
  const hasAlerts = instruments.some((i) => data[i].alerts && data[i].alerts!.length > 0);

  const version = isElasticNet ? 'v4.4' : 'v4.3';

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <Layers className="w-5 h-5 text-primary" />
        <h2 className="text-lg font-bold text-slate-100">
          Feature Selection — {isElasticNet ? 'Elastic Net' : 'LASSO'} + Boruta
        </h2>
        <Badge variant="outline" className="text-xs border-primary/30 text-primary">
          {version}
        </Badge>
        {isElasticNet && (
          <Badge variant="outline" className="text-xs border-blue-500/30 text-blue-400 bg-blue-500/10">
            L1+L2
          </Badge>
        )}
      </div>

      <Tabs defaultValue="summary" className="w-full">
        <TabsList className="bg-slate-800/50 border border-slate-700/50 flex-wrap">
          <TabsTrigger value="summary" className="text-xs">
            Resumo
          </TabsTrigger>
          {instruments.map((inst) => (
            <TabsTrigger key={inst} value={inst} className="text-xs">
              {INSTRUMENT_LABELS[inst]?.split(' ')[0] || inst}
            </TabsTrigger>
          ))}
          <TabsTrigger value="stability" className="text-xs">
            <Shield className="w-3 h-3 mr-1" />
            Estabilidade
          </TabsTrigger>
          {hasInteractions && (
            <TabsTrigger value="interactions" className="text-xs">
              <Zap className="w-3 h-3 mr-1" />
              Interações
            </TabsTrigger>
          )}
          {hasAlerts && (
            <TabsTrigger value="alerts" className="text-xs">
              <Bell className="w-3 h-3 mr-1" />
              Alertas
            </TabsTrigger>
          )}
          <TabsTrigger value="lasso-path" className="text-xs">
            <TrendingDown className="w-3 h-3 mr-1" />
            {isElasticNet ? 'ENet Path' : 'LASSO Path'}
          </TabsTrigger>
          <TabsTrigger value="rolling" className="text-xs">
            <BarChart3 className="w-3 h-3 mr-1" />
            Rolling
          </TabsTrigger>
          <TabsTrigger value="temporal" className="text-xs">
            <Clock className="w-3 h-3 mr-1" />
            Temporal
          </TabsTrigger>
        </TabsList>

        <TabsContent value="summary">
          <SummaryView data={data} />
        </TabsContent>

        {instruments.map((inst) => (
          <TabsContent key={inst} value={inst}>
            <InstrumentCard inst={inst} result={data[inst]} />
          </TabsContent>
        ))}

        <TabsContent value="stability">
          <StabilityHeatmap data={data} />
        </TabsContent>

        {hasInteractions && (
          <TabsContent value="interactions">
            <InteractionsPanel data={data} />
          </TabsContent>
        )}

        {hasAlerts && (
          <TabsContent value="alerts">
            <InstabilityAlertsPanel data={data} />
          </TabsContent>
        )}

        <TabsContent value="lasso-path">
          <LassoPathChart data={data} />
        </TabsContent>

        <TabsContent value="rolling">
          <RollingStabilityChart
            rollingData={(temporal as any)?.rolling_stability || null}
            featurePersistence={(temporal as any)?.summary?.feature_persistence || null}
          />
        </TabsContent>

        <TabsContent value="temporal">
          <TemporalSelectionPanel temporal={temporal as any} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
