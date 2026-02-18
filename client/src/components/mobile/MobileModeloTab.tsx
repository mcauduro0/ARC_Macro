/**
 * MobileModeloTab — Model details: Health Score, Feature Selection, SHAP, Charts
 * Now uses MobileTouchChart for native touch-optimized charts
 */

import { useState, useMemo, type ReactNode } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Card, CardContent } from '@/components/ui/card';
import {
  ChevronDown,
  Heart,
  Filter,
  BarChart3,
  LineChart as LineChartIcon,
  Brain,
  TrendingUp,
  Activity,
  Zap,
} from 'lucide-react';
import { ModelHealthPanel } from '@/components/ModelHealthPanel';
import { FeatureSelectionPanel } from '@/components/FeatureSelectionPanel';
import { ShapPanel } from '@/components/ShapPanel';
import { ShapHistoryPanel } from '@/components/ShapHistoryPanel';
import { ChartsSection } from '@/components/ChartsSection';
import { ModelDetails } from '@/components/ModelDetails';
import {
  MobileTouchChart,
  MobileSpotChart,
  MobileScoreChart,
  MobileRegimeChart,
  MobileRstarChart,
} from '@/components/mobile/MobileTouchChart';
import type { MacroDashboard, TimeSeriesPoint, RegimePoint, CyclicalPoint, StateVarPoint, ScorePoint, RstarTsPoint } from '@/hooks/useModelData';
import type { ShapImportanceData } from '@/components/ShapPanel';
import type { ShapHistoryEntry } from '@/components/ShapHistoryPanel';

interface Props {
  dashboard: MacroDashboard;
  timeseries: TimeSeriesPoint[];
  regimeProbs: RegimePoint[];
  cyclicalFactors: CyclicalPoint[];
  stateVariables?: StateVarPoint[];
  score?: ScorePoint[];
  rstarTs?: RstarTsPoint[];
  shapImportance?: ShapImportanceData | null;
  shapHistory?: ShapHistoryEntry[] | null;
}

// ── Collapsible Section ────────────────────────────────────────────────────

function MobileSection({
  title,
  icon: Icon,
  children,
  defaultOpen = false,
  badge,
}: {
  title: string;
  icon: typeof Heart;
  children: ReactNode;
  defaultOpen?: boolean;
  badge?: string;
}) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className="border-b border-border/30 last:border-b-0">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-4 py-3.5 active:bg-accent/30 transition-colors"
      >
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center">
            <Icon className="w-4 h-4 text-primary" />
          </div>
          <span className="text-sm font-medium text-foreground">{title}</span>
          {badge && (
            <span className="px-1.5 py-0.5 rounded-md bg-primary/10 text-primary text-[10px] font-semibold">
              {badge}
            </span>
          )}
        </div>
        <motion.div
          animate={{ rotate: open ? 180 : 0 }}
          transition={{ duration: 0.2 }}
        >
          <ChevronDown className="w-4 h-4 text-muted-foreground" />
        </motion.div>
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.25 }}
            className="overflow-hidden"
          >
            <div className="px-2 pb-4">
              {children}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// ── Chart Sub-Tab Selector ────────────────────────────────────────────────

type ChartTab = 'spot' | 'score' | 'regime' | 'rstar' | 'state';

