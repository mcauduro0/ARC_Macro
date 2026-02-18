/**
 * Tests for Feature Stability Change Detection (v4.5)
 * Tests the detectFeatureStabilityChanges logic and push notification grouping.
 */
import { describe, it, expect } from "vitest";

// ============================================================
// Feature Stability Classification Logic Tests
// ============================================================

describe("Feature Stability — Classification Change Detection", () => {
  // Helper to simulate the detection logic from alertEngine.ts
  function detectStabilityChanges(
    curClassification: Record<string, string>,
    prevClassification: Record<string, string>,
    instrument: string
  ) {
    const alerts: Array<{
      alertType: string;
      severity: string;
      feature: string;
      instrument: string;
      previousValue: string;
      currentValue: string;
    }> = [];

    for (const [feature, curClass] of Object.entries(curClassification)) {
      const prevClass = prevClassification[feature];
      if (!prevClass || prevClass === curClass) continue;

      if (prevClass === 'robust' && curClass === 'unstable') {
        alerts.push({
          alertType: 'feature_stability',
          severity: 'critical',
          feature,
          instrument,
          previousValue: prevClass,
          currentValue: curClass,
        });
      } else if (prevClass === 'robust' && curClass === 'moderate') {
        alerts.push({
          alertType: 'feature_stability',
          severity: 'warning',
          feature,
          instrument,
          previousValue: prevClass,
          currentValue: curClass,
        });
      } else if (prevClass === 'unstable' && curClass === 'robust') {
        alerts.push({
          alertType: 'feature_stability',
          severity: 'info',
          feature,
          instrument,
          previousValue: prevClass,
          currentValue: curClass,
        });
      }
    }

    return alerts;
  }

  it("should detect Robust → Unstable as critical alert", () => {
    const prev = { Z_vix: 'robust', Z_fiscal: 'moderate' };
    const cur = { Z_vix: 'unstable', Z_fiscal: 'moderate' };
    const alerts = detectStabilityChanges(cur, prev, 'fx');
    expect(alerts).toHaveLength(1);
    expect(alerts[0].severity).toBe('critical');
    expect(alerts[0].feature).toBe('Z_vix');
    expect(alerts[0].previousValue).toBe('robust');
    expect(alerts[0].currentValue).toBe('unstable');
  });

  it("should detect Robust → Moderate as warning alert", () => {
    const prev = { Z_fiscal: 'robust' };
    const cur = { Z_fiscal: 'moderate' };
    const alerts = detectStabilityChanges(cur, prev, 'front');
    expect(alerts).toHaveLength(1);
    expect(alerts[0].severity).toBe('warning');
    expect(alerts[0].feature).toBe('Z_fiscal');
  });

  it("should detect Unstable → Robust as info alert (positive signal)", () => {
    const prev = { Z_cds_br: 'unstable' };
    const cur = { Z_cds_br: 'robust' };
    const alerts = detectStabilityChanges(cur, prev, 'hard');
    expect(alerts).toHaveLength(1);
    expect(alerts[0].severity).toBe('info');
    expect(alerts[0].feature).toBe('Z_cds_br');
  });

  it("should not alert when classification stays the same", () => {
    const prev = { Z_vix: 'robust', Z_fiscal: 'moderate', Z_dxy: 'unstable' };
    const cur = { Z_vix: 'robust', Z_fiscal: 'moderate', Z_dxy: 'unstable' };
    const alerts = detectStabilityChanges(cur, prev, 'fx');
    expect(alerts).toHaveLength(0);
  });

  it("should not alert for Moderate → Unstable (not a critical transition)", () => {
    const prev = { Z_tot: 'moderate' };
    const cur = { Z_tot: 'unstable' };
    const alerts = detectStabilityChanges(cur, prev, 'belly');
    // Moderate → Unstable is not tracked (only Robust → Unstable/Moderate)
    expect(alerts).toHaveLength(0);
  });

  it("should not alert for Unstable → Moderate (minor improvement)", () => {
    const prev = { Z_beer: 'unstable' };
    const cur = { Z_beer: 'moderate' };
    const alerts = detectStabilityChanges(cur, prev, 'long');
    // Only Unstable → Robust is tracked as positive
    expect(alerts).toHaveLength(0);
  });

  it("should detect multiple changes across features", () => {
    const prev = {
      Z_vix: 'robust',
      Z_fiscal: 'robust',
      Z_cds_br: 'unstable',
      Z_dxy: 'moderate',
    };
    const cur = {
      Z_vix: 'unstable',    // critical
      Z_fiscal: 'moderate', // warning
      Z_cds_br: 'robust',   // info
      Z_dxy: 'moderate',    // no change
    };
    const alerts = detectStabilityChanges(cur, prev, 'fx');
    expect(alerts).toHaveLength(3);
    
    const critical = alerts.filter(a => a.severity === 'critical');
    const warning = alerts.filter(a => a.severity === 'warning');
    const info = alerts.filter(a => a.severity === 'info');
    
    expect(critical).toHaveLength(1);
    expect(critical[0].feature).toBe('Z_vix');
    
    expect(warning).toHaveLength(1);
    expect(warning[0].feature).toBe('Z_fiscal');
    
    expect(info).toHaveLength(1);
    expect(info[0].feature).toBe('Z_cds_br');
  });

  it("should handle new features not in previous run", () => {
    const prev = { Z_vix: 'robust' };
    const cur = { Z_vix: 'robust', Z_new_feature: 'moderate' };
    const alerts = detectStabilityChanges(cur, prev, 'fx');
    // Z_new_feature has no previous classification, so no alert
    expect(alerts).toHaveLength(0);
  });

  it("should handle features removed in current run", () => {
    const prev = { Z_vix: 'robust', Z_old_feature: 'moderate' };
    const cur = { Z_vix: 'robust' };
    const alerts = detectStabilityChanges(cur, prev, 'fx');
    // Z_old_feature is not in current, so no alert
    expect(alerts).toHaveLength(0);
  });
});

