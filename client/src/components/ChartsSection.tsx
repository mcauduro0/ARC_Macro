import { TimeSeriesPoint, RegimePoint, CyclicalPoint } from '@/hooks/useModelData';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip as RTooltip,
  ResponsiveContainer, AreaChart, Area, ReferenceLine, Legend,
  BarChart, Bar
} from 'recharts';
import { motion } from 'framer-motion';
import { useMemo, useState } from 'react';

interface Props {
  timeseries: TimeSeriesPoint[];
  regimeProbs: RegimePoint[];
  cyclicalFactors: CyclicalPoint[];
}

const COLORS = {
  spot: '#06b6d4',
  ppp_abs: '#a78bfa',
  ppp_rel: '#818cf8',
  fx_beer: '#34d399',
  z_ppp: '#06b6d4',
  z_beer: '#34d399',
  z_cycle: '#fbbf24',
  score_total: '#f472b6',
  carry: '#34d399',
  riskoff: '#f43f5e',
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

function filterByRange<T extends { date: string }>(data: T[], range: TimeRange): T[] {
  if (range === 'ALL') return data;
  const now = new Date();
  const years = range === '5Y' ? 5 : 10;
  const cutoff = new Date(now.getFullYear() - years, now.getMonth(), 1);
  return data.filter(d => new Date(d.date) >= cutoff);
}

export function ChartsSection({ timeseries, regimeProbs, cyclicalFactors }: Props) {
  const [timeRange, setTimeRange] = useState<TimeRange>('10Y');

  const filteredTS = useMemo(() => filterByRange(timeseries, timeRange), [timeseries, timeRange]);
  const filteredRegime = useMemo(() => filterByRange(regimeProbs, timeRange), [regimeProbs, timeRange]);
  const filteredCyclical = useMemo(() => filterByRange(cyclicalFactors, timeRange), [cyclicalFactors, timeRange]);

  const formatDate = (d: string) => {
    if (!d) return '';
    return d.slice(0, 7);
  };

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
          <Tabs defaultValue="fairvalue" className="w-full">
            <TabsList className="bg-secondary/50 mb-4">
              <TabsTrigger value="fairvalue" className="text-xs">Fair Value</TabsTrigger>
              <TabsTrigger value="zscores" className="text-xs">Z-Scores</TabsTrigger>
              <TabsTrigger value="regime" className="text-xs">Regime</TabsTrigger>
              <TabsTrigger value="cyclical" className="text-xs">Cíclico</TabsTrigger>
              <TabsTrigger value="score" className="text-xs">Score</TabsTrigger>
            </TabsList>

            {/* Fair Value Chart */}
            <TabsContent value="fairvalue">
              <div className="h-[360px]">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={filteredTS} margin={{ top: 5, right: 20, bottom: 5, left: 10 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke={COLORS.grid} />
                    <XAxis dataKey="date" tickFormatter={formatDate} tick={{ fontSize: 10, fill: COLORS.text }} interval="preserveStartEnd" />
                    <YAxis tick={{ fontSize: 10, fill: COLORS.text }} domain={['auto', 'auto']} />
                    <RTooltip content={<CustomTooltip />} />
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                    <Line type="monotone" dataKey="spot" stroke={COLORS.spot} strokeWidth={2} dot={false} name="Spot" connectNulls />
                    <Line type="monotone" dataKey="ppp_abs" stroke={COLORS.ppp_abs} strokeWidth={1.5} dot={false} name="PPP Abs" strokeDasharray="6 3" connectNulls />
                    <Line type="monotone" dataKey="ppp_rel" stroke={COLORS.ppp_rel} strokeWidth={1.5} dot={false} name="PPP Rel" strokeDasharray="4 2" connectNulls />
                    <Line type="monotone" dataKey="fx_beer" stroke={COLORS.fx_beer} strokeWidth={1.5} dot={false} name="BEER FV" connectNulls />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </TabsContent>

            {/* Z-Scores Chart */}
            <TabsContent value="zscores">
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
                    <Line type="monotone" dataKey="z_ppp" stroke={COLORS.z_ppp} strokeWidth={1.5} dot={false} name="Z PPP" connectNulls />
                    <Line type="monotone" dataKey="z_beer" stroke={COLORS.z_beer} strokeWidth={1.5} dot={false} name="Z BEER" connectNulls />
                    <Line type="monotone" dataKey="z_cycle" stroke={COLORS.z_cycle} strokeWidth={1.5} dot={false} name="Z Cíclico" connectNulls />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </TabsContent>

            {/* Regime Probabilities */}
            <TabsContent value="regime">
              <div className="h-[360px]">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={filteredRegime} margin={{ top: 5, right: 20, bottom: 5, left: 10 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke={COLORS.grid} />
                    <XAxis dataKey="date" tickFormatter={formatDate} tick={{ fontSize: 10, fill: COLORS.text }} interval="preserveStartEnd" />
                    <YAxis tick={{ fontSize: 10, fill: COLORS.text }} domain={[0, 1]} tickFormatter={(v: number) => `${(v * 100).toFixed(0)}%`} />
                    <RTooltip content={<CustomTooltip />} />
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                    <Area type="monotone" dataKey="P_Carry" stackId="1" stroke={COLORS.carry} fill={COLORS.carry} fillOpacity={0.4} name="Carry" connectNulls />
                    <Area type="monotone" dataKey="P_RiskOff" stackId="1" stroke={COLORS.riskoff} fill={COLORS.riskoff} fillOpacity={0.4} name="Risk Off" connectNulls />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </TabsContent>

            {/* Cyclical Factors */}
            <TabsContent value="cyclical">
              <div className="h-[360px]">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={filteredCyclical} margin={{ top: 5, right: 20, bottom: 5, left: 10 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke={COLORS.grid} />
                    <XAxis dataKey="date" tickFormatter={formatDate} tick={{ fontSize: 10, fill: COLORS.text }} interval="preserveStartEnd" />
                    <YAxis tick={{ fontSize: 10, fill: COLORS.text }} domain={[-3, 4]} />
                    <RTooltip content={<CustomTooltip />} />
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                    <ReferenceLine y={0} stroke="rgba(255,255,255,0.2)" />
                    <Line type="monotone" dataKey="Z_DXY" stroke="#06b6d4" strokeWidth={1} dot={false} name="DXY" connectNulls />
                    <Line type="monotone" dataKey="Z_COMMODITIES" stroke="#34d399" strokeWidth={1} dot={false} name="Commodities" connectNulls />
                    <Line type="monotone" dataKey="Z_EMBI" stroke="#f43f5e" strokeWidth={1} dot={false} name="EMBI" connectNulls />
                    <Line type="monotone" dataKey="Z_RIR" stroke="#a78bfa" strokeWidth={1} dot={false} name="Juros Reais" connectNulls />
                    <Line type="monotone" dataKey="Z_FLOW" stroke="#fbbf24" strokeWidth={1} dot={false} name="Fluxo" connectNulls />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </TabsContent>

            {/* Score Total */}
            <TabsContent value="score">
              <div className="h-[360px]">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={filteredTS} margin={{ top: 5, right: 20, bottom: 5, left: 10 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke={COLORS.grid} />
                    <XAxis dataKey="date" tickFormatter={formatDate} tick={{ fontSize: 10, fill: COLORS.text }} interval="preserveStartEnd" />
                    <YAxis tick={{ fontSize: 10, fill: COLORS.text }} domain={[-3, 3]} />
                    <RTooltip content={<CustomTooltip />} />
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                    <ReferenceLine y={0} stroke="rgba(255,255,255,0.2)" />
                    <ReferenceLine y={1} stroke="rgba(52,211,153,0.3)" strokeDasharray="3 3" label={{ value: 'BRL Depreciado', position: 'right', fill: 'rgba(52,211,153,0.5)', fontSize: 10 }} />
                    <ReferenceLine y={-1} stroke="rgba(244,63,94,0.3)" strokeDasharray="3 3" label={{ value: 'BRL Sobrevalorizado', position: 'right', fill: 'rgba(244,63,94,0.5)', fontSize: 10 }} />
                    <Area type="monotone" dataKey="score_total" stroke={COLORS.score_total} fill={COLORS.score_total} fillOpacity={0.15} strokeWidth={2} dot={false} name="Score Total" connectNulls />
                    <Line type="monotone" dataKey="score_struct" stroke="rgba(255,255,255,0.3)" strokeWidth={1} dot={false} name="Score Estrutural" strokeDasharray="4 2" connectNulls />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </TabsContent>
          </Tabs>
        </CardContent>
      </Card>
    </motion.div>
  );
}
