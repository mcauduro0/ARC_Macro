/**
 * MobileTouchChart — Touch-optimized chart wrapper for Recharts
 * 
 * Features:
 * - Pinch-to-zoom on time axis
 * - Persistent tap-to-show tooltip (not hover-based)
 * - Simplified axes with fewer ticks
 * - Swipe to pan when zoomed
 * - Full-screen mode toggle
 */

import { useState, useCallback, useRef, useMemo, useEffect, type ReactNode } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  ResponsiveContainer,
  LineChart, Line,
  AreaChart, Area,
  BarChart, Bar,
  XAxis, YAxis, CartesianGrid,
  Tooltip as RTooltip,
  ReferenceLine, Legend,
} from 'recharts';
import { Maximize2, Minimize2, ZoomIn, ZoomOut, RotateCcw } from 'lucide-react';

// ── Types ──────────────────────────────────────────────────────────────────

interface ChartLine {
  dataKey: string;
  color: string;
  label: string;
  strokeWidth?: number;
  strokeDasharray?: string;
  type?: 'line' | 'area';
  fillOpacity?: number;
}

interface MobileTouchChartProps {
  data: any[];
  lines: ChartLine[];
  xKey?: string;
  height?: number;
  title?: string;
  subtitle?: string;
  yDomain?: [number | string, number | string];
  yTickFormatter?: (value: number) => string;
  xTickFormatter?: (value: string) => string;
  referenceLines?: Array<{ y: number; label: string; color: string; strokeDasharray?: string }>;
  showLegend?: boolean;
  chartType?: 'line' | 'area' | 'mixed';
  connectNulls?: boolean;
}

// ── Custom Mobile Tooltip ──────────────────────────────────────────────────

function MobileTooltip({ active, payload, label, lines }: any) {
  if (!active || !payload?.length) return null;

  return (
    <div className="bg-background/95 backdrop-blur-sm border border-border/50 rounded-lg px-3 py-2 shadow-lg max-w-[200px]">
      <p className="text-[10px] text-muted-foreground font-mono mb-1">{label}</p>
      {payload.map((entry: any, i: number) => {
        const lineConfig = lines?.find((l: ChartLine) => l.dataKey === entry.dataKey);
        return (
          <div key={i} className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-1.5">
              <div
                className="w-2 h-2 rounded-full"
                style={{ backgroundColor: entry.color }}
              />
              <span className="text-[10px] text-foreground truncate max-w-[100px]">
                {lineConfig?.label || entry.name}
              </span>
            </div>
            <span className="font-data text-[11px] font-semibold text-foreground">
              {typeof entry.value === 'number' ? entry.value.toFixed(4) : entry.value}
            </span>
          </div>
        );
      })}
    </div>
  );
}

// ── Compact Legend ──────────────────────────────────────────────────────────

function CompactLegend({ lines }: { lines: ChartLine[] }) {
  return (
    <div className="flex flex-wrap gap-x-3 gap-y-1 px-2 pb-1">
      {lines.map(line => (
        <div key={line.dataKey} className="flex items-center gap-1">
          <div
            className="w-2 h-2 rounded-full"
            style={{ backgroundColor: line.color }}
          />
          <span className="text-[9px] text-muted-foreground">{line.label}</span>
        </div>
      ))}
    </div>
  );
}

// ── Main Component ─────────────────────────────────────────────────────────

