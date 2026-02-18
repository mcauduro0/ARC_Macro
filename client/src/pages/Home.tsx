/**
 * ARC Macro — Cross-Asset Dashboard
 * Design: "Institutional Command Center" - Dark slate theme
 * Responsive: Desktop (full layout) + Mobile (tab-based navigation)
 */

import { useState, useMemo, lazy, Suspense } from 'react';
import { useModelData } from '@/hooks/useModelData';
import { useIsMobile } from '@/hooks/useMobile';
import { StatusBar } from '@/components/StatusBar';
import { OverviewGrid } from '@/components/OverviewGrid';
import { ChartsSection } from '@/components/ChartsSection';
import { StressTestPanel } from '@/components/StressTestPanel';
import { BacktestPanel } from '@/components/BacktestPanel';
import { ShapPanel } from '@/components/ShapPanel';
import { ShapHistoryPanel } from '@/components/ShapHistoryPanel';
import { ActionPanel } from '@/components/ActionPanel';
import { ModelDetails } from '@/components/ModelDetails';
import { EquilibriumPanel } from '@/components/EquilibriumPanel';
import { ModelChangelogPanel } from '@/components/ModelChangelogPanel';
import { RegimeWeightHeatmap } from '@/components/RegimeWeightHeatmap';
import { WhatIfPanel } from '@/components/WhatIfPanel';
import { ModelAlertsPanel } from '@/components/ModelAlertsPanel';
import { CombinedStressPanel } from '@/components/CombinedStressPanel';
import { RstarBacktestPanel } from '@/components/RstarBacktestPanel';
import { SovereignRiskPanel } from '@/components/SovereignRiskPanel';
import { PipelinePanel } from '@/components/PipelinePanel';
import { DataSourceHealthPanel } from '@/components/DataSourceHealthPanel';
import { FeatureSelectionPanel } from '@/components/FeatureSelectionPanel';
import { ModelHealthPanel } from '@/components/ModelHealthPanel';
import { MobileLayout, type MobileTab } from '@/components/MobileLayout';
import { MobileOverviewTab } from '@/components/mobile/MobileOverviewTab';
import { MobileModeloTab } from '@/components/mobile/MobileModeloTab';
import { MobilePortfolioTab } from '@/components/mobile/MobilePortfolioTab';
import { MobileAlertasTab } from '@/components/mobile/MobileAlertasTab';
import { MobileMoreTab } from '@/components/mobile/MobileMoreTab';
import { Loader2 } from 'lucide-react';

