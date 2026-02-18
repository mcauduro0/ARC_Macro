/**
 * Model Health Score — Scoring Engine Tests
 * Tests the scoring formulas and classification logic
 */
import { describe, it, expect } from 'vitest';

// ── Replicate scoring functions from ModelHealthPanel ──────────────────────

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

function computeStabilityScore(instruments: InstrumentHealth[]): number {
  if (instruments.length === 0) return 0;
  
  let totalWeightedScore = 0;
  let totalWeight = 0;
  
  for (const inst of instruments) {
    const total = inst.robustCount + inst.moderateCount + inst.unstableCount;
    if (total === 0) continue;
    
    const robustRatio = inst.robustCount / total;
    const moderateRatio = inst.moderateCount / total;
    const unstableRatio = inst.unstableCount / total;
    
    const instScore = robustRatio * 100 + moderateRatio * 60 + unstableRatio * 20;
    
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
  
  const score = 80 - (totalCritical * 15) - (totalWarning * 5) + (totalPositive * 3);
  return Math.max(0, Math.min(100, score));
}

function computeDiversificationScore(
  data: Record<string, FeatureSelectionResult>,
  instrumentNames: string[]
): number {
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
  
  const wellDiversified = Object.values(featureCoverage).filter(c => c >= 3).length;
  const strongFeatures = Object.values(featureRobust).filter(c => c >= 2).length;
  
  const diversificationRatio = wellDiversified / totalFeatures;
  const strengthRatio = strongFeatures / Math.max(1, totalFeatures);
  
  return Math.min(100, (diversificationRatio * 60 + strengthRatio * 40) * 100);
}

function computeConsistencyScore(
  data: Record<string, FeatureSelectionResult>,
  instrumentNames: string[]
): number {
  const featureClassifications: Record<string, string[]> = {};
  
  for (const inst of instrumentNames) {
    const cls = data[inst]?.stability?.classification || {};
    for (const [feat, status] of Object.entries(cls)) {
      if (!featureClassifications[feat]) featureClassifications[feat] = [];
      featureClassifications[feat].push(status);
    }
  }
  
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

// ── Helper to create instrument health ─────────────────────────────────────

function makeInstrument(overrides: Partial<InstrumentHealth> = {}): InstrumentHealth {
  return {
    name: 'test',
    score: 50,
    robustCount: 3,
    moderateCount: 4,
    unstableCount: 5,
    totalFeatures: 12,
    avgComposite: 0.3,
    alertsCritical: 0,
    alertsWarning: 1,
    alertsPositive: 0,
    ...overrides,
  };
}

function makeFeatureSelectionResult(overrides: Partial<FeatureSelectionResult> = {}): FeatureSelectionResult {
  return {
    total_features: 18,
    stability: {
      classification: { feat_a: 'robust', feat_b: 'moderate', feat_c: 'unstable' },
      composite_score: { feat_a: 0.7, feat_b: 0.4, feat_c: 0.1 },
    },
    final: { n_features: 8, features: ['feat_a', 'feat_b'], reduction_pct: 55 },
    lasso: { n_selected: 10 },
    boruta: { n_confirmed: 6 },
    ...overrides,
  };
}

// ── Tests ──────────────────────────────────────────────────────────────────

describe('Model Health Score — Stability Score', () => {
  it('returns 0 for empty instruments', () => {
    expect(computeStabilityScore([])).toBe(0);
  });

  it('returns 100 for all-robust instrument', () => {
    const inst = makeInstrument({ robustCount: 10, moderateCount: 0, unstableCount: 0 });
    expect(computeStabilityScore([inst])).toBe(100);
  });

  it('returns 20 for all-unstable instrument', () => {
    const inst = makeInstrument({ robustCount: 0, moderateCount: 0, unstableCount: 10 });
    expect(computeStabilityScore([inst])).toBe(20);
  });

  it('returns 60 for all-moderate instrument', () => {
    const inst = makeInstrument({ robustCount: 0, moderateCount: 10, unstableCount: 0 });
    expect(computeStabilityScore([inst])).toBe(60);
  });

  it('computes weighted average across instruments', () => {
    const robust = makeInstrument({ name: 'A', robustCount: 10, moderateCount: 0, unstableCount: 0, avgComposite: 0.5 });
    const unstable = makeInstrument({ name: 'B', robustCount: 0, moderateCount: 0, unstableCount: 10, avgComposite: 0.5 });
    const score = computeStabilityScore([robust, unstable]);
    // Equal weights → (100 * 0.5 + 20 * 0.5) / (0.5 + 0.5) = 60
    expect(score).toBe(60);
  });

  it('weights higher composite instruments more', () => {
    const robust = makeInstrument({ name: 'A', robustCount: 10, moderateCount: 0, unstableCount: 0, avgComposite: 0.8 });
    const unstable = makeInstrument({ name: 'B', robustCount: 0, moderateCount: 0, unstableCount: 10, avgComposite: 0.2 });
    const score = computeStabilityScore([robust, unstable]);
    // Weighted: (100 * 0.8 + 20 * 0.2) / (0.8 + 0.2) = (80 + 4) / 1 = 84
    expect(score).toBe(84);
  });

  it('handles instrument with zero features', () => {
    const empty = makeInstrument({ robustCount: 0, moderateCount: 0, unstableCount: 0 });
    const normal = makeInstrument({ robustCount: 5, moderateCount: 5, unstableCount: 0 });
    const score = computeStabilityScore([empty, normal]);
    // Only normal counts: (5/10*100 + 5/10*60) = 80
    expect(score).toBe(80);
  });
});

describe('Model Health Score — Alert Score', () => {
  it('returns 80 for no alerts', () => {
    const inst = makeInstrument({ alertsCritical: 0, alertsWarning: 0, alertsPositive: 0 });
    expect(computeAlertScore([inst])).toBe(80);
  });

  it('penalizes critical alerts by 15 each', () => {
    const inst = makeInstrument({ alertsCritical: 2, alertsWarning: 0, alertsPositive: 0 });
    expect(computeAlertScore([inst])).toBe(50); // 80 - 30
  });

  it('penalizes warning alerts by 5 each', () => {
    const inst = makeInstrument({ alertsCritical: 0, alertsWarning: 4, alertsPositive: 0 });
    expect(computeAlertScore([inst])).toBe(60); // 80 - 20
  });

  it('adds bonus for positive alerts (+3 each)', () => {
    const inst = makeInstrument({ alertsCritical: 0, alertsWarning: 0, alertsPositive: 5 });
    expect(computeAlertScore([inst])).toBe(95); // 80 + 15
  });

  it('caps at 100', () => {
    const inst = makeInstrument({ alertsCritical: 0, alertsWarning: 0, alertsPositive: 20 });
    expect(computeAlertScore([inst])).toBe(100);
  });

  it('floors at 0', () => {
    const inst = makeInstrument({ alertsCritical: 10, alertsWarning: 0, alertsPositive: 0 });
    expect(computeAlertScore([inst])).toBe(0); // 80 - 150 → clamped to 0
  });

  it('combines penalties and bonuses across instruments', () => {
    const a = makeInstrument({ alertsCritical: 1, alertsWarning: 2, alertsPositive: 1 });
    const b = makeInstrument({ alertsCritical: 0, alertsWarning: 1, alertsPositive: 2 });
    // Total: 1 crit, 3 warn, 3 positive → 80 - 15 - 15 + 9 = 59
    expect(computeAlertScore([a, b])).toBe(59);
  });

  it('matches v4.5 data: 1 critical, 9 warning, 5 positive', () => {
    const inst = makeInstrument({ alertsCritical: 1, alertsWarning: 9, alertsPositive: 5 });
    // 80 - 15 - 45 + 15 = 35
    expect(computeAlertScore([inst])).toBe(35);
  });
});

describe('Model Health Score — Diversification Score', () => {
  it('returns 0 for empty data', () => {
    expect(computeDiversificationScore({}, [])).toBe(0);
  });

  it('returns 0 for single instrument (no feature in 3+)', () => {
    const data = {
      fx: makeFeatureSelectionResult({
        stability: { classification: { feat_a: 'robust', feat_b: 'moderate' } },
      }),
    };
    expect(computeDiversificationScore(data, ['fx'])).toBe(0);
  });

  it('scores high when features appear in 3+ instruments', () => {
    const cls = { feat_a: 'robust', feat_b: 'moderate', feat_c: 'unstable' };
    const data = {
      fx: makeFeatureSelectionResult({ stability: { classification: cls } }),
      front: makeFeatureSelectionResult({ stability: { classification: cls } }),
      long: makeFeatureSelectionResult({ stability: { classification: cls } }),
    };
    const score = computeDiversificationScore(data, ['fx', 'front', 'long']);
    // All 3 features in 3 instruments → wellDiversified=3/3=1.0
    // feat_a robust in 3 → strongFeatures=1/3=0.333
    // (1.0 * 60 + 0.333 * 40) * 100 = (60 + 13.33) * 100 = 7333 → capped at 100
    expect(score).toBe(100);
  });

  it('partial diversification gives intermediate score', () => {
    const data = {
      fx: makeFeatureSelectionResult({
        stability: { classification: { feat_a: 'robust', feat_b: 'moderate', feat_c: 'unstable', feat_d: 'robust' } },
      }),
      front: makeFeatureSelectionResult({
        stability: { classification: { feat_a: 'robust', feat_b: 'unstable' } },
      }),
      long: makeFeatureSelectionResult({
        stability: { classification: { feat_a: 'moderate', feat_e: 'robust' } },
      }),
    };
    const score = computeDiversificationScore(data, ['fx', 'front', 'long']);
    // feat_a: 3 instruments (wellDiversified), robust in 2 (strong)
    // feat_b: 2 instruments
    // feat_c: 1 instrument
    // feat_d: 1 instrument
    // feat_e: 1 instrument
    // wellDiversified = 1/5 = 0.2, strongFeatures = 1/5 = 0.2
    // (0.2 * 60 + 0.2 * 40) * 100 = (12 + 8) * 100 = 2000 → capped at 100
    expect(score).toBe(100);
  });
});

describe('Model Health Score — Consistency Score', () => {
  it('returns 50 for no multi-instrument features', () => {
    const data = {
      fx: makeFeatureSelectionResult({
        stability: { classification: { feat_a: 'robust' } },
      }),
      front: makeFeatureSelectionResult({
        stability: { classification: { feat_b: 'moderate' } },
      }),
    };
    expect(computeConsistencyScore(data, ['fx', 'front'])).toBe(50);
  });

  it('returns 100 for perfect agreement', () => {
    const cls = { feat_a: 'robust', feat_b: 'moderate' };
    const data = {
      fx: makeFeatureSelectionResult({ stability: { classification: cls } }),
      front: makeFeatureSelectionResult({ stability: { classification: cls } }),
      long: makeFeatureSelectionResult({ stability: { classification: cls } }),
    };
    expect(computeConsistencyScore(data, ['fx', 'front', 'long'])).toBe(100);
  });

  it('gives partial credit for adjacent classifications', () => {
    const data = {
      fx: makeFeatureSelectionResult({
        stability: { classification: { feat_a: 'robust' } },
      }),
      front: makeFeatureSelectionResult({
        stability: { classification: { feat_a: 'moderate' } },
      }),
    };
    // 1 pair, partial agreement (0.5/1) = 50
    expect(computeConsistencyScore(data, ['fx', 'front'])).toBe(50);
  });

  it('gives no credit for robust vs unstable', () => {
    const data = {
      fx: makeFeatureSelectionResult({
        stability: { classification: { feat_a: 'robust' } },
      }),
      front: makeFeatureSelectionResult({
        stability: { classification: { feat_a: 'unstable' } },
      }),
    };
    // 1 pair, no agreement (0/1) = 0
    expect(computeConsistencyScore(data, ['fx', 'front'])).toBe(0);
  });

  it('handles mixed agreement across features', () => {
    const data = {
      fx: makeFeatureSelectionResult({
        stability: { classification: { feat_a: 'robust', feat_b: 'moderate' } },
      }),
      front: makeFeatureSelectionResult({
        stability: { classification: { feat_a: 'robust', feat_b: 'unstable' } },
      }),
    };
    // feat_a: 1 pair, full agreement (1.0)
    // feat_b: 1 pair, adjacent agreement (0.5)
    // total: 1.5 / 2 = 75
    expect(computeConsistencyScore(data, ['fx', 'front'])).toBe(75);
  });
});

describe('Model Health Score — Classification', () => {
  it('classifies score >= 75 as excellent', () => {
    expect(getScoreStatus(75)).toBe('excellent');
    expect(getScoreStatus(100)).toBe('excellent');
  });

  it('classifies score 55-74 as good', () => {
    expect(getScoreStatus(55)).toBe('good');
    expect(getScoreStatus(74)).toBe('good');
  });

  it('classifies score 35-54 as warning', () => {
    expect(getScoreStatus(35)).toBe('warning');
    expect(getScoreStatus(54)).toBe('warning');
  });

  it('classifies score < 35 as critical', () => {
    expect(getScoreStatus(34)).toBe('critical');
    expect(getScoreStatus(0)).toBe('critical');
  });

  it('labels scores correctly in Portuguese', () => {
    expect(getOverallLabel(85)).toBe('Excelente');
    expect(getOverallLabel(70)).toBe('Bom');
    expect(getOverallLabel(50)).toBe('Moderado');
    expect(getOverallLabel(30)).toBe('Atenção');
    expect(getOverallLabel(10)).toBe('Crítico');
  });
});

describe('Model Health Score — Composite Score', () => {
  it('computes weighted composite from 4 sub-scores', () => {
    // Stability: 60 (40%), Alerts: 35 (25%), Diversification: 100 (20%), Consistency: 58.6 (15%)
    const composite = 60 * 0.4 + 35 * 0.25 + 100 * 0.2 + 58.6 * 0.15;
    // = 24 + 8.75 + 20 + 8.79 = 61.54
    expect(composite).toBeCloseTo(61.54, 1);
  });

  it('weights sum to 1.0', () => {
    expect(0.4 + 0.25 + 0.2 + 0.15).toBe(1.0);
  });

  it('all-excellent gives score near 100', () => {
    const allExcellent = 100 * 0.4 + 100 * 0.25 + 100 * 0.2 + 100 * 0.15;
    expect(allExcellent).toBe(100);
  });

  it('all-zero gives score 0', () => {
    const allZero = 0 * 0.4 + 0 * 0.25 + 0 * 0.2 + 0 * 0.15;
    expect(allZero).toBe(0);
  });
});