export function MobileTouchChart({
  data,
  lines,
  xKey = 'date',
  height = 220,
  title,
  subtitle,
  yDomain,
  yTickFormatter,
  xTickFormatter,
  referenceLines,
  showLegend = true,
  chartType = 'line',
  connectNulls = true,
}: MobileTouchChartProps) {
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [zoomLevel, setZoomLevel] = useState(1);
  const [panOffset, setPanOffset] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);
  const touchStartRef = useRef<{ x: number; y: number; distance?: number }>({ x: 0, y: 0 });

  // Calculate visible data range based on zoom and pan
  const visibleData = useMemo(() => {
    if (zoomLevel <= 1) return data;
    const totalPoints = data.length;
    const visiblePoints = Math.max(10, Math.floor(totalPoints / zoomLevel));
    const maxOffset = totalPoints - visiblePoints;
    const offset = Math.min(Math.max(0, Math.floor(panOffset)), maxOffset);
    return data.slice(offset, offset + visiblePoints);
  }, [data, zoomLevel, panOffset]);

  // Touch handlers for pinch-to-zoom
  const handleTouchStart = useCallback((e: React.TouchEvent) => {
    if (e.touches.length === 2) {
      const dx = e.touches[0].clientX - e.touches[1].clientX;
      const dy = e.touches[0].clientY - e.touches[1].clientY;
      touchStartRef.current = {
        x: (e.touches[0].clientX + e.touches[1].clientX) / 2,
        y: (e.touches[0].clientY + e.touches[1].clientY) / 2,
        distance: Math.sqrt(dx * dx + dy * dy),
      };
    } else if (e.touches.length === 1) {
      touchStartRef.current = {
        x: e.touches[0].clientX,
        y: e.touches[0].clientY,
      };
    }
  }, []);

  const handleTouchMove = useCallback((e: React.TouchEvent) => {
    if (e.touches.length === 2 && touchStartRef.current.distance) {
      // Pinch zoom
      const dx = e.touches[0].clientX - e.touches[1].clientX;
      const dy = e.touches[0].clientY - e.touches[1].clientY;
      const newDistance = Math.sqrt(dx * dx + dy * dy);
      const scale = newDistance / touchStartRef.current.distance;
      setZoomLevel(prev => Math.min(5, Math.max(1, prev * scale)));
      touchStartRef.current.distance = newDistance;
    } else if (e.touches.length === 1 && zoomLevel > 1) {
      // Pan when zoomed
      const dx = e.touches[0].clientX - touchStartRef.current.x;
      const pointsPerPixel = data.length / (containerRef.current?.clientWidth || 300);
      setPanOffset(prev => Math.max(0, prev - dx * pointsPerPixel * 0.5));
      touchStartRef.current.x = e.touches[0].clientX;
    }
  }, [zoomLevel, data.length]);

  // Zoom controls
  const handleZoomIn = useCallback(() => {
    setZoomLevel(prev => Math.min(5, prev * 1.5));
  }, []);

  const handleZoomOut = useCallback(() => {
    setZoomLevel(prev => {
      const next = prev / 1.5;
      if (next <= 1.1) {
        setPanOffset(0);
        return 1;
      }
      return next;
    });
  }, []);

  const handleReset = useCallback(() => {
    setZoomLevel(1);
    setPanOffset(0);
  }, []);

  // Default formatters
  const defaultXFormatter = useCallback((value: string) => {
    if (!value) return '';
    // Show only month/year for dates
    if (value.includes('-')) {
      const parts = value.split('-');
      return `${parts[1]}/${parts[0]?.slice(2)}`;
    }
    return value;
  }, []);

  const defaultYFormatter = useCallback((value: number) => {
    if (Math.abs(value) >= 1000) return `${(value / 1000).toFixed(1)}k`;
    if (Math.abs(value) < 0.01) return value.toFixed(4);
    if (Math.abs(value) < 1) return value.toFixed(2);
    return value.toFixed(1);
  }, []);

  const xFormatter = xTickFormatter || defaultXFormatter;
  const yFormatter = yTickFormatter || defaultYFormatter;

  // Calculate tick count based on data points
  const xTickCount = Math.min(5, Math.floor(visibleData.length / 4));

  const chartHeight = isFullscreen ? 400 : height;

  const chartContent = (
    <div
      ref={containerRef}
      className="relative"
      onTouchStart={handleTouchStart}
      onTouchMove={handleTouchMove}
    >
      {/* Title bar */}
      {(title || subtitle) && (
        <div className="flex items-center justify-between px-2 pb-1">
          <div>
            {title && <h4 className="text-xs font-semibold text-foreground">{title}</h4>}
            {subtitle && <p className="text-[9px] text-muted-foreground">{subtitle}</p>}
          </div>
          <div className="flex items-center gap-1">
            {zoomLevel > 1 && (
              <button
                onClick={handleReset}
                className="w-6 h-6 flex items-center justify-center rounded bg-muted/20 active:bg-muted/40"
              >
                <RotateCcw className="w-3 h-3 text-muted-foreground" />
              </button>
            )}
            <button
              onClick={handleZoomOut}
              className="w-6 h-6 flex items-center justify-center rounded bg-muted/20 active:bg-muted/40"
              disabled={zoomLevel <= 1}
            >
              <ZoomOut className={`w-3 h-3 ${zoomLevel <= 1 ? 'text-muted-foreground/30' : 'text-muted-foreground'}`} />
            </button>
            <button
              onClick={handleZoomIn}
              className="w-6 h-6 flex items-center justify-center rounded bg-muted/20 active:bg-muted/40"
              disabled={zoomLevel >= 5}
            >
              <ZoomIn className={`w-3 h-3 ${zoomLevel >= 5 ? 'text-muted-foreground/30' : 'text-muted-foreground'}`} />
            </button>
            <button
              onClick={() => setIsFullscreen(!isFullscreen)}
              className="w-6 h-6 flex items-center justify-center rounded bg-muted/20 active:bg-muted/40"
            >
              {isFullscreen ? (
                <Minimize2 className="w-3 h-3 text-muted-foreground" />
              ) : (
                <Maximize2 className="w-3 h-3 text-muted-foreground" />
              )}
            </button>
          </div>
        </div>
      )}

      {/* Legend */}
      {showLegend && <CompactLegend lines={lines} />}

      {/* Zoom indicator */}
      {zoomLevel > 1 && (
        <div className="absolute top-1 left-1/2 -translate-x-1/2 z-10 px-2 py-0.5 rounded-full bg-primary/10 text-primary text-[9px] font-semibold">
          {zoomLevel.toFixed(1)}x zoom
        </div>
      )}

      {/* Chart */}
      <ResponsiveContainer width="100%" height={chartHeight}>
        {chartType === 'area' || lines.every(l => l.type === 'area') ? (
          <AreaChart data={visibleData} margin={{ top: 5, right: 10, bottom: 5, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
            <XAxis
              dataKey={xKey}
              tick={{ fontSize: 9, fill: 'rgba(255,255,255,0.4)' }}
              tickFormatter={xFormatter}
              interval={Math.max(0, Math.floor(visibleData.length / xTickCount) - 1)}
              axisLine={{ stroke: 'rgba(255,255,255,0.1)' }}
              tickLine={false}
            />
            <YAxis
              tick={{ fontSize: 9, fill: 'rgba(255,255,255,0.4)' }}
              tickFormatter={yFormatter}
              domain={yDomain || ['auto', 'auto']}
              width={40}
              axisLine={false}
              tickLine={false}
            />
            <RTooltip
              content={<MobileTooltip lines={lines} />}
              trigger="click"
              wrapperStyle={{ zIndex: 100 }}
            />
            {referenceLines?.map((ref, i) => (
              <ReferenceLine
                key={i}
                y={ref.y}
                stroke={ref.color}
                strokeDasharray={ref.strokeDasharray || '3 3'}
                label={{ value: ref.label, fontSize: 9, fill: ref.color }}
              />
            ))}
            {lines.map(line => (
              <Area
                key={line.dataKey}
                type="monotone"
                dataKey={line.dataKey}
                stroke={line.color}
                fill={line.color}
                fillOpacity={line.fillOpacity ?? 0.1}
                strokeWidth={line.strokeWidth || 1.5}
                strokeDasharray={line.strokeDasharray}
                connectNulls={connectNulls}
                dot={false}
                activeDot={{ r: 4, strokeWidth: 2, fill: line.color }}
              />
            ))}
          </AreaChart>
        ) : (
          <LineChart data={visibleData} margin={{ top: 5, right: 10, bottom: 5, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
            <XAxis
              dataKey={xKey}
              tick={{ fontSize: 9, fill: 'rgba(255,255,255,0.4)' }}
              tickFormatter={xFormatter}
              interval={Math.max(0, Math.floor(visibleData.length / xTickCount) - 1)}
              axisLine={{ stroke: 'rgba(255,255,255,0.1)' }}
              tickLine={false}
            />
            <YAxis
              tick={{ fontSize: 9, fill: 'rgba(255,255,255,0.4)' }}
              tickFormatter={yFormatter}
              domain={yDomain || ['auto', 'auto']}
              width={40}
              axisLine={false}
              tickLine={false}
            />
            <RTooltip
              content={<MobileTooltip lines={lines} />}
              trigger="click"
              wrapperStyle={{ zIndex: 100 }}
            />
            {referenceLines?.map((ref, i) => (
              <ReferenceLine
                key={i}
                y={ref.y}
                stroke={ref.color}
                strokeDasharray={ref.strokeDasharray || '3 3'}
                label={{ value: ref.label, fontSize: 9, fill: ref.color }}
              />
            ))}
            {lines.map(line =>
              line.type === 'area' ? (
                <Area
                  key={line.dataKey}
                  type="monotone"
                  dataKey={line.dataKey}
                  stroke={line.color}
                  fill={line.color}
                  fillOpacity={line.fillOpacity ?? 0.1}
                  strokeWidth={line.strokeWidth || 1.5}
                  strokeDasharray={line.strokeDasharray}
                  connectNulls={connectNulls}
                  dot={false}
                  activeDot={{ r: 4, strokeWidth: 2, fill: line.color }}
                />
              ) : (
                <Line
                  key={line.dataKey}
                  type="monotone"
                  dataKey={line.dataKey}
                  stroke={line.color}
                  strokeWidth={line.strokeWidth || 1.5}
                  strokeDasharray={line.strokeDasharray}
                  dot={false}
                  activeDot={{ r: 4, strokeWidth: 2, fill: line.color }}
                  connectNulls={connectNulls}
                />
              )
            )}
          </LineChart>
        )}
      </ResponsiveContainer>
    </div>
  );

  // Fullscreen overlay
  if (isFullscreen) {
    return (
      <AnimatePresence>
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 z-[100] bg-background/98 backdrop-blur-md flex flex-col"
        >
          <div className="flex items-center justify-between px-4 py-3 border-b border-border/30">
            <div>
              {title && <h3 className="text-sm font-semibold text-foreground">{title}</h3>}
              {subtitle && <p className="text-[10px] text-muted-foreground">{subtitle}</p>}
            </div>
            <button
              onClick={() => setIsFullscreen(false)}
              className="w-8 h-8 flex items-center justify-center rounded-lg bg-muted/20 active:bg-muted/40"
            >
              <Minimize2 className="w-4 h-4 text-muted-foreground" />
            </button>
          </div>
          <div className="flex-1 px-2 py-4">
            {chartContent}
          </div>
        </motion.div>
      </AnimatePresence>
    );
  }

  return chartContent;
}

// ── Pre-configured Chart Variants ──────────────────────────────────────────

export function MobileSpotChart({ data }: { data: any[] }) {
  return (
    <MobileTouchChart
      data={data}
      title="USDBRL Spot vs Fair Values"
      lines={[
        { dataKey: 'spot', color: '#06b6d4', label: 'Spot' },
        { dataKey: 'ppp_fair', color: '#a78bfa', label: 'PPP Fair', strokeDasharray: '4 2' },
        { dataKey: 'beer_fair', color: '#34d399', label: 'BEER Fair', strokeDasharray: '4 2' },
        { dataKey: 'fx_fair', color: '#f59e0b', label: 'FX Fair', strokeDasharray: '4 2' },
      ]}
      height={200}
    />
  );
}

export function MobileScoreChart({ data }: { data: any[] }) {
  return (
    <MobileTouchChart
      data={data}
      title="Score Composto"
      lines={[
        { dataKey: 'score_total', color: '#06b6d4', label: 'Score Total', strokeWidth: 2 },
      ]}
      referenceLines={[
        { y: 0, label: 'Neutro', color: 'rgba(255,255,255,0.2)' },
      ]}
      height={180}
    />
  );
}

export function MobileRegimeChart({ data }: { data: any[] }) {
  return (
    <MobileTouchChart
      data={data}
      title="Regime Probabilities"
      chartType="area"
      lines={[
        { dataKey: 'P_carry', color: '#34d399', label: 'Carry', type: 'area', fillOpacity: 0.3 },
        { dataKey: 'P_riskoff', color: '#f43f5e', label: 'Risk-Off', type: 'area', fillOpacity: 0.3 },
        { dataKey: 'P_domestic_stress', color: '#f59e0b', label: 'Dom. Stress', type: 'area', fillOpacity: 0.3 },
      ]}
      yDomain={[0, 1]}
      yTickFormatter={(v) => `${(v * 100).toFixed(0)}%`}
      height={180}
    />
  );
}

export function MobileRstarChart({ data }: { data: any[] }) {
  return (
    <MobileTouchChart
      data={data}
      title="r* Real vs SELIC*"
      lines={[
        { dataKey: 'rstar_composite', color: '#06b6d4', label: 'r* Real', strokeWidth: 2 },
        { dataKey: 'selic_star', color: '#f59e0b', label: 'SELIC*', strokeDasharray: '4 2' },
        { dataKey: 'selic_atual', color: '#a78bfa', label: 'SELIC Atual', strokeDasharray: '2 2' },
      ]}
      yTickFormatter={(v) => `${v.toFixed(1)}%`}
      height={200}
    />
  );
}

export function MobileEquityCurveChart({ data }: { data: any[] }) {
  return (
    <MobileTouchChart
      data={data}
      title="Equity Curve (Overlay)"
      lines={[
        { dataKey: 'cumulative_overlay', color: '#06b6d4', label: 'Overlay', strokeWidth: 2 },
        { dataKey: 'cumulative_total', color: '#f59e0b', label: 'Total (CDI+)', strokeWidth: 1.5, strokeDasharray: '4 2' },
      ]}
      referenceLines={[
        { y: 0, label: '', color: 'rgba(255,255,255,0.1)' },
      ]}
      yTickFormatter={(v) => `${(v * 100).toFixed(1)}%`}
      height={200}
    />
  );
}
