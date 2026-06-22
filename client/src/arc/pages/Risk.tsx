// Risk — live PRE-TRADE VaR/ES gate. Operational loss control on sizing only:
//   applied_leverage = min(vol-target, var_limit/VaR_per_unit, es_limit/ES_per_unit).
// It touches the proposal's leverage/sized_exposure — NEVER the frozen/live holdout. With <24 months of
// causal history the gate is INACTIVE. No forward Sharpe/DSR is shown anywhere on this page (sizing, not alpha).
import type { ReactNode } from "react";
import type { Sleeve, WebState } from "@shared/autonomy";
import { Dot, Pct, Pos, Tag } from "../components";
import { useAutonomyState } from "../useAutonomy";

// Pre-committed loss budget — RiskLimits defaults, restated for the desk (never computed from data).
const LIMITS = {
  varLimit: 0.055,
  esLimit: 0.075,
  alpha: 0.05,
  minHistory: 24,
  method: "cornish-fisher",
};

function HeadCell({ children, w, right }: { children: ReactNode; w?: number; right?: boolean }) {
  return (
    <th className="mesa-label" style={{ textAlign: right ? "right" : "left", padding: "6px 10px", width: w }}>
      {children}
    </th>
  );
}

function Meta({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div>
      <div className="mesa-label">{label}</div>
      <div className="mesa-num mesa-h">{value ?? "—"}</div>
    </div>
  );
}

function GateCell({ s }: { s: Sleeve }) {
  const p = s.proposal;
  if (!p) return <span className="mesa-dim mesa-num">—</span>;
  if (!p.risk_gate_active) return <Tag kind="inactive">INACTIVE</Tag>;
  return <Tag kind="operate">{p.risk_gate_binding || "vol_target"}</Tag>;
}

function GateNote({ s }: { s: Sleeve }) {
  const p = s.proposal;
  if (!p || p.risk_gate_active) return null;
  // Pre-verdict / short-history reason — purely operational, dim.
  const reason =
    p.risk_gate_binding === "inactive" || p.risk_gate_binding === ""
      ? `inactive — <${LIMITS.minHistory} mo causal history`
      : p.risk_gate_binding;
  return <div className="mesa-label mesa-dim" style={{ marginTop: 2 }}>{reason}</div>;
}

function SleeveRow({ s }: { s: Sleeve }) {
  const p = s.proposal;
  if (!p) {
    return (
      <tr className="mesa-row mesa-rowhover">
        <td style={{ padding: "9px 10px" }}>
          <div className="mesa-h">{s.name}</div>
          <div className="mesa-label">{s.instrument_label}</div>
        </td>
        <td colSpan={6} style={{ padding: "9px 10px" }}>
          <span className="mesa-dim mesa-num">—</span>{" "}
          <span className="mesa-label">
            no live proposal — run <span className="mesa-amber">python scripts/dump_web_state.py</span>
          </span>
        </td>
      </tr>
    );
  }
  return (
    <tr className="mesa-row mesa-rowhover">
      <td style={{ padding: "9px 10px" }}>
        <div className="mesa-h">{s.name}</div>
        <div className="mesa-label">{s.instrument_label}</div>
      </td>
      <td style={{ padding: "9px 10px" }}>
        <GateCell s={s} />
        <GateNote s={s} />
      </td>
      <td style={{ padding: "9px 10px", textAlign: "right" }}>
        {p.risk_gate_active ? <Pct value={p.var_forecast} /> : <span className="mesa-dim mesa-num">—</span>}
      </td>
      <td style={{ padding: "9px 10px", textAlign: "right" }}>
        {p.risk_gate_active ? <Pct value={p.es_forecast} /> : <span className="mesa-dim mesa-num">—</span>}
      </td>
      <td style={{ padding: "9px 10px", textAlign: "right" }}>
        <Pos value={p.leverage_for_vol_target} signed={false} digits={2} />
      </td>
      <td style={{ padding: "9px 10px", textAlign: "right" }}>
        <Pos value={p.sized_exposure} />
      </td>
      <td style={{ padding: "9px 10px", textAlign: "center" }}>
        <Dot kind={p.circuit_halted ? "halt" : "live"} />
      </td>
    </tr>
  );
}

type Flag = { sleeve: string; kind: "circuit" | "drift"; text: string };

function collectFlags(sleeves: Sleeve[]): Flag[] {
  const flags: Flag[] = [];
  for (const s of sleeves) {
    const p = s.proposal;
    if (!p) continue;
    for (const r of p.circuit_reasons) flags.push({ sleeve: s.name, kind: "circuit", text: r });
    for (const w of p.drift_warnings) flags.push({ sleeve: s.name, kind: "drift", text: w });
  }
  return flags;
}

