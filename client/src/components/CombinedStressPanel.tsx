/**
 * CombinedStressPanel — Combined Fiscal + External Shock Scenarios
 *
 * Preset scenarios that combine multiple shocks simultaneously and show
 * the cross-asset impact on DOL Futuro (Câmbio), DI curve, r*, and EMBI.
 * Includes transmission chain visualization: Fiscal → CDS → EMBI → FX → DI
 */

import { useState, useMemo, useCallback } from 'react';
import { MacroDashboard } from '@/hooks/useModelData';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { Button } from '@/components/ui/button';
import { motion, AnimatePresence } from 'framer-motion';
import {
  AlertTriangle, Zap, TrendingUp, TrendingDown, ArrowRight,
  Info, Shield, Flame, Globe, Building2
} from 'lucide-react';

interface Props {
  dashboard: MacroDashboard;
}

/** Combined stress scenario definition */
interface CombinedScenario {
  id: string;
  label: string;
  icon: React.ReactNode;
  severity: 'moderate' | 'severe' | 'extreme';
  description: string;
  category: string;
  // Shock magnitudes
  shocks: {
    debt_gdp_delta: number;      // pp change
    primary_balance_delta: number; // pp change
    cds_delta: number;            // bps change
    embi_delta: number;           // bps change
    vix_delta: number;            // points change
    dxy_delta: number;            // % change
    ipca_exp_delta: number;       // pp change
    ust10y_delta: number;         // pp change
    selic_delta: number;          // pp change (BCB reaction)
  };
  // Historical reference
  reference?: string;
}

const SCENARIOS: CombinedScenario[] = [
  {
    id: 'em_crisis_fiscal',
    label: 'EM Crisis + Fiscal Expansion',
    icon: <Globe className="w-4 h-4" />,
    severity: 'extreme',
    category: 'Combined',
    description: 'Crise em emergentes (flight to quality) combinada com expansão fiscal doméstica. Duplo choque: externo + fiscal.',
    shocks: {
      debt_gdp_delta: 8,
      primary_balance_delta: -2.5,
      cds_delta: 200,
      embi_delta: 250,
      vix_delta: 15,
      dxy_delta: 8,
      ipca_exp_delta: 2.0,
      ust10y_delta: -0.5,
      selic_delta: 3.0,
    },
    reference: 'Inspirado em 2015 (Dilma) + 2018 (Turquia/Argentina)',
  },
  {
    id: 'taper_tantrum',
    label: 'Taper Tantrum 2.0',
    icon: <TrendingUp className="w-4 h-4" />,
    severity: 'severe',
    category: 'External',
    description: 'Fed sinaliza aperto agressivo. UST 10Y sobe 150bps, DXY fortalece, EM sofrem outflows.',
    shocks: {
      debt_gdp_delta: 2,
      primary_balance_delta: -0.5,
      cds_delta: 80,
      embi_delta: 120,
      vix_delta: 10,
      dxy_delta: 6,
      ipca_exp_delta: 0.8,
      ust10y_delta: 1.5,
      selic_delta: 1.5,
    },
    reference: 'Referência: Taper Tantrum 2013 (UST +130bps, USDBRL +20%)',
  },
  {
    id: 'lula_fiscal_2',
    label: 'Fiscal Dominance',
    icon: <Building2 className="w-4 h-4" />,
    severity: 'severe',
    category: 'Fiscal',
    description: 'Dominância fiscal: governo abandona arcabouço, déficit primário atinge -4%, dívida/PIB acelera.',
    shocks: {
      debt_gdp_delta: 12,
      primary_balance_delta: -3.5,
      cds_delta: 150,
      embi_delta: 180,
      vix_delta: 5,
      dxy_delta: 2,
      ipca_exp_delta: 2.5,
      ust10y_delta: 0,
      selic_delta: 4.0,
    },
    reference: 'Inspirado em 2015-16 (Dilma II) + 2024 (pacote fiscal)',
  },
  {
    id: 'covid_v2',
    label: 'Pandemia / Black Swan',
    icon: <AlertTriangle className="w-4 h-4" />,
    severity: 'extreme',
    category: 'Systemic',
    description: 'Choque sistêmico global: VIX >40, flight to quality, colapso de commodities, fiscal emergencial.',
    shocks: {
      debt_gdp_delta: 15,
      primary_balance_delta: -5.0,
      cds_delta: 300,
      embi_delta: 350,
      vix_delta: 25,
      dxy_delta: 10,
      ipca_exp_delta: 1.5,
      ust10y_delta: -1.0,
      selic_delta: -3.0,
    },
    reference: 'Referência: COVID Mar/2020 (VIX 82, USDBRL 5.90)',
  },
  {
    id: 'goldilocks',
    label: 'Goldilocks + Consolidação',
    icon: <Shield className="w-4 h-4" />,
    severity: 'moderate',
    category: 'Positive',
    description: 'Cenário benigno: Fed corta juros, EM recebem fluxo, Brasil consolida fiscal.',
    shocks: {
      debt_gdp_delta: -3,
      primary_balance_delta: 1.5,
      cds_delta: -50,
      embi_delta: -60,
      vix_delta: -5,
      dxy_delta: -4,
      ipca_exp_delta: -0.5,
      ust10y_delta: -0.8,
      selic_delta: -2.0,
    },
    reference: 'Inspirado em 2017 (Temer) + 2019 (reforma previdência)',
  },
];

