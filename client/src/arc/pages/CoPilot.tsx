// Co-pilot — the human-in-the-loop workspace. The loop PROPOSES; the operator DECIDES (APPROVE / OVERRIDE /
// SKIP). Each decision is immutable and feeds the SEPARATE `operator` stream — it can never touch the frozen
// scored holdout, which accrues deterministically toward its one-shot verdict. This screen shows, per sleeve:
// the current proposal, the three streams (frozen / live / operator), the last committed decision, and the
// decide control.
import { useState } from "react";
import type { ReactNode } from "react";
import type { DecideAction, Sleeve, StreamSummary, WebState } from "@shared/autonomy";
import { Pct, Pos, Tag, actionTag } from "../components";
import { useAutonomyState, useDecide } from "../useAutonomy";

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <div className="mesa-label">{label}</div>
      <div className="mesa-num mesa-h" style={{ fontSize: 13 }}>{children}</div>
    </div>
  );
}

function StreamCell({ name, s }: { name: string; s: StreamSummary }) {
  return (
    <div className="mesa-panel" style={{ padding: "8px 10px", flex: 1, minWidth: 120 }}>
      <div className="flex items-center justify-between" style={{ marginBottom: 4 }}>
        <span className="mesa-label">{name}</span>
        <span className="mesa-num mesa-dim" style={{ fontSize: 11 }}>n={s.n}</span>
      </div>
      <div className="flex items-center justify-between">
        <span className="mesa-label">cum</span>
        <Pct value={Number.isNaN(s.cum_return) ? null : s.cum_return} />
      </div>
      <div className="flex items-center justify-between">
        <span className="mesa-label">max dd</span>
        <span className={s.max_drawdown < 0 ? "mesa-num mesa-neg" : "mesa-num mesa-dim"}>
          {Number.isNaN(s.max_drawdown) ? "—" : `${(s.max_drawdown * 100).toFixed(1)}%`}
        </span>
      </div>
      <div className="flex items-center justify-between">
        <span className="mesa-label">pos</span>
        <Pos value={Number.isNaN(s.last_position) ? null : s.last_position} />
      </div>
    </div>
  );
}

function DecideForm({ sleeve, month }: { sleeve: Sleeve; month: string }) {
  const decide = useDecide();
  const [action, setAction] = useState<DecideAction>("APPROVE");
  const [position, setPosition] = useState("");
  const [rationale, setRationale] = useState("");

  const proposed = sleeve.proposal?.proposed_position;
  const canSubmit =
    !decide.isPending && (action !== "OVERRIDE" || (position.trim() !== "" && !Number.isNaN(Number(position))));

  const submit = () => {
    decide.mutate({
      strategy: sleeve.name,
      month,
      action,
      rationale: rationale.trim(),
      decided_by: "owner",
      position: action === "OVERRIDE" ? Number(position) : null,
    });
  };

  const actions: { a: DecideAction; hint: string }[] = [
    { a: "APPROVE", hint: proposed == null ? "take the proposed position" : `take ${proposed.toFixed(3)}` },
    { a: "SKIP", hint: "stay flat (0.0)" },
    { a: "OVERRIDE", hint: "set your own position" },
  ];

  if (decide.isSuccess) {
    return (
      <div className="mesa-panel" style={{ padding: "10px 12px", borderColor: "rgba(52,211,153,0.4)" }}>
        <span className="mesa-num mesa-pos">✓ committed</span>
        <span className="mesa-label" style={{ marginLeft: 8 }}>
          {action} for {month} — operator stream updated. The frozen holdout was not touched.
        </span>
      </div>
    );
  }

  return (
    <div className="mesa-panel" style={{ padding: "10px 12px" }}>
      <div className="flex items-center" style={{ gap: 6, flexWrap: "wrap" }}>
        {actions.map(({ a, hint }) => (
          <button
            key={a}
            type="button"
            onClick={() => setAction(a)}
            className={`mesa-tag ${action === a ? actionBtnKind(a) : ""}`}
            style={{ cursor: "pointer", background: "transparent", opacity: action === a ? 1 : 0.55 }}
            title={hint}
          >
            {a}
          </button>
        ))}
        {action === "OVERRIDE" && (
          <input
            value={position}
            onChange={(e) => setPosition(e.target.value)}
            placeholder="position e.g. -1.0"
            className="mesa-num"
            style={inputStyle}
            inputMode="decimal"
          />
        )}
        <input
          value={rationale}
          onChange={(e) => setRationale(e.target.value)}
          placeholder="rationale (optional)"
          style={{ ...inputStyle, flex: 1, minWidth: 160 }}
        />
        <button
          type="button"
          onClick={submit}
          disabled={!canSubmit}
          className="mesa-tag"
          style={{
            cursor: canSubmit ? "pointer" : "not-allowed",
            background: canSubmit ? "rgba(245,165,36,0.12)" : "transparent",
            borderColor: "rgba(245,165,36,0.5)", color: "var(--amber)", opacity: canSubmit ? 1 : 0.4,
          }}
        >
          {decide.isPending ? "committing…" : `commit ${action}`}
        </button>
      </div>
      {decide.error && (
        <div className="mesa-label mesa-neg" style={{ marginTop: 8, lineHeight: 1.6 }}>
          rejected: {decide.error.message}
        </div>
      )}
      <div className="mesa-label" style={{ marginTop: 8 }}>
        Decides month {month}. APPROVE/OVERRIDE/SKIP is immutable per (month, hash) — a different later choice
        is rejected by the ledger.
      </div>
    </div>
  );
}