function RiskView({ data }: { data: WebState }) {
  const { meta, sleeves } = data;
  const flags = collectFlags(sleeves);
  return (
    <div className="flex flex-col" style={{ gap: 16 }}>
      {/* pre-committed loss budget — stated, never derived from the data */}
      <section className="mesa-panel">
        <header className="flex items-center justify-between px-3 py-2 border-b mesa-divider">
          <span className="mesa-label">Pre-committed monthly budget (95%)</span>
          <span className="mesa-label">PRE-TRADE · sizing only · not alpha</span>
        </header>
        <div className="flex" style={{ gap: 28, padding: "12px 14px", flexWrap: "wrap" }}>
          <Meta label="VaR limit" value={<Pct value={LIMITS.varLimit} />} />
          <Meta label="ES limit" value={<Pct value={LIMITS.esLimit} />} />
          <Meta label="alpha" value={LIMITS.alpha.toFixed(2)} />
          <Meta label="min history" value={`${LIMITS.minHistory} mo`} />
          <Meta label="method" value={`${LIMITS.method} (fat-tail aware)`} />
        </div>
        <div className="mesa-label" style={{ padding: "0 14px 12px", lineHeight: 1.7 }}>
          applied_leverage = min(vol-target, var_limit/VaR_per_unit, es_limit/ES_per_unit). Absolute, not
          vol-scaled — a higher vol target makes the gate bind sooner.
        </div>
      </section>

      {/* meta strip */}
      <div className="flex" style={{ gap: 24 }}>
        <Meta label="data through" value={meta.data_through} />
        <Meta label="as of" value={meta.as_of} />
        <Meta label="proposals" value={meta.has_proposals ? "fresh" : "stale (run dump)"} />
      </div>

      {/* per-sleeve pre-trade gate */}
      <section className="mesa-panel">
        <header className="flex items-center justify-between px-3 py-2 border-b mesa-divider">
          <span className="mesa-label">Pre-trade gate · per sleeve</span>
          <span className="mesa-label">bounds losses → bounds leverage</span>
        </header>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr className="mesa-row">
              <HeadCell w={220}>sleeve</HeadCell>
              <HeadCell w={150}>gate</HeadCell>
              <HeadCell right>VaR95</HeadCell>
              <HeadCell right>ES</HeadCell>
              <HeadCell right>vol-target lev</HeadCell>
              <HeadCell right>sized exposure</HeadCell>
              <HeadCell w={70}>circuit</HeadCell>
            </tr>
          </thead>
          <tbody>
            {sleeves.map((s) => <SleeveRow key={s.name} s={s} />)}
          </tbody>
        </table>
      </section>

      {/* flags — every circuit reason and drift warning across sleeves */}
      <section className="mesa-panel">
        <header className="flex items-center justify-between px-3 py-2 border-b mesa-divider">
          <span className="mesa-label">Flags · circuit & drift</span>
          <span className="mesa-label">{flags.length} active</span>
        </header>
        <div style={{ padding: "10px 14px" }}>
          {flags.length === 0 ? (
            <div className="mesa-label">No circuit or drift flags.</div>
          ) : (
            <div className="flex flex-col" style={{ gap: 8 }}>
              {flags.map((f, i) => (
                <div key={`${f.sleeve}-${i}`} className="flex items-center" style={{ gap: 10 }}>
                  <Dot kind={f.kind === "circuit" ? "halt" : "warn"} />
                  <Tag kind={f.kind === "circuit" ? "halt" : "warmup"}>{f.kind}</Tag>
                  <span className="mesa-h" style={{ fontSize: 12 }}>{f.sleeve}</span>
                  <span className="mesa-num">{f.text}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </section>

      <p className="mesa-label" style={{ lineHeight: 1.7 }}>
        The gate only bounds losses — it can never change the scored holdout. It clips proposal leverage and
        sized exposure, leaving the frozen/live streams untouched. Risk control, not a signal: no forward
        Sharpe or DSR appears here.
      </p>
    </div>
  );
}

function Loading() {
  return <div className="mesa-label" style={{ padding: 8 }}>loading risk state…</div>;
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

export function Risk() {
  const { data, isLoading, error } = useAutonomyState();
  if (isLoading) return <Loading />;
  if (error || !data) return <BridgeOffline message={error?.message} />;
  return <RiskView data={data} />;
}
