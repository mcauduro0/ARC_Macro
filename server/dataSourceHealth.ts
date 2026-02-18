/**
 * Data Source Health Service
 * Tracks the status, latency, and uptime of each external data source.
 * Integrates with the pipeline to record health metrics after each data collection run.
 */

import { getDb } from "./db";
import { dataSourceHealth } from "../drizzle/schema";
import { eq } from "drizzle-orm";

// ============================================================
// Data Source Registry
// ============================================================

export interface DataSourceDef {
  name: string;
  label: string;
  description: string;
  endpoint: string;
  checkFn: () => Promise<HealthCheckResult>;
}

export interface HealthCheckResult {
  status: "healthy" | "degraded" | "down";
  latencyMs: number;
  seriesCount?: number;
  lastDataDate?: string;
  error?: string;
}

interface HistoryEntry {
  timestamp: string;
  status: "healthy" | "degraded" | "down";
  latencyMs: number;
  error?: string;
}

const MAX_HISTORY_ENTRIES = 30;

/**
 * All data sources used by the ARC Macro model.
 */
// API keys from environment (with fallback defaults for development)
const FRED_KEY = process.env.FRED_API_KEY || "e63bf4ad4b21136be0b68c27e7e510d9";
const TE_KEY = process.env.TE_API_KEY || "DB5A57F91781451:A8A888DFE5F9495";
const FMP_KEY = process.env.FMP_API_KEY || "NzfGEUAOUqFjkYP0Q8AD48TapcCZVUEL";
const ANBIMA_CLIENT_ID_HEALTH = process.env.ANBIMA_CLIENT_ID || "qoSZCWnsbfSK";
const ANBIMA_CLIENT_SECRET_HEALTH = process.env.ANBIMA_CLIENT_SECRET || "xgAbycH1LIb0";

export const DATA_SOURCES: DataSourceDef[] = [
  {
    name: "bcb",
    label: "Banco Central do Brasil (SGS)",
    description: "SELIC, IPCA, PTAX, Dívida/PIB via SGS API",
    endpoint: "https://api.bcb.gov.br/dados/serie/bcdata.sgs.432/dados",
    checkFn: () => checkHttpEndpoint("https://api.bcb.gov.br/dados/serie/bcdata.sgs.432/dados?formato=json&dataInicial=01/01/2025", "bcb"),
  },
  {
    name: "fred",
    label: "Federal Reserve (FRED)",
    description: "US Treasury yields, VIX, DXY, NFCI, CPI, breakeven inflation",
    endpoint: "https://api.stlouisfed.org/fred/series/observations",
    checkFn: () => checkHttpEndpoint(`https://api.stlouisfed.org/fred/series/observations?series_id=DGS10&api_key=${FRED_KEY}&file_type=json&limit=5&sort_order=desc`, "fred"),
  },
  {
    name: "yahoo",
    label: "Yahoo Finance",
    description: "FX (USDBRL), commodities (iron ore, oil), VIX, DXY, equity indices",
    endpoint: "https://query1.finance.yahoo.com/v8/finance/chart/",
    checkFn: () => checkHttpEndpoint("https://query1.finance.yahoo.com/v8/finance/chart/BRL=X?range=5d&interval=1d", "yahoo"),
  },
  {
    name: "anbima",
    label: "ANBIMA Feed API",
    description: "DI curve (ETTJ), NTN-B/NTN-F yields, term structure (primary BR rates source)",
    endpoint: "https://api.anbima.com.br/feed/precos-indices/v1/titulos-publicos/mercado-secundario-TPF",
    checkFn: () => checkAnbimaEndpoint(),
  },
  {
    name: "trading_economics",
    label: "Trading Economics",
    description: "DI curve (3M-10Y) — fallback for BR rates",
    endpoint: "https://api.tradingeconomics.com/markets/historical/",
    checkFn: () => checkHttpEndpoint(`https://api.tradingeconomics.com/markets/historical/BRIRD1YT=RR?c=${TE_KEY}&d1=2025-01-01`, "trading_economics"),
  },
  {
    name: "ipeadata",
    label: "IPEADATA",
    description: "EMBI+ spread, SELIC Over, NTN-B yields",
    endpoint: "http://www.ipeadata.gov.br/api/oData4/ValoresSerie",
    checkFn: () => checkHttpEndpoint("http://www.ipeadata.gov.br/api/oData4/ValoresSerie(SERCODIGO='JPM366_EMBI366')?$top=5&$orderby=VALDATA%20desc&$format=json", "ipeadata"),
  },
  {
    name: "fmp",
    label: "Financial Modeling Prep",
    description: "US Treasury yields (backup), economic calendar",
    endpoint: "https://financialmodelingprep.com/api/v4/treasury",
    checkFn: () => checkHttpEndpoint(`https://financialmodelingprep.com/api/v4/treasury?from=2025-01-01&to=2025-01-10&apikey=${FMP_KEY}`, "fmp"),
  },
];

