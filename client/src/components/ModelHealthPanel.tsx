/**
 * ModelHealthPanel — Consolidated Model Health Score (0-100)
 * 
 * Combines four sub-scores:
 *   1. Stability (40%): Weighted avg of composite scores, robust features count more
 *   2. Alerts (25%): Penalty for critical/warning, bonus for positive
 *   3. Diversification (20%): Feature coverage across instruments
 *   4. Consistency (15%): Cross-instrument agreement on feature classifications
 */

import { useMemo } from 'react';
import {
  Activity,
  Shield,
  AlertTriangle,
  Layers,
  GitBranch,
  TrendingUp,
  TrendingDown,
  Minus,
  CheckCircle2,
  XCircle,
  Info,
  Zap,
} from 'lucide-react';

// ── Types ──────────────────────────────────────────────────────────────────

interface FeatureSelectionResult {
  instrument?: string;
  total_features: number;
  stability?: {
    composite_score?: Record<string, number>;
    classification: Record<string, string>;
    thresholds?: { robust: number; moderate: number };
  };
  interactions?: {
    n_tested: number;
    n_confirmed: number;
    confirmed: string[];
  };
  alerts?: Array<{
    type: 'critical' | 'warning' | 'info';
    feature: string;
    instrument: string;
    transition?: string;
    message: string;
  }>;
  final: {
    n_features: number;
    features: string[];
    reduction_pct: number;
  };
  lasso: { n_selected: number };
  boruta: { n_confirmed: number };
}

interface SubScore {
  value: number;       // 0-100
  weight: number;      // 0-1
  label: string;
  icon: React.ReactNode;
  details: string;
  status: 'excellent' | 'good' | 'warning' | 'critical';
}

interface InstrumentHealth {
  name: string;
  score: number;
  robustCount: number;
  moderateCount: number;
  unstableCount: number;
  totalFeatures: number;
  avgComposite: number;
  alertsCritical: number;
  alertsWarning: number;
  alertsPositive: number;
}

interface HealthDiagnostic {
  severity: 'critical' | 'warning' | 'info' | 'positive';
  message: string;
  action: string;
}

interface ModelHealthPanelProps {
  data: Record<string, FeatureSelectionResult> | null | undefined;
}

// ── Scoring Engine ─────────────────────────────────────────────────────────

function computeStabilityScore(instruments: InstrumentHealth[]): number {
  if (instruments.length === 0) return 0;
  
  let totalWeightedScore = 0;
  let totalWeight = 0;
  
  for (const inst of instruments) {
    const total = inst.robustCount + inst.moderateCount + inst.unstableCount;
    if (total === 0) continue;
    
    // Robust ratio contributes most, moderate partially, unstable penalizes
    const robustRatio = inst.robustCount / total;
    const moderateRatio = inst.moderateCount / total;
    const unstableRatio = inst.unstableCount / total;
    
    // Score: robust=100, moderate=60, unstable=20
    const instScore = robustRatio * 100 + moderateRatio * 60 + unstableRatio * 20;
    
    // Weight by avg composite score (instruments with higher scores matter more)
    const weight = Math.max(0.1, inst.avgComposite);
    totalWeightedScore += instScore * weight;
    totalWeight += weight;
  }
  
  return totalWeight > 0 ? Math.min(100, totalWeightedScore / totalWeight) : 0;
}

function computeAlertScore(instruments: InstrumentHealth[]): number {
  let totalCritical = 0;
  let totalWarning = 0;
  let totalPositive = 0;
  
  for (const inst of instruments) {
    totalCritical += inst.alertsCritical;
    totalWarning += inst.alertsWarning;
    totalPositive += inst.alertsPositive;
  }
  
  // Start at 80, penalize for critical (-15 each) and warning (-5 each), bonus for positive (+3 each)
  const score = 80 - (totalCritical * 15) - (totalWarning * 5) + (totalPositive * 3);
  return Math.max(0, Math.min(100, score));
}

