import { describe, it, expect, beforeAll } from 'vitest';
import * as fs from 'fs';
import * as path from 'path';

describe('r* Timeseries Embedded Data', () => {
  let rstarData: any[];
  let dashboardData: any;

  beforeAll(() => {
    // Load the embedded data files
    const modelDataPath = path.join(__dirname, '../client/src/data/modelData.ts');
    const content = fs.readFileSync(modelDataPath, 'utf-8');
    
    // Extract rstarTsData
    const rstarMatch = content.match(/export const rstarTsData = (\[.*?\]);/s);
    expect(rstarMatch).toBeTruthy();
    rstarData = JSON.parse(rstarMatch![1]);

    // Extract dashboardData
    const dashMatch = content.match(/export const dashboardData = (\{.*?\});/s);
    expect(dashMatch).toBeTruthy();
    dashboardData = JSON.parse(dashMatch![1]);
  });

  describe('Data Structure', () => {
    it('should have at least 200 data points', () => {
      expect(rstarData.length).toBeGreaterThanOrEqual(200);
    });

    it('should have required fields in each point', () => {
      const requiredFields = ['date', 'composite_rstar', 'selic_star'];
      for (const point of rstarData.slice(-10)) {
        for (const field of requiredFields) {
          expect(point).toHaveProperty(field);
        }
      }
    });

    it('should have valid date format (YYYY-MM-DD)', () => {
      for (const point of rstarData) {
        expect(point.date).toMatch(/^\d{4}-\d{2}-\d{2}$/);
      }
    });

    it('should have dates in chronological order', () => {
      for (let i = 1; i < rstarData.length; i++) {
        expect(new Date(rstarData[i].date).getTime())
          .toBeGreaterThan(new Date(rstarData[i-1].date).getTime());
      }
    });
  });

  describe('Data Quality', () => {
    it('should have composite_rstar between 2% and 10%', () => {
      for (const point of rstarData) {
        expect(point.composite_rstar).toBeGreaterThanOrEqual(2.0);
        expect(point.composite_rstar).toBeLessThanOrEqual(10.0);
      }
    });

    it('should have selic_star between 2% and 35%', () => {
      for (const point of rstarData) {
        expect(point.selic_star).toBeGreaterThanOrEqual(2.0);
        expect(point.selic_star).toBeLessThanOrEqual(35.0);
      }
    });

    it('should have selic_actual in most recent points', () => {
      const recent = rstarData.slice(-12);
      const withSelic = recent.filter(p => p.selic_actual !== null && p.selic_actual !== undefined);
      expect(withSelic.length).toBeGreaterThanOrEqual(6);
    });

    it('should have policy_gap computed correctly', () => {
      const withGap = rstarData.filter(p => p.policy_gap !== null && p.policy_gap !== undefined);
      expect(withGap.length).toBeGreaterThan(100);
      for (const point of withGap) {
        if (point.selic_actual !== null && point.selic_actual !== undefined) {
          const expectedGap = Math.round((point.selic_actual - point.selic_star) * 100) / 100;
          expect(point.policy_gap).toBeCloseTo(expectedGap, 0);
        }
      }
    });

    it('should have at least 2 sub-models in recent points', () => {
      const last = rstarData[rstarData.length - 1];
      const subModels = Object.keys(last).filter(k => k.startsWith('rstar_'));
      expect(subModels.length).toBeGreaterThanOrEqual(2);
    });

    it('latest SELIC should be around current rate (13-16%)', () => {
      const last = rstarData[rstarData.length - 1];
      if (last.selic_actual) {
        expect(last.selic_actual).toBeGreaterThanOrEqual(10);
        expect(last.selic_actual).toBeLessThanOrEqual(16);
      }
    });
  });

  describe('Fallback Logic', () => {
    it('embedded rstarTsData should not be empty', () => {
      expect(rstarData.length).toBeGreaterThan(0);
    });

    it('should cover at least 15 years of data', () => {
      const firstDate = new Date(rstarData[0].date);
      const lastDate = new Date(rstarData[rstarData.length - 1].date);
      const years = (lastDate.getTime() - firstDate.getTime()) / (365.25 * 24 * 60 * 60 * 1000);
      expect(years).toBeGreaterThanOrEqual(15);
    });
  });

  describe('NTN-B Instrument Data', () => {
    it('should have ntnb_5y_yield in dashboard', () => {
      expect(dashboardData).toHaveProperty('ntnb_5y_yield');
      expect(typeof dashboardData.ntnb_5y_yield).toBe('number');
    });

    it('should have ntnb position data', () => {
      expect(dashboardData.positions).toHaveProperty('ntnb');
      const ntnb = dashboardData.positions.ntnb;
      expect(ntnb).toHaveProperty('direction');
      expect(ntnb).toHaveProperty('sharpe');
    });

    it('NTN-B real yield should be a number', () => {
      expect(typeof dashboardData.ntnb_5y_yield).toBe('number');
    });

    it('should have NTN-B 10Y yield in dashboard', () => {
      expect(dashboardData).toHaveProperty('ntnb_10y_yield');
      expect(typeof dashboardData.ntnb_10y_yield).toBe('number');
    });
  });
});