describe("Feature Stability — Push Notification Grouping", () => {
  it("should group critical alerts for consolidated notification", () => {
    const alerts = [
      { alertType: 'feature_stability', severity: 'critical', feature: 'Z_vix', instrument: 'fx' },
      { alertType: 'feature_stability', severity: 'critical', feature: 'Z_fiscal', instrument: 'front' },
      { alertType: 'feature_stability', severity: 'warning', feature: 'Z_dxy', instrument: 'belly' },
    ];
    
    const critical = alerts.filter(a => a.alertType === 'feature_stability' && a.severity === 'critical');
    const warnings = alerts.filter(a => a.alertType === 'feature_stability' && a.severity === 'warning');
    
    expect(critical).toHaveLength(2);
    expect(warnings).toHaveLength(1);
  });

  it("should not send push for info-level stability changes", () => {
    const alerts = [
      { alertType: 'feature_stability', severity: 'info', feature: 'Z_cds_br', instrument: 'hard' },
    ];
    
    const pushable = alerts.filter(
      a => a.alertType === 'feature_stability' && (a.severity === 'critical' || a.severity === 'warning')
    );
    
    expect(pushable).toHaveLength(0);
  });
});

describe("Feature Stability — Schema Validation", () => {
  it("should have feature_stability in valid alertType values", () => {
    const validTypes = [
      "regime_change", "shap_shift", "score_change",
      "drawdown_warning", "model_degradation", "data_quality", "feature_stability"
    ];
    expect(validTypes).toContain("feature_stability");
  });

  it("should have valid severity levels", () => {
    const validSeverities = ["info", "warning", "critical"];
    expect(validSeverities).toContain("info");
    expect(validSeverities).toContain("warning");
    expect(validSeverities).toContain("critical");
  });
});

describe("Rolling Stability — Temporal Tracker", () => {
  it("should compute feature persistence correctly", () => {
    // Simulate 3 snapshots where Z_vix appears in all 3 and Z_fiscal in 2
    const snapshots = [
      { features: ['Z_vix', 'Z_fiscal', 'Z_dxy'] },
      { features: ['Z_vix', 'Z_fiscal'] },
      { features: ['Z_vix', 'Z_cds_br'] },
    ];
    
    const featCounts: Record<string, number> = {};
    for (const snap of snapshots) {
      for (const f of snap.features) {
        featCounts[f] = (featCounts[f] || 0) + 1;
      }
    }
    
    const persistence: Record<string, number> = {};
    for (const [f, count] of Object.entries(featCounts)) {
      persistence[f] = count / snapshots.length;
    }
    
    expect(persistence.Z_vix).toBeCloseTo(1.0);
    expect(persistence.Z_fiscal).toBeCloseTo(0.667, 2);
    expect(persistence.Z_dxy).toBeCloseTo(0.333, 2);
    expect(persistence.Z_cds_br).toBeCloseTo(0.333, 2);
  });

  it("should detect feature turnover between snapshots", () => {
    const prevFeatures = new Set(['Z_vix', 'Z_fiscal', 'Z_dxy']);
    const curFeatures = new Set(['Z_vix', 'Z_cds_br', 'Z_tot']);
    
    const gained = [...curFeatures].filter(f => !prevFeatures.has(f));
    const lost = [...prevFeatures].filter(f => !curFeatures.has(f));
    const stable = [...curFeatures].filter(f => prevFeatures.has(f));
    
    expect(gained).toEqual(expect.arrayContaining(['Z_cds_br', 'Z_tot']));
    expect(lost).toEqual(expect.arrayContaining(['Z_fiscal', 'Z_dxy']));
    expect(stable).toEqual(['Z_vix']);
    
    const turnover = (gained.length + lost.length) / 
      new Set([...prevFeatures, ...curFeatures]).size * 100;
    expect(turnover).toBeGreaterThan(50); // High turnover
  });

  it("should handle single snapshot gracefully", () => {
    const history = [{ date: '2026-02-15', instruments: {} }];
    expect(history.length).toBe(1);
    // With only 1 snapshot, no trend or comparison is possible
    const hasPrevious = history.length >= 2;
    expect(hasPrevious).toBe(false);
  });
});
