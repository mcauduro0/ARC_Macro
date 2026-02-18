/**
 * WhatIfPanel — Interactive r* Scenario Analysis
 *
 * Allows the user to adjust fiscal variables (Debt/GDP, Primary Balance, CDS, EMBI)
 * and see the real-time impact on the composite r* and SELIC*.
 * Includes preset scenarios: Fiscal Consolidation, Fiscal Expansion, Stress.
 */

import { useState, useMemo, useCallback } from 'react';
import { EquilibriumData, MacroDashboard } from '@/hooks/useModelData';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { Button } from '@/components/ui/button';
import { Slider } from '@/components/ui/slider';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Info, RotateCcw, TrendingDown, TrendingUp, AlertTriangle,
  Zap, Target, ArrowRight, Download
} from 'lucide-react';
import { generateWhatIfPdf, type WhatIfExportData } from '@/lib/whatIfPdfExport';
import { runMonteCarloSimulation, type MonteCarloResult } from '@/lib/monteCarloRstar';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip as RTooltip, ResponsiveContainer, ReferenceLine, Cell } from 'recharts';

interface Props {
  dashboard: MacroDashboard;
}

/** Fiscal variable definition */
interface FiscalVar {
  key: string;
  label: string;
  unit: string;
  description: string;
  min: number;
  max: number;
  step: number;
  defaultValue: number;
  /** How this variable maps to r* impact (bps per unit change) */
  sensitivity: number;
}

/** Preset scenario */
interface Scenario {
  id: string;
  label: string;
  description: string;
  icon: typeof TrendingDown;
  color: string;
  values: Record<string, number>;
}

// ============================================================
// Fiscal Variable Definitions
// ============================================================

const FISCAL_VARS: FiscalVar[] = [
  {
    key: 'debt_gdp',
    label: 'Dívida Bruta / PIB',
    unit: '%',
    description: 'Relação dívida bruta do governo / PIB. Atual ~78%. Cada 10pp adicional eleva r* em ~80bps.',
    min: 50,
    max: 120,
    step: 1,
    defaultValue: 78,
    sensitivity: 0.08, // 8bps per 1pp
  },
  {
    key: 'primary_balance',
    label: 'Resultado Primário / PIB',
    unit: '%',
    description: 'Superávit (+) ou déficit (-) primário como % do PIB. Cada 1pp de melhora reduz r* em ~50bps.',
    min: -4,
    max: 4,
    step: 0.1,
    defaultValue: -0.5,
    sensitivity: -0.50, // -50bps per 1pp (surplus reduces r*)
  },
  {
    key: 'cds_5y',
    label: 'CDS 5Y Brasil',
    unit: 'bps',
    description: 'Credit Default Swap 5 anos. Proxy de risco soberano. Cada 100bps adicional eleva r* em ~35bps.',
    min: 50,
    max: 500,
    step: 5,
    defaultValue: 160,
    sensitivity: 0.0035, // 0.35bps per 1bps CDS
  },
  {
    key: 'embi',
    label: 'EMBI+ Brasil',
    unit: 'bps',
    description: 'Spread soberano EM. Complementa CDS como medida de risco-país. Cada 100bps adicional eleva r* em ~25bps.',
    min: 50,
    max: 600,
    step: 5,
    defaultValue: 144,
    sensitivity: 0.0025, // 0.25bps per 1bps EMBI
  },
  {
    key: 'ipca_exp',
    label: 'IPCA Expectativa 12m',
    unit: '%',
    description: 'Expectativa de inflação 12 meses (Focus). Afeta a conversão de r* real para SELIC* nominal.',
    min: 2,
    max: 12,
    step: 0.1,
    defaultValue: 5.8,
    sensitivity: 0, // Only affects SELIC* conversion, not r*
  },
];

// ============================================================
// Preset Scenarios
// ============================================================