function actionBtnKind(a: DecideAction): string {
  if (a === "APPROVE") return "operate";
  if (a === "SKIP") return "warmup";
  return "accruing";
}

const inputStyle: React.CSSProperties = {
  background: "var(--panel-2)", border: "1px solid var(--line-2)", color: "var(--txt)",
  fontFamily: "inherit", fontSize: 12, padding: "3px 8px", outline: "none",
};

function SleeveCard({ sleeve }: { sleeve: Sleeve }) {
  const p = sleeve.proposal;
  const at = actionTag(p?.action_suggestion);
  const decided = Boolean(p?.operator_decided);
  const month = p?.month ?? "";
  const last = sleeve.last_operator_decision;

  return (
    <section className="mesa-panel" style={{ padding: 14 }}>
      <header className="flex items-center justify-between" style={{ marginBottom: 12 }}>
        <div className="flex items-center" style={{ gap: 10 }}>
          <span className="mesa-h" style={{ fontSize: 14 }}>{sleeve.name}</span>
          <span className="mesa-label">{sleeve.instrument_label}</span>
          <Tag kind={at.kind}>{at.label}</Tag>
        </div>
        <span className="mesa-label mesa-num">
          {sleeve.n_operator_decisions} operator decision{sleeve.n_operator_decisions === 1 ? "" : "s"}
        </span>
      </header>

      {!p && (
        <div className="mesa-label" style={{ lineHeight: 1.7 }}>
          No proposal cached — run <span className="mesa-amber">python scripts/dump_web_state.py</span>.
        </div>
      )}

      {p && (
        <>
          <div className="flex" style={{ gap: 22, flexWrap: "wrap", marginBottom: 12 }}>
            <Field label="month">{month || "warmup"}</Field>
            <Field label="frozen (scored)"><Pos value={p.frozen_position} /></Field>
            <Field label="proposed (live)"><Pos value={p.proposed_position} /></Field>
            <Field label="sized exposure"><Pos value={p.sized_exposure} /></Field>
            {p.risk_gate_active && <Field label="VaR95"><Pct value={p.var_forecast} /></Field>}
            {p.circuit_halted && <Field label="circuit"><span className="mesa-neg">HALTED</span></Field>}
          </div>

          <div className="flex" style={{ gap: 8, marginBottom: 12 }}>
            <StreamCell name="frozen" s={sleeve.streams.frozen} />
            <StreamCell name="live" s={sleeve.streams.live} />
            <StreamCell name="operator" s={sleeve.streams.operator} />
          </div>

          {(p.circuit_reasons.length > 0 || p.drift_warnings.length > 0) && (
            <div className="mesa-label" style={{ marginBottom: 12, lineHeight: 1.6 }}>
              {p.circuit_reasons.map((r, i) => <div key={`c${i}`} className="mesa-neg">⚠ {r}</div>)}
              {p.drift_warnings.map((r, i) => <div key={`d${i}`} className="mesa-amber">⚠ {r}</div>)}
            </div>
          )}

          {decided && last && last.month === month ? (
            <div className="mesa-panel" style={{ padding: "10px 12px", borderColor: "rgba(96,165,250,0.4)" }}>
              <div className="flex items-center" style={{ gap: 10 }}>
                <span className="mesa-label">committed</span>
                <Tag kind={last.action === "APPROVE" ? "operate" : last.action === "SKIP" ? "warmup" : "accruing"}>
                  {last.action}
                </Tag>
                <span className="mesa-label">took</span>
                <Pos value={last.operator_position} />
                <span className="mesa-label">by {last.decided_by}</span>
              </div>
              {last.rationale && (
                <div className="mesa-label" style={{ marginTop: 6 }}>“{last.rationale}”</div>
              )}
              <div className="mesa-label" style={{ marginTop: 6 }}>
                Immutable for {month} — re-deciding is rejected by the ledger.
              </div>
            </div>
          ) : month ? (
            <DecideForm sleeve={sleeve} month={month} />
          ) : (
            <div className="mesa-label">Warming up — no decidable month yet.</div>
          )}
        </>
      )}
    </section>
  );
}

