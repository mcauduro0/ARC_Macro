// ARC Macro 2.0 — typed contract for the autonomy web state.
// Mirrors arc/webapi/state.py exactly. Shared by the Node/tRPC proxy (server/autonomyRouter.ts) and the
// React app (client/src/arc). Honesty contract: pre-verdict the payload carries ONLY operational state
// (counts, positions, returns, drawdown) — never a forward Sharpe/DSR; `verdict` is null until the
// one-shot holdout fires.

export type ReadinessState = "ACCRUING" | "READY" | "OVERSHOT" | "SPENT" | "UNBOOKED";

export interface StreamSummary {
  n: number;
  cum_return: number;
  last_position: number;
  max_drawdown: number;
}

export interface SleeveContract {
  n_trials: number | null;
  eval_at_n: number;
  dsr_min: number;
  forward_start: string | null;
  booked: boolean;
}

export interface Readiness {
  ready: boolean;
  state: ReadinessState;
  message: string;
}

export interface Verdict {
  passed: boolean;
  reason: string;
  dsr: number;
  sr_annual: number;
  n: number;
  dsr_min: number;
  n_trials: number;
}

export interface Proposal {
  asof: string;
  strategy: string;
  strategy_hash: string;
  month: string;
  action_suggestion: string; // OPERATE | HALT | HOLD(warmup)
  frozen_position: number;
  proposed_position: number;
  target_vol_ann: number;
  leverage_for_vol_target: number;
  sized_exposure: number;
  circuit_halted: boolean;
  circuit_reasons: string[];
  drift_warnings: string[];
  n_frozen_months: number;
  operator_decided: boolean;
  operator_pnl: Record<string, number>;
  proposal_digest: string;
  note: string;
  var_forecast: number;
  es_forecast: number;
  risk_gate_binding: string; // vol_target | var_limit | es_limit | inactive | ""
  risk_gate_active: boolean;
}

export interface OperatorDecisionInfo {
  month: string;
  action: string;
  operator_position: number;
  proposed_position: number;
  rationale: string;
  decided_by: string;
}

export interface Sleeve {
  name: string;
  instrument: string;
  instrument_label: string;
  kind: string;
  hash: string;
  contract: SleeveContract;
  n_forward_months: number;
  months_to_verdict: number;
  readiness: Readiness;
  verdict: Verdict | null;
  streams: { frozen: StreamSummary; live: StreamSummary; operator: StreamSummary };
  n_operator_decisions: number;
  last_operator_decision: OperatorDecisionInfo | null;
  proposal: Proposal | null;
}

export interface Pool {
  name: string;
  hash: string;
  members: string[];
  contract: SleeveContract;
  n_common_forward_months: number;
  months_to_verdict: number;
  readiness: Readiness;
  verdict: Verdict | null;
  rationale: string;
}

export interface WebStateMeta {
  as_of: string | null;
  dumped_at: string | null;
  data_through: string | null;
  n_promoted: number;
  honesty: string;
  has_proposals: boolean;
}

export interface WebState {
  meta: WebStateMeta;
  sleeves: Sleeve[];
  pool: Pool;
  macro: unknown | null;
}

// ---------------------------------------------------------------------------
// Raw immutable ledger records — mirror arc/autonomy/ledger.py dataclasses exactly.
// Served by GET /api/autonomy/ledger/{strategy} for the Ledger/Audit + Research screens.
// ---------------------------------------------------------------------------
export interface LedgerDecision {
  month: string;
  strategy_hash: string;
  frozen_position: number;
  live_position: number;
  signal: number;
  signal_z: number;
  data_max_knowledge_time: string;
  input_digest: string;
  run_id: string;
  created_at: string;
}

export interface LedgerRealization {
  month: string;
  strategy_hash: string;
  stream: string; // frozen | live | operator
  held_position: number;
  prev_held: number;
  realized_return: number;
  sleeve_return: number;
  realized_knowledge_time: string;
  return_vintage_seq: number;
  reconciled_at: string;
  run_id: string;
}

export interface LedgerOperatorDecision {
  month: string;
  strategy_hash: string;
  action: string; // APPROVE | OVERRIDE | SKIP
  proposed_position: number;
  operator_position: number;
  rationale: string;
  decided_by: string;
  proposal_digest: string;
  run_id: string;
  decided_at: string;
}

export interface LedgerResponse {
  strategy: string;
  decisions: LedgerDecision[];
  realizations: { frozen: LedgerRealization[]; live: LedgerRealization[]; operator: LedgerRealization[] };
  operator_decisions: LedgerOperatorDecision[];
}

export type DecideAction = "APPROVE" | "OVERRIDE" | "SKIP";

export interface DecideInput {
  strategy: string;
  month: string;
  action: DecideAction;
  rationale?: string;
  decided_by?: string;
  position?: number | null;
  decided_at?: string;
}