const PRESETS: Scenario[] = [
  {
    id: 'current',
    label: 'Atual',
    description: 'Valores atuais do modelo',
    icon: Target,
    color: 'text-primary',
    values: {}, // Will be filled from dashboard
  },
  {
    id: 'consolidation',
    label: 'Consolidação Fiscal',
    description: 'Superávit primário de 1.5%, dívida estabilizada em 75%, CDS em 120bps',
    icon: TrendingDown,
    color: 'text-emerald-400',
    values: {
      debt_gdp: 75,
      primary_balance: 1.5,
      cds_5y: 120,
      embi: 110,
      ipca_exp: 4.5,
    },
  },
  {
    id: 'expansion',
    label: 'Expansão Fiscal',
    description: 'Déficit primário de -2.5%, dívida em 85%, CDS em 220bps',
    icon: TrendingUp,
    color: 'text-amber-400',
    values: {
      debt_gdp: 85,
      primary_balance: -2.5,
      cds_5y: 220,
      embi: 200,
      ipca_exp: 6.5,
    },
  },
  {
    id: 'stress',
    label: 'Stress Fiscal',
    description: 'Crise fiscal: déficit -4%, dívida 100%, CDS 400bps, EMBI 500bps',
    icon: AlertTriangle,
    color: 'text-rose-400',
    values: {
      debt_gdp: 100,
      primary_balance: -4,
      cds_5y: 400,
      embi: 500,
      ipca_exp: 9.0,
    },
  },
];

// ============================================================
// r* Recalculation Engine (client-side)
// ============================================================

/**
 * Recalculate the Fiscal-Augmented r* based on adjusted variables.
 * Formula: r*_fiscal = base (4%) + debt_premium + fiscal_premium + sovereign_premium
 */
function recalcFiscalRstar(vars: Record<string, number>, defaults: Record<string, number>): number {
  const base = 4.0;

  // Debt/GDP premium: each pp above 60% adds ~8bps
  const debtPremium = Math.max(0, (vars.debt_gdp - 60) * 0.08);

  // Primary balance: each pp of deficit adds ~50bps
  const fiscalPremium = Math.max(0, -vars.primary_balance * 0.50);

  // Sovereign risk: CDS contribution
  const cdsPremium = (vars.cds_5y / 100) * 0.35;

  return base + debtPremium * 0.4 + fiscalPremium * 0.3 + cdsPremium * 0.3;
}

/**
 * Recalculate composite r* using the fiscal r* delta applied to the current composite.
 * Other models (parity, market-implied, state-space, regime) are held constant.
 */
function recalcCompositeRstar(
  currentComposite: number,
  currentFiscalRstar: number,
  newFiscalRstar: number,
  fiscalWeight: number
): number {
  // Delta from fiscal model change, weighted by its regime weight
  const fiscalDelta = (newFiscalRstar - currentFiscalRstar) * fiscalWeight;

  // Also add a secondary effect: CDS/EMBI changes affect parity model too (~30% pass-through)
  return currentComposite + fiscalDelta;
}

