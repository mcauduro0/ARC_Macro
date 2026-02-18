/**
 * Market Data Service — Real-time B3 price fetching and Mark-to-Market engine.
 *
 * Data sources (priority order):
 *   1. ANBIMA Feed API — DI curve (ETTJ), NTN-B/NTN-F yields, term structure
 *   2. BCB SGS API — PTAX, SELIC target, CDI daily
 *   3. Polygon.io — FX spot real-time (USDBRL)
 *   4. Yahoo Finance — VIX, Ibovespa, US Treasuries, DXY (fallback)
 *   5. Manual input — Fallback for illiquid instruments
 *
 * Features:
 *   - ANBIMA OAuth2 authentication with token caching
 *   - DI curve term structure (3M, 6M, 1Y, 2Y, 3Y, 5Y, 10Y)
 *   - NTN-B real yields and breakeven inflation
 *   - Polygon.io real-time FX quotes
 *   - Mark-to-market P&L engine
 *   - Trade slippage computation
 *   - Factor exposure analysis
 *   - Risk alert engine
 */

import { ENV } from "./_core/env";

// ============================================================
// TYPES
// ============================================================

export interface MarketPrices {
  timestamp: string;
  source: string;
  // FX
  spotUsdbrl: number;
  ptaxBid: number;
  ptaxAsk: number;
  // DI Curve (from ANBIMA ETTJ)
  di3m: number;
  di6m: number;
  di1y: number;
  di2y: number;
  di3y: number;
  di5y: number;
  di10y: number;
  // CDI / SELIC
  cdiDaily: number;
  cdiAnnual: number;
  selicTarget: number;
  // NTN-B (from ANBIMA)
  ntnbRate5y: number;
  ntnbRate10y: number;
  breakeven5y: number;
  breakeven10y: number;
  // Cupom Cambial
  cupomCambial: number;
  // Credit
  embiSpread: number;
  // Global
  vix: number;
  ibovespa: number;
  ust2y: number;
  ust10y: number;
  dxy: number;
  // Data quality
  anbimaAvailable: boolean;
  anbimaRefDate: string;
  polygonAvailable: boolean;
}

export interface PositionMtm {
  instrument: string;
  b3Ticker: string;
  direction: string;
  contracts: number;
  entryPrice: number;
  currentPrice: number;
  priceDelta: number;
  unrealizedPnlBrl: number;
  unrealizedPnlPct: number;
  dv01PnlBrl?: number;
  fxDeltaPnlBrl?: number;
}

export interface PortfolioPnlResult {
  date: string;
  positions: PositionMtm[];
  totalOverlayPnlBrl: number;
  cdiPnlBrl: number;
  totalPnlBrl: number;
  totalPnlPct: number;
  fxPnlBrl: number;
  frontPnlBrl: number;
  bellyPnlBrl: number;
  longPnlBrl: number;
  hardPnlBrl: number;
  excessReturnBrl: number;
  excessReturnPct: number;
}

// ============================================================
// PRICE CACHE
// ============================================================

interface CachedPrices {
  prices: MarketPrices;
  fetchedAt: number;
}

let priceCache: CachedPrices | null = null;
const CACHE_TTL_MS = 5 * 60 * 1000; // 5 minutes

// ============================================================
// ANBIMA FEED API — OAuth2 + DI Curve + NTN-B
// ============================================================

const ANBIMA_CLIENT_ID = process.env.ANBIMA_CLIENT_ID || "qoSZCWnsbfSK";
const ANBIMA_CLIENT_SECRET = process.env.ANBIMA_CLIENT_SECRET || "xgAbycH1LIb0";
const ANBIMA_AUTH_URL = "https://api.anbima.com.br/oauth/access-token";
const ANBIMA_BASE_URL = process.env.ANBIMA_BASE_URL || "https://api.anbima.com.br";

let anbimaTokenCache: { token: string | null; expiresAt: number } = {
  token: null,
  expiresAt: 0,
};