function computeDiversificationScore(
  data: Record<string, FeatureSelectionResult>,
  instrumentNames: string[]
): number {
  // Count how many instruments each feature appears in (via classification)
  const featureCoverage: Record<string, number> = {};
  const featureRobust: Record<string, number> = {};
  
  for (const inst of instrumentNames) {
    const cls = data[inst]?.stability?.classification || {};
    for (const [feat, status] of Object.entries(cls)) {
      featureCoverage[feat] = (featureCoverage[feat] || 0) + 1;
      if (status === 'robust') {
        featureRobust[feat] = (featureRobust[feat] || 0) + 1;
      }
    }
  }
  
  const totalFeatures = Object.keys(featureCoverage).length;
  if (totalFeatures === 0) return 0;
  
  // Features in 3+ instruments = well diversified
  const wellDiversified = Object.values(featureCoverage).filter(c => c >= 3).length;
  // Features robust in 2+ instruments = very strong
  const strongFeatures = Object.values(featureRobust).filter(c => c >= 2).length;
  
  const diversificationRatio = wellDiversified / totalFeatures;
  const strengthRatio = strongFeatures / Math.max(1, totalFeatures);
  
  // 60% from diversification, 40% from strength
  return Math.min(100, (diversificationRatio * 60 + strengthRatio * 40) * 100);
}

function computeConsistencyScore(
  data: Record<string, FeatureSelectionResult>,
  instrumentNames: string[]
): number {
  // Measure how consistently features are classified across instruments
  const featureClassifications: Record<string, string[]> = {};
  
  for (const inst of instrumentNames) {
    const cls = data[inst]?.stability?.classification || {};
    for (const [feat, status] of Object.entries(cls)) {
      if (!featureClassifications[feat]) featureClassifications[feat] = [];
      featureClassifications[feat].push(status);
    }
  }
  
  // For features in 2+ instruments, check classification agreement
  let totalAgreement = 0;
  let totalPairs = 0;
  
  for (const classifications of Object.values(featureClassifications)) {
    if (classifications.length < 2) continue;
    
    for (let i = 0; i < classifications.length; i++) {
      for (let j = i + 1; j < classifications.length; j++) {
        totalPairs++;
        if (classifications[i] === classifications[j]) {
          totalAgreement++;
        } else if (
          // Adjacent classifications count as partial agreement
          (classifications[i] === 'robust' && classifications[j] === 'moderate') ||
          (classifications[i] === 'moderate' && classifications[j] === 'robust') ||
          (classifications[i] === 'moderate' && classifications[j] === 'unstable') ||
          (classifications[i] === 'unstable' && classifications[j] === 'moderate')
        ) {
          totalAgreement += 0.5;
        }
      }
    }
  }
  
  return totalPairs > 0 ? Math.min(100, (totalAgreement / totalPairs) * 100) : 50;
}

function getScoreStatus(score: number): 'excellent' | 'good' | 'warning' | 'critical' {
  if (score >= 75) return 'excellent';
  if (score >= 55) return 'good';
  if (score >= 35) return 'warning';
  return 'critical';
}

function getOverallLabel(score: number): string {
  if (score >= 80) return 'Excelente';
  if (score >= 65) return 'Bom';
  if (score >= 45) return 'Moderado';
  if (score >= 25) return 'Atenção';
  return 'Crítico';
}

function getOverallColor(score: number): string {
  if (score >= 80) return 'text-emerald-400';
  if (score >= 65) return 'text-cyan-400';
  if (score >= 45) return 'text-yellow-400';
  if (score >= 25) return 'text-orange-400';
  return 'text-red-400';
}

function getOverallBg(score: number): string {
  if (score >= 80) return 'from-emerald-500/20 to-emerald-500/5';
  if (score >= 65) return 'from-cyan-500/20 to-cyan-500/5';
  if (score >= 45) return 'from-yellow-500/20 to-yellow-500/5';
  if (score >= 25) return 'from-orange-500/20 to-orange-500/5';
  return 'from-red-500/20 to-red-500/5';
}

function getSubScoreColor(status: string): string {
  switch (status) {
    case 'excellent': return 'text-emerald-400';
    case 'good': return 'text-cyan-400';
    case 'warning': return 'text-yellow-400';
    case 'critical': return 'text-red-400';
    default: return 'text-slate-400';
  }
}

function getSubScoreBarColor(status: string): string {
  switch (status) {
    case 'excellent': return 'bg-emerald-500';
    case 'good': return 'bg-cyan-500';
    case 'warning': return 'bg-yellow-500';
    case 'critical': return 'bg-red-500';
    default: return 'bg-slate-500';
  }
}

