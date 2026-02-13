import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip as RTooltip,
  ResponsiveContainer, Legend,
} from 'recharts';
import { motion } from 'framer-motion';
import { useState, useMemo } from 'react';
import { TrendingUp, ChevronDown, ChevronUp } from 'lucide-react';

/**
 * SHAP Historical Evolution Panel
 * Shows how feature importance evolves over time across the backtest period,
 * enabling detection of structural regime changes in model drivers.
 */

export interface ShapHistoryEntry {
  date: string;
  instrument: string;
  feature: string;
  importance: number;
}

interface Props {
  shapHistory: ShapHistoryEntry[] | null;
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

// Distinct color palette for stacked area chart (up to 18 features)
const FEATURE_COLORS = [
  '#60a5fa', // blue-400
  '#f97316', // orange-500
  '#34d399', // emerald-400
  '#f43f5e', // rose-500
  '#a78bfa', // violet-400
  '#fbbf24', // amber-400
  '#22d3ee', // cyan-400
  '#fb7185', // rose-400
  '#4ade80', // green-400
  '#c084fc', // purple-400
  '#f59e0b', // amber-500
  '#38bdf8', // sky-400
  '#e879f9', // fuchsia-400
  '#2dd4bf', // teal-400
  '#facc15', // yellow-400
  '#818cf8', // indigo-400
  '#fb923c', // orange-400
  '#94a3b8', // slate-400
];

function formatDate(dateStr: string): string {
  const d = new Date(dateStr);
  return d.toLocaleDateString('pt-BR', { month: 'short', year: '2-digit' });
}

function CustomTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;

  // Sort by value descending
  const sorted = [...payload].sort((a: any, b: any) => (b.value || 0) - (a.value || 0));

  return (
    <div className="bg-card/95 backdrop-blur-sm border border-border rounded-lg px-3 py-2 shadow-xl max-h-[300px] overflow-y-auto">
      <p className="text-[10px] font-semibold text-foreground mb-1.5 border-b border-border/50 pb-1">
        {formatDate(label)}
      </p>
      {sorted.map((entry: any, i: number) => {
        if (!entry.value || entry.value < 0.0001) return null;
        const featureKey = entry.dataKey;
        return (
          <div key={i} className="flex items-center justify-between gap-3 py-0.5">
            <div className="flex items-center gap-1.5">
              <span
                className="w-2 h-2 rounded-full inline-block"
                style={{ backgroundColor: entry.color }}
              />
              <span className="text-[9px] text-muted-foreground">
                {FEATURE_LABELS[featureKey] || featureKey}
              </span>
            </div>
            <span className="text-[9px] font-data font-bold text-foreground">
              {(entry.value * 100).toFixed(1)}%
            </span>
          </div>
        );
      })}
    </div>
  );
}