async function getAnbimaToken(): Promise<string | null> {
  const now = Date.now() / 1000;
  if (anbimaTokenCache.token && now < anbimaTokenCache.expiresAt - 60) {
    return anbimaTokenCache.token;
  }

  const credentials = `${ANBIMA_CLIENT_ID}:${ANBIMA_CLIENT_SECRET}`;
  const b64 = Buffer.from(credentials).toString("base64");

  try {
    const resp = await fetch(ANBIMA_AUTH_URL, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Basic ${b64}`,
      },
      body: JSON.stringify({ grant_type: "client_credentials" }),
      signal: AbortSignal.timeout(10000),
    });

    if (!resp.ok) {
      console.error(`[ANBIMA] Auth failed: HTTP ${resp.status}`);
      return null;
    }

    const data = await resp.json();
    const token = data.access_token;
    const expiresIn = data.expires_in || 3600;
    anbimaTokenCache = { token, expiresAt: now + expiresIn };
    console.log(`[ANBIMA] Token obtained (expires in ${expiresIn}s)`);
    return token;
  } catch (e: any) {
    console.error(`[ANBIMA] Auth error: ${e.message}`);
    return null;
  }
}

async function anbimaGet(endpoint: string): Promise<any | null> {
  const token = await getAnbimaToken();
  if (!token) return null;

  const url = `${ANBIMA_BASE_URL}${endpoint}`;
  try {
    const resp = await fetch(url, {
      headers: {
        client_id: ANBIMA_CLIENT_ID,
        access_token: token,
      },
      signal: AbortSignal.timeout(15000),
    });

    if (resp.ok) {
      return await resp.json();
    }
    console.error(`[ANBIMA] ${endpoint}: HTTP ${resp.status}`);
    return null;
  } catch (e: any) {
    console.error(`[ANBIMA] ${endpoint}: ${e.message}`);
    return null;
  }
}

interface AnbimaEttjResult {
  refDate: string;
  di3m: number;
  di6m: number;
  di1y: number;
  di2y: number;
  di3y: number;
  di5y: number;
  di10y: number;
  ntnb5y: number;
  ntnb10y: number;
}

/**
 * Fetch DI curve term structure (ETTJ) from ANBIMA Feed API.
 * Returns pre-fixed rates and IPCA (real) rates by vertex.
 */
async function fetchAnbimaEttj(): Promise<AnbimaEttjResult | null> {
  console.log("[ANBIMA] Fetching ETTJ (DI curve + NTN-B)...");
  const data = await anbimaGet(
    "/feed/precos-indices/v1/titulos-publicos/curvas-juros"
  );

  if (!data || !Array.isArray(data) || data.length === 0) {
    console.log("[ANBIMA] No ETTJ data returned");
    return null;
  }

  const rec = data[0];
  const refDate = rec.data_referencia || "unknown";
  const ettj = rec.ettj || [];

  if (!ettj.length) {
    console.log("[ANBIMA] No ETTJ vertices");
    return null;
  }

  // Vertex mapping: business days → tenor
  const duToTenor: Record<number, string> = {
    63: "di3m",
    126: "di6m",
    252: "di1y",
    504: "di2y",
    756: "di3y",
    1260: "di5y",
    2520: "di10y",
  };

  const duToNtnb: Record<number, string> = {
    1260: "ntnb5y",
    2520: "ntnb10y",
  };

  const result: Record<string, number> = {};

  for (const vertex of ettj) {
    const du = vertex.vertice_du || 0;
    const preRate = vertex.taxa_prefixadas;
    const ipcaRate = vertex.taxa_ipca;

    if (du in duToTenor && preRate != null) {
      result[duToTenor[du]] = parseFloat(preRate);
    }
    if (du in duToNtnb && ipcaRate != null) {
      result[duToNtnb[du]] = parseFloat(ipcaRate);
    }
  }

  console.log(
    `[ANBIMA] ETTJ ref=${refDate}: DI1Y=${result.di1y?.toFixed(2)}%, DI5Y=${result.di5y?.toFixed(2)}%, DI10Y=${result.di10y?.toFixed(2)}%`
  );

  return {
    refDate,
    di3m: result.di3m || 0,
    di6m: result.di6m || 0,
    di1y: result.di1y || 0,
    di2y: result.di2y || 0,
    di3y: result.di3y || 0,
    di5y: result.di5y || 0,
    di10y: result.di10y || 0,
    ntnb5y: result.ntnb5y || 0,
    ntnb10y: result.ntnb10y || 0,
  };
}

interface AnbimaBondResult {
  ntnbYields: { maturity: string; rate: number; du: number }[];
  ntnfYields: { maturity: string; rate: number; du: number }[];
}

/**
 * Fetch NTN-B and NTN-F indicative rates from ANBIMA secondary market.
 */
async function fetchAnbimaBonds(): Promise<AnbimaBondResult | null> {
  console.log("[ANBIMA] Fetching bond yields (NTN-B/NTN-F)...");
  const data = await anbimaGet(
    "/feed/precos-indices/v1/titulos-publicos/mercado-secundario-TPF"
  );

  if (!data || !Array.isArray(data)) {
    console.log("[ANBIMA] No bond data returned");
    return null;
  }

  const ntnbYields: { maturity: string; rate: number; du: number }[] = [];
  const ntnfYields: { maturity: string; rate: number; du: number }[] = [];

  for (const bond of data) {
    const tipo = String(bond.tipo_titulo || "");
    const rate = bond.taxa_indicativa;
    const matDate = bond.data_vencimento;
    const du = bond.du || 0;

    if (rate == null || !matDate) continue;

    if (tipo.includes("NTN-B") && !tipo.includes("NTN-B Principal")) {
      ntnbYields.push({ maturity: matDate, rate: parseFloat(rate), du });
    } else if (tipo.includes("NTN-F")) {
      ntnfYields.push({ maturity: matDate, rate: parseFloat(rate), du });
    }
  }

  // Sort by maturity
  ntnbYields.sort((a, b) => a.du - b.du);
  ntnfYields.sort((a, b) => a.du - b.du);

  if (ntnbYields.length > 0) {
    console.log(
      `[ANBIMA] NTN-B: ${ntnbYields.length} bonds, shortest=${ntnbYields[0].rate.toFixed(2)}%, longest=${ntnbYields[ntnbYields.length - 1].rate.toFixed(2)}%`
    );
  }

  return { ntnbYields, ntnfYields };
}

// ============================================================
// POLYGON.IO — Real-time FX
// ============================================================

async function fetchPolygonFx(): Promise<number | null> {
  const apiKey = process.env.POLYGON_API_KEY;
  if (!apiKey) {
    console.log("[Polygon] No API key, skipping");
    return null;
  }

  try {
    // Use last trade endpoint for real-time price
    const url = `https://api.polygon.io/v1/last/currencies/USD/BRL?apiKey=${apiKey}`;
    const resp = await fetch(url, { signal: AbortSignal.timeout(10000) });
    if (!resp.ok) {
      // Fallback to previous close
      const url2 = `https://api.polygon.io/v2/aggs/ticker/C:USDBRL/prev?adjusted=true&apiKey=${apiKey}`;
      const resp2 = await fetch(url2, { signal: AbortSignal.timeout(10000) });
      if (resp2.ok) {
        const data2 = await resp2.json();
        const close = data2?.results?.[0]?.c;
        if (close) {
          console.log(`[Polygon] USDBRL prev close: ${close}`);
          return close;
        }
      }
      return null;
    }
    const data = await resp.json();
    const price = data?.last?.price || data?.last?.ask;
    if (price) {
      console.log(`[Polygon] USDBRL real-time: ${price}`);
      return price;
    }
    return null;
  } catch (e: any) {
    console.error(`[Polygon] FX error: ${e.message}`);
    return null;
  }
}

// ============================================================
// BCB SGS API
// ============================================================

async function fetchBcbSeries(
  seriesCode: number,
  lastN: number = 1
): Promise<number | null> {
  try {
    const url = `https://api.bcb.gov.br/dados/serie/bcdata.sgs.${seriesCode}/dados/ultimos/${lastN}?formato=json`;
    const resp = await fetch(url, { signal: AbortSignal.timeout(10000) });
    if (!resp.ok) return null;
    const data = await resp.json();
    if (Array.isArray(data) && data.length > 0) {
      return parseFloat(data[data.length - 1].valor);
    }
    return null;
  } catch {
    return null;
  }
}

// ============================================================
// YAHOO FINANCE API (fallback for global indices)
// ============================================================

async function fetchYahooQuote(symbol: string): Promise<number | null> {
  try {
    const url = `https://query1.finance.yahoo.com/v8/finance/chart/${symbol}?range=1d&interval=1d`;
    const resp = await fetch(url, {
      signal: AbortSignal.timeout(10000),
      headers: { "User-Agent": "Mozilla/5.0" },
    });
    if (!resp.ok) return null;
    const data = await resp.json();
    const meta = data?.chart?.result?.[0]?.meta;
    return meta?.regularMarketPrice ?? null;
  } catch {
    return null;
  }
}

// ============================================================
// FETCH ALL MARKET PRICES — Integrated from all sources
// ============================================================

export async function fetchMarketPrices(
  forceRefresh = false
): Promise<MarketPrices> {
  // Check cache
  if (
    !forceRefresh &&
    priceCache &&
    Date.now() - priceCache.fetchedAt < CACHE_TTL_MS
  ) {
    return priceCache.prices;
  }

  console.log("[MarketData] Fetching latest market prices from all sources...");

  // Parallel fetch from all sources
  const [
    anbimaEttj,
    anbimaBonds,
    polygonFx,
    ptaxBid,
    ptaxAsk,
    selicTarget,
    cdiDaily,
    yahooUsdbrl,
    vix,
    ibov,
    ust10y,
    ust2y,
    dxy,
  ] = await Promise.all([
    fetchAnbimaEttj(),
    fetchAnbimaBonds(),
    fetchPolygonFx(),
    fetchBcbSeries(10813, 1), // PTAX venda
    fetchBcbSeries(1, 1), // PTAX compra
    fetchBcbSeries(432, 1), // SELIC target
    fetchBcbSeries(12, 1), // CDI daily
    fetchYahooQuote("BRL=X"), // USDBRL fallback
    fetchYahooQuote("^VIX"),
    fetchYahooQuote("^BVSP"),
    fetchYahooQuote("^TNX"),
    fetchYahooQuote("^IRX"), // US 2Y proxy (13-week T-bill)
    fetchYahooQuote("DX-Y.NYB"),
  ]);

  // === FX: Polygon > PTAX > Yahoo ===
  const spotUsdbrl = polygonFx || ptaxBid || yahooUsdbrl || 5.2;
  const anbimaAvailable = anbimaEttj !== null;
  const polygonAvailable = polygonFx !== null;

  // === Rates: ANBIMA > SELIC-based estimates ===
  const selicAnnual = selicTarget || 14.25;
  const cdiAnnualRate = cdiDaily
    ? (Math.pow(1 + cdiDaily / 100, 252) - 1) * 100
    : selicAnnual - 0.1;

  // DI curve from ANBIMA (real data) or SELIC-based estimates (fallback)
  const di3m = anbimaEttj?.di3m || selicAnnual + 0.1;
  const di6m = anbimaEttj?.di6m || selicAnnual + 0.15;
  const di1y = anbimaEttj?.di1y || selicAnnual + 0.25;
  const di2y = anbimaEttj?.di2y || selicAnnual - 0.2;
  const di3y = anbimaEttj?.di3y || selicAnnual - 0.5;
  const di5y = anbimaEttj?.di5y || selicAnnual - 0.8;
  const di10y = anbimaEttj?.di10y || selicAnnual - 0.3;

  // === NTN-B: ANBIMA ETTJ > Bond market > Estimates ===
  let ntnbRate5y = anbimaEttj?.ntnb5y || 0;
  let ntnbRate10y = anbimaEttj?.ntnb10y || 0;

  // If ETTJ didn't have IPCA rates, try bond market
  if (!ntnbRate5y && anbimaBonds?.ntnbYields.length) {
    // Find closest to 5Y (1260 du)
    const closest5y = anbimaBonds.ntnbYields.reduce((prev, curr) =>
      Math.abs(curr.du - 1260) < Math.abs(prev.du - 1260) ? curr : prev
    );
    ntnbRate5y = closest5y.rate;
  }
  if (!ntnbRate10y && anbimaBonds?.ntnbYields.length) {
    const closest10y = anbimaBonds.ntnbYields.reduce((prev, curr) =>
      Math.abs(curr.du - 2520) < Math.abs(prev.du - 2520) ? curr : prev
    );
    ntnbRate10y = closest10y.rate;
  }

  // Fallback estimates
  if (!ntnbRate5y) ntnbRate5y = di5y - 5.5;
  if (!ntnbRate10y) ntnbRate10y = di10y - 5.5 - 0.3;

  // Breakeven inflation = Nominal - Real
  const breakeven5y = di5y - ntnbRate5y;
  const breakeven10y = di10y - ntnbRate10y;

  // Cupom cambial (DDI implied)
  const cupomCambial = di1y - ((ust10y || 4.0) + 2.0);

  // EMBI spread (from FRED or estimate)
  const embiSpread = 200; // Would need Bloomberg/FRED for real-time

  const sources: string[] = [];
  if (anbimaAvailable) sources.push("ANBIMA");
  if (polygonAvailable) sources.push("Polygon");
  sources.push("BCB");
  if (vix || ibov || ust10y) sources.push("Yahoo");

  const prices: MarketPrices = {
    timestamp: new Date().toISOString(),
    source: sources.join("/"),
    // FX
    spotUsdbrl,
    ptaxBid: ptaxBid || spotUsdbrl,
    ptaxAsk: ptaxAsk || spotUsdbrl,
    // DI Curve
    di3m,
    di6m,
    di1y,
    di2y,
    di3y,
    di5y,
    di10y,
    // CDI / SELIC
    cdiDaily: cdiDaily || cdiAnnualRate / 252,
    cdiAnnual: cdiAnnualRate,
    selicTarget: selicAnnual,
    // NTN-B
    ntnbRate5y,
    ntnbRate10y,
    breakeven5y,
    breakeven10y,
    // Cupom Cambial
    cupomCambial,
    // Credit
    embiSpread,
    // Global
    vix: vix || 15,
    ibovespa: ibov || 130000,
    ust2y: ust2y ? ust2y / 100 : (ust10y || 4.0) - 0.3,
    ust10y: ust10y || 4.0,
    dxy: dxy || 104,
    // Data quality
    anbimaAvailable,
    anbimaRefDate: anbimaEttj?.refDate || "",
    polygonAvailable,
  };

  // Update cache
  priceCache = { prices, fetchedAt: Date.now() };
  console.log(
    `[MarketData] Updated: USDBRL=${spotUsdbrl.toFixed(4)} [${polygonAvailable ? "Polygon" : "BCB/Yahoo"}], ` +
      `DI1Y=${di1y.toFixed(2)}% DI5Y=${di5y.toFixed(2)}% DI10Y=${di10y.toFixed(2)}% [${anbimaAvailable ? "ANBIMA" : "estimate"}], ` +
      `SELIC=${selicAnnual}%, CDI=${cdiAnnualRate.toFixed(2)}%`
  );

  return prices;
}

// ============================================================
// MARK-TO-MARKET ENGINE
// ============================================================

export interface MtmPosition {
  instrument: string;
  b3Ticker: string;
  b3InstrumentType: string;
  direction: string;
  contracts: number;
  notionalBrl: number;
  notionalUsd: number | null;
  entryPrice: number;
  dv01Brl: number | null;
  fxDeltaBrl: number | null;
  spreadDv01Usd: number | null;
}

/**
 * Compute mark-to-market P&L for all positions using real market prices.
 */
export function computeMtm(
  positions: MtmPosition[],
  prices: MarketPrices,
  aumBrl: number
): PortfolioPnlResult {
  const date = new Date().toISOString().slice(0, 10);
  const positionMtms: PositionMtm[] = [];

  let fxPnl = 0,
    frontPnl = 0,
    bellyPnl = 0,
    longPnl = 0,
    hardPnl = 0;

  for (const pos of positions) {
    const sign =
      pos.direction === "long" ? 1 : pos.direction === "short" ? -1 : 0;
    let currentPrice = pos.entryPrice;
    let pnlBrl = 0;

    switch (pos.instrument) {
      case "fx": {
        currentPrice = prices.spotUsdbrl;
        const fxNotional =
          pos.notionalUsd || pos.notionalBrl / prices.spotUsdbrl;
        pnlBrl = fxNotional * (currentPrice - pos.entryPrice) * sign;
        fxPnl += pnlBrl;
        break;
      }
      case "front": {
        currentPrice = prices.di1y;
        const yieldDeltaBps = (currentPrice - pos.entryPrice) * 100;
        pnlBrl = (pos.dv01Brl || 0) * yieldDeltaBps * sign * -1;
        frontPnl += pnlBrl;
        break;
      }
      case "belly": {
        currentPrice = prices.di5y;
        const yieldDeltaBps = (currentPrice - pos.entryPrice) * 100;
        pnlBrl = (pos.dv01Brl || 0) * yieldDeltaBps * sign * -1;
        bellyPnl += pnlBrl;
        break;
      }
      case "long": {
        currentPrice = prices.di10y;
        const yieldDeltaBps = (currentPrice - pos.entryPrice) * 100;
        pnlBrl = (pos.dv01Brl || 0) * yieldDeltaBps * sign * -1;
        longPnl += pnlBrl;
        break;
      }
      case "hard": {
        currentPrice = prices.embiSpread;
        const spreadDelta = currentPrice - pos.entryPrice;
        pnlBrl =
          (pos.spreadDv01Usd || 0) *
          spreadDelta *
          sign *
          -1 *
          prices.spotUsdbrl;
        hardPnl += pnlBrl;
        break;
      }
    }

    positionMtms.push({
      instrument: pos.instrument,
      b3Ticker: pos.b3Ticker,
      direction: pos.direction,
      contracts: pos.contracts,
      entryPrice: pos.entryPrice,
      currentPrice,
      priceDelta: currentPrice - pos.entryPrice,
      unrealizedPnlBrl: pnlBrl,
      unrealizedPnlPct: aumBrl > 0 ? (pnlBrl / aumBrl) * 100 : 0,
    });
  }

  const totalOverlayPnl = fxPnl + frontPnl + bellyPnl + longPnl + hardPnl;
  const cdiPnl = aumBrl * (prices.cdiDaily / 100);
  const totalPnl = totalOverlayPnl + cdiPnl;

  return {
    date,
    positions: positionMtms,
    totalOverlayPnlBrl: totalOverlayPnl,
    cdiPnlBrl: cdiPnl,
    totalPnlBrl: totalPnl,
    totalPnlPct: aumBrl > 0 ? (totalPnl / aumBrl) * 100 : 0,
    fxPnlBrl: fxPnl,
    frontPnlBrl: frontPnl,
    bellyPnlBrl: bellyPnl,
    longPnlBrl: longPnl,
    hardPnlBrl: hardPnl,
    excessReturnBrl: totalOverlayPnl,
    excessReturnPct: aumBrl > 0 ? (totalOverlayPnl / aumBrl) * 100 : 0,
  };
}

// ============================================================
// TRADE APPROVAL WORKFLOW
// ============================================================

export type TradeStatus =
  | "recommended"
  | "pending_approval"
  | "approved"
  | "executing"
  | "executed"
  | "partially_filled"
  | "cancelled"
  | "rejected";

export interface TradeOrder {
  id?: number;
  instrument: string;
  b3Ticker: string;
  b3InstrumentType: string;
  action: "BUY" | "SELL";
  contracts: number;
  targetPrice: number;
  status: TradeStatus;
  recommendedAt: string;
  approvedAt?: string;
  executedAt?: string;
  executedPrice?: number;
  executedContracts?: number;
  slippageBps?: number;
  slippageBrl?: number;
  commissionBrl: number;
  totalCostBrl: number;
  reason: string;
  notionalBrl: number;
}

/**
 * Compute slippage between target and executed price.
 */
export function computeSlippage(
  instrument: string,
  targetPrice: number,
  executedPrice: number,
  contracts: number,
  spotUsdbrl: number
): { slippageBps: number; slippageBrl: number } {
  if (targetPrice === 0 || executedPrice === 0) {
    return { slippageBps: 0, slippageBrl: 0 };
  }

  let slippageBps = 0;
  let slippageBrl = 0;

  switch (instrument) {
    case "fx": {
      slippageBps =
        (Math.abs(executedPrice - targetPrice) / targetPrice) * 10000;
      slippageBrl = Math.abs(executedPrice - targetPrice) * contracts * 10000;
      break;
    }
    case "front":
    case "belly":
    case "long": {
      slippageBps = Math.abs(executedPrice - targetPrice) * 100;
      const dv01PerContract =
        (100000 / (1 + targetPrice / 100)) * 0.01;
      slippageBrl = (slippageBps * dv01PerContract * contracts) / 100;
      break;
    }
    case "hard": {
      slippageBps = Math.abs(executedPrice - targetPrice);
      slippageBrl =
        (slippageBps * 50 * contracts * spotUsdbrl) / 10000;
      break;
    }
  }

  return {
    slippageBps: Math.round(slippageBps * 100) / 100,
    slippageBrl: Math.round(slippageBrl * 100) / 100,
  };
}

// ============================================================
// RISK DASHBOARD — FACTOR EXPOSURE
// ============================================================

export interface FactorExposure {
  factor: string;
  label: string;
  exposureBrl: number;
  exposurePctAum: number;
  riskContributionPct: number;
  limit: number;
  limitPctAum: number;
  utilizationPct: number;
  breached: boolean;
}

export interface RiskLimits {
  maxVarDaily95Pct: number;
  maxDrawdownPct: number;
  maxGrossLeverage: number;
  maxFxExposurePctAum: number;
  maxRatesExposurePctAum: number;
  maxCreditExposurePctAum: number;
  maxSingleInstrumentPct: number;
  minMarginBufferPct: number;
}

export const DEFAULT_RISK_LIMITS: RiskLimits = {
  maxVarDaily95Pct: 2.0,
  maxDrawdownPct: 10.0,
  maxGrossLeverage: 5.0,
  maxFxExposurePctAum: 30.0,
  maxRatesExposurePctAum: 100.0,
  maxCreditExposurePctAum: 50.0,
  maxSingleInstrumentPct: 60.0,
  minMarginBufferPct: 70.0,
};

/**
 * Compute factor exposure breakdown for risk dashboard.
 */
export function computeFactorExposure(
  positions: MtmPosition[],
  aumBrl: number,
  limits: RiskLimits = DEFAULT_RISK_LIMITS
): FactorExposure[] {
  let fxExposure = 0,
    ratesExposure = 0,
    creditExposure = 0;
  let fxRisk = 0,
    ratesRisk = 0,
    creditRisk = 0;

  for (const pos of positions) {
    const absNotional = Math.abs(pos.notionalBrl);
    switch (pos.instrument) {
      case "fx":
        fxExposure += absNotional;
        fxRisk += Math.abs(pos.fxDeltaBrl || 0);
        break;
      case "front":
      case "belly":
      case "long":
        ratesExposure += absNotional;
        ratesRisk += Math.abs(pos.dv01Brl || 0) * 100;
        break;
      case "hard":
        creditExposure += absNotional;
        creditRisk += Math.abs(pos.spreadDv01Usd || 0) * 50;
        break;
    }
  }

  const totalRisk = fxRisk + ratesRisk + creditRisk || 1;

  return [
    {
      factor: "fx",
      label: "Câmbio (FX)",
      exposureBrl: fxExposure,
      exposurePctAum: aumBrl > 0 ? (fxExposure / aumBrl) * 100 : 0,
      riskContributionPct: (fxRisk / totalRisk) * 100,
      limit: limits.maxFxExposurePctAum,
      limitPctAum: limits.maxFxExposurePctAum,
      utilizationPct:
        aumBrl > 0
          ? ((fxExposure / aumBrl) * 100) / limits.maxFxExposurePctAum * 100
          : 0,
      breached:
        aumBrl > 0 &&
        (fxExposure / aumBrl) * 100 > limits.maxFxExposurePctAum,
    },
    {
      factor: "rates",
      label: "Juros (Rates)",
      exposureBrl: ratesExposure,
      exposurePctAum: aumBrl > 0 ? (ratesExposure / aumBrl) * 100 : 0,
      riskContributionPct: (ratesRisk / totalRisk) * 100,
      limit: limits.maxRatesExposurePctAum,
      limitPctAum: limits.maxRatesExposurePctAum,
      utilizationPct:
        aumBrl > 0
          ? ((ratesExposure / aumBrl) * 100) / limits.maxRatesExposurePctAum * 100
          : 0,
      breached:
        aumBrl > 0 &&
        (ratesExposure / aumBrl) * 100 > limits.maxRatesExposurePctAum,
    },
    {
      factor: "credit",
      label: "Crédito (Hard Currency)",
      exposureBrl: creditExposure,
      exposurePctAum: aumBrl > 0 ? (creditExposure / aumBrl) * 100 : 0,
      riskContributionPct: (creditRisk / totalRisk) * 100,
      limit: limits.maxCreditExposurePctAum,
      limitPctAum: limits.maxCreditExposurePctAum,
      utilizationPct:
        aumBrl > 0
          ? ((creditExposure / aumBrl) * 100) / limits.maxCreditExposurePctAum * 100
          : 0,
      breached:
        aumBrl > 0 &&
        (creditExposure / aumBrl) * 100 > limits.maxCreditExposurePctAum,
    },
  ];
}

// ============================================================
// RISK ALERT ENGINE
// ============================================================

export interface RiskAlert {
  type:
    | "var_breach"
    | "drawdown_breach"
    | "margin_warning"
    | "regime_change"
    | "leverage_breach"
    | "factor_limit"
    | "rebalance_due";
  severity: "info" | "warning" | "critical";
  title: string;
  message: string;
  metricValue: number;
  thresholdValue: number;
  timestamp: string;
}

export interface RiskCheckInput {
  varDaily95Pct: number;
  currentDrawdownPct: number;
  grossLeverage: number;
  marginUtilizationPct: number;
  factorExposures: FactorExposure[];
  regime?: string;
  lastRebalanceDate?: string;
}

/**
 * Check all risk limits and generate alerts.
 */
export function checkRiskLimits(
  input: RiskCheckInput,
  limits: RiskLimits = DEFAULT_RISK_LIMITS
): RiskAlert[] {
  const alerts: RiskAlert[] = [];
  const now = new Date().toISOString();

  if (input.varDaily95Pct > limits.maxVarDaily95Pct) {
    alerts.push({
      type: "var_breach",
      severity:
        input.varDaily95Pct > limits.maxVarDaily95Pct * 1.5
          ? "critical"
          : "warning",
      title: `VaR diário 95% excedeu limite`,
      message: `VaR atual: ${input.varDaily95Pct.toFixed(2)}% do AUM (limite: ${limits.maxVarDaily95Pct}%).`,
      metricValue: input.varDaily95Pct,
      thresholdValue: limits.maxVarDaily95Pct,
      timestamp: now,
    });
  }

  if (Math.abs(input.currentDrawdownPct) > limits.maxDrawdownPct) {
    alerts.push({
      type: "drawdown_breach",
      severity:
        Math.abs(input.currentDrawdownPct) > limits.maxDrawdownPct * 1.5
          ? "critical"
          : "warning",
      title: `Drawdown excedeu limite`,
      message: `Drawdown atual: ${input.currentDrawdownPct.toFixed(2)}% (limite: -${limits.maxDrawdownPct}%).`,
      metricValue: input.currentDrawdownPct,
      thresholdValue: -limits.maxDrawdownPct,
      timestamp: now,
    });
  }

  if (input.grossLeverage > limits.maxGrossLeverage) {
    alerts.push({
      type: "leverage_breach",
      severity: "warning",
      title: `Alavancagem bruta excedeu limite`,
      message: `Alavancagem: ${input.grossLeverage.toFixed(1)}x (limite: ${limits.maxGrossLeverage}x).`,
      metricValue: input.grossLeverage,
      thresholdValue: limits.maxGrossLeverage,
      timestamp: now,
    });
  }

  if (input.marginUtilizationPct > 100 - limits.minMarginBufferPct) {
    alerts.push({
      type: "margin_warning",
      severity: input.marginUtilizationPct > 40 ? "critical" : "warning",
      title: `Margem utilizada acima do limite`,
      message: `Margem: ${input.marginUtilizationPct.toFixed(1)}% do AUM.`,
      metricValue: input.marginUtilizationPct,
      thresholdValue: 100 - limits.minMarginBufferPct,
      timestamp: now,
    });
  }

  for (const factor of input.factorExposures) {
    if (factor.breached) {
      alerts.push({
        type: "factor_limit",
        severity: "warning",
        title: `Exposição ${factor.label} excedeu limite`,
        message: `Exposição: ${factor.exposurePctAum.toFixed(1)}% do AUM (limite: ${factor.limitPctAum}%).`,
        metricValue: factor.exposurePctAum,
        thresholdValue: factor.limitPctAum,
        timestamp: now,
      });
    }
  }

  if (input.regime === "risk_off" || input.regime === "domestic_stress") {
    alerts.push({
      type: "regime_change",
      severity: input.regime === "risk_off" ? "critical" : "warning",
      title: `Regime: ${input.regime === "risk_off" ? "Risk-Off Global" : "Domestic Stress"}`,
      message: `Modelo detectou regime adverso. Revisar posições.`,
      metricValue: 0,
      thresholdValue: 0,
      timestamp: now,
    });
  }

  if (input.lastRebalanceDate) {
    const daysSinceRebal = Math.floor(
      (Date.now() - new Date(input.lastRebalanceDate).getTime()) / 86400000
    );
    if (daysSinceRebal > 30) {
      alerts.push({
        type: "rebalance_due",
        severity: daysSinceRebal > 45 ? "warning" : "info",
        title: `Rebalanceamento pendente`,
        message: `Último rebalanceamento: ${daysSinceRebal} dias atrás.`,
        metricValue: daysSinceRebal,
        thresholdValue: 30,
        timestamp: now,
      });
    }
  }

  return alerts;
}