function generateDiagnostics(
  subScores: SubScore[],
  instruments: InstrumentHealth[],
  data: Record<string, FeatureSelectionResult>,
  instrumentNames: string[]
): HealthDiagnostic[] {
  const diagnostics: HealthDiagnostic[] = [];
  
  // Check stability
  const stabilityScore = subScores.find(s => s.label === 'Estabilidade');
  if (stabilityScore && stabilityScore.value < 40) {
    diagnostics.push({
      severity: 'critical',
      message: 'Estabilidade das features muito baixa — modelo pode ser instável',
      action: 'Considere aumentar n_subsamples ou usar regularização mais forte (maior l1_ratio)'
    });
  }
  
  // Check for instruments with no robust features
  for (const inst of instruments) {
    if (inst.robustCount === 0 && inst.totalFeatures > 0) {
      diagnostics.push({
        severity: 'warning',
        message: `${inst.name.toUpperCase()} não possui features robustas`,
        action: `Revisar feature set para ${inst.name} — considere adicionar variáveis mais estáveis`
      });
    }
  }
  
  // Check alerts
  const totalCritical = instruments.reduce((s, i) => s + i.alertsCritical, 0);
  if (totalCritical > 0) {
    diagnostics.push({
      severity: 'critical',
      message: `${totalCritical} alerta(s) crítico(s) — features mudaram de Robust→Unstable`,
      action: 'Investigar possível mudança de regime macro — monitorar próximas 2-3 execuções'
    });
  }
  
  // Check diversification
  const diversificationScore = subScores.find(s => s.label === 'Diversificação');
  if (diversificationScore && diversificationScore.value < 30) {
    diagnostics.push({
      severity: 'warning',
      message: 'Baixa diversificação — poucas features compartilhadas entre instrumentos',
      action: 'Considere adicionar features macro globais que afetem múltiplos instrumentos'
    });
  }
  
  // Check consistency
  const consistencyScore = subScores.find(s => s.label === 'Consistência');
  if (consistencyScore && consistencyScore.value < 40) {
    diagnostics.push({
      severity: 'info',
      message: 'Baixa consistência — features classificadas diferentemente entre instrumentos',
      action: 'Isso pode ser normal se instrumentos têm drivers distintos (FX vs DI)'
    });
  }
  
  // Check interactions
  let totalConfirmed = 0;
  let totalTested = 0;
  for (const inst of instrumentNames) {
    totalConfirmed += data[inst]?.interactions?.n_confirmed || 0;
    totalTested += data[inst]?.interactions?.n_tested || 0;
  }
  if (totalConfirmed > 0) {
    diagnostics.push({
      severity: 'positive',
      message: `${totalConfirmed}/${totalTested} interações confirmadas — efeitos não-lineares capturados`,
      action: 'Interações validadas por Boruta estão integradas no ensemble'
    });
  }
  
  // Positive: high stability
  if (stabilityScore && stabilityScore.value >= 70) {
    diagnostics.push({
      severity: 'positive',
      message: 'Alta estabilidade — features robustas bem distribuídas',
      action: 'Modelo em boa forma — manter monitoramento regular'
    });
  }
  
  return diagnostics;
}

// ── Gauge Component ────────────────────────────────────────────────────────