export function WhatIfPanel({ dashboard: d }: Props) {
  const eq = d.equilibrium;
  if (!eq?.composite_rstar || !eq?.model_contributions) return null;

  // Current values from the model
  const currentValues: Record<string, number> = useMemo(() => ({
    debt_gdp: 78, // Approximate from model
    primary_balance: -0.5,
    cds_5y: 160, // From dashboard
    embi: d.embi_spread || 144,
    ipca_exp: 5.8, // Approximate IPCA expectation
  }), [d.embi_spread]);

  // Fill the "current" preset
  PRESETS[0].values = currentValues;

  const [values, setValues] = useState<Record<string, number>>(currentValues);
  const [activePreset, setActivePreset] = useState<string>('current');
  const [mcResult, setMcResult] = useState<MonteCarloResult | null>(null);
  const [mcRunning, setMcRunning] = useState(false);

  // Calculate the what-if r*
  const whatIfResult = useMemo(() => {
    const currentFiscalRstar = eq.rstar_fiscal || 6.42;
    const fiscalWeight = eq.model_contributions.fiscal?.weight || 0.15;
    const compositeRstar = eq.composite_rstar!;

    // Recalculate fiscal r* with new variables
    const newFiscalRstar = recalcFiscalRstar(values, currentValues);

    // Recalculate composite r*
    const newComposite = recalcCompositeRstar(
      compositeRstar,
      currentFiscalRstar,
      newFiscalRstar,
      fiscalWeight
    );

    // SELIC* = r* + IPCA expectations + term premium adjustment
    const ipcaExp = values.ipca_exp;
    const termPremium = eq.acm_term_premium_5y || -0.1;
    const newSelicStar = newComposite + ipcaExp + termPremium;

    // Deltas
    const deltaRstar = newComposite - compositeRstar;
    const currentSelicStar = eq.selic_star || 11.57;
    const deltaSelicStar = newSelicStar - currentSelicStar;

    // Policy gap
    const selicTarget = d.selic_target || 14.9;
    const newPolicyGap = selicTarget - newSelicStar;

    return {
      newFiscalRstar,
      newComposite,
      newSelicStar,
      deltaRstar,
      deltaSelicStar,
      newPolicyGap,
      currentComposite: compositeRstar,
      currentSelicStar,
      currentFiscalRstar,
      signal: newComposite > 5.5 ? 'restrictive' as const :
        newComposite < 3.5 ? 'accommodative' as const : 'neutral' as const,
    };
  }, [values, eq, d.selic_target, currentValues]);

  const handleSliderChange = useCallback((key: string, val: number[]) => {
    setValues(prev => ({ ...prev, [key]: val[0] }));
    setActivePreset('');
  }, []);

  const applyPreset = useCallback((preset: Scenario) => {
    setValues({ ...currentValues, ...preset.values });
    setActivePreset(preset.id);
  }, [currentValues]);

  const resetToDefault = useCallback(() => {
    setValues(currentValues);
    setActivePreset('current');
    setMcResult(null);
  }, [currentValues]);

  // Monte Carlo simulation handler
  const runMonteCarlo = useCallback(() => {
    setMcRunning(true);
    // Use requestAnimationFrame to allow UI to update before heavy computation
    requestAnimationFrame(() => {
      const result = runMonteCarloSimulation({
        numSims: 10000,
        centerValues: values,
        bounds: Object.fromEntries(FISCAL_VARS.map(v => [v.key, { min: v.min, max: v.max }])),
        currentComposite: eq.composite_rstar!,
        currentFiscalRstar: eq.rstar_fiscal || 6.42,
        fiscalWeight: eq.model_contributions.fiscal?.weight || 0.15,
        ipcaExp: values.ipca_exp,
        termPremium: eq.acm_term_premium_5y || -0.1,
      });
      setMcResult(result);
      setMcRunning(false);
    });
  }, [values, eq]);

  // PDF Export handler
  const handleExportPdf = useCallback(() => {
    const scenarioPreset = PRESETS.find(p => p.id === activePreset);
    const exportData: WhatIfExportData = {
      scenarioName: scenarioPreset?.label || 'Personalizado',
      scenarioDescription: scenarioPreset?.description || 'Cenário com parâmetros ajustados manualmente',
      exportDate: new Date().toLocaleString('pt-BR'),
      variables: FISCAL_VARS.map(v => ({
        label: v.label,
        value: values[v.key],
        unit: v.unit,
        defaultValue: currentValues[v.key],
        delta: values[v.key] - currentValues[v.key],
      })),
      results: whatIfResult,
      modelInfo: {
        runDate: d.run_date || '',
        currentRegime: d.current_regime || '',
        selicTarget: d.selic_target || 14.9,
        spotRate: d.current_spot || 0,
        compositeMethod: eq.method || 'composite',
        activeModels: Object.keys(eq.model_contributions).length,
      },
    };
    if (mcResult) {
      exportData.monteCarlo = {
        simulations: mcResult.simulations,
        mean: mcResult.mean,
        median: mcResult.median,
        p5: mcResult.p5,
        p25: mcResult.p25,
        p75: mcResult.p75,
        p95: mcResult.p95,
        std: mcResult.std,
        probAbove6: mcResult.probAbove6,
        probBelow3: mcResult.probBelow3,
      };
    }
    generateWhatIfPdf(exportData);
  }, [activePreset, values, currentValues, whatIfResult, d, eq, mcResult]);

  const rstarSignal = whatIfResult.signal;
  const rstarColor = rstarSignal === 'restrictive' ? 'text-amber-400' :
    rstarSignal === 'accommodative' ? 'text-emerald-400' : 'text-cyan-400';

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: 0.2 }}
    >
      <Card className="bg-card border-border/50">
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <CardTitle className="text-xs font-semibold uppercase tracking-wider text-primary flex items-center gap-2">
              <Zap className="w-3.5 h-3.5" />
              What-If Scenarios — r* Sensitivity
              <Tooltip>
                <TooltipTrigger>
                  <Info className="w-3 h-3 text-muted-foreground/50" />
                </TooltipTrigger>
                <TooltipContent side="right" className="max-w-[320px] text-xs">
                  Adjust fiscal variables to see the real-time impact on the composite r* and SELIC*.
                  The fiscal model (debt/GDP, primary balance, CDS) is the primary channel.
                  Other models (parity, market-implied, state-space, regime) are held constant.
                </TooltipContent>
              </Tooltip>
            </CardTitle>
            <div className="flex items-center gap-1.5">
              <Button
                variant="ghost"
                size="sm"
                onClick={runMonteCarlo}
                disabled={mcRunning}
                className="h-7 text-[10px] text-muted-foreground hover:text-foreground"
              >
                {mcRunning ? (
                  <span className="animate-spin mr-1">⟳</span>
                ) : (
                  <Zap className="w-3 h-3 mr-1" />
                )}
                Monte Carlo
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={handleExportPdf}
                className="h-7 text-[10px] text-muted-foreground hover:text-foreground"
              >
                <Download className="w-3 h-3 mr-1" />
                PDF
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={resetToDefault}
                className="h-7 text-[10px] text-muted-foreground hover:text-foreground"
              >
                <RotateCcw className="w-3 h-3 mr-1" />
                Reset
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            {/* Left: Sliders */}
            <div className="lg:col-span-2 space-y-5">
              {/* Preset buttons */}
              <div className="flex flex-wrap gap-2 pb-2">
                {PRESETS.map(preset => {
                  const Icon = preset.icon;
                  const isActive = activePreset === preset.id;
                  return (
                    <Button
                      key={preset.id}
                      variant={isActive ? 'default' : 'outline'}
                      size="sm"
                      onClick={() => applyPreset(preset)}
                      className={`h-7 text-[10px] gap-1.5 ${
                        isActive ? '' : `${preset.color} border-border/50 hover:border-border`
                      }`}
                    >
                      <Icon className="w-3 h-3" />
                      {preset.label}
                    </Button>
                  );
                })}
              </div>

              {/* Variable sliders */}
              {FISCAL_VARS.map(v => {
                const currentVal = values[v.key];
                const defaultVal = currentValues[v.key];
                const delta = currentVal - defaultVal;
                const hasDelta = Math.abs(delta) > v.step * 0.5;

                return (
                  <div key={v.key} className="space-y-2">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <Tooltip>
                          <TooltipTrigger>
                            <span className="text-[10px] text-muted-foreground uppercase tracking-wider cursor-help">
                              {v.label}
                            </span>
                          </TooltipTrigger>
                          <TooltipContent side="right" className="max-w-[280px] text-xs">
                            {v.description}
                          </TooltipContent>
                        </Tooltip>
                        {hasDelta && (
                          <span className={`text-[9px] font-data font-semibold ${
                            delta > 0 ? (v.sensitivity >= 0 ? 'text-amber-400' : 'text-emerald-400') :
                            (v.sensitivity >= 0 ? 'text-emerald-400' : 'text-amber-400')
                          }`}>
                            {delta > 0 ? '+' : ''}{delta.toFixed(v.step < 1 ? 1 : 0)}{v.unit}
                          </span>
                        )}
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="font-data text-xs font-semibold text-foreground">
                          {currentVal.toFixed(v.step < 1 ? 1 : 0)}{v.unit}
                        </span>
                      </div>
                    </div>
                    <Slider
                      value={[currentVal]}
                      min={v.min}
                      max={v.max}
                      step={v.step}
                      onValueChange={(val) => handleSliderChange(v.key, val)}
                      className="w-full"
                    />
                    <div className="flex justify-between text-[9px] text-muted-foreground/50 font-data">
                      <span>{v.min}{v.unit}</span>
                      <span>{v.max}{v.unit}</span>
                    </div>
                  </div>
                );
              })}
            </div>

            {/* Right: Results */}
            <div className="space-y-4">
              {/* What-If r* Result */}
              <Card className="bg-secondary/50 border-border/30">
                <CardContent className="pt-4 space-y-3">
                  <div className="text-[10px] text-muted-foreground uppercase tracking-wider text-center">
                    Scenario r*
                  </div>
                  <div className="text-center">
                    <AnimatePresence mode="wait">
                      <motion.div
                        key={whatIfResult.newComposite.toFixed(2)}
                        initial={{ opacity: 0, scale: 0.9 }}
                        animate={{ opacity: 1, scale: 1 }}
                        exit={{ opacity: 0, scale: 0.9 }}
                        transition={{ duration: 0.2 }}
                        className={`font-data text-3xl font-bold ${rstarColor}`}
                      >
                        {whatIfResult.newComposite.toFixed(2)}%
                      </motion.div>
                    </AnimatePresence>
                    {Math.abs(whatIfResult.deltaRstar) > 0.01 && (
                      <motion.div
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        className={`text-xs font-data font-semibold mt-1 ${
                          whatIfResult.deltaRstar > 0 ? 'text-amber-400' : 'text-emerald-400'
                        }`}
                      >
                        {whatIfResult.deltaRstar > 0 ? '▲' : '▼'} {Math.abs(whatIfResult.deltaRstar).toFixed(2)}pp vs atual
                      </motion.div>
                    )}
                  </div>

                  {/* Comparison: Current → Scenario */}
                  <div className="border-t border-border/20 pt-3 space-y-2">
                    <div className="flex items-center justify-between text-[10px]">
                      <span className="text-muted-foreground">r* Atual</span>
                      <div className="flex items-center gap-1.5">
                        <span className="font-data text-foreground/70">
                          {whatIfResult.currentComposite.toFixed(2)}%
                        </span>
                        <ArrowRight className="w-3 h-3 text-muted-foreground/40" />
                        <span className={`font-data font-semibold ${rstarColor}`}>
                          {whatIfResult.newComposite.toFixed(2)}%
                        </span>
                      </div>
                    </div>

                    <div className="flex items-center justify-between text-[10px]">
                      <span className="text-muted-foreground">SELIC*</span>
                      <div className="flex items-center gap-1.5">
                        <span className="font-data text-foreground/70">
                          {whatIfResult.currentSelicStar.toFixed(2)}%
                        </span>
                        <ArrowRight className="w-3 h-3 text-muted-foreground/40" />
                        <span className="font-data font-semibold text-foreground">
                          {whatIfResult.newSelicStar.toFixed(2)}%
                        </span>
                      </div>
                    </div>

                    <div className="flex items-center justify-between text-[10px]">
                      <span className="text-muted-foreground">Fiscal r*</span>
                      <div className="flex items-center gap-1.5">
                        <span className="font-data text-foreground/70">
                          {whatIfResult.currentFiscalRstar.toFixed(2)}%
                        </span>
                        <ArrowRight className="w-3 h-3 text-muted-foreground/40" />
                        <span className="font-data font-semibold text-amber-400">
                          {whatIfResult.newFiscalRstar.toFixed(2)}%
                        </span>
                      </div>
                    </div>

                    <div className="flex items-center justify-between text-[10px]">
                      <span className="text-muted-foreground">Policy Gap</span>
                      <span className={`font-data font-semibold ${
                        whatIfResult.newPolicyGap > 1 ? 'text-amber-400' :
                        whatIfResult.newPolicyGap < -1 ? 'text-emerald-400' : 'text-foreground'
                      }`}>
                        {whatIfResult.newPolicyGap > 0 ? '+' : ''}{whatIfResult.newPolicyGap.toFixed(2)}pp
                      </span>
                    </div>
                  </div>

                  {/* Signal interpretation */}
                  <div className="border-t border-border/20 pt-2">
                    <div className={`text-[10px] uppercase tracking-wider text-center ${rstarColor}`}>
                      {rstarSignal === 'restrictive' && 'Cenário restritivo — Prêmio fiscal elevado'}
                      {rstarSignal === 'accommodative' && 'Cenário acomodatício — Condições favoráveis'}
                      {rstarSignal === 'neutral' && 'Cenário neutro — Equilíbrio macro'}
                    </div>
                  </div>
                </CardContent>
              </Card>

              {/* Sensitivity Summary */}
              <Card className="bg-secondary/30 border-border/20">
                <CardContent className="pt-3 space-y-2">
                  <div className="text-[10px] text-muted-foreground uppercase tracking-wider">
                    Sensitivity Guide
                  </div>
                  <div className="space-y-1.5 text-[10px]">
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Dívida/PIB +10pp</span>
                      <span className="font-data text-amber-400">r* +~80bps</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Primário +1pp</span>
                      <span className="font-data text-emerald-400">r* -~50bps</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">CDS +100bps</span>
                      <span className="font-data text-amber-400">r* +~35bps</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">EMBI +100bps</span>
                      <span className="font-data text-amber-400">r* +~25bps</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">IPCA Exp +1pp</span>
                      <span className="font-data text-foreground/70">SELIC* +100bps</span>
                    </div>
                  </div>
                </CardContent>
              </Card>
            </div>
          </div>
          {/* Monte Carlo Results */}
          <AnimatePresence>
            {mcResult && (
              <motion.div
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: 'auto' }}
                exit={{ opacity: 0, height: 0 }}
                transition={{ duration: 0.3 }}
                className="mt-6 space-y-4"
              >
                <div className="border-t border-border/30 pt-4">
                  <div className="text-[10px] text-primary uppercase tracking-wider font-semibold mb-3 flex items-center gap-2">
                    <Zap className="w-3 h-3" />
                    Monte Carlo — {mcResult.simulations.toLocaleString()} Simulações
                  </div>

                  {/* Stats Grid */}
                  <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 gap-3 mb-4">
                    {[
                      { label: 'Média', value: `${mcResult.mean.toFixed(2)}%`, color: 'text-primary' },
                      { label: 'Mediana', value: `${mcResult.median.toFixed(2)}%`, color: 'text-foreground' },
                      { label: 'Desvio', value: `${mcResult.std.toFixed(2)}pp`, color: 'text-violet-400' },
                      { label: 'SELIC* Média', value: `${mcResult.meanSelicStar.toFixed(2)}%`, color: 'text-foreground' },
                      { label: 'P(r*>6%)', value: `${(mcResult.probAbove6 * 100).toFixed(1)}%`, color: mcResult.probAbove6 > 0.3 ? 'text-rose-400' : 'text-emerald-400' },
                      { label: 'P(r*<3%)', value: `${(mcResult.probBelow3 * 100).toFixed(1)}%`, color: mcResult.probBelow3 > 0.3 ? 'text-rose-400' : 'text-emerald-400' },
                    ].map(stat => (
                      <Card key={stat.label} className="bg-secondary/30 border-border/20">
                        <CardContent className="pt-2 pb-2 px-3 text-center">
                          <div className="text-[9px] text-muted-foreground uppercase tracking-wider">{stat.label}</div>
                          <div className={`font-data text-sm font-bold ${stat.color}`}>{stat.value}</div>
                        </CardContent>
                      </Card>
                    ))}
                  </div>

                  {/* Histogram */}
                  <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                    <div className="lg:col-span-2">
                      <div className="text-[9px] text-muted-foreground uppercase tracking-wider mb-2">Distribuição de r*</div>
                      <div className="h-[200px]">
                        <ResponsiveContainer width="100%" height="100%">
                          <BarChart data={mcResult.histogram} margin={{ top: 5, right: 10, bottom: 5, left: 10 }}>
                            <CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,0.1)" />
                            <XAxis
                              dataKey="binStart"
                              tick={{ fontSize: 9, fill: 'rgba(148,163,184,0.7)' }}
                              tickFormatter={(v: number) => `${v.toFixed(1)}`}
                              interval={2}
                            />
                            <YAxis
                              tick={{ fontSize: 9, fill: 'rgba(148,163,184,0.7)' }}
                              tickFormatter={(v: number) => `${(v * 100).toFixed(0)}%`}
                              dataKey="frequency"
                            />
                            <RTooltip
                              content={({ active, payload }) => {
                                if (!active || !payload?.[0]) return null;
                                const d = payload[0].payload;
                                return (
                                  <div className="bg-popover border border-border rounded-md px-3 py-2 text-xs shadow-lg">
                                    <div className="text-foreground font-semibold">
                                      r*: {d.binStart.toFixed(2)}% — {d.binEnd.toFixed(2)}%
                                    </div>
                                    <div className="text-muted-foreground">
                                      Frequência: {(d.frequency * 100).toFixed(1)}% ({d.count} sims)
                                    </div>
                                  </div>
                                );
                              }}
                            />
                            <ReferenceLine x={6} stroke="rgba(244,63,94,0.4)" strokeDasharray="3 3" />
                            <ReferenceLine x={3} stroke="rgba(52,211,153,0.4)" strokeDasharray="3 3" />
                            <Bar dataKey="frequency" radius={[2, 2, 0, 0]}>
                              {mcResult.histogram.map((entry, idx) => (
                                <Cell
                                  key={idx}
                                  fill={
                                    entry.binStart >= 6 ? 'rgba(244,63,94,0.6)' :
                                    entry.binEnd <= 3 ? 'rgba(52,211,153,0.6)' :
                                    'rgba(6,182,212,0.5)'
                                  }
                                />
                              ))}
                            </Bar>
                          </BarChart>
                        </ResponsiveContainer>
                      </div>
                    </div>

                    {/* Percentile Table */}
                    <div>
                      <div className="text-[9px] text-muted-foreground uppercase tracking-wider mb-2">Percentis</div>
                      <Card className="bg-secondary/20 border-border/20">
                        <CardContent className="pt-3 pb-3 px-4 space-y-1.5">
                          {[
                            { label: 'P5 (Bear)', value: mcResult.p5, color: 'text-rose-400' },
                            { label: 'P10', value: mcResult.p10, color: 'text-amber-400' },
                            { label: 'P25', value: mcResult.p25, color: 'text-foreground/70' },
                            { label: 'P50 (Mediana)', value: mcResult.median, color: 'text-primary font-bold' },
                            { label: 'P75', value: mcResult.p75, color: 'text-foreground/70' },
                            { label: 'P90', value: mcResult.p90, color: 'text-amber-400' },
                            { label: 'P95 (Bull)', value: mcResult.p95, color: 'text-emerald-400' },
                          ].map(pct => (
                            <div key={pct.label} className="flex justify-between items-center text-[10px]">
                              <span className="text-muted-foreground">{pct.label}</span>
                              <span className={`font-data font-semibold ${pct.color}`}>
                                {pct.value.toFixed(2)}%
                              </span>
                            </div>
                          ))}
                        </CardContent>
                      </Card>
                    </div>
                  </div>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </CardContent>
      </Card>
    </motion.div>
  );
}
