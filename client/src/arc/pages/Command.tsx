// Command — the honest at-a-glance. Forward-paper accrual, today's co-pilot proposals (VaR-gated sizing),
// and the prime directive front and centre: nothing is promoted until the forward holdout decides.
import type { ReactNode } from "react";
import type { Pool, Sleeve, WebState } from "@shared/autonomy";
import { AccrualBar, actionTag, Pct, Pos, ReadinessTag, Tag } from "../components";
import { useAutonomyState } from "../useAutonomy";

function HeadCell({ children, w }: { children: ReactNode; w?: number }) {
  return (
    <th className="mesa-label" style={{ textAlign: "left", padding: "6px 10px", width: w }}>
      {children}
    </th>
  );
}

function SleeveRow({ s }: { s: Sleeve }) {
  const p = s.proposal;
  const at = actionTag(p?.action_suggestion);
  return (
    <tr className="mesa-row mesa-rowhover">
      <td style={{ padding: "9px 10px" }}>
        <div className="mesa-h">{s.name}</div>
        <div className="mesa-label">{s.instrument_label}</div>
      </td>
      <td style={{ padding: "9px 10px" }}><Tag kind={at.kind}>{at.label}</Tag></td>
      <td style={{ padding: "9px 10px", textAlign: "right" }}>
        <Pos value={p?.proposed_position} />
      </td>
      <td style={{ padding: "9px 10px", textAlign: "right" }}>
        {p?.risk_gate_active ? <Pct value={p.var_forecast} /> : <span className="mesa-dim mesa-num">—</span>}
      </td>
      <td style={{ padding: "9px 10px", minWidth: 150 }}>
        <AccrualBar value={s.n_forward_months} total={s.contract.eval_at_n} />
      </td>
      <td style={{ padding: "9px 10px" }}><ReadinessTag readiness={s.readiness} /></td>
      <td style={{ padding: "9px 10px", textAlign: "right" }} className="mesa-num mesa-dim">
        {s.months_to_verdict} mo
      </td>
    </tr>
  );
}

function PoolRow({ pool }: { pool: Pool }) {
  return (
    <tr className="mesa-row mesa-rowhover" style={{ background: "rgba(245,165,36,0.03)" }}>
      <td style={{ padding: "9px 10px" }}>
        <div className="mesa-h">pool</div>
        <div className="mesa-label">equal-weight · ~1y sooner</div>
      </td>
      <td style={{ padding: "9px 10px" }}><span className="mesa-label">3 sleeves</span></td>
      <td style={{ padding: "9px 10px", textAlign: "right" }} className="mesa-dim">—</td>
      <td style={{ padding: "9px 10px", textAlign: "right" }} className="mesa-dim">—</td>
      <td style={{ padding: "9px 10px", minWidth: 150 }}>
        <AccrualBar value={pool.n_common_forward_months} total={pool.contract.eval_at_n} />
      </td>
      <td style={{ padding: "9px 10px" }}><ReadinessTag readiness={pool.readiness} /></td>
      <td style={{ padding: "9px 10px", textAlign: "right" }} className="mesa-num mesa-dim">
        {pool.months_to_verdict} mo
      </td>
    </tr>
  );
}

function CommandView({ data }: { data: WebState }) {
  const { meta, sleeves, pool } = data;
  return (
    <div className="flex flex-col" style={{ gap: 16 }}>
      {/* the prime directive — stark, never hidden */}
      <div className="mesa-banner flex items-center justify-between" style={{ padding: "10px 14px" }}>
        <div className="flex items-center" style={{ gap: 10 }}>
          <span style={{ fontSize: 13 }}>⚠</span>
          <span className="mesa-num">
            NOTHING PROMOTED — the forward holdout is the only promoter. Pre-verdict, no track record is shown.
          </span>
        </div>
        <span className="mesa-num mesa-h">{meta.n_promoted} promoted</span>
      </div>

      {/* meta strip */}
      <div className="flex" style={{ gap: 24 }}>
        <Meta label="data through" value={meta.data_through} />
        <Meta label="as of" value={meta.as_of} />
        <Meta label="proposals" value={meta.has_proposals ? "fresh" : "stale (run dump)"} />
      </div>

      {/* forward paper */}
      <section className="mesa-panel">
        <header className="flex items-center justify-between px-3 py-2 border-b mesa-divider">
          <span className="mesa-label">Forward paper · candidates</span>
          <span className="mesa-label">propose → decide → forward holdout</span>
        </header>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr className="mesa-row">
              <HeadCell w={220}>sleeve</HeadCell>
              <HeadCell>proposal</HeadCell>
              <HeadCell>position</HeadCell>
              <HeadCell>VaR95</HeadCell>
              <HeadCell w={180}>accrual</HeadCell>
              <HeadCell>status</HeadCell>
              <HeadCell>to verdict</HeadCell>
            </tr>
          </thead>
          <tbody>
            {sleeves.map((s) => <SleeveRow key={s.name} s={s} />)}
            <PoolRow pool={pool} />
          </tbody>
        </table>
      </section>

      <p className="mesa-label" style={{ lineHeight: 1.7 }}>
        {meta.honesty}
        {!meta.has_proposals && (
          <>
            {" "}Proposals are stale — run <span className="mesa-amber">python scripts/dump_web_state.py</span>.
          </>
        )}
      </p>
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

export function Command() {
  const { data, isLoading, error } = useAutonomyState();
  if (isLoading) return <Loading />;
  if (error || !data) return <BridgeOffline message={error?.message} />;
  return <CommandView data={data} />;
}
