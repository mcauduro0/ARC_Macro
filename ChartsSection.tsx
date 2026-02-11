import { TimeSeriesPoint, RegimePoint, CyclicalPoint, StateVarPoint } from '@/hooks/useModelData';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip as RTooltip,
  ResponsiveContainer, AreaChart, Area, ReferenceLine, Legend,
} from 'recharts';
import { motion } from 'framer-motion';
import { useMemo, useState } from 'react';

interface Props {
  timeseries: TimeSeriesPoint[];
  regimeProbs: RegimePoint[];
  cyclicalFactors: CyclicalPoint[];
  stateVariables?: StateVarPoint[];
}

const COLORS = {
  spot: '#06b6d4',
  ppp_fair: '#a78bfa',
  fx_fair: '#f59e0b',
  beer_fair: '#34d399',
  // Z-scores from state variables
  z_x1: '#06b6d4',    // Diferencial Real
  z_x2: '#f472b6',    // Surpresa Inflação
  z_x3: '#f43f5e',    // Fiscal Risk
  z_x4: '#34d399',    // Termos de Troca
  z_x5: '#a78bfa',    // Dólar Global
  z_x6: '#fbbf24',    // Risk Global
  z_x7: '#818cf8',    // Hiato
  // Regime
  carry: '#34d399',
  riskoff: '#f43f5e',
  stress: '#fbbf24',
  // Grid
  grid: 'rgba(255,255,255,0.05)',
  text: 'rgba(255,255,255,0.5)',
};

function CustomTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-card/95 backdrop-blur-sm border border-border rounded-lg px-3 py-2 shadow-xl">
      <p className="text-xs text-muted-foreground mb-1 font-data">{label}</p>
      {payload.map((entry: any, i: number) => (
        <div key={i} className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full" style={{ backgroundColor: entry.color }} />
          <span className="text-xs text-muted-foreground">{entry.name}:</span>
          <span className="text-xs font-data font-semibold text-foreground">
            {typeof entry.value === 'number' ? entry.value.toFixed(4) : entry.value}
          </span>
        </div>
      ))}
    </div>
  );
}

type TimeRange = '5Y' | '10Y' | 'ALL';
type TabValue = 'fairvalue' | 'zscores' | 'regime' | 'cyclical';

function filterByRange<T extends { date: string }>(data: T[], range: TimeRange): T[] {
  if (range === 'ALL') return data;
  const now = new Date();
  const years = range === '5Y' ? 5 : 10;
  const cutoff = new Date(now.getFullYear() - years, now.getMonth(), 1);
  return data.filter(d => new Date(d.date) >= cutoff);
}