function HealthGauge({ score, size = 200 }: { score: number; size?: number }) {
  const radius = (size - 20) / 2;
  const circumference = Math.PI * radius; // half circle
  const strokeWidth = 12;
  const progress = (score / 100) * circumference;
  
  const color = score >= 80 ? '#34d399' : score >= 65 ? '#22d3ee' : score >= 45 ? '#facc15' : score >= 25 ? '#fb923c' : '#f87171';
  const bgColor = '#1e293b';
  
  return (
    <div className="relative flex items-center justify-center" style={{ width: size, height: size * 0.6 }}>
      <svg
        width={size}
        height={size * 0.6}
        viewBox={`0 0 ${size} ${size * 0.6}`}
        className="overflow-visible"
      >
        {/* Background arc */}
        <path
          d={`M ${strokeWidth / 2 + 4} ${size * 0.55} A ${radius} ${radius} 0 0 1 ${size - strokeWidth / 2 - 4} ${size * 0.55}`}
          fill="none"
          stroke={bgColor}
          strokeWidth={strokeWidth}
          strokeLinecap="round"
        />
        {/* Progress arc */}
        <path
          d={`M ${strokeWidth / 2 + 4} ${size * 0.55} A ${radius} ${radius} 0 0 1 ${size - strokeWidth / 2 - 4} ${size * 0.55}`}
          fill="none"
          stroke={color}
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeDasharray={`${progress} ${circumference}`}
          className="transition-all duration-1000 ease-out"
        />
        {/* Score text */}
        <text
          x={size / 2}
          y={size * 0.42}
          textAnchor="middle"
          fill={color}
          fontSize={size * 0.22}
          fontWeight="bold"
          fontFamily="monospace"
        >
          {Math.round(score)}
        </text>
        <text
          x={size / 2}
          y={size * 0.56}
          textAnchor="middle"
          fill="#94a3b8"
          fontSize={size * 0.07}
          fontWeight="500"
        >
          / 100
        </text>
      </svg>
    </div>
  );
}

// ── Mini Gauge for instruments ─────────────────────────────────────────────

function MiniGauge({ score, size = 48 }: { score: number; size?: number }) {
  const color = score >= 75 ? '#34d399' : score >= 55 ? '#22d3ee' : score >= 35 ? '#facc15' : '#f87171';
  const pct = score / 100;
  
  return (
    <div className="relative" style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox="0 0 48 48">
        <circle cx="24" cy="24" r="20" fill="none" stroke="#1e293b" strokeWidth="4" />
        <circle
          cx="24" cy="24" r="20"
          fill="none"
          stroke={color}
          strokeWidth="4"
          strokeLinecap="round"
          strokeDasharray={`${pct * 125.6} 125.6`}
          transform="rotate(-90 24 24)"
          className="transition-all duration-700"
        />
        <text x="24" y="28" textAnchor="middle" fill={color} fontSize="13" fontWeight="bold" fontFamily="monospace">
          {Math.round(score)}
        </text>
      </svg>
    </div>
  );
}

// ── Main Component ─────────────────────────────────────────────────────────

