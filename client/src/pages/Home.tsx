/**
 * BRLUSD Institutional FX Model Dashboard
 * Design: "Institutional Command Center" - Dark slate theme
 * Hierarchy: Status Bar → Alerts → Overview Grid → Detail Charts → Stress Tests → SHAP → Changelog → Action Panel
 */

import { useModelData } from '@/hooks/useModelData';
import { StatusBar } from '@/components/StatusBar';
import { OverviewGrid } from '@/components/OverviewGrid';
import { ChartsSection } from '@/components/ChartsSection';
import { StressTestPanel } from '@/components/StressTestPanel';
import { BacktestPanel } from '@/components/BacktestPanel';
import { ShapPanel } from '@/components/ShapPanel';
import { ShapHistoryPanel } from '@/components/ShapHistoryPanel';
import { ActionPanel } from '@/components/ActionPanel';
import { ModelDetails } from '@/components/ModelDetails';
import { ModelChangelogPanel } from '@/components/ModelChangelogPanel';
import { ModelAlertsPanel } from '@/components/ModelAlertsPanel';
import { Loader2 } from 'lucide-react';

export default function Home() {
  const { dashboard, timeseries, regimeProbs, cyclicalFactors, stateVariables, score, backtest, shapImportance, shapHistory, loading, error, source, lastUpdated } = useModelData();

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <div className="flex flex-col items-center gap-4">
          <Loader2 className="w-8 h-8 animate-spin text-primary" />
          <p className="text-muted-foreground text-sm font-medium tracking-wide uppercase">
            Carregando Macro Risk OS...
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

  return (
    <div className="min-h-screen bg-background">
      {/* Status Bar - Mission Status */}
      <StatusBar dashboard={dashboard} source={source} lastUpdated={lastUpdated} />

      {/* Main Content */}
      <main className="container py-6 space-y-6">
        {/* Alerts - Regime changes, SHAP shifts, score changes */}
        <ModelAlertsPanel />

        {/* Overview Grid - 4 asset classes + state variables + regime */}
        <OverviewGrid dashboard={dashboard} />

        {/* Charts Section - Historical time series */}
        <ChartsSection
          timeseries={timeseries}
          regimeProbs={regimeProbs}
          cyclicalFactors={cyclicalFactors}
          stateVariables={stateVariables}
          score={score}
        />

        {/* Backtest - Hypothetical P&L */}
        <BacktestPanel backtest={backtest} />

        {/* SHAP Feature Importance - Model Drivers */}
        <ShapPanel shapImportance={shapImportance} />

        {/* SHAP Temporal Evolution - Structural Changes */}
        <ShapHistoryPanel shapHistory={shapHistory} />

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
          <span>Macro Risk OS v3.9.1 — FX + Rates + Sovereign</span>
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