export function ChartsSection({ timeseries, regimeProbs, cyclicalFactors, stateVariables = [] }: Props) {
  const [timeRange, setTimeRange] = useState<TimeRange>('10Y');
  const [activeTab, setActiveTab] = useState<TabValue>('fairvalue');

  const Z_FIELDS = [
    'Z_X1_diferencial_real', 'Z_X2_surpresa_inflacao', 'Z_X3_fiscal_risk',
    'Z_X4_termos_de_troca', 'Z_X5_dolar_global', 'Z_X6_risk_global', 'Z_X7_hiato'
  ] as const;

  // Normalize data: ensure every point has all Z-score keys (even if null)
  // Recharts ignores missing keys entirely but treats null/undefined values with connectNulls
  const normalizeZScores = <T extends Record<string, any>>(data: T[]): T[] => {
    return data.map(pt => {
      const normalized = { ...pt };
      for (const field of Z_FIELDS) {
        if (!(field in normalized)) {
          (normalized as any)[field] = null;
        }
      }
      return normalized;
    });
  };

  const filteredTS = useMemo(() => normalizeZScores(filterByRange(timeseries, timeRange)), [timeseries, timeRange]);
  const filteredRegime = useMemo(() => filterByRange(regimeProbs, timeRange), [regimeProbs, timeRange]);
  const filteredStateVars = useMemo(() => normalizeZScores(filterByRange(stateVariables, timeRange)), [stateVariables, timeRange]);
  const filteredCyclical = useMemo(() => filterByRange(cyclicalFactors, timeRange), [cyclicalFactors, timeRange]);
  
  const hasCyclicalData = filteredCyclical.length > 0;
  const hasStateVarData = filteredStateVars.length > 0;

  const formatDate = (d: string) => {
    if (!d) return '';
    return d.slice(0, 7);
  };

  const tabs: { value: TabValue; label: string }[] = [
    { value: 'fairvalue', label: 'Fair Value' },
    { value: 'zscores', label: 'Z-Scores' },
    { value: 'regime', label: 'Regime' },
    { value: 'cyclical', label: 'Cíclico' },
  ];

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.4, duration: 0.4 }}
    >
      <Card className="bg-card border-border/50">
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between">
            <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Séries Históricas
            </CardTitle>
            <div className="flex items-center gap-1">
              {(['5Y', '10Y', 'ALL'] as TimeRange[]).map(r => (
                <button
                  key={r}
                  onClick={() => setTimeRange(r)}
                  className={`px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider rounded transition-colors ${
                    timeRange === r
                      ? 'bg-primary/20 text-primary'
                      : 'text-muted-foreground hover:text-foreground hover:bg-secondary'
                  }`}
                >
                  {r}
                </button>
              ))}
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {/* Custom tab buttons instead of Radix Tabs to avoid hidden rendering issues */}
          <div className="flex gap-1 mb-4 bg-secondary/50 rounded-lg p-1 w-fit">
            {tabs.map(tab => (
              <button
                key={tab.value}
                onClick={() => setActiveTab(tab.value)}
                className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
                  activeTab === tab.value
                    ? 'bg-background text-foreground shadow-sm'
                    : 'text-muted-foreground hover:text-foreground'
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>

          {/* Only render the active chart - prevents width/height 0 issues */}
          {activeTab === 'fairvalue' && (
            <div className="h-[360px]">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={filteredTS} margin={{ top: 5, right: 20, bottom: 5, left: 10 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={COLORS.grid} />
                  <XAxis dataKey="date" tickFormatter={formatDate} tick={{ fontSize: 10, fill: COLORS.text }} interval="preserveStartEnd" />
                  <YAxis tick={{ fontSize: 10, fill: COLORS.text }} domain={['auto', 'auto']} />
                  <RTooltip content={<CustomTooltip />} />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  <Line type="monotone" dataKey="spot" stroke={COLORS.spot} strokeWidth={2} dot={false} name="Spot" connectNulls isAnimationActive={false} />
                  <Line type="monotone" dataKey="ppp_fair" stroke={COLORS.ppp_fair} strokeWidth={1.5} dot={false} name="PPP Fair" strokeDasharray="6 3" connectNulls isAnimationActive={false} />
                  <Line type="monotone" dataKey="beer_fair" stroke={COLORS.beer_fair} strokeWidth={1.5} dot={false} name="BEER Fair" connectNulls isAnimationActive={false} />
                  <Line type="monotone" dataKey="fx_fair" stroke={COLORS.fx_fair} strokeWidth={1.5} dot={false} name="FX Fair (BEER+Regime)" strokeDasharray="4 2" connectNulls isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}


          {activeTab === 'zscores' && (
            <div className="h-[360px]">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={filteredTS} margin={{ top: 5, right: 20, bottom: 5, left: 10 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={COLORS.grid} />
                  <XAxis dataKey="date" tickFormatter={formatDate} tick={{ fontSize: 10, fill: COLORS.text }} interval="preserveStartEnd" />
                  <YAxis tick={{ fontSize: 10, fill: COLORS.text }} domain={[-3, 3]} />
                  <RTooltip content={<CustomTooltip />} />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  <ReferenceLine y={0} stroke="rgba(255,255,255,0.2)" />
                  <ReferenceLine y={1} stroke="rgba(52,211,153,0.2)" strokeDasharray="3 3" />
                  <ReferenceLine y={-1} stroke="rgba(244,63,94,0.2)" strokeDasharray="3 3" />
                  <Line type="monotone" dataKey="Z_X1_diferencial_real" stroke={COLORS.z_x1} strokeWidth={2.5} strokeOpacity={1} dot={false} name="Diferencial Real" connectNulls isAnimationActive={false} />
                  <Line type="monotone" dataKey="Z_X2_surpresa_inflacao" stroke={COLORS.z_x2} strokeWidth={2.5} strokeOpacity={1} dot={false} name="Surpresa Inflação" connectNulls isAnimationActive={false} />
                  <Line type="monotone" dataKey="Z_X3_fiscal_risk" stroke={COLORS.z_x3} strokeWidth={2.5} strokeOpacity={1} dot={false} name="Risco Fiscal" connectNulls isAnimationActive={false} />
                  <Line type="monotone" dataKey="Z_X4_termos_de_troca" stroke={COLORS.z_x4} strokeWidth={2.5} strokeOpacity={1} dot={false} name="Termos de Troca" connectNulls isAnimationActive={false} />
                  <Line type="monotone" dataKey="Z_X5_dolar_global" stroke={COLORS.z_x5} strokeWidth={2.5} strokeOpacity={1} dot={false} name="Dólar Global" connectNulls isAnimationActive={false} />
                  <Line type="monotone" dataKey="Z_X6_risk_global" stroke={COLORS.z_x6} strokeWidth={2.5} strokeOpacity={1} dot={false} name="Risk Global" connectNulls isAnimationActive={false} />
                  <Line type="monotone" dataKey="Z_X7_hiato" stroke={COLORS.z_x7} strokeWidth={2.5} strokeOpacity={1} dot={false} name="Hiato" connectNulls isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}

          {activeTab === 'regime' && (
            <div className="h-[360px]">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={filteredRegime} margin={{ top: 5, right: 20, bottom: 5, left: 10 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={COLORS.grid} />
                  <XAxis dataKey="date" tickFormatter={formatDate} tick={{ fontSize: 10, fill: COLORS.text }} interval="preserveStartEnd" />
                  <YAxis tick={{ fontSize: 10, fill: COLORS.text }} domain={[0, 1]} tickFormatter={(v: number) => `${(v * 100).toFixed(0)}%`} />
                  <RTooltip content={<CustomTooltip />} />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  <Area type="monotone" dataKey="P_Carry" stackId="1" stroke={COLORS.carry} fill={COLORS.carry} fillOpacity={0.4} name="Carry" connectNulls isAnimationActive={false} />
                  <Area type="monotone" dataKey="P_RiskOff" stackId="1" stroke={COLORS.riskoff} fill={COLORS.riskoff} fillOpacity={0.4} name="Risk Off" connectNulls isAnimationActive={false} />
                  <Area type="monotone" dataKey="P_StressDom" stackId="1" stroke={COLORS.stress} fill={COLORS.stress} fillOpacity={0.4} name="Stress Dom" connectNulls isAnimationActive={false} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}

          {activeTab === 'cyclical' && (
            <div className="h-[360px]">
              <ResponsiveContainer width="100%" height="100%">
                {hasCyclicalData ? (
                  <LineChart data={filteredCyclical} margin={{ top: 5, right: 20, bottom: 5, left: 10 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke={COLORS.grid} />
                    <XAxis dataKey="date" tickFormatter={formatDate} tick={{ fontSize: 10, fill: COLORS.text }} interval="preserveStartEnd" />
                    <YAxis tick={{ fontSize: 10, fill: COLORS.text }} domain={[-3, 4]} />
                    <RTooltip content={<CustomTooltip />} />
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                    <ReferenceLine y={0} stroke="rgba(255,255,255,0.2)" />
                    <Line type="monotone" dataKey="Z_DXY" stroke="#06b6d4" strokeWidth={2} dot={false} name="DXY" connectNulls isAnimationActive={false} />
                    <Line type="monotone" dataKey="Z_COMMODITIES" stroke="#34d399" strokeWidth={2} dot={false} name="Commodities" connectNulls isAnimationActive={false} />
                    <Line type="monotone" dataKey="Z_EMBI" stroke="#f43f5e" strokeWidth={2} dot={false} name="EMBI" connectNulls isAnimationActive={false} />
                    <Line type="monotone" dataKey="Z_RIR" stroke="#a78bfa" strokeWidth={2} dot={false} name="Juros Reais" connectNulls isAnimationActive={false} />
                    <Line type="monotone" dataKey="Z_FLOW" stroke="#fbbf24" strokeWidth={2} dot={false} name="Fluxo" connectNulls isAnimationActive={false} />
                  </LineChart>
                ) : hasStateVarData ? (
                  <LineChart data={filteredStateVars} margin={{ top: 5, right: 20, bottom: 5, left: 10 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke={COLORS.grid} />
                    <XAxis dataKey="date" tickFormatter={formatDate} tick={{ fontSize: 10, fill: COLORS.text }} interval="preserveStartEnd" />
                    <YAxis tick={{ fontSize: 10, fill: COLORS.text }} domain={[-3, 4]} />
                    <RTooltip content={<CustomTooltip />} />
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                    <ReferenceLine y={0} stroke="rgba(255,255,255,0.2)" />
                    <Line type="monotone" dataKey="Z_X1_diferencial_real" stroke={COLORS.z_x1} strokeWidth={2} dot={false} name="Diferencial Real" connectNulls isAnimationActive={false} />
                    <Line type="monotone" dataKey="Z_X2_surpresa_inflacao" stroke={COLORS.z_x2} strokeWidth={2} dot={false} name="Surpresa Inflação" connectNulls isAnimationActive={false} />
                    <Line type="monotone" dataKey="Z_X3_fiscal_risk" stroke={COLORS.z_x3} strokeWidth={2} dot={false} name="Risco Fiscal" connectNulls isAnimationActive={false} />
                    <Line type="monotone" dataKey="Z_X4_termos_de_troca" stroke={COLORS.z_x4} strokeWidth={2} dot={false} name="Termos de Troca" connectNulls isAnimationActive={false} />
                    <Line type="monotone" dataKey="Z_X5_dolar_global" stroke={COLORS.z_x5} strokeWidth={2} dot={false} name="Dólar Global" connectNulls isAnimationActive={false} />
                    <Line type="monotone" dataKey="Z_X6_risk_global" stroke={COLORS.z_x6} strokeWidth={2} dot={false} name="Risk Global" connectNulls isAnimationActive={false} />
                    <Line type="monotone" dataKey="Z_X7_hiato" stroke={COLORS.z_x7} strokeWidth={2} dot={false} name="Hiato" connectNulls isAnimationActive={false} />
                  </LineChart>
                ) : (
                  <LineChart data={[]} margin={{ top: 5, right: 20, bottom: 5, left: 10 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke={COLORS.grid} />
                    <XAxis tick={{ fontSize: 10, fill: COLORS.text }} />
                    <YAxis tick={{ fontSize: 10, fill: COLORS.text }} />
                  </LineChart>
                )}
              </ResponsiveContainer>
            </div>
          )}
        </CardContent>
      </Card>
    </motion.div>
  );
}