function InstrumentHistory({
  instrument,
  data,
  features,
  expanded,
  onToggle,
}: {
  instrument: string;
  data: Array<Record<string, number | string>>;
  features: string[];
  expanded: boolean;
  onToggle: () => void;
}) {
  const label = INSTRUMENT_LABELS[instrument] || instrument;

  // Identify top features by average importance across time
  const featureAvg = useMemo(() => {
    const avgMap: Record<string, number> = {};
    for (const feat of features) {
      const values = data.map(d => (d[feat] as number) || 0);
      avgMap[feat] = values.reduce((a, b) => a + b, 0) / Math.max(values.length, 1);
    }
    return Object.entries(avgMap).sort((a, b) => b[1] - a[1]);
  }, [data, features]);

  const topFeatures = expanded ? featureAvg.map(f => f[0]) : featureAvg.slice(0, 6).map(f => f[0]);

  // Detect structural shifts: compare first half vs second half importance
  const structuralShifts = useMemo(() => {
    if (data.length < 4) return [];
    const mid = Math.floor(data.length / 2);
    const firstHalf = data.slice(0, mid);
    const secondHalf = data.slice(mid);

    const shifts: Array<{ feature: string; change: number; direction: string }> = [];
    for (const feat of features) {
      const avgFirst = firstHalf.reduce((s, d) => s + ((d[feat] as number) || 0), 0) / firstHalf.length;
      const avgSecond = secondHalf.reduce((s, d) => s + ((d[feat] as number) || 0), 0) / secondHalf.length;
      const change = avgSecond - avgFirst;
      if (Math.abs(change) > 0.02) { // >2% shift threshold
        shifts.push({
          feature: FEATURE_LABELS[feat] || feat,
          change: change * 100,
          direction: change > 0 ? 'rising' : 'falling',
        });
      }
    }
    return shifts.sort((a, b) => Math.abs(b.change) - Math.abs(a.change)).slice(0, 3);
  }, [data, features]);

  return (
    <div className="bg-secondary/20 rounded-lg p-3 border border-border/30">
      <div className="flex items-center justify-between mb-2">
        <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">
          {label}
        </p>
        <span className="text-[9px] text-muted-foreground font-data">
          {data.length} snapshots · {features.length} features
        </span>
      </div>

      {/* Structural shift alerts */}
      {structuralShifts.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mb-2">
          {structuralShifts.map((shift, i) => (
            <span
              key={i}
              className={`text-[8px] font-data px-1.5 py-0.5 rounded border ${
                shift.direction === 'rising'
                  ? 'text-amber-400 border-amber-400/30 bg-amber-400/10'
                  : 'text-blue-400 border-blue-400/30 bg-blue-400/10'
              }`}
            >
              {shift.direction === 'rising' ? '↑' : '↓'} {shift.feature}: {shift.change > 0 ? '+' : ''}{shift.change.toFixed(1)}pp
            </span>
          ))}
        </div>
      )}

      <div className="h-[220px]">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ top: 5, right: 10, bottom: 5, left: 10 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
            <XAxis
              dataKey="date"
              tick={{ fontSize: 8, fill: 'rgba(255,255,255,0.4)' }}
              tickFormatter={formatDate}
              interval="preserveStartEnd"
            />
            <YAxis
              tick={{ fontSize: 8, fill: 'rgba(255,255,255,0.4)' }}
              tickFormatter={(v: number) => `${(v * 100).toFixed(0)}%`}
              width={40}
            />
            <RTooltip content={<CustomTooltip />} />
            {topFeatures.map((feat, i) => (
              <Area
                key={feat}
                type="monotone"
                dataKey={feat}
                stackId="1"
                stroke={FEATURE_COLORS[i % FEATURE_COLORS.length]}
                fill={FEATURE_COLORS[i % FEATURE_COLORS.length]}
                fillOpacity={0.6}
                strokeWidth={0.5}
              />
            ))}
          </AreaChart>
        </ResponsiveContainer>
      </div>

      {/* Legend */}
      <div className="flex flex-wrap gap-x-3 gap-y-1 mt-2">
        {topFeatures.map((feat, i) => (
          <div key={feat} className="flex items-center gap-1">
            <span
              className="w-2 h-2 rounded-full inline-block"
              style={{ backgroundColor: FEATURE_COLORS[i % FEATURE_COLORS.length] }}
            />
            <span className="text-[8px] text-muted-foreground">
              {FEATURE_LABELS[feat] || feat}
            </span>
          </div>
        ))}
      </div>

      {features.length > 6 && (
        <button
          onClick={onToggle}
          className="flex items-center gap-1 text-[10px] text-muted-foreground hover:text-foreground transition-colors mt-1"
        >
          {expanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
          {expanded ? 'Mostrar top 6' : `Mostrar todas (${features.length})`}
        </button>
      )}
    </div>
  );
}

