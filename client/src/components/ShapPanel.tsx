import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip as RTooltip,
  ResponsiveContainer, Cell, ReferenceLine,
} from 'recharts';
import { motion } from 'framer-motion';
import { useState, useMemo } from 'react';
import { Brain, ChevronDown, ChevronUp } from 'lucide-react';

/**
 * SHAP Feature Importance Panel
 * Displays SHAP values for each instrument's features,
 * showing which macro factors are driving the model's current predictions.
 */

interface ShapFeature {
  mean_abs: number;
  current: number;
  rank: number;
}

export interface ShapImportanceData {
  [instrument: string]: {
    [feature: string]: ShapFeature;
  };
}

interface Props {
  shapImportance: ShapImportanceData | null;
}

const INSTRUMENT_LABELS: Record<string, string> = {
  fx: 'FX (USDBRL)',
  front: 'Front-End (DI 1Y)',
  belly: 'Belly (DI 5Y)',
  long: 'Long-End (DI 10Y)',
  hard: 'Hard Currency (EMBI)',
};

const FEATURE_LABELS: Record<string, string> = {
  Z_real_diff: 'Diferencial Real',
  Z_infl_surprise: 'Surpresa Inflação',
  Z_fiscal: 'Risco Fiscal',
  Z_tot: 'Termos de Troca',
  Z_dxy: 'Dólar Global',
  Z_vix: 'VIX / Risco',
  Z_cds_br: 'CDS Brasil',
  Z_beer: 'BEER Misalignment',
  Z_reer_gap: 'REER Gap',
  Z_term_premium: 'Prêmio de Termo',
  Z_cip_basis: 'CIP Basis',
  Z_iron_ore: 'Minério de Ferro',
  Z_focus_fx: 'Focus FX (BCB)',
  Z_cftc_brl: 'CFTC Positioning',
  Z_idp_flow: 'Fluxo IDP',
  Z_portfolio_flow: 'Fluxo Portfólio',
  Z_hiato: 'Hiato do Produto',
  Z_embi: 'EMBI Spread',
};

function getBarColor(value: number): string {
  if (value > 0) return '#34d399'; // positive = green (bullish BRL / long rates)
  return '#f43f5e'; // negative = red (bearish BRL / short rates)
}

function CustomTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  const entry = payload[0];
  const featureLabel = FEATURE_LABELS[label] || label;
  return (
    <div className="bg-card/95 backdrop-blur-sm border border-border rounded-lg px-3 py-2 shadow-xl">
      <p className="text-xs font-semibold text-foreground mb-1">{featureLabel}</p>
      <div className="flex items-center gap-2">
        <span className="text-xs text-muted-foreground">SHAP atual:</span>
        <span className={`text-xs font-data font-bold ${entry.value >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
          {entry.value >= 0 ? '+' : ''}{(entry.value * 10000).toFixed(1)} bps
        </span>
      </div>
      <div className="flex items-center gap-2 mt-0.5">
        <span className="text-xs text-muted-foreground">Importância média:</span>
        <span className="text-xs font-data text-foreground">
          {((entry.payload as any)?.mean_abs * 10000).toFixed(1)} bps
        </span>
      </div>
    </div>
  );
}

function InstrumentShap({ instrument, features }: { instrument: string; features: Record<string, ShapFeature> }) {
  const [expanded, setExpanded] = useState(false);

  const chartData = useMemo(() => {
    const sorted = Object.entries(features)
      .sort((a, b) => Math.abs(b[1].current) - Math.abs(a[1].current));
    
    return sorted.map(([feat, vals]) => ({
      feature: feat,
      label: FEATURE_LABELS[feat] || feat,
      current: vals.current,
      mean_abs: vals.mean_abs,
      rank: vals.rank,
    }));
  }, [features]);

  const topN = expanded ? chartData : chartData.slice(0, 8);
  const label = INSTRUMENT_LABELS[instrument] || instrument;

  // Net direction from SHAP
  const netShap = chartData.reduce((sum, d) => sum + d.current, 0);
  const direction = netShap > 0.001 ? 'BULLISH' : netShap < -0.001 ? 'BEARISH' : 'NEUTRAL';
  const dirColor = direction === 'BULLISH' ? 'text-emerald-400' : direction === 'BEARISH' ? 'text-red-400' : 'text-muted-foreground';

  return (
    <div className="bg-secondary/20 rounded-lg p-3 border border-border/30">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">{label}</p>
          <span className={`text-[9px] font-data font-bold ${dirColor} bg-secondary/50 px-1.5 py-0.5 rounded`}>
            {direction}
          </span>
        </div>
        <span className="text-[9px] text-muted-foreground font-data">
          Net SHAP: {(netShap * 10000).toFixed(1)} bps
        </span>
      </div>
      
      <div className="h-[200px]">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            data={topN}
            layout="vertical"
            margin={{ top: 5, right: 20, bottom: 5, left: 100 }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
            <XAxis
              type="number"
              tick={{ fontSize: 9, fill: 'rgba(255,255,255,0.5)' }}
              tickFormatter={(v: number) => `${(v * 10000).toFixed(0)} bps`}
            />
            <YAxis
              type="category"
              dataKey="feature"
              tick={{ fontSize: 9, fill: 'rgba(255,255,255,0.5)' }}
              tickFormatter={(v: string) => FEATURE_LABELS[v] || v}
              width={95}
            />
            <RTooltip content={<CustomTooltip />} />
            <ReferenceLine x={0} stroke="rgba(255,255,255,0.2)" strokeWidth={1} />
            <Bar dataKey="current" radius={[0, 3, 3, 0]} maxBarSize={16}>
              {topN.map((entry, index) => (
                <Cell key={index} fill={getBarColor(entry.current)} fillOpacity={0.8} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      {chartData.length > 8 && (
        <button
          onClick={() => setExpanded(!expanded)}
          className="flex items-center gap-1 text-[10px] text-muted-foreground hover:text-foreground transition-colors mt-1"
        >
          {expanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
          {expanded ? 'Mostrar menos' : `Mostrar todas (${chartData.length})`}
        </button>
      )}
    </div>
  );
}

export function ShapPanel({ shapImportance }: Props) {
  const [selectedInstrument, setSelectedInstrument] = useState<string | null>(null);

  const instruments = useMemo(() => {
    if (!shapImportance) return [];
    return Object.keys(shapImportance).filter(k => Object.keys(shapImportance[k]).length > 0);
  }, [shapImportance]);

  if (!shapImportance || instruments.length === 0) {
    return null;
  }

  const displayInstruments = selectedInstrument
    ? instruments.filter(i => i === selectedInstrument)
    : instruments;

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.6, duration: 0.4 }}
    >
      <Card className="bg-card border-border/50">
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between flex-wrap gap-2">
            <div className="flex items-center gap-2">
              <Brain className="w-4 h-4 text-purple-400" />
              <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                SHAP Feature Importance — Drivers do Modelo
              </CardTitle>
            </div>
            <div className="flex items-center gap-1 bg-secondary/50 rounded-lg p-0.5">
              <button
                onClick={() => setSelectedInstrument(null)}
                className={`px-2 py-1 text-[10px] font-medium rounded transition-colors ${
                  selectedInstrument === null
                    ? 'bg-background text-foreground shadow-sm'
                    : 'text-muted-foreground hover:text-foreground'
                }`}
              >
                Todos
              </button>
              {instruments.map(inst => (
                <button
                  key={inst}
                  onClick={() => setSelectedInstrument(inst)}
                  className={`px-2 py-1 text-[10px] font-medium rounded transition-colors ${
                    selectedInstrument === inst
                      ? 'bg-background text-foreground shadow-sm'
                      : 'text-muted-foreground hover:text-foreground'
                  }`}
                >
                  {inst.toUpperCase()}
                </button>
              ))}
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-[10px] text-muted-foreground/70 leading-relaxed">
            Valores SHAP indicam a contribuição de cada feature para a previsão atual do modelo.
            Barras verdes indicam contribuição positiva (bullish), vermelhas indicam negativa (bearish).
            Valores em basis points (bps) de retorno esperado.
          </p>
          <div className={`grid gap-3 ${displayInstruments.length === 1 ? 'grid-cols-1' : 'grid-cols-1 lg:grid-cols-2'}`}>
            {displayInstruments.map(inst => (
              <InstrumentShap
                key={inst}
                instrument={inst}
                features={shapImportance[inst]}
              />
            ))}
          </div>
        </CardContent>
      </Card>
    </motion.div>
  );
}
