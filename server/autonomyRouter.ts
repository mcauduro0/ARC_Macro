// tRPC proxy for the ARC 2.0 autonomy bridge (arc/webapi FastAPI). Falls back to demo data when offline.
// Operator decisions are stored locally in the MySQL database (operator_decisions table) so the
// Co-Pilot works end-to-end without the Python bridge running.
import { z } from "zod";
import { eq, and, desc } from "drizzle-orm";
import type { DecideInput, LedgerResponse, WebState } from "@shared/autonomy";
import { publicProcedure, router } from "./_core/trpc";
import { FALLBACK_WEB_STATE } from "./autonomyFallback";
import { getDb } from "./db";
import { operatorDecisions } from "../drizzle/schema";

export const ARC_API_BASE = process.env.ARC_API_URL ?? "http://localhost:8787";

/** GET a JSON resource from the ARC FastAPI bridge; returns null on failure (graceful). */
async function arcApiGetOrNull<T>(path: string): Promise<T | null> {
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 3000);
    const res = await fetch(`${ARC_API_BASE}${path}`, {
      headers: { accept: "application/json" },
      signal: controller.signal,
    });
    clearTimeout(timeout);
    if (!res.ok) return null;
    return (await res.json()) as T;
  } catch {
    return null;
  }
}

/** Load all operator decisions from the local DB for a given strategy. */
async function getDecisionsForStrategy(strategy: string) {
  const db = await getDb();
  if (!db) return [];
  try {
    return await db
      .select()
      .from(operatorDecisions)
      .where(eq(operatorDecisions.strategy, strategy))
      .orderBy(desc(operatorDecisions.createdAt));
  } catch {
    return [];
  }
}

/** Check if a decision already exists for (strategy, month) — immutability guard. */
async function decisionExists(strategy: string, month: string): Promise<boolean> {
  const db = await getDb();
  if (!db) return false;
  try {
    const rows = await db
      .select({ id: operatorDecisions.id })
      .from(operatorDecisions)
      .where(and(eq(operatorDecisions.strategy, strategy), eq(operatorDecisions.month, month)))
      .limit(1);
    return rows.length > 0;
  } catch {
    return false;
  }
}