function ChartTabSelector({ active, onChange }: { active: ChartTab; onChange: (tab: ChartTab) => void }) {
  const tabs: Array<{ id: ChartTab; label: string }> = [
    { id: 'spot', label: 'Spot/FV' },
    { id: 'score', label: 'Score' },
    { id: 'regime', label: 'Regime' },
    { id: 'rstar', label: 'r*' },
    { id: 'state', label: 'Z-Scores' },
  ];

  return (
    <div className="flex gap-1 overflow-x-auto pb-2 px-1 -mx-1 scrollbar-hide">
      {tabs.map(tab => (
        <button
          key={tab.id}
          onClick={() => onChange(tab.id)}
          className={`px-3 py-1.5 rounded-full text-[10px] font-semibold whitespace-nowrap transition-colors ${
            active === tab.id
              ? 'bg-primary/20 text-primary'
              : 'bg-muted/10 text-muted-foreground active:bg-muted/20'
          }`}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}

// ── Main Component ─────────────────────────────────────────────────────────

export function MobileModeloTab({
  dashboard,
  timeseries,
  regimeProbs,
  cyclicalFactors,
  stateVariables,
  score,
  rstarTs,
  shapImportance,
  shapHistory,
}: Props) {
  const [chartTab, setChartTab] = useState<ChartTab>('spot');

  // Prepare state variable chart data
  const stateVarLines = useMemo(() => [
    { dataKey: 'Z_X1_diferencial_real', color: '#06b6d4', label: 'Dif. Real' },
    { dataKey: 'Z_X2_surpresa_inflacao', color: '#f472b6', label: 'Surp. Inflação' },
    { dataKey: 'Z_X3_fiscal_risk', color: '#f43f5e', label: 'Risco Fiscal' },
    { dataKey: 'Z_X4_termos_de_troca', color: '#34d399', label: 'Termos Troca' },
    { dataKey: 'Z_X6_risk_global', color: '#a78bfa', label: 'VIX' },
  ], []);

  return (
    <div className="py-2">
      <div className="px-4 py-2 mb-1">
        <h2 className="text-lg font-semibold text-foreground">Detalhes do Modelo</h2>
        <p className="text-xs text-muted-foreground">Saúde, features, SHAP e séries temporais</p>
      </div>

      <MobileSection title="Saúde do Modelo" icon={Heart} defaultOpen={true} badge="v4.6">
        <div className="overflow-x-auto -mx-2">
          <ModelHealthPanel data={dashboard?.feature_selection} />
        </div>
      </MobileSection>

      {/* Native Mobile Charts with Touch Optimization */}
      <MobileSection title="Gráficos Interativos" icon={LineChartIcon} defaultOpen={false} badge="Touch">
        <div className="space-y-3">
          <ChartTabSelector active={chartTab} onChange={setChartTab} />

          {chartTab === 'spot' && timeseries.length > 0 && (
            <MobileSpotChart data={timeseries} />
          )}

          {chartTab === 'score' && score && score.length > 0 && (
            <MobileScoreChart data={score} />
          )}

          {chartTab === 'regime' && regimeProbs.length > 0 && (
            <MobileRegimeChart data={regimeProbs} />
          )}

          {chartTab === 'rstar' && (
            rstarTs && rstarTs.length > 0 ? (
              <MobileRstarChart data={rstarTs} />
            ) : (
              <div className="flex items-center justify-center h-[200px]">
                <div className="text-center">
                  <p className="text-sm text-muted-foreground">Dados de r* não disponíveis.</p>
                  <p className="text-xs text-muted-foreground/60 mt-1">Será gerado na próxima execução.</p>
                </div>
              </div>
            )
          )}

          {chartTab === 'state' && stateVariables && stateVariables.length > 0 && (
            <MobileTouchChart
              data={stateVariables}
              title="State Variables (Z-Scores)"
              lines={stateVarLines}
              referenceLines={[{ y: 0, label: '', color: 'rgba(255,255,255,0.15)' }]}
              height={200}
            />
          )}

          <p className="text-[9px] text-muted-foreground/50 text-center px-4">
            Toque para ver valores • Pinch para zoom • Botões ⊕⊖ para zoom manual
          </p>
        </div>
      </MobileSection>

      <MobileSection title="Feature Selection" icon={Filter} badge="ENet+Boruta">
        <div className="overflow-x-auto -mx-2">
          <FeatureSelectionPanel
            data={dashboard?.feature_selection}
            temporal={dashboard?.feature_selection_temporal}
          />
        </div>
      </MobileSection>

      <MobileSection title="SHAP Importance" icon={BarChart3}>
        <div className="overflow-x-auto -mx-2">
          <ShapPanel shapImportance={shapImportance || null} />
        </div>
      </MobileSection>

      <MobileSection title="SHAP Temporal" icon={TrendingUp}>
        <div className="overflow-x-auto -mx-2">
          <ShapHistoryPanel shapHistory={shapHistory || null} />
        </div>
      </MobileSection>

      {/* Keep full ChartsSection as fallback for complete desktop-style charts */}
      <MobileSection title="Séries Temporais (Completo)" icon={Activity}>
        <div className="overflow-x-auto -mx-2">
          <ChartsSection
            timeseries={timeseries}
            regimeProbs={regimeProbs}
            cyclicalFactors={cyclicalFactors}
            stateVariables={stateVariables}
            score={score}
            rstarTs={rstarTs}
          />
        </div>
      </MobileSection>

      <MobileSection title="Detalhes Regressão" icon={Brain}>
        <div className="overflow-x-auto -mx-2">
          <ModelDetails dashboard={dashboard} />
        </div>
      </MobileSection>
    </div>
  );
}
