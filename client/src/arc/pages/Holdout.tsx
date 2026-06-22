// Holdout & Governance — pre-registration + verdict-countdown screen.
// A candidate is judged ONLY by its one-shot forward holdout: the evaluation point (eval_at_n) and the bar
// (dsr_min, deflated for n_trials cumulative hypotheses) are pre-committed before any forward data. No optional
// stopping. HONESTY: a forward Sharpe/DSR may appear ONLY inside an `if (verdict)` branch.
import type { ReactNode } from "react";
import type { Pool, Sleeve, SleeveContract, Verdict, WebState } from "@shared/autonomy";
import { AccrualBar, ReadinessTag, Tag } from "../components";
import { useAutonomyState } from "../useAutonomy";

function Field({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div>
      <div className="mesa-label">{label}</div>
      <div className="mesa-num mesa-h">{value}</div>
      {hint && <div className="mesa-label" style={{ marginTop: 2, opacity: 0.7 }}>{hint}</div>}
    </div>
  );
}

function ContractBasis({ contract }: { contract: SleeveContract }) {
  return (
    <div className="flex" style={{ gap: 28, flexWrap: "wrap" }}>
      <Field
        label="n_trials"
        value={contract.n_trials ?? "—"}
        hint="cumulative hypotheses deflated for"
      />
      <Field label="eval_at_n" value={contract.eval_at_n} hint="pre-committed forward sample" />
      <Field label="dsr_min" value={contract.dsr_min.toFixed(2)} hint="DSR bar to clear" />
      <Field label="forward_start" value={contract.forward_start ?? "—"} hint="research cutoff" />
      <div>
        <div className="mesa-label">booking</div>
        <Tag kind={contract.booked ? "ready" : "unbooked"}>{contract.booked ? "BOOKED" : "UNBOOKED"}</Tag>
      </div>
    </div>
  );
}

// HONESTY GATE: this component is the ONLY place sr_annual / dsr surface, and it is rendered exclusively
// from an `if (verdict)` branch below. Pre-verdict, callers pass no verdict and nothing here runs.
function VerdictBlock({ verdict }: { verdict: Verdict }) {
  const tint = verdict.passed ? "rgba(74,222,128,0.06)" : "rgba(248,113,113,0.06)";
  const border = verdict.passed ? "rgba(74,222,128,0.4)" : "rgba(248,113,113,0.4)";
  return (
    <div
      className="mesa-panel"
      style={{ padding: "12px 14px", marginTop: 12, background: tint, borderColor: border }}
    >
      <div className="flex items-center justify-between" style={{ marginBottom: 10 }}>
        <span className="mesa-h" style={{ fontSize: 13 }}>holdout fired</span>
        <Tag kind={verdict.passed ? "ready" : "halt"}>{verdict.passed ? "PASS" : "FAIL"}</Tag>
      </div>
      <div className="flex" style={{ gap: 28, flexWrap: "wrap" }}>
        <Field
          label="DSR"
          value={
            <span className={verdict.dsr >= verdict.dsr_min ? "mesa-pos" : "mesa-neg"}>
              {verdict.dsr.toFixed(3)}
            </span>
          }
          hint={`bar ${verdict.dsr_min.toFixed(2)}`}
        />
        <Field label="Sharpe (ann.)" value={verdict.sr_annual.toFixed(2)} hint="realized forward" />
        <Field label="n" value={verdict.n} hint={`${verdict.n_trials} trials deflated`} />
      </div>
      <div className="mesa-label" style={{ marginTop: 10, lineHeight: 1.6 }}>{verdict.reason}</div>
    </div>
  );
}

function Countdown({
  value,
  total,
  monthsToVerdict,
  readiness,
}: {
  value: number;
  total: number;
  monthsToVerdict: number;
  readiness: Sleeve["readiness"];
}) {
  return (
    <div style={{ marginTop: 12 }}>
      <div className="flex items-center justify-between" style={{ marginBottom: 6 }}>
        <span className="mesa-label">forward accrual → verdict</span>
        <span className="mesa-num mesa-h">{monthsToVerdict} mo to verdict</span>
      </div>
      <AccrualBar value={value} total={total} />
      <div className="flex items-center" style={{ gap: 10, marginTop: 8 }}>
        <ReadinessTag readiness={readiness} />
        <span className="mesa-label" style={{ lineHeight: 1.5 }}>{readiness.message}</span>
      </div>
    </div>
  );
}

function CardHeader({ title, subtitle, hash }: { title: string; subtitle: string; hash: string }) {
  return (
    <header className="flex items-center justify-between px-3 py-2 border-b mesa-divider">
      <div>
        <span className="mesa-h">{title}</span>
        <span className="mesa-label" style={{ marginLeft: 8 }}>{subtitle}</span>
      </div>
      <span className="mesa-num mesa-dim" style={{ fontSize: 11 }}>{hash.slice(0, 8)}</span>
    </header>
  );
}