export function ModelHealthPanel({ data }: ModelHealthPanelProps) {
  const { overallScore, subScores, instruments, diagnostics } = useMemo(() => {
    if (!data) return { overallScore: 0, subScores: [] as SubScore[], instruments: [] as InstrumentHealth[], diagnostics: [] as HealthDiagnostic[] };
    
    const instrumentNames = Object.keys(data).filter(k => k !== 'metadata');
    
    // Build per-instrument health
    const instrumentsHealth: InstrumentHealth[] = instrumentNames.map(name => {
      const inst = data[name];
      const cls = inst?.stability?.classification || {};
      const comp = inst?.stability?.composite_score || {};
      const alerts = inst?.alerts || [];
      
      const robustCount = Object.values(cls).filter(v => v === 'robust').length;
      const moderateCount = Object.values(cls).filter(v => v === 'moderate').length;
      const unstableCount = Object.values(cls).filter(v => v === 'unstable').length;
      
      const scores = Object.values(comp).filter(v => typeof v === 'number') as number[];
      const avgComposite = scores.length > 0 ? scores.reduce((a, b) => a + b, 0) / scores.length : 0;
      
      const alertsCritical = alerts.filter(a => a.type === 'critical').length;
      const alertsWarning = alerts.filter(a => a.type === 'warning').length;
      const alertsPositive = alerts.filter(a => a.type === 'info' || a.type === 'positive' as string).length;
      
      // Instrument score: weighted by classification distribution
      const total = robustCount + moderateCount + unstableCount;
      const instScore = total > 0
        ? (robustCount / total) * 100 + (moderateCount / total) * 55 + (unstableCount / total) * 15
        : 0;
      
      return {
        name,
        score: instScore,
        robustCount,
        moderateCount,
        unstableCount,
        totalFeatures: total,
        avgComposite,
        alertsCritical,
        alertsWarning,
        alertsPositive,
      };
    });
    
    // Compute sub-scores
    const stabilityValue = computeStabilityScore(instrumentsHealth);
    const alertsValue = computeAlertScore(instrumentsHealth);
    const diversificationValue = computeDiversificationScore(data, instrumentNames);
    const consistencyValue = computeConsistencyScore(data, instrumentNames);
    
    const subs: SubScore[] = [
      {
        value: stabilityValue,
        weight: 0.40,
        label: 'Estabilidade',
        icon: <Shield className="w-4 h-4" />,
        details: `Robustas: ${instrumentsHealth.reduce((s, i) => s + i.robustCount, 0)} | Moderadas: ${instrumentsHealth.reduce((s, i) => s + i.moderateCount, 0)} | Instáveis: ${instrumentsHealth.reduce((s, i) => s + i.unstableCount, 0)}`,
        status: getScoreStatus(stabilityValue),
      },
      {
        value: alertsValue,
        weight: 0.25,
        label: 'Alertas',
        icon: <AlertTriangle className="w-4 h-4" />,
        details: `Críticos: ${instrumentsHealth.reduce((s, i) => s + i.alertsCritical, 0)} | Atenção: ${instrumentsHealth.reduce((s, i) => s + i.alertsWarning, 0)} | Positivos: ${instrumentsHealth.reduce((s, i) => s + i.alertsPositive, 0)}`,
        status: getScoreStatus(alertsValue),
      },
      {
        value: diversificationValue,
        weight: 0.20,
        label: 'Diversificação',
        icon: <Layers className="w-4 h-4" />,
        details: `Cobertura cross-instrument das features`,
        status: getScoreStatus(diversificationValue),
      },
      {
        value: consistencyValue,
        weight: 0.15,
        label: 'Consistência',
        icon: <GitBranch className="w-4 h-4" />,
        details: `Concordância de classificação entre instrumentos`,
        status: getScoreStatus(consistencyValue),
      },
    ];
    
    const overall = subs.reduce((sum, s) => sum + s.value * s.weight, 0);
    const diags = generateDiagnostics(subs, instrumentsHealth, data, instrumentNames);
    
    return { overallScore: overall, subScores: subs, instruments: instrumentsHealth, diagnostics: diags };
  }, [data]);
  
  if (!data) return null;
  
  const instrumentLabels: Record<string, string> = {
    fx: 'FX',
    front: 'Front',
    long: 'Long',
    belly: 'Belly',
    hard: 'Hard',
  };
  
  return (
    <div className="bg-slate-900/60 border border-slate-700/50 rounded-xl p-5">
      {/* Header */}
      <div className="flex items-center gap-2 mb-4">
        <Activity className="w-5 h-5 text-cyan-400" />
        <h3 className="text-sm font-semibold text-slate-200 uppercase tracking-wider">
          Model Health Score
        </h3>
      </div>
      
      {/* Main Score + Sub-scores Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
        {/* Left: Main Gauge */}
        <div className="lg:col-span-4 flex flex-col items-center justify-center">
          <HealthGauge score={overallScore} size={220} />
          <div className={`text-lg font-bold mt-1 ${getOverallColor(overallScore)}`}>
            {getOverallLabel(overallScore)}
          </div>
          <p className="text-xs text-slate-500 mt-1 text-center">
            Score composto ponderado
          </p>
        </div>
        
        {/* Right: Sub-scores */}
        <div className="lg:col-span-8 space-y-3">
          {subScores.map((sub) => (
            <div key={sub.label} className="bg-slate-800/40 rounded-lg p-3">
              <div className="flex items-center justify-between mb-1.5">
                <div className="flex items-center gap-2">
                  <span className={getSubScoreColor(sub.status)}>{sub.icon}</span>
                  <span className="text-xs font-medium text-slate-300">{sub.label}</span>
                  <span className="text-[10px] text-slate-500">({(sub.weight * 100).toFixed(0)}%)</span>
                </div>
                <span className={`text-sm font-bold font-mono ${getSubScoreColor(sub.status)}`}>
                  {sub.value.toFixed(1)}
                </span>
              </div>
              {/* Progress bar */}
              <div className="w-full h-1.5 bg-slate-700/50 rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all duration-700 ${getSubScoreBarColor(sub.status)}`}
                  style={{ width: `${Math.min(100, sub.value)}%` }}
                />
              </div>
              <p className="text-[10px] text-slate-500 mt-1">{sub.details}</p>
            </div>
          ))}
        </div>
      </div>
      
      {/* Per-Instrument Health Cards */}
      <div className="mt-5">
        <h4 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
          Saúde por Instrumento
        </h4>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
          {instruments.map((inst) => {
            const label = instrumentLabels[inst.name] || inst.name.toUpperCase();
            const instColor = inst.score >= 75 ? 'border-emerald-500/30' : inst.score >= 55 ? 'border-cyan-500/30' : inst.score >= 35 ? 'border-yellow-500/30' : 'border-red-500/30';
            
            return (
              <div key={inst.name} className={`bg-slate-800/40 rounded-lg p-3 border ${instColor}`}>
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-semibold text-slate-300">{label}</span>
                  <MiniGauge score={inst.score} size={36} />
                </div>
                
                {/* Classification bars */}
                <div className="flex gap-0.5 h-2 rounded-full overflow-hidden mb-2">
                  {inst.robustCount > 0 && (
                    <div
                      className="bg-emerald-500 transition-all"
                      style={{ width: `${(inst.robustCount / inst.totalFeatures) * 100}%` }}
                      title={`Robust: ${inst.robustCount}`}
                    />
                  )}
                  {inst.moderateCount > 0 && (
                    <div
                      className="bg-yellow-500 transition-all"
                      style={{ width: `${(inst.moderateCount / inst.totalFeatures) * 100}%` }}
                      title={`Moderate: ${inst.moderateCount}`}
                    />
                  )}
                  {inst.unstableCount > 0 && (
                    <div
                      className="bg-red-500/70 transition-all"
                      style={{ width: `${(inst.unstableCount / inst.totalFeatures) * 100}%` }}
                      title={`Unstable: ${inst.unstableCount}`}
                    />
                  )}
                </div>
                
                <div className="flex justify-between text-[10px] text-slate-500">
                  <span className="text-emerald-400">{inst.robustCount}R</span>
                  <span className="text-yellow-400">{inst.moderateCount}M</span>
                  <span className="text-red-400">{inst.unstableCount}U</span>
                </div>
                
                {/* Alert badges */}
                {(inst.alertsCritical > 0 || inst.alertsWarning > 0) && (
                  <div className="flex gap-1 mt-1.5">
                    {inst.alertsCritical > 0 && (
                      <span className="text-[9px] bg-red-500/20 text-red-400 px-1.5 py-0.5 rounded-full">
                        {inst.alertsCritical} crit
                      </span>
                    )}
                    {inst.alertsWarning > 0 && (
                      <span className="text-[9px] bg-yellow-500/20 text-yellow-400 px-1.5 py-0.5 rounded-full">
                        {inst.alertsWarning} warn
                      </span>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
      
      {/* Diagnostics */}
      {diagnostics.length > 0 && (
        <div className="mt-5">
          <h4 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
            Diagnósticos e Recomendações
          </h4>
          <div className="space-y-2">
            {diagnostics.map((diag, i) => {
              const icon = diag.severity === 'critical' ? <XCircle className="w-3.5 h-3.5 text-red-400 shrink-0" />
                : diag.severity === 'warning' ? <AlertTriangle className="w-3.5 h-3.5 text-yellow-400 shrink-0" />
                : diag.severity === 'positive' ? <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                : <Info className="w-3.5 h-3.5 text-cyan-400 shrink-0" />;
              
              const borderColor = diag.severity === 'critical' ? 'border-red-500/30'
                : diag.severity === 'warning' ? 'border-yellow-500/30'
                : diag.severity === 'positive' ? 'border-emerald-500/30'
                : 'border-cyan-500/30';
              
              return (
                <div key={i} className={`bg-slate-800/30 border ${borderColor} rounded-lg px-3 py-2 flex gap-2`}>
                  <div className="mt-0.5">{icon}</div>
                  <div className="min-w-0">
                    <p className="text-xs text-slate-300">{diag.message}</p>
                    <p className="text-[10px] text-slate-500 mt-0.5">→ {diag.action}</p>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
      
      {/* Formula Legend */}
      <div className="mt-4 pt-3 border-t border-slate-700/30">
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-[10px] text-slate-500">
          <span>Score = Σ(sub_i × peso_i)</span>
          <span>Estabilidade: 40%</span>
          <span>Alertas: 25%</span>
          <span>Diversificação: 20%</span>
          <span>Consistência: 15%</span>
        </div>
      </div>
    </div>
  );
}