/** Calculate cross-asset impact from combined shocks */
function calculateImpact(dashboard: MacroDashboard, scenario: CombinedScenario) {
  const s = scenario.shocks;
  const eq = dashboard.equilibrium;

  // Current values
  const currentSpot = dashboard.current_spot;
  const currentDI1Y = dashboard.di_1y;
  const currentDI2Y = dashboard.di_2y;
  const currentDI5Y = dashboard.di_5y;
  const currentDI10Y = dashboard.di_10y;
  const currentEMBI = dashboard.embi_spread;
  const currentVIX = dashboard.vix;
  const currentDXY = dashboard.dxy;
  const currentSelic = dashboard.selic_target;
  const currentRstar = eq?.composite_rstar || 4.75;
  const currentSelicStar = eq?.selic_star || 11.57;

  // FX impact: EMBI + DXY + VIX → USDBRL
  // Empirical elasticities (from BEER model)
  const embiImpactFX = (s.embi_delta / 100) * 0.12;  // +100bps EMBI → +12% USDBRL
  const dxyImpactFX = (s.dxy_delta / 100) * 1.2;     // +1% DXY → +1.2% USDBRL
  const vixImpactFX = (s.vix_delta / 10) * 0.04;     // +10pts VIX → +4% USDBRL
  const fxPctChange = embiImpactFX + dxyImpactFX + vixImpactFX;
  const newSpot = currentSpot * (1 + fxPctChange);

  // DI curve impact: SELIC + risk premium + term premium
  const newSelic = currentSelic + s.selic_delta;
  const riskPremiumDelta = s.cds_delta / 100 * 0.5; // CDS → DI risk premium
  const newDI1Y = currentDI1Y + s.selic_delta * 0.8 + riskPremiumDelta * 0.3;
  const newDI2Y = currentDI2Y + s.selic_delta * 0.6 + riskPremiumDelta * 0.5;
  const newDI5Y = currentDI5Y + s.selic_delta * 0.4 + riskPremiumDelta * 0.7;
  const newDI10Y = currentDI10Y + s.selic_delta * 0.3 + riskPremiumDelta * 0.8;

  // r* impact (fiscal channel)
  const debtGdpNew = 78 + s.debt_gdp_delta; // Assume current ~78%
  const debtPremium = Math.max(0, (debtGdpNew - 60) * 0.08);
  const primaryNew = -0.5 + s.primary_balance_delta;
  const fiscalPremium = Math.max(0, -primaryNew * 0.50);
  const cdsNew = 150 + s.cds_delta;
  const cdsPremium = (cdsNew / 100) * 0.35;
  const newFiscalRstar = 4.0 + debtPremium * 0.4 + fiscalPremium * 0.3 + cdsPremium * 0.3;
  const fiscalWeight = eq?.model_contributions?.fiscal?.weight || 0.15;
  const rstarDelta = (newFiscalRstar - (eq?.rstar_fiscal || 6.42)) * fiscalWeight;
  const newRstar = currentRstar + rstarDelta;
  const newSelicStar = newRstar + (5 + s.ipca_exp_delta) + (eq?.acm_term_premium_5y || -0.1);

  // EMBI
  const newEMBI = currentEMBI + s.embi_delta;

  return {
    fx: {
      current: currentSpot,
      stressed: Math.round(newSpot * 1000) / 1000,
      pctChange: Math.round(fxPctChange * 10000) / 100,
    },
    di: {
      di1y: { current: currentDI1Y, stressed: Math.round(newDI1Y * 100) / 100 },
      di2y: { current: currentDI2Y, stressed: Math.round(newDI2Y * 100) / 100 },
      di5y: { current: currentDI5Y, stressed: Math.round(newDI5Y * 100) / 100 },
      di10y: { current: currentDI10Y, stressed: Math.round(newDI10Y * 100) / 100 },
    },
    selic: { current: currentSelic, stressed: Math.round(newSelic * 100) / 100 },
    rstar: {
      current: currentRstar,
      stressed: Math.round(newRstar * 100) / 100,
      delta: Math.round(rstarDelta * 100) / 100,
    },
    selicStar: {
      current: currentSelicStar,
      stressed: Math.round(newSelicStar * 100) / 100,
    },
    embi: { current: currentEMBI, stressed: Math.round(newEMBI) },
    vix: { current: currentVIX, stressed: Math.round((currentVIX + s.vix_delta) * 10) / 10 },
    dxy: { current: currentDXY, stressed: Math.round((currentDXY * (1 + s.dxy_delta / 100)) * 100) / 100 },
  };
}

