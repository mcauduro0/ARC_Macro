/**
 * Centralized instrument naming and B3 contract specifications.
 * All components should import from here for consistent labeling.
 */

export const INSTRUMENT_LABELS: Record<string, string> = {
  fx: 'DOL Futuro (Câmbio)',
  front: 'Front-End (DI 1Y)',
  belly: 'Belly (DI 2-3Y)',
  long: 'Long-End (DI 5Y)',
  hard: 'Cupom Cambial (DDI)',
  ntnb: 'NTN-B (Cupom de Inflação)',
};

export const INSTRUMENT_SHORT: Record<string, string> = {
  fx: 'DOL',
  front: 'DI 1Y',
  belly: 'DI 5Y',
  long: 'DI 10Y',
  hard: 'DDI',
  ntnb: 'NTN-B',
};

export const B3_CONTRACTS: Record<string, { ticker: string; exchange: string; maturity: string; contractSize: string; tickSize: string }> = {
  fx: { ticker: 'DOL (Cheio) / WDO (Mini)', exchange: 'B3 (BM&F)', maturity: 'Mensal (1o du)', contractSize: 'USD 50.000 / USD 10.000', tickSize: 'R$ 0,50 / R$ 0,10' },
  front: { ticker: 'DI1', exchange: 'B3 (BM&F)', maturity: 'F25/F26 (1Y)', contractSize: 'R$ 100.000', tickSize: '1 bp' },
  belly: { ticker: 'DI1', exchange: 'B3 (BM&F)', maturity: 'F27/F28 (2-3Y)', contractSize: 'R$ 100.000', tickSize: '1 bp' },
  long: { ticker: 'DI1', exchange: 'B3 (BM&F)', maturity: 'F30/F35 (5-10Y)', contractSize: 'R$ 100.000', tickSize: '1 bp' },
  hard: { ticker: 'DDI1', exchange: 'B3 (BM&F)', maturity: 'DDI F25/F26', contractSize: 'USD 50.000', tickSize: '0.001%' },
  ntnb: { ticker: 'NTN-B (IPCA+)', exchange: 'ANBIMA/Tesouro Direto', maturity: 'NTN-B 2030/2035', contractSize: 'R$ 1.000 (face)', tickSize: '0.01%' },
};

export const ALL_INSTRUMENTS = ['fx', 'front', 'belly', 'long', 'hard', 'ntnb'] as const;
export type InstrumentKey = typeof ALL_INSTRUMENTS[number];