function CoPilotView({ data }: { data: WebState }) {
  return (
    <div className="flex flex-col" style={{ gap: 16 }}>
      <div className="mesa-banner flex items-center justify-between" style={{ padding: "10px 14px" }}>
        <div className="flex items-center" style={{ gap: 10 }}>
          <span style={{ fontSize: 13 }}>◆</span>
          <span className="mesa-num">
            The loop proposes; you decide. APPROVE / OVERRIDE / SKIP feeds the operator stream — the frozen
            holdout is untouchable.
          </span>
        </div>
        {!data.meta.has_proposals && <span className="mesa-num mesa-h">proposals stale</span>}
      </div>

      <div className="flex flex-col" style={{ gap: 14 }}>
        {data.sleeves.map((s) => <SleeveCard key={s.name} sleeve={s} />)}
      </div>

      <p className="mesa-label" style={{ lineHeight: 1.7 }}>
        Three streams per sleeve: <span className="mesa-h">frozen</span> (deterministic scored holdout — the
        verdict's only input), <span className="mesa-h">live</span> (auto-operate baseline), and{" "}
        <span className="mesa-h">operator</span> (your decisions). Only the operator stream responds to the
        buttons above; promotion remains a separate, token-gated, human-issued call.
      </p>
    </div>
  );
}

function Offline({ message }: { message?: string }) {
  return (
    <div className="mesa-panel" style={{ padding: 16, borderColor: "rgba(248,113,113,0.4)" }}>
      <div className="mesa-h" style={{ marginBottom: 8 }}>ARC API bridge offline</div>
      <div className="mesa-label" style={{ lineHeight: 1.8 }}>
        Start the bridge: <span className="mesa-amber">uvicorn arc.webapi.app:app --port 8787</span><br />
        Refresh proposals: <span className="mesa-amber">python scripts/dump_web_state.py</span>
        {message && <><br /><span className="mesa-neg">{message}</span></>}
      </div>
    </div>
  );
}

export function CoPilot() {
  const { data, isLoading, error } = useAutonomyState();
  if (isLoading) return <div className="mesa-label" style={{ padding: 8 }}>loading co-pilot…</div>;
  if (error || !data) return <Offline message={error?.message} />;
  return <CoPilotView data={data} />;
}