export default function Home() {
  const { dashboard, timeseries, regimeProbs, cyclicalFactors, stateVariables, score, rstarTs, backtest, shapImportance, shapHistory, loading, error, source, lastUpdated } = useModelData();
  const isMobileDevice = useIsMobile();
  // Allow ?mobile=true URL param to force mobile view for testing
  const forceMobile = typeof window !== 'undefined' && new URLSearchParams(window.location.search).get('mobile') === 'true';
  const isMobile = isMobileDevice || forceMobile;
  const [activeTab, setActiveTab] = useState<MobileTab>('overview');

  // Count alerts for badge
  const alertCount = useMemo(() => {
    if (!dashboard?.feature_selection) return 0;
    let count = 0;
    for (const [key, inst] of Object.entries(dashboard.feature_selection)) {
      if (key === 'summary' || key === 'temporal') continue;
      const alerts = (inst as any)?.alerts;
      if (Array.isArray(alerts)) {
        count += alerts.filter((a: any) => a.type === 'critical' || a.type === 'warning').length;
      }
    }
    return count;
  }, [dashboard?.feature_selection]);

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <div className="flex flex-col items-center gap-4">
          <Loader2 className="w-8 h-8 animate-spin text-primary" />
          <p className="text-muted-foreground text-sm font-medium tracking-wide uppercase">
            Carregando ARC Macro...
          </p>
        </div>
      </div>
    );
  }

  if (error || !dashboard) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <div className="text-center">
          <p className="text-destructive text-lg font-semibold">Erro ao carregar dados</p>
          <p className="text-muted-foreground mt-2">{error}</p>
        </div>
      </div>
    );
  }

  // ── Mobile Layout ──────────────────────────────────────────────────────

  if (isMobile) {
    return (
      <MobileLayout
        dashboard={dashboard}
        source={source}
        lastUpdated={lastUpdated}
        activeTab={activeTab}
        onTabChange={setActiveTab}
        alertCount={alertCount}
      >
        {activeTab === 'overview' && (
          <MobileOverviewTab dashboard={dashboard} />
        )}
        {activeTab === 'modelo' && (
          <MobileModeloTab
            dashboard={dashboard}
            timeseries={timeseries}
            regimeProbs={regimeProbs}
            cyclicalFactors={cyclicalFactors}
            stateVariables={stateVariables}
            score={score}
            rstarTs={rstarTs}
            shapImportance={shapImportance}
            shapHistory={shapHistory}
          />
        )}
        {activeTab === 'portfolio' && (
          <MobilePortfolioTab
            dashboard={dashboard}
            backtest={backtest}
            rstarTs={rstarTs}
            shapImportance={shapImportance}
          />
        )}
        {activeTab === 'alertas' && (
          <MobileAlertasTab />
        )}
        {activeTab === 'mais' && (
          <MobileMoreTab dashboard={dashboard} />
        )}
      </MobileLayout>
    );
  }

  // ── Desktop Layout ─────────────────────────────────────────────────────

  return (
    <div className="min-h-screen bg-background">
      {/* Status Bar - Mission Status */}
      <StatusBar dashboard={dashboard} source={source} lastUpdated={lastUpdated} />

      {/* Main Content */}
      <main className="container py-6 space-y-6">
        {/* Pipeline - Daily automated update trigger + status */}
        <PipelinePanel />

        {/* Data Source Health - Status, latency, uptime of external sources */}
        <DataSourceHealthPanel />

        {/* Alerts - Regime changes, SHAP shifts, score changes */}
        <ModelAlertsPanel />

        {/* Overview Grid - 4 asset classes + state variables + regime */}
        <OverviewGrid dashboard={dashboard} />

        {/* Composite Equilibrium Rate Breakdown */}
        <EquilibriumPanel dashboard={dashboard} />

        {/* Regime Weight Heatmap - Model weight evolution across regimes */}
        <RegimeWeightHeatmap dashboard={dashboard} />

        {/* What-If Scenarios - Interactive r* sensitivity analysis */}
        <WhatIfPanel dashboard={dashboard} />

        {/* Sovereign Risk Dashboard */}
        <SovereignRiskPanel dashboard={dashboard} />

        {/* Combined Stress Testing */}
        <CombinedStressPanel dashboard={dashboard} />

        {/* r* Signal Backtesting */}
        <RstarBacktestPanel rstarTs={rstarTs} backtest={backtest} />

        {/* Charts Section - Historical time series */}
        <ChartsSection
          timeseries={timeseries}
          regimeProbs={regimeProbs}
          cyclicalFactors={cyclicalFactors}
          stateVariables={stateVariables}
          score={score}
          rstarTs={rstarTs}
        />

        {/* Backtest - Hypothetical P&L */}
        <BacktestPanel backtest={backtest} />

        {/* SHAP Feature Importance - Model Drivers */}
        <ShapPanel shapImportance={shapImportance} />

        {/* SHAP Temporal Evolution - Structural Changes */}
        <ShapHistoryPanel shapHistory={shapHistory} />

        {/* Model Health Score - Consolidated health dashboard */}
        <ModelHealthPanel data={dashboard?.feature_selection} />

        {/* Feature Selection - LASSO + Boruta dual selection results */}
        <FeatureSelectionPanel data={dashboard?.feature_selection} temporal={dashboard?.feature_selection_temporal} />

        {/* Stress Tests - Historical scenarios */}
        <StressTestPanel dashboard={dashboard} />

        {/* Action Panel - Expected Return + Sizing */}
        <ActionPanel dashboard={dashboard} backtest={backtest} />

        {/* Model Changelog - Version history with metrics comparison */}
        <ModelChangelogPanel />

        {/* Model Details - Regression stats */}
        <ModelDetails dashboard={dashboard} />
      </main>

      {/* Footer */}
      <footer className="border-t border-border/50 py-4 mt-8">
        <div className="container flex items-center justify-between text-xs text-muted-foreground">
          <span>ARC Macro v4.6 — FX + Rates + Sovereign</span>
          <div className="flex items-center gap-3">
            {lastUpdated && (
              <span>Atualizado: {lastUpdated.toLocaleString('pt-BR')}</span>
            )}
            <span>Run: {dashboard.run_date}</span>
          </div>
        </div>
      </footer>
    </div>
  );
}
