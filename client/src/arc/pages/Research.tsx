// Research / Diagnostics — honest diagnostics. We surface (a) LIVE operational diagnostics from the current
// proposals (sizing gate, freeze depth, drift/circuit counts) and (b) the DOCUMENTED measurement discipline.
// We never fabricate result numbers: no invented IC/SHAP/null values, and never a forward Sharpe/DSR pre-verdict.
import type { ReactNode } from "react";
import type { Proposal, Sleeve, WebState } from "@shared/autonomy";
import { actionTag, Pct, Pos, Tag } from "../components";
import { useAutonomyState } from "../useAutonomy";

function HeadCell({ children, w }: { children: ReactNode; w?: number }) {
  return (
    <th className="mesa-label" style={{ textAlign: "left", padding: "6px 10px", width: w }}>
      {children}
    </th>
  );
}

function Num({ children }: { children: ReactNode }) {
  return <td style={{ padding: "9px 10px", textAlign: "right" }} className="mesa-num">{children}</td>;
}

/** Gate label — only the binding gate, or "inactive". This is operational sizing, not a track record. */
function gateLabel(p: Proposal): { text: string; active: boolean } {
  if (!p.risk_gate_active) return { text: "inactive", active: false };
  const b = p.risk_gate_binding;
  return { text: b && b !== "inactive" ? b : "active", active: true };
}

function DiagRow({ s }: { s: Sleeve }) {
  const p = s.proposal;
  if (!p) {
    return (
      <tr className="mesa-row mesa-rowhover">
        <td style={{ padding: "9px 10px" }}>
          <div className="mesa-h">{s.name}</div>
          <div className="mesa-label">{s.instrument_label}</div>
        </td>
        <td style={{ padding: "9px 10px" }} className="mesa-dim" colSpan={5}>
          no proposal — run <span className="mesa-amber">python scripts/dump_web_state.py</span>
        </td>
      </tr>
    );
  }
  const at = actionTag(p.action_suggestion);
  const gate = gateLabel(p);
  return (
    <tr className="mesa-row mesa-rowhover">
      <td style={{ padding: "9px 10px" }}>
        <div className="mesa-h">{s.name}</div>
        <div className="mesa-label">{s.instrument_label}</div>
      </td>
      <td style={{ padding: "9px 10px" }}><Tag kind={at.kind}>{at.label}</Tag></td>
      <td style={{ padding: "9px 10px" }}>
        <Tag kind={gate.active ? "operate" : "spent"}>{gate.text}</Tag>
      </td>
      <Num><span className="mesa-h">{p.n_frozen_months}</span></Num>
      <td style={{ padding: "9px 10px", textAlign: "right" }}>
        <span className={p.drift_warnings.length ? "mesa-num mesa-amber" : "mesa-num mesa-dim"}>
          {p.drift_warnings.length}
        </span>
      </td>
      <td style={{ padding: "9px 10px", textAlign: "right" }}>
        <span className={p.circuit_reasons.length ? "mesa-num mesa-neg" : "mesa-num mesa-dim"}>
          {p.circuit_reasons.length}
        </span>
      </td>
    </tr>
  );
}

const DISCIPLINE: { rule: string; how: string }[] = [
  {
    rule: "forward-only one-shot holdout",
    how: "the verdict fires once, at eval_at_n; no optional stopping, no peeking, no re-runs",
  },
  {
    rule: "deflation for cumulative trials",
    how: "DSR penalises the running hypothesis count (n_trials) before any pass is granted",
  },
  {
    rule: "as-of / point-in-time data",
    how: "every input is stamped to its publication lag; no future bars enter a decision",
  },
  {
    rule: "leakage canaries",
    how: "a beautiful backtest is treated as leakage until the forward window disproves it",
  },
  {
    rule: "operator overlay is sandboxed",
    how: "the human overlay books its own stream and can never touch the scored holdout",
  },
];

function DisciplineRow({ rule, how }: { rule: string; how: string }) {
  return (
    <div className="mesa-row mesa-rowhover flex items-center justify-between" style={{ padding: "8px 12px", gap: 16 }}>
      <span className="mesa-h" style={{ minWidth: 220 }}>{rule}</span>
      <span className="mesa-label" style={{ textAlign: "right", lineHeight: 1.5 }}>{how}</span>
    </div>
  );
}

function StreamCells({ s, stream }: { s: Sleeve; stream: "frozen" | "live" | "operator" }) {
  const x = s.streams[stream];
  return (
    <tr className="mesa-row mesa-rowhover">
      <td style={{ padding: "9px 10px" }}>
        <div className="mesa-h">{s.name}</div>
        <div className="mesa-label">{stream}</div>
      </td>
      <Num><span className="mesa-h">{x.n}</span></Num>
      <Num><Pct value={x.cum_return} /></Num>
      <Num><Pct value={x.max_drawdown} /></Num>
      <Num><Pos value={x.last_position} /></Num>
    </tr>
  );
}