export function CombinedStressPanel({ dashboard }: Props) {
  const [activeScenario, setActiveScenario] = useState<string | null>(null);

  const scenario = useMemo(() =>
    SCENARIOS.find(s => s.id === activeScenario) || null,
    [activeScenario]
  );

  const impact = useMemo(() => {
    if (!scenario) return null;
    return calculateImpact(dashboard, scenario);
  }, [scenario, dashboard]);

  const severityColor = useCallback((severity: string) => {
    switch (severity) {
      case 'extreme': return 'text-rose-400 bg-rose-400/10 border-rose-400/30';
      case 'severe': return 'text-amber-400 bg-amber-400/10 border-amber-400/30';
      case 'moderate': return 'text-emerald-400 bg-emerald-400/10 border-emerald-400/30';
      default: return 'text-muted-foreground';
    }
  }, []);

  const deltaColor = (val: number, invert = false) => {
    const positive = invert ? val < 0 : val > 0;
    if (Math.abs(val) < 0.01) return 'text-muted-foreground';
    return positive ? 'text-amber-400' : 'text-emerald-400';
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: 0.15 }}
    >
      <Card className="bg-card border-border/50">
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <CardTitle className="text-xs font-semibold uppercase tracking-wider text-primary flex items-center gap-2">
              <Flame className="w-3.5 h-3.5" />
              Stress Testing — Cenários Combinados
              <Tooltip>
                <TooltipTrigger>
                  <Info className="w-3 h-3 text-muted-foreground/50" />
                </TooltipTrigger>
                <TooltipContent side="right" className="max-w-[320px] text-xs">
                  Cenários que combinam choques fiscais e externos simultaneamente.
                  Mostra o impacto cruzado em FX, DI, r*, EMBI e SELIC.
                  Elasticidades baseadas em regressões históricas do modelo BEER.
                </TooltipContent>
              </Tooltip>
            </CardTitle>
          </div>
        </CardHeader>
        <CardContent>
          {/* Scenario Selector */}
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2 mb-5">
            {SCENARIOS.map(s => (
              <Button
                key={s.id}
                variant={activeScenario === s.id ? 'default' : 'outline'}
                size="sm"
                onClick={() => setActiveScenario(activeScenario === s.id ? null : s.id)}
                className={`h-auto py-2 px-3 text-left flex flex-col items-start gap-1 ${
                  activeScenario === s.id ? '' : 'bg-transparent'
                }`}
              >
                <div className="flex items-center gap-1.5 text-[10px] font-semibold">
                  {s.icon}
                  <span className="truncate">{s.label}</span>
                </div>
                <span className={`text-[9px] px-1.5 py-0.5 rounded-full border ${severityColor(s.severity)}`}>
                  {s.severity}
                </span>
              </Button>
            ))}
          </div>

          {/* Impact Display */}
          <AnimatePresence mode="wait">
            {scenario && impact && (
              <motion.div
                key={scenario.id}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -10 }}
                transition={{ duration: 0.25 }}
                className="space-y-4"
              >
                {/* Scenario Description */}
                <div className="bg-secondary/30 rounded-lg p-3 border border-border/20">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="text-xs font-semibold text-foreground">{scenario.label}</div>
                      <div className="text-[10px] text-muted-foreground mt-1">{scenario.description}</div>
                      {scenario.reference && (
                        <div className="text-[9px] text-muted-foreground/60 mt-1 italic">{scenario.reference}</div>
                      )}
                    </div>
                    <span className={`text-[9px] px-2 py-1 rounded-full border whitespace-nowrap ${severityColor(scenario.severity)}`}>
                      {scenario.category}
                    </span>
                  </div>
                </div>

                {/* Transmission Chain */}
                <div className="flex items-center justify-center gap-1 text-[9px] text-muted-foreground py-1 flex-wrap">
                  <span className="text-amber-400 font-semibold">Fiscal</span>
                  <ArrowRight className="w-3 h-3" />
                  <span>CDS</span>
                  <ArrowRight className="w-3 h-3" />
                  <span>EMBI</span>
                  <ArrowRight className="w-3 h-3" />
                  <span className="text-primary font-semibold">FX</span>
                  <ArrowRight className="w-3 h-3" />
                  <span className="text-violet-400 font-semibold">DI Curve</span>
                  <ArrowRight className="w-3 h-3" />
                  <span className="text-emerald-400 font-semibold">r*</span>
                </div>

                {/* Impact Grid */}
                <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
                  {/* FX */}
                  <Card className="bg-secondary/20 border-border/20">
                    <CardContent className="pt-3 pb-3 px-4">
                      <div className="text-[9px] text-muted-foreground uppercase tracking-wider">USDBRL</div>
                      <div className="flex items-baseline gap-2 mt-1">
                        <span className="font-data text-lg font-bold text-foreground">{impact.fx.stressed.toFixed(3)}</span>
                        <span className={`font-data text-xs ${deltaColor(impact.fx.pctChange)}`}>
                          {impact.fx.pctChange > 0 ? '+' : ''}{impact.fx.pctChange.toFixed(1)}%
                        </span>
                      </div>
                      <div className="text-[9px] text-muted-foreground/60">de {impact.fx.current.toFixed(3)}</div>
                    </CardContent>
                  </Card>

                  {/* SELIC */}
                  <Card className="bg-secondary/20 border-border/20">
                    <CardContent className="pt-3 pb-3 px-4">
                      <div className="text-[9px] text-muted-foreground uppercase tracking-wider">SELIC Target</div>
                      <div className="flex items-baseline gap-2 mt-1">
                        <span className="font-data text-lg font-bold text-foreground">{impact.selic.stressed.toFixed(1)}%</span>
                        <span className={`font-data text-xs ${deltaColor(scenario.shocks.selic_delta)}`}>
                          {scenario.shocks.selic_delta > 0 ? '+' : ''}{scenario.shocks.selic_delta.toFixed(1)}pp
                        </span>
                      </div>
                      <div className="text-[9px] text-muted-foreground/60">de {impact.selic.current.toFixed(1)}%</div>
                    </CardContent>
                  </Card>

                  {/* r* */}
                  <Card className="bg-secondary/20 border-border/20">
                    <CardContent className="pt-3 pb-3 px-4">
                      <div className="text-[9px] text-muted-foreground uppercase tracking-wider">r* Composto</div>
                      <div className="flex items-baseline gap-2 mt-1">
                        <span className="font-data text-lg font-bold text-primary">{impact.rstar.stressed.toFixed(2)}%</span>
                        <span className={`font-data text-xs ${deltaColor(impact.rstar.delta)}`}>
                          {impact.rstar.delta > 0 ? '+' : ''}{impact.rstar.delta.toFixed(2)}pp
                        </span>
                      </div>
                      <div className="text-[9px] text-muted-foreground/60">de {impact.rstar.current.toFixed(2)}%</div>
                    </CardContent>
                  </Card>

                  {/* EMBI */}
                  <Card className="bg-secondary/20 border-border/20">
                    <CardContent className="pt-3 pb-3 px-4">
                      <div className="text-[9px] text-muted-foreground uppercase tracking-wider">EMBI Spread</div>
                      <div className="flex items-baseline gap-2 mt-1">
                        <span className="font-data text-lg font-bold text-foreground">{impact.embi.stressed} bps</span>
                        <span className={`font-data text-xs ${deltaColor(scenario.shocks.embi_delta)}`}>
                          {scenario.shocks.embi_delta > 0 ? '+' : ''}{scenario.shocks.embi_delta}
                        </span>
                      </div>
                      <div className="text-[9px] text-muted-foreground/60">de {impact.embi.current} bps</div>
                    </CardContent>
                  </Card>
                </div>

                {/* DI Curve Impact */}
                <Card className="bg-secondary/20 border-border/20">
                  <CardContent className="pt-3 pb-3 px-4">
                    <div className="text-[9px] text-muted-foreground uppercase tracking-wider mb-3">Curva DI — Impacto do Cenário</div>
                    <div className="grid grid-cols-4 gap-4">
                      {[
                        { label: 'DI 1Y', ...impact.di.di1y },
                        { label: 'DI 2Y', ...impact.di.di2y },
                        { label: 'DI 5Y', ...impact.di.di5y },
                        { label: 'DI 10Y', ...impact.di.di10y },
                      ].map(pt => {
                        const delta = pt.stressed - pt.current;
                        return (
                          <div key={pt.label} className="text-center">
                            <div className="text-[9px] text-muted-foreground">{pt.label}</div>
                            <div className="font-data text-sm font-bold text-foreground mt-0.5">{pt.stressed.toFixed(2)}%</div>
                            <div className={`font-data text-[10px] ${deltaColor(delta)}`}>
                              {delta > 0 ? '+' : ''}{delta.toFixed(0)}bps
                            </div>
                            {/* Visual bar */}
                            <div className="mt-1 h-1.5 bg-secondary/50 rounded-full overflow-hidden">
                              <div
                                className={`h-full rounded-full transition-all ${delta > 0 ? 'bg-amber-400/60' : 'bg-emerald-400/60'}`}
                                style={{ width: `${Math.min(100, Math.abs(delta) / 5 * 100)}%` }}
                              />
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </CardContent>
                </Card>

                {/* Shock Components Table */}
                <Card className="bg-secondary/20 border-border/20">
                  <CardContent className="pt-3 pb-3 px-4">
                    <div className="text-[9px] text-muted-foreground uppercase tracking-wider mb-2">Componentes do Choque</div>
                    <div className="grid grid-cols-3 sm:grid-cols-5 gap-x-4 gap-y-2 text-[10px]">
                      {[
                        { label: 'Dívida/PIB', value: `${scenario.shocks.debt_gdp_delta > 0 ? '+' : ''}${scenario.shocks.debt_gdp_delta}pp`, color: deltaColor(scenario.shocks.debt_gdp_delta) },
                        { label: 'Primário', value: `${scenario.shocks.primary_balance_delta > 0 ? '+' : ''}${scenario.shocks.primary_balance_delta}pp`, color: deltaColor(scenario.shocks.primary_balance_delta, true) },
                        { label: 'CDS 5Y', value: `${scenario.shocks.cds_delta > 0 ? '+' : ''}${scenario.shocks.cds_delta}bps`, color: deltaColor(scenario.shocks.cds_delta) },
                        { label: 'VIX', value: `${scenario.shocks.vix_delta > 0 ? '+' : ''}${scenario.shocks.vix_delta}pts`, color: deltaColor(scenario.shocks.vix_delta) },
                        { label: 'DXY', value: `${scenario.shocks.dxy_delta > 0 ? '+' : ''}${scenario.shocks.dxy_delta}%`, color: deltaColor(scenario.shocks.dxy_delta) },
                        { label: 'IPCA Exp', value: `${scenario.shocks.ipca_exp_delta > 0 ? '+' : ''}${scenario.shocks.ipca_exp_delta}pp`, color: deltaColor(scenario.shocks.ipca_exp_delta) },
                        { label: 'UST 10Y', value: `${scenario.shocks.ust10y_delta > 0 ? '+' : ''}${scenario.shocks.ust10y_delta}pp`, color: deltaColor(scenario.shocks.ust10y_delta) },
                        { label: 'SELIC (BCB)', value: `${scenario.shocks.selic_delta > 0 ? '+' : ''}${scenario.shocks.selic_delta}pp`, color: deltaColor(scenario.shocks.selic_delta) },
                        { label: 'EMBI', value: `${scenario.shocks.embi_delta > 0 ? '+' : ''}${scenario.shocks.embi_delta}bps`, color: deltaColor(scenario.shocks.embi_delta) },
                      ].map(item => (
                        <div key={item.label} className="flex justify-between">
                          <span className="text-muted-foreground">{item.label}</span>
                          <span className={`font-data font-semibold ${item.color}`}>{item.value}</span>
                        </div>
                      ))}
                    </div>
                  </CardContent>
                </Card>
              </motion.div>
            )}
          </AnimatePresence>

          {!activeScenario && (
            <div className="text-center py-6 text-muted-foreground/50 text-xs">
              Selecione um cenário acima para ver o impacto cruzado em FX, DI, r* e EMBI
            </div>
          )}
        </CardContent>
      </Card>
    </motion.div>
  );
}