export function ShapHistoryPanel({ shapHistory }: Props) {
  const [selectedInstrument, setSelectedInstrument] = useState<string | null>(null);
  const [expandedInstruments, setExpandedInstruments] = useState<Set<string>>(new Set());

  // Transform flat array into per-instrument pivoted data
  const { instruments, pivotedData, featuresByInstrument } = useMemo(() => {
    if (!shapHistory || shapHistory.length === 0) {
      return { instruments: [], pivotedData: {} as Record<string, Array<Record<string, number | string>>>, featuresByInstrument: {} as Record<string, string[]> };
    }

    // Get unique instruments and dates
    const instSet = new Set<string>();
    const featByInst: Record<string, Set<string>> = {};
    const datesByInst: Record<string, Set<string>> = {};

    for (const entry of shapHistory) {
      instSet.add(entry.instrument);
      if (!featByInst[entry.instrument]) featByInst[entry.instrument] = new Set();
      if (!datesByInst[entry.instrument]) datesByInst[entry.instrument] = new Set();
      featByInst[entry.instrument].add(entry.feature);
      datesByInst[entry.instrument].add(entry.date);
    }

    const instruments = Array.from(instSet).sort();
    const featuresByInstrument: Record<string, string[]> = {};
    for (const inst of instruments) {
      featuresByInstrument[inst] = Array.from(featByInst[inst]).sort();
    }

    // Build pivoted data: [{date, feat1: importance, feat2: importance, ...}, ...]
    const pivotedData: Record<string, Array<Record<string, number | string>>> = {};
    for (const inst of instruments) {
      const dates = Array.from(datesByInst[inst]).sort();
      const rows: Array<Record<string, number | string>> = [];

      for (const date of dates) {
        const row: Record<string, number | string> = { date };
        // Normalize: compute total importance for this date to get relative shares
        const entries = shapHistory.filter(e => e.instrument === inst && e.date === date);
        const totalImportance = entries.reduce((s, e) => s + Math.abs(e.importance), 0);

        for (const entry of entries) {
          // Store as fraction of total importance (0-1 scale)
          row[entry.feature] = totalImportance > 0 ? Math.abs(entry.importance) / totalImportance : 0;
        }
        rows.push(row);
      }
      pivotedData[inst] = rows;
    }

    return { instruments, pivotedData, featuresByInstrument };
  }, [shapHistory]);

  if (!shapHistory || shapHistory.length === 0 || instruments.length === 0) {
    return null;
  }

  const displayInstruments = selectedInstrument
    ? instruments.filter(i => i === selectedInstrument)
    : instruments;

  const toggleExpanded = (inst: string) => {
    setExpandedInstruments(prev => {
      const next = new Set(prev);
      if (next.has(inst)) next.delete(inst);
      else next.add(inst);
      return next;
    });
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.7, duration: 0.4 }}
    >
      <Card className="bg-card border-border/50">
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between flex-wrap gap-2">
            <div className="flex items-center gap-2">
              <TrendingUp className="w-4 h-4 text-amber-400" />
              <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                SHAP Evolução Temporal — Mudanças Estruturais
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
            Evolução da importância relativa das features (SHAP) ao longo do backtest.
            Áreas empilhadas mostram a contribuição proporcional de cada variável macro.
            Mudanças abruptas na composição indicam transições estruturais nos drivers do modelo.
            Tags coloridas destacam as maiores mudanças entre a primeira e segunda metade do período.
          </p>
          <div className={`grid gap-3 ${displayInstruments.length === 1 ? 'grid-cols-1' : 'grid-cols-1 xl:grid-cols-2'}`}>
            {displayInstruments.map(inst => (
              <InstrumentHistory
                key={inst}
                instrument={inst}
                data={pivotedData[inst] || []}
                features={featuresByInstrument[inst] || []}
                expanded={expandedInstruments.has(inst)}
                onToggle={() => toggleExpanded(inst)}
              />
            ))}
          </div>
        </CardContent>
      </Card>
    </motion.div>
  );
}