/** Enrich the fallback WebState with decisions stored in the local DB. */
async function enrichStateWithDbDecisions(state: WebState): Promise<WebState> {
  const db = await getDb();
  if (!db) return state;

  try {
    const allDecisions = await db
      .select()
      .from(operatorDecisions)
      .orderBy(desc(operatorDecisions.createdAt));

    if (allDecisions.length === 0) return state;

    // Group decisions by strategy
    const byStrategy = new Map<string, typeof allDecisions>();
    for (const d of allDecisions) {
      const arr = byStrategy.get(d.strategy) ?? [];
      arr.push(d);
      byStrategy.set(d.strategy, arr);
    }

    // Update each sleeve with its decisions
    const enrichedSleeves = state.sleeves.map((sleeve) => {
      const decisions = byStrategy.get(sleeve.name);
      if (!decisions || decisions.length === 0) return sleeve;

      const latest = decisions[0]; // most recent decision for this strategy
      const currentMonth = sleeve.proposal?.month;

      // Update n_operator_decisions count
      const enriched = {
        ...sleeve,
        n_operator_decisions: decisions.length,
        last_operator_decision: {
          month: latest.month,
          action: latest.action,
          operator_position: latest.operatorPosition,
          proposed_position: latest.proposedPosition,
          rationale: latest.rationale ?? "",
          decided_by: latest.decidedBy,
        },
      };

      // If the latest decision is for the current proposal month, mark as decided
      if (currentMonth && latest.month === currentMonth && enriched.proposal) {
        enriched.proposal = {
          ...enriched.proposal,
          operator_decided: true,
        };
      }

      return enriched;
    });

    return { ...state, sleeves: enrichedSleeves };
  } catch {
    return state;
  }
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
  state: publicProcedure.query(async () => {
    // Try the live Python bridge first
    const live = await arcApiGetOrNull<WebState>("/api/autonomy/state");
    const baseState = live ?? FALLBACK_WEB_STATE;
    // Enrich with locally stored operator decisions
    return enrichStateWithDbDecisions(baseState);
  }),

  /** Just the engine-computed current proposals (empty until the dump job runs). */
  proposals: publicProcedure.query(async () => {
    const live = await arcApiGetOrNull<Record<string, unknown>>("/api/autonomy/proposals");
    return live ?? {};
  }),

  /** Raw immutable ledger records for one sleeve. */
  ledger: publicProcedure
    .input(z.object({ strategy: z.string() }))
    .query(async ({ input }) => {
      const live = await arcApiGetOrNull<LedgerResponse>(`/api/autonomy/ledger/${input.strategy}`);
      if (live) return live;

      // Fallback: build ledger from local DB decisions
      const decisions = await getDecisionsForStrategy(input.strategy);
      const operatorDecisionRecords = decisions.map((d) => ({
        month: d.month,
        strategy_hash: d.strategyHash,
        action: d.action,
        proposed_position: d.proposedPosition,
        operator_position: d.operatorPosition,
        rationale: d.rationale ?? "",
        decided_by: d.decidedBy,
        proposal_digest: d.proposalDigest ?? "",
        run_id: "local",
        decided_at: d.createdAt?.toISOString() ?? new Date().toISOString(),
      }));

      return {
        strategy: input.strategy,
        decisions: [],
        realizations: { frozen: [], live: [], operator: [] },
        operator_decisions: operatorDecisionRecords,
      } satisfies LedgerResponse;
    }),

  /** Record a co-pilot operator decision (immutable; touches only the operator stream).
   *  Stores in local DB. Does NOT require the Python bridge to be running. */
  decide: publicProcedure.input(decideSchema).mutation(async ({ input }) => {
    const db = await getDb();
    if (!db) {
      throw new Error("Database unavailable — cannot persist decision");
    }

    // Immutability check: reject if (strategy, month) already decided
    const exists = await decisionExists(input.strategy, input.month);
    if (exists) {
      throw new Error(`IMMUTABLE: decision for (${input.strategy}, ${input.month}) already exists — cannot overwrite`);
    }

    // Determine the operator position based on action
    let operatorPosition: number;
    if (input.action === "APPROVE") {
      // Get the proposed position from the current state
      const state = await arcApiGetOrNull<WebState>("/api/autonomy/state") ?? FALLBACK_WEB_STATE;
      const sleeve = state.sleeves.find((s) => s.name === input.strategy);
      operatorPosition = sleeve?.proposal?.proposed_position ?? input.position ?? 0;
    } else if (input.action === "SKIP") {
      operatorPosition = 0;
    } else {
      // OVERRIDE: use the provided position
      operatorPosition = input.position ?? 0;
    }

    // Get strategy hash and proposal digest from current state
    const state = await arcApiGetOrNull<WebState>("/api/autonomy/state") ?? FALLBACK_WEB_STATE;
    const sleeve = state.sleeves.find((s) => s.name === input.strategy);
    const strategyHash = sleeve?.hash ?? "unknown";
    const proposalDigest = sleeve?.proposal?.proposal_digest ?? "";
    const proposedPosition = sleeve?.proposal?.proposed_position ?? 0;

    // Insert into DB
    await db.insert(operatorDecisions).values({
      strategy: input.strategy,
      month: input.month,
      strategyHash,
      action: input.action,
      proposedPosition,
      operatorPosition,
      rationale: input.rationale || null,
      decidedBy: input.decided_by,
      proposalDigest: proposalDigest || null,
    });

    return {
      ok: true,
      decision: {
        strategy: input.strategy,
        month: input.month,
        action: input.action,
        operator_position: operatorPosition,
        proposed_position: proposedPosition,
        rationale: input.rationale,
        decided_by: input.decided_by,
      },
    };
  }),
});