function SleeveCard({ s }: { s: Sleeve }) {
  return (
    <section className="mesa-panel">
      <CardHeader title={s.name} subtitle={s.instrument_label} hash={s.hash} />
      <div style={{ padding: "12px 14px" }}>
        <ContractBasis contract={s.contract} />
        <Countdown
          value={s.n_forward_months}
          total={s.contract.eval_at_n}
          monthsToVerdict={s.months_to_verdict}
          readiness={s.readiness}
        />
        {/* HONESTY: sr_annual / dsr only ever inside this verdict !== null branch. */}
        {s.verdict ? (
          <VerdictBlock verdict={s.verdict} />
        ) : (
          <div className="mesa-label" style={{ marginTop: 12, opacity: 0.7 }}>
            ◆ Pre-verdict — no Sharpe or DSR is shown until the holdout fires.
          </div>
        )}
      </div>
    </section>
  );
}

function PoolCard({ pool }: { pool: Pool }) {
  return (
    <section className="mesa-panel" style={{ background: "rgba(245,165,36,0.03)" }}>
      <CardHeader
        title={pool.name}
        subtitle={`equal-weight pool of ${pool.members.length}`}
        hash={pool.hash}
      />
      <div style={{ padding: "12px 14px" }}>
        <ContractBasis contract={pool.contract} />
        <Countdown
          value={pool.n_common_forward_months}
          total={pool.contract.eval_at_n}
          monthsToVerdict={pool.months_to_verdict}
          readiness={pool.readiness}
        />
        <div className="mesa-label" style={{ marginTop: 12, lineHeight: 1.6 }}>{pool.rationale}</div>
        <div className="mesa-label mesa-amber" style={{ marginTop: 6, lineHeight: 1.6 }}>
          K_eff ≈ 2.92 → a verdict ~1y sooner IF several sleeves carry real edge (else pooling dilutes).
        </div>
        {pool.verdict ? (
          <VerdictBlock verdict={pool.verdict} />
        ) : (
          <div className="mesa-label" style={{ marginTop: 12, opacity: 0.7 }}>
            ◆ Pre-verdict — no Sharpe or DSR is shown until the holdout fires.
          </div>
        )}
      </div>
    </section>
  );
}

function HoldoutView({ data }: { data: WebState }) {
  const { meta, sleeves, pool } = data;
  return (
    <div className="flex flex-col" style={{ gap: 16 }}>
      <div className="mesa-banner flex items-center justify-between" style={{ padding: "10px 14px" }}>
        <div className="flex items-center" style={{ gap: 10 }}>
          <span style={{ fontSize: 13 }}>⚠</span>
          <span className="mesa-num">
            Pre-registered forward holdouts. No optional stopping; the evaluation point and bar were fixed
            before forward data.
          </span>
        </div>
        <span className="mesa-num mesa-h">{meta.n_promoted} promoted</span>
      </div>

      <div className="flex" style={{ gap: 24 }}>
        <Field label="data through" value={meta.data_through ?? "—"} />
        <Field label="as of" value={meta.as_of ?? "—"} />
        <Field label="proposals" value={meta.has_proposals ? "fresh" : "stale (run dump)"} />
      </div>

      {sleeves.length === 0 ? (
        <div className="mesa-panel" style={{ padding: 16, borderColor: "rgba(248,113,113,0.4)" }}>
          <div className="mesa-h" style={{ marginBottom: 8 }}>No pre-registrations</div>
          <div className="mesa-label">
            Run <span className="mesa-amber">python scripts/dump_web_state.py</span> to populate the holdout state.
          </div>
        </div>
      ) : (
        <div className="flex flex-col" style={{ gap: 16 }}>
          {sleeves.map((s) => <SleeveCard key={s.name} s={s} />)}
          <PoolCard pool={pool} />
        </div>
      )}

      <p className="mesa-label" style={{ lineHeight: 1.7 }}>
        Deflation basis: the bar is the Deflated Sharpe Ratio. The more hypotheses tested (n_trials, the
        cumulative count across every candidate ever evaluated), the higher the DSR threshold a candidate must
        clear — so a wider search demands a stronger forward result. The evaluation point and bar are committed
        before forward data and never moved; only months after forward_start count toward the holdout.
      </p>
    </div>
  );
}

function Loading() {
  return <div className="mesa-label" style={{ padding: 8 }}>loading holdout state…</div>;
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

export function Holdout() {
  const { data, isLoading, error } = useAutonomyState();
  if (isLoading) return <Loading />;
  if (error || !data) return <BridgeOffline message={error?.message} />;
  return <HoldoutView data={data} />;
}
