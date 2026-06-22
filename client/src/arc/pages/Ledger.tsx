// Ledger / Audit — the immutable record explorer. Append-only, hash-provenanced, one record per
// (month, stream). A repaint is rejected at the ledger. Pre-verdict honesty holds here too: we only
// surface what was actually written (decisions, realizations, operator overrides) — never a forward
// Sharpe/DSR. Those live behind the holdout, not in this raw record.
import { useState } from "react";
import type { ReactNode } from "react";
import type {
  LedgerDecision,
  LedgerOperatorDecision,
  LedgerRealization,
  LedgerResponse,
} from "@shared/autonomy";
import { Pct, Pos, Tag } from "../components";
import { useLedger } from "../useAutonomy";

const STRATEGIES = ["momentum", "nowcast", "fiscal"] as const;
const STREAMS = ["frozen", "live", "operator"] as const;
type Stream = (typeof STREAMS)[number];

function HeadCell({ children, w, right }: { children: ReactNode; w?: number; right?: boolean }) {
  return (
    <th className="mesa-label" style={{ textAlign: right ? "right" : "left", padding: "6px 10px", width: w }}>
      {children}
    </th>
  );
}

function Cell({ children, right, dim }: { children: ReactNode; right?: boolean; dim?: boolean }) {
  return (
    <td
      className={dim ? "mesa-num mesa-dim" : undefined}
      style={{ padding: "8px 10px", textAlign: right ? "right" : "left" }}
    >
      {children}
    </td>
  );
}

function Mono({ children }: { children: ReactNode }) {
  return <span className="mesa-num mesa-dim">{children}</span>;
}

function Empty({ cols, label }: { cols: number; label: string }) {
  return (
    <tr className="mesa-row">
      <td colSpan={cols} style={{ padding: "12px 10px" }} className="mesa-label">
        — {label}
      </td>
    </tr>
  );
}

function Section({
  title,
  right,
  children,
}: {
  title: ReactNode;
  right?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="mesa-panel">
      <header className="flex items-center justify-between px-3 py-2 border-b mesa-divider">
        <span className="mesa-label">{title}</span>
        {right}
      </header>
      <table style={{ width: "100%", borderCollapse: "collapse" }}>{children}</table>
    </section>
  );
}

// ---- 1) decisions -----------------------------------------------------------
function DecisionsTable({ rows }: { rows: LedgerDecision[] }) {
  const shown = rows.slice(-24);
  return (
    <Section
      title="decisions · what we committed at as-of"
      right={<span className="mesa-label">{rows.length} records</span>}
    >
      <thead>
        <tr className="mesa-row">
          <HeadCell w={88}>month</HeadCell>
          <HeadCell right>frozen</HeadCell>
          <HeadCell right>live</HeadCell>
          <HeadCell right>signal_z</HeadCell>
          <HeadCell>knowledge</HeadCell>
          <HeadCell>digest</HeadCell>
          <HeadCell>run_id</HeadCell>
        </tr>
      </thead>
      <tbody>
        {shown.length === 0 && <Empty cols={7} label="no decisions yet" />}
        {shown.map((d) => (
          <tr className="mesa-row mesa-rowhover" key={`${d.month}-${d.run_id}`}>
            <Cell><span className="mesa-num mesa-h">{d.month}</span></Cell>
            <Cell right><Pos value={d.frozen_position} /></Cell>
            <Cell right><Pos value={d.live_position} /></Cell>
            <Cell right><Pos value={d.signal_z} signed /></Cell>
            <Cell dim>{d.data_max_knowledge_time}</Cell>
            <Cell><Mono>{d.input_digest.slice(0, 10)}</Mono></Cell>
            <Cell><Mono>{d.run_id}</Mono></Cell>
          </tr>
        ))}
      </tbody>
    </Section>
  );
}

// ---- 2) realizations (per stream) ------------------------------------------
function RealizationsTable({
  byStream,
  stream,
  onStream,
}: {
  byStream: LedgerResponse["realizations"];
  stream: Stream;
  onStream: (s: Stream) => void;
}) {
  const all = byStream[stream] ?? [];
  const shown = all.slice(-24);
  const truncated = all.length - shown.length;
  return (
    <Section
      title="realizations · what actually settled"
      right={
        <div className="flex items-center" style={{ gap: 10 }}>
          {STREAMS.map((s) => (
            <span
              key={s}
              className={`mesa-link ${s === stream ? "mesa-amber" : "mesa-dim"}`}
              style={{ cursor: "pointer", fontSize: 11, textTransform: "uppercase" }}
              onClick={() => onStream(s)}
            >
              {s} ({(byStream[s] ?? []).length})
            </span>
          ))}
        </div>
      }
    >
      <thead>
        <tr className="mesa-row">
          <HeadCell w={88}>month</HeadCell>
          <HeadCell right>held</HeadCell>
          <HeadCell right>sleeve_return</HeadCell>
          <HeadCell>knowledge</HeadCell>
          <HeadCell right>vintage</HeadCell>
        </tr>
      </thead>
      <tbody>
        {shown.length === 0 && <Empty cols={5} label={`no ${stream} realizations yet`} />}
        {shown.map((r: LedgerRealization) => (
          <tr className="mesa-row mesa-rowhover" key={`${r.month}-${r.return_vintage_seq}-${r.run_id}`}>
            <Cell><span className="mesa-num mesa-h">{r.month}</span></Cell>
            <Cell right><Pos value={r.held_position} /></Cell>
            <Cell right><Pct value={r.sleeve_return} digits={2} /></Cell>
            <Cell dim>{r.realized_knowledge_time}</Cell>
            <Cell right dim>{r.return_vintage_seq}</Cell>
          </tr>
        ))}
        {truncated > 0 && (
          <tr className="mesa-row">
            <td colSpan={5} style={{ padding: "8px 10px" }} className="mesa-label">
              showing latest 24 · {truncated} earlier {stream} records elided (the full chain is in the ledger)
            </td>
          </tr>
        )}
      </tbody>
    </Section>
  );
}