// ============================================================
// Health Check Functions
// ============================================================

async function checkHttpEndpoint(url: string, sourceName: string): Promise<HealthCheckResult> {
  const start = Date.now();
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);

    const response = await fetch(url, {
      signal: controller.signal,
      headers: {
        "User-Agent": "MacroRiskOS/4.1 HealthCheck",
      },
    });
    clearTimeout(timeout);

    const latencyMs = Date.now() - start;

    if (response.ok) {
      return {
        status: latencyMs > 10000 ? "degraded" : "healthy",
        latencyMs,
      };
    } else {
      return {
        status: response.status >= 500 ? "down" : "degraded",
        latencyMs,
        error: `HTTP ${response.status} ${response.statusText}`,
      };
    }
  } catch (error) {
    const latencyMs = Date.now() - start;
    const errMsg = error instanceof Error ? error.message : String(error);
    return {
      status: "down",
      latencyMs,
      error: errMsg.includes("abort") ? "Timeout (15s)" : errMsg,
    };
  }
}

async function checkAnbimaEndpoint(): Promise<HealthCheckResult> {
  const start = Date.now();
  try {
    // ANBIMA requires OAuth2 token first
    const authResponse = await fetch("https://api.anbima.com.br/oauth/access-token", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: "Basic " + Buffer.from(`${ANBIMA_CLIENT_ID_HEALTH}:${ANBIMA_CLIENT_SECRET_HEALTH}`).toString("base64"),
      },
      body: JSON.stringify({ grant_type: "client_credentials" }),
    });

    if (!authResponse.ok) {
      return {
        status: "down",
        latencyMs: Date.now() - start,
        error: `Auth failed: HTTP ${authResponse.status}`,
      };
    }

    const latencyMs = Date.now() - start;
    return {
      status: latencyMs > 10000 ? "degraded" : "healthy",
      latencyMs,
    };
  } catch (error) {
    return {
      status: "down",
      latencyMs: Date.now() - start,
      error: error instanceof Error ? error.message : String(error),
    };
  }
}

// ============================================================
// Health Check Execution
// ============================================================

/**
 * Run health checks on all data sources and persist results to DB.
 */
