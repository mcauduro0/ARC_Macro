/**
 * LassoPathChart — v4.3 Interactive LASSO Coefficient Path Visualization
 * Shows how LASSO coefficients evolve as alpha (regularization) changes.
 * Features enter/exit the model at different alpha values.
 *
 * Accepts Python output format: path is a list of {alpha, log_alpha, coefficients, n_nonzero, is_optimal}
 */

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { TrendingDown, Crosshair } from 'lucide-react';
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip as RTooltip,
  ReferenceLine,
  Legend,
} from 'recharts';

const FEATURE_LABELS: Record<string, string> = {
  Z_real_diff: 'Dif. Real',
  Z_infl_surprise: 'Surpresa Infl.',
  Z_fiscal: 'Risco Fiscal',
  Z_tot: 'Termos Troca',
  Z_dxy: 'DXY',
  Z_vix: 'VIX',
  Z_cds_br: 'CDS Brasil',
  Z_beer: 'BEER',
  Z_reer_gap: 'REER Gap',
  Z_term_premium: 'Term Prem.',
  Z_cip_basis: 'CIP Basis',
  Z_iron_ore: 'Minério',
  Z_policy_gap: 'Policy Gap',
  Z_rstar_composite: 'r* Comp.',
  Z_rstar_momentum: 'r* Mom.',
  Z_fiscal_component: 'Comp. Fiscal',
  Z_sovereign_component: 'Comp. Soberano',
  Z_selic_star_gap: 'SELIC* Gap',
  rstar_regime_signal: 'Regime r*',
  Z_rstar_curve_gap: 'r* Curve',
  Z_focus_fx: 'Focus FX',
  Z_ewz: 'EWZ',
  Z_portfolio_flow: 'Fluxo Port.',
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
  Z_bop: 'BoP',
  Z_cftc_brl: 'CFTC BRL',
  Z_idp_flow: 'IDP Flow',
  Z_pb_momentum: 'PB Mom.',
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

const LINE_COLORS = [
  '#22d3ee', '#a78bfa', '#f472b6', '#34d399', '#fbbf24',
  '#fb923c', '#60a5fa', '#e879f9', '#4ade80', '#f87171',
  '#38bdf8', '#c084fc', '#fb7185', '#2dd4bf', '#facc15',
  '#818cf8', '#f97316', '#a3e635', '#e11d48', '#06b6d4',
];

/** Python output format: list of path points */
interface PathPoint {
  alpha: number;
  log_alpha: number;
  coefficients: Record<string, number>;
  n_nonzero: number;
  is_optimal: string | boolean;
}

/** Normalized format for the chart */
interface NormalizedPath {
  alphas: number[];
  coefficients: Record<string, number[]>;
  selected_alpha: number;
  n_alphas: number;
}

/** Normalize Python list format OR dict format into a consistent structure */
function normalizePath(raw: any, fallbackAlpha?: number): NormalizedPath | null {
  if (!raw) return null;

  // Already in dict format: {alphas, coefficients, selected_alpha, n_alphas}
  if (raw.alphas && raw.coefficients && !Array.isArray(raw.alphas?.[0])) {
    return raw as NormalizedPath;
  }

  // Python list format: [{alpha, log_alpha, coefficients, n_nonzero, is_optimal}, ...]
  if (Array.isArray(raw) && raw.length > 0 && raw[0].alpha !== undefined) {
    const points = raw as PathPoint[];
    const alphas = points.map((p) => p.alpha);
    const featureNames = Object.keys(points[0].coefficients || {});
    const coefficients: Record<string, number[]> = {};
    featureNames.forEach((f) => {
      coefficients[f] = points.map((p) => p.coefficients[f] || 0);
    });
    const optimalPoint = points.find(
      (p) => p.is_optimal === true || p.is_optimal === 'True' || p.is_optimal === 'true'
    );
    const selected_alpha = optimalPoint?.alpha || fallbackAlpha || alphas[Math.floor(alphas.length / 2)];

    return {
      alphas,
      coefficients,
      selected_alpha,
      n_alphas: alphas.length,
    };
  }

  return null;
}

interface LassoPathChartProps {
  data: Record<string, { lasso?: { path?: any; alpha?: number; selected?: string[] } }> | null | undefined;
}

function PathChart({
  instData,
  instName,
}: {
  instData: { path?: any; alpha?: number; selected?: string[] };
  instName: string;
}) {
  const path = normalizePath(instData.path, instData.alpha);
  if (!path || !path.alphas || !path.coefficients) {
    return (
      <Card className="bg-slate-800/50 border-slate-700/50">
        <CardContent className="p-6 text-center">
          <p className="text-sm text-slate-400">
            LASSO path não disponível para {INSTRUMENT_LABELS[instName] || instName}.
          </p>
        </CardContent>
      </Card>
    );
  }

  const features = Object.keys(path.coefficients);
  const selectedAlpha = path.selected_alpha || instData.alpha || 0;

  // Build chart data: each point = one alpha value
  const chartData = path.alphas.map((alpha, idx) => {
    const point: Record<string, number> = { alpha, log_alpha: Math.log10(alpha + 1e-10) };
    features.forEach((feat) => {
      point[feat] = path.coefficients[feat]?.[idx] || 0;
    });
    return point;
  });

  // Determine which features are ever non-zero
  const activeFeatures = features.filter((f) =>
    path.coefficients[f]?.some((c) => Math.abs(c) > 1e-6)
  );

  // Sort by max absolute coefficient
  activeFeatures.sort((a, b) => {
    const maxA = Math.max(...(path.coefficients[a]?.map(Math.abs) || [0]));
    const maxB = Math.max(...(path.coefficients[b]?.map(Math.abs) || [0]));
    return maxB - maxA;
  });

  const displayFeatures = activeFeatures.slice(0, 15);
  const selectedSet = new Set(instData.selected || []);

  return (
    <Card className="bg-slate-800/50 border-slate-700/50">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm text-slate-300">
            {INSTRUMENT_LABELS[instName] || instName}
          </CardTitle>
          <div className="flex items-center gap-2">
            <Badge variant="outline" className="text-xs border-blue-500/30 text-blue-400">
              α* = {selectedAlpha.toFixed(4)}
            </Badge>
            <Badge variant="outline" className="text-xs border-emerald-500/30 text-emerald-400">
              {instData.selected?.length || 0} selecionadas
            </Badge>
            <Badge variant="outline" className="text-xs border-slate-500/30 text-slate-400">
              {path.n_alphas} alphas
            </Badge>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={320}>
          <LineChart data={chartData} margin={{ top: 5, right: 20, bottom: 25, left: 20 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#334155" strokeOpacity={0.3} />
            <XAxis
              dataKey="log_alpha"
              type="number"
              domain={['auto', 'auto']}
              tickFormatter={(v: number) => `10^${v.toFixed(1)}`}
              stroke="#64748b"
              fontSize={10}
              label={{
                value: 'log₁₀(α)',
                position: 'insideBottom',
                offset: -15,
                fill: '#94a3b8',
                fontSize: 11,
              }}
            />
            <YAxis
              stroke="#64748b"
              fontSize={10}
              label={{
                value: 'Coeficiente',
                angle: -90,
                position: 'insideLeft',
                offset: -5,
                fill: '#94a3b8',
                fontSize: 11,
              }}
            />
            <RTooltip
              contentStyle={{
                backgroundColor: '#1e293b',
                border: '1px solid #475569',
                borderRadius: '8px',
                fontSize: '11px',
              }}
              labelFormatter={(v: number) => `α = ${Math.pow(10, v).toFixed(6)}`}
              formatter={(value: number, name: string) => [
                value.toFixed(4),
                FEATURE_LABELS[name] || name,
              ]}
            />
            <ReferenceLine
              x={Math.log10(selectedAlpha + 1e-10)}
              stroke="#f59e0b"
              strokeDasharray="5 5"
              strokeWidth={2}
              label={{ value: 'α*', fill: '#f59e0b', fontSize: 12, position: 'top' }}
            />
            <ReferenceLine y={0} stroke="#475569" strokeWidth={1} />
            {displayFeatures.map((feat, idx) => (
              <Line
                key={feat}
                dataKey={feat}
                name={feat}
                stroke={LINE_COLORS[idx % LINE_COLORS.length]}
                strokeWidth={selectedSet.has(feat) ? 2.5 : 1}
                strokeOpacity={selectedSet.has(feat) ? 1 : 0.4}
                dot={false}
                strokeDasharray={selectedSet.has(feat) ? undefined : '3 3'}
              />
            ))}
            <Legend
              wrapperStyle={{ fontSize: '10px', paddingTop: '10px' }}
              formatter={(value: string) => (
                <span className={selectedSet.has(value) ? 'font-bold' : 'opacity-50'}>
                  {FEATURE_LABELS[value] || value}
                </span>
              )}
            />
          </LineChart>
        </ResponsiveContainer>

        {/* Entry/exit points */}
        <div className="mt-3 pt-3 border-t border-slate-700/30">
          <div className="text-xs text-slate-400 mb-2 flex items-center gap-1">
            <Crosshair className="w-3 h-3" />
            Features no α* selecionado:
          </div>
          <div className="flex flex-wrap gap-1">
            {(instData.selected || []).map((f) => (
              <span
                key={f}
                className="text-[10px] px-1.5 py-0.5 rounded bg-blue-500/15 text-blue-300 border border-blue-500/20 font-mono"
              >
                {FEATURE_LABELS[f] || f}
              </span>
            ))}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

export function LassoPathChart({ data }: LassoPathChartProps) {
  if (!data) return null;

  // Check if any instrument has path data (either list or dict format)
  const instruments = Object.keys(data).filter((i) => {
    const path = data[i]?.lasso?.path;
    if (!path) return false;
    if (Array.isArray(path)) return path.length > 0;
    if (typeof path === 'object' && path.alphas) return path.alphas.length > 0;
    return false;
  });

  if (instruments.length === 0) {
    return (
      <Card className="bg-slate-800/50 border-slate-700/50">
        <CardContent className="p-6 text-center">
          <TrendingDown className="w-8 h-8 text-slate-500 mx-auto mb-2" />
          <p className="text-sm text-slate-400">
            LASSO path não disponível. Execute o pipeline v4.3 para gerar resultados.
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      {/* Explanation card */}
      <Card className="bg-blue-500/5 border-blue-500/20">
        <CardContent className="p-3">
          <div className="flex items-center gap-2 mb-1">
            <TrendingDown className="w-4 h-4 text-blue-400" />
            <span className="text-sm font-semibold text-blue-300">LASSO Coefficient Path</span>
          </div>
          <p className="text-xs text-slate-400 leading-relaxed">
            Mostra como os coeficientes LASSO evoluem em função de α (regularização). À esquerda
            (α baixo), mais features ativas. À direita (α alto), apenas as mais robustas
            sobrevivem. A linha vertical amarela marca o α* ótimo selecionado por cross-validation.
            Linhas sólidas = features selecionadas; tracejadas = eliminadas.
          </p>
        </CardContent>
      </Card>

      <Tabs defaultValue={instruments[0]} className="w-full">
        <TabsList className="bg-slate-800/50 border border-slate-700/50">
          {instruments.map((inst) => (
            <TabsTrigger key={inst} value={inst} className="text-xs">
              {INSTRUMENT_LABELS[inst]?.split(' ')[0] || inst}
            </TabsTrigger>
          ))}
        </TabsList>

        {instruments.map((inst) => (
          <TabsContent key={inst} value={inst}>
            <PathChart instData={data[inst].lasso!} instName={inst} />
          </TabsContent>
        ))}
      </Tabs>
    </div>
  );
}