function ResearchView({ data }: { data: WebState }) {
  const { meta, sleeves } = data;
  const proposing = sleeves.filter((s) => s.proposal);
  const operate = proposing.filter((s) => s.proposal!.action_suggestion === "OPERATE").length;
  const halt = proposing.filter((s) => s.proposal!.action_suggestion === "HALT").length;
  const warmup = proposing.length - operate - halt;
  const gatesActive = proposing.filter((s) => s.proposal!.risk_gate_active).length;

  return (
    <div className="flex flex-col" style={{ gap: 16 }}>
      <div className="mesa-banner flex items-center" style={{ padding: "10px 14px", gap: 10 }}>
        <span style={{ fontSize: 13 }}>⚠</span>
        <span className="mesa-num">
          Honest diagnostics. We report nulls where null and deflate for the cumulative hypothesis count.
          A beautiful backtest is treated as leakage until disproven.
        </span>
      </div>

      <div className="flex" style={{ gap: 24 }}>
        <Meta label="data through" value={meta.data_through} />
        <Meta label="as of" value={meta.as_of} />
        <Meta label="proposals" value={meta.has_proposals ? "fresh" : "stale (run dump)"} />
      </div>

      {/* (a) LIVE operational diagnostics from the current proposals */}
      <section className="mesa-panel">
        <header className="flex items-center justify-between px-3 py-2 border-b mesa-divider">
          <span className="mesa-label">Current diagnostics · live proposals</span>
          <span className="mesa-label">
            {operate} OPERATE · {halt} HALT · {warmup} WARMUP · {gatesActive} gate{gatesActive === 1 ? "" : "s"} active
          </span>
        </header>
        {proposing.length === 0 ? (
          <div className="mesa-label" style={{ padding: "12px 14px", lineHeight: 1.7 }}>
            No live proposals. Run <span className="mesa-amber">python scripts/dump_web_state.py</span> to refresh.
          </div>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr className="mesa-row">
                <HeadCell w={220}>sleeve</HeadCell>
                <HeadCell>action</HeadCell>
                <HeadCell>risk gate</HeadCell>
                <HeadCell>frozen mo</HeadCell>
                <HeadCell>drift</HeadCell>
                <HeadCell>circuit</HeadCell>
              </tr>
            </thead>
            <tbody>{sleeves.map((s) => <DiagRow key={s.name} s={s} />)}</tbody>
          </table>
        )}
      </section>

      {/* (b) DOCUMENTED measurement discipline — not fresh results */}
      <section className="mesa-panel">
        <header className="flex items-center justify-between px-3 py-2 border-b mesa-divider">
          <span className="mesa-label">Discipline &amp; guardrails</span>
          <span className="mesa-label">documented method · not fresh results</span>
        </header>
        <div>{DISCIPLINE.map((d) => <DisciplineRow key={d.rule} rule={d.rule} how={d.how} />)}</div>
      </section>

      {/* operational stream summaries — the only P&L we are allowed to show pre-verdict */}
      <section className="mesa-panel">
        <header className="flex items-center justify-between px-3 py-2 border-b mesa-divider">
          <span className="mesa-label">Streams · operational P&amp;L</span>
          <span className="mesa-label">frozen · live · operator</span>
        </header>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr className="mesa-row">
              <HeadCell w={220}>sleeve · stream</HeadCell>
              <HeadCell>n</HeadCell>
              <HeadCell>cum return</HeadCell>
              <HeadCell>max drawdown</HeadCell>
              <HeadCell>last position</HeadCell>
            </tr>
          </thead>
          <tbody>
            {sleeves.flatMap((s) => [
              <StreamCells key={`${s.name}-frozen`} s={s} stream="frozen" />,
              <StreamCells key={`${s.name}-live`} s={s} stream="live" />,
              <StreamCells key={`${s.name}-operator`} s={s} stream="operator" />,
            ])}
          </tbody>
        </table>
        <div className="mesa-label" style={{ padding: "10px 14px", lineHeight: 1.7 }}>
          operational P&amp;L only — never a forward Sharpe/DSR (those exist only post-verdict).
        </div>
      </section>

      <p className="mesa-label" style={{ lineHeight: 1.7 }}>{meta.honesty}</p>
    </div>
  );
}

function Meta({ label, value }: { label: string; value: string | null }) {
  return (
    <div>
      <div className="mesa-label">{label}</div>
      <div className="mesa-num mesa-h">{value ?? "—"}</div>
    </div>
  );
}

function Loading() {
  return <div className="mesa-label" style={{ padding: 8 }}>loading autonomy state…</div>;
}

function BridgeOffline({ message }: { message?: string }) {
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

export function Research() {
  const { data, isLoading, error } = useAutonomyState();
  if (isLoading) return <Loading />;
  if (error || !data) return <BridgeOffline message={error?.message} />;
  return <ResearchView data={data} />;
}