export async function checkAllDataSources(): Promise<Array<{
  name: string;
  label: string;
  status: "healthy" | "degraded" | "down" | "unknown";
  latencyMs: number;
  error?: string;
  uptimePercent: number;
  lastSuccessAt?: string;
  lastDataDate?: string;
  history: HistoryEntry[];
}>> {
  const db = await getDb();
  const results: Array<{
    name: string;
    label: string;
    status: "healthy" | "degraded" | "down" | "unknown";
    latencyMs: number;
    error?: string;
    uptimePercent: number;
    lastSuccessAt?: string;
    lastDataDate?: string;
    history: HistoryEntry[];
  }> = [];

  for (const source of DATA_SOURCES) {
    let checkResult: HealthCheckResult;
    try {
      checkResult = await source.checkFn();
    } catch (err) {
      checkResult = {
        status: "down",
        latencyMs: 0,
        error: err instanceof Error ? err.message : String(err),
      };
    }

    // Get existing record from DB
    let existing: any = null;
    if (db) {
      const rows = await db
        .select()
        .from(dataSourceHealth)
        .where(eq(dataSourceHealth.sourceName, source.name))
        .limit(1);
      existing = rows[0] || null;
    }

    // Build history
    const existingHistory: HistoryEntry[] = (existing?.historyJson as HistoryEntry[]) || [];
    const newEntry: HistoryEntry = {
      timestamp: new Date().toISOString(),
      status: checkResult.status,
      latencyMs: checkResult.latencyMs,
      ...(checkResult.error ? { error: checkResult.error } : {}),
    };
    const history = [...existingHistory, newEntry].slice(-MAX_HISTORY_ENTRIES);

    // Calculate uptime
    const checksTotal = (existing?.checksTotal || 0) + 1;
    const checksSuccess = (existing?.checksSuccess || 0) + (checkResult.status !== "down" ? 1 : 0);
    const uptimePercent = Math.round((checksSuccess / checksTotal) * 10000) / 100;

    // Upsert to DB
    if (db) {
      if (existing) {
        await db
          .update(dataSourceHealth)
          .set({
            status: checkResult.status,
            latencyMs: checkResult.latencyMs,
            ...(checkResult.status !== "down"
              ? { lastSuccessAt: new Date() }
              : { lastFailureAt: new Date(), lastError: checkResult.error }),
            seriesCount: checkResult.seriesCount ?? existing.seriesCount,
            lastDataDate: checkResult.lastDataDate ?? existing.lastDataDate,
            checksTotal,
            checksSuccess,
            uptimePercent,
            historyJson: history,
          } as any)
          .where(eq(dataSourceHealth.id, existing.id));
      } else {
        await db.insert(dataSourceHealth).values({
          sourceName: source.name,
          sourceLabel: source.label,
          status: checkResult.status,
          latencyMs: checkResult.latencyMs,
          ...(checkResult.status !== "down"
            ? { lastSuccessAt: new Date() }
            : { lastFailureAt: new Date(), lastError: checkResult.error }),
          seriesCount: checkResult.seriesCount ?? 0,
          lastDataDate: checkResult.lastDataDate,
          checksTotal: 1,
          checksSuccess: checkResult.status !== "down" ? 1 : 0,
          uptimePercent: checkResult.status !== "down" ? 100 : 0,
          historyJson: [newEntry],
        });
      }
    }

    results.push({
      name: source.name,
      label: source.label,
      status: checkResult.status,
      latencyMs: checkResult.latencyMs,
      error: checkResult.error,
      uptimePercent,
      lastSuccessAt: existing?.lastSuccessAt
        ? new Date(existing.lastSuccessAt).toISOString()
        : checkResult.status !== "down"
          ? new Date().toISOString()
          : undefined,
      lastDataDate: checkResult.lastDataDate ?? existing?.lastDataDate,
      history,
    });
  }

  return results;
}

/**
 * Get the latest health status from DB (no live check).
 */
export async function getDataSourceHealthStatus(): Promise<Array<{
  name: string;
  label: string;
  status: "healthy" | "degraded" | "down" | "unknown";
  latencyMs: number | null;
  error?: string | null;
  uptimePercent: number;
  lastSuccessAt?: string | null;
  lastDataDate?: string | null;
  history: HistoryEntry[];
}>> {
  const db = await getDb();
  if (!db) return [];

  const rows = await db.select().from(dataSourceHealth);

  return rows.map((row) => ({
    name: row.sourceName,
    label: row.sourceLabel,
    status: row.status as "healthy" | "degraded" | "down" | "unknown",
    latencyMs: row.latencyMs,
    error: row.lastError,
    uptimePercent: row.uptimePercent ?? 100,
    lastSuccessAt: row.lastSuccessAt ? new Date(row.lastSuccessAt).toISOString() : null,
    lastDataDate: row.lastDataDate,
    history: (row.historyJson as HistoryEntry[]) || [],
  }));
}
