// tRPC proxy for the ARC 2.0 autonomy bridge (arc/webapi FastAPI). The React app stays on tRPC + React
// Query; this router forwards to the Python service so the UI talks to the SAME arc.autonomy functions
// the CLI does. The FastAPI base URL is ARC_API_URL (default http://localhost:8787).

import { z } from "zod";
import type { DecideInput, WebState } from "@shared/autonomy";
import { publicProcedure, router } from "./_core/trpc";

export const ARC_API_BASE = process.env.ARC_API_URL ?? "http://localhost:8787";

/** GET a JSON resource from the ARC FastAPI bridge; throws a readable error on a non-2xx. */
export async function arcApiGet<T>(path: string): Promise<T> {
  const res = await fetch(`${ARC_API_BASE}${path}`, { headers: { accept: "application/json" } });
  if (!res.ok) {
    throw new Error(`ARC API GET ${path} failed (${res.status})`);
  }
  return (await res.json()) as T;
}

/** POST a co-pilot decision; surfaces the FastAPI `detail` (409 immutable / 400 invalid) as the error. */
export async function arcApiDecide(input: DecideInput): Promise<{ ok: boolean; decision: unknown }> {
  const res = await fetch(`${ARC_API_BASE}/api/autonomy/decide`, {
    method: "POST",
    headers: { "content-type": "application/json", accept: "application/json" },
    body: JSON.stringify(input),
  });
  const body = (await res.json().catch(() => ({}))) as { detail?: unknown; ok?: boolean; decision?: unknown };
  if (!res.ok) {
    const detail = typeof body?.detail === "string" ? body.detail : `decide failed (${res.status})`;
    throw new Error(detail);
  }
  return { ok: Boolean(body.ok), decision: body.decision };
}

const decideSchema = z.object({
  strategy: z.string(),
  month: z.string(),
  action: z.enum(["APPROVE", "OVERRIDE", "SKIP"]),
  rationale: z.string().default(""),
  decided_by: z.string().default("owner"),
  position: z.number().nullable().optional(),
  decided_at: z.string().default(""),
});

export const autonomyRouter = router({
  /** Full web state: per-sleeve contract/readiness/streams + pool + cached proposals (honest, no scores). */
  state: publicProcedure.query(() => arcApiGet<WebState>("/api/autonomy/state")),

  /** Just the engine-computed current proposals (empty until the dump job runs). */
  proposals: publicProcedure.query(() => arcApiGet<Record<string, unknown>>("/api/autonomy/proposals")),

  /** Raw immutable ledger records for one sleeve. */
  ledger: publicProcedure
    .input(z.object({ strategy: z.string() }))
    .query(({ input }) => arcApiGet<Record<string, unknown>>(`/api/autonomy/ledger/${input.strategy}`)),

  /** Record a co-pilot operator decision (immutable; touches only the operator stream). */
  decide: publicProcedure.input(decideSchema).mutation(({ input }) => arcApiDecide(input)),
});