// ---- 3) operator decisions --------------------------------------------------
function OperatorTable({ rows }: { rows: LedgerOperatorDecision[] }) {
  const shown = rows.slice(-24);
  return (
    <Section
      title="operator decisions · co-pilot overrides"
      right={<span className="mesa-label">{rows.length} records</span>}
    >
      <thead>
        <tr className="mesa-row">
          <HeadCell w={88}>month</HeadCell>
          <HeadCell>action</HeadCell>
          <HeadCell right>proposed</HeadCell>
          <HeadCell right>operator</HeadCell>
          <HeadCell>rationale</HeadCell>
          <HeadCell>by</HeadCell>
          <HeadCell>digest</HeadCell>
        </tr>
      </thead>
      <tbody>
        {shown.length === 0 && <Empty cols={7} label="no operator decisions yet" />}
        {shown.map((o) => (
          <tr className="mesa-row mesa-rowhover" key={`${o.month}-${o.run_id}`}>
            <Cell><span className="mesa-num mesa-h">{o.month}</span></Cell>
            <Cell><Tag kind={o.action.toLowerCase()}>{o.action}</Tag></Cell>
            <Cell right><Pos value={o.proposed_position} /></Cell>
            <Cell right><Pos value={o.operator_position} /></Cell>
            <Cell>
              <span className="mesa-dim" style={{ fontSize: 12 }}>{o.rationale || "—"}</span>
            </Cell>
            <Cell dim>{o.decided_by || "—"}</Cell>
            <Cell><Mono>{o.proposal_digest.slice(0, 10)}</Mono></Cell>
          </tr>
        ))}
      </tbody>
    </Section>
  );
}

function provenanceHash(data: LedgerResponse): string | null {
  const fromDecision = data.decisions[0]?.strategy_hash;
  if (fromDecision) return fromDecision;
  for (const s of STREAMS) {
    const h = data.realizations[s]?.[0]?.strategy_hash;
    if (h) return h;
  }
  return data.operator_decisions[0]?.strategy_hash ?? null;
}

function LedgerView({ data }: { data: LedgerResponse }) {
  const [stream, setStream] = useState<Stream>("frozen");
  const hash = provenanceHash(data);
  return (
    <div className="flex flex-col" style={{ gap: 16 }}>
      <div className="mesa-banner flex items-center justify-between" style={{ padding: "10px 14px" }}>
        <div className="flex items-center" style={{ gap: 10 }}>
          <span style={{ fontSize: 13 }}>◆</span>
          <span className="mesa-num">
            Append-only, hash-provenanced, one record per (month, stream). A repaint is rejected at the ledger.
          </span>
        </div>
        <span className="mesa-num mesa-h">{hash ? hash.slice(0, 12) : "no provenance"}</span>
      </div>

      <DecisionsTable rows={data.decisions} />
      <RealizationsTable byStream={data.realizations} stream={stream} onStream={setStream} />
      <OperatorTable rows={data.operator_decisions} />

      <p className="mesa-label" style={{ lineHeight: 1.7 }}>
        Raw immutable records only · forward Sharpe / DSR never live here — they appear behind the one-shot
        holdout, not in the audit trail.
      </p>
    </div>
  );
}

function StrategyTabs({ strategy, onPick }: { strategy: string; onPick: (s: string) => void }) {
  return (
    <div className="flex items-center" style={{ gap: 16 }}>
      <span className="mesa-label">sleeve ledger</span>
      <div className="flex items-center" style={{ gap: 14 }}>
        {STRATEGIES.map((s) => (
          <span
            key={s}
            className={`mesa-link ${s === strategy ? "mesa-amber mesa-h" : "mesa-dim"}`}
            style={{ cursor: "pointer", textTransform: "uppercase", fontSize: 12 }}
            onClick={() => onPick(s)}
          >
            {s}
          </span>
        ))}
      </div>
    </div>
  );
}

function Loading() {
  return <div className="mesa-label" style={{ padding: 8 }}>loading ledger…</div>;
}

function BridgeOffline({ message }: { message?: string }) {
  return (
    <div className="mesa-panel" style={{ padding: 16, borderColor: "rgba(248,113,113,0.4)" }}>
      <div className="mesa-h" style={{ marginBottom: 8 }}>ARC API bridge offline</div>
      <div className="mesa-label" style={{ lineHeight: 1.8 }}>
        Start the bridge: <span className="mesa-amber">uvicorn arc.webapi.app:app --port 8787</span><br />
        Refresh records: <span className="mesa-amber">python scripts/dump_web_state.py</span>
        {message && <><br /><span className="mesa-neg">{message}</span></>}
      </div>
    </div>
  );
}

export function Ledger() {
  const [strategy, setStrategy] = useState("momentum");
  const { data, isLoading, error } = useLedger(strategy);
  return (
    <div className="flex flex-col" style={{ gap: 16 }}>
      <StrategyTabs strategy={strategy} onPick={setStrategy} />
      {isLoading ? (
        <Loading />
      ) : error || !data ? (
        <BridgeOffline message={error?.message} />
      ) : (
        <LedgerView key={strategy} data={data} />
      )}
    </div>
  );
}
