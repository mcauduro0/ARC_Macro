// Macro Engine — the point-in-time macro context behind the sleeves: composite r*, regime probabilities,
// the state-variable vector, FX fair value, and the DI curve. Every field is REAL engine output (the dump's
// `_extract_macro`) and rendered ONLY when present; absence is shown as absence (see `notes`). This is macro
// context, not strategy performance — no forward Sharpe/DSR lives here.
import type { ReactNode } from "react";
import type {
  MacroContext,
  MacroCurvePoint,
  MacroRegime,
  MacroRStar,
  MacroStateVar,
  WebState,
} from "@shared/autonomy";
import { useAutonomyState } from "../useAutonomy";

// ---- tiny dependency-free sparkline -----------------------------------------
function Spark({ values, w = 220, h = 36 }: { values: number[]; w?: number; h?: number }) {
  if (values.length < 2) return null;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const pts = values
    .map((v, i) => {
      const x = (i / (values.length - 1)) * (w - 2) + 1;
      const y = h - 1 - ((v - min) / span) * (h - 2);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  return (
    <svg width={w} height={h} style={{ display: "block" }}>
      <polyline points={pts} fill="none" stroke="var(--amber)" strokeWidth="1.5" />
    </svg>
  );
}

function Panel({ title, right, children }: { title: ReactNode; right?: ReactNode; children: ReactNode }) {
  return (
    <section className="mesa-panel">
      <header className="flex items-center justify-between px-3 py-2 border-b mesa-divider">
        <span className="mesa-label">{title}</span>
        {right}
      </header>
      <div style={{ padding: "12px 14px" }}>{children}</div>
    </section>
  );
}

// ---- r* ----------------------------------------------------------------------
function RStarCard({ rstar }: { rstar: MacroRStar }) {
  const vals = rstar.history.map((h) => h[1]);
  const first = vals[0];
  const last = rstar.latest;
  const delta = last - first;
  return (
    <Panel title="composite r* · neutral real rate" right={<span className="mesa-label">{rstar.unit}</span>}>
      <div className="flex items-center justify-between" style={{ gap: 18 }}>
        <div>
          <div className="mesa-num mesa-h" style={{ fontSize: 28, lineHeight: 1 }}>{last.toFixed(2)}</div>
          <div className="mesa-label" style={{ marginTop: 4 }}>
            {rstar.history.length}-mo trend{" "}
            <span className={delta >= 0 ? "mesa-pos" : "mesa-neg"}>
              {delta >= 0 ? "+" : ""}{delta.toFixed(2)}
            </span>
          </div>
        </div>
        <Spark values={vals} />
      </div>
    </Panel>
  );
}

// ---- regime ------------------------------------------------------------------
const REGIME_TINT: Record<string, string> = {
  P_carry: "var(--green)", P_riskoff: "var(--amber)", P_stress: "var(--red)",
  P_domestic_calm: "var(--green)", P_domestic_stress: "var(--red)",
};

function ProbBar({ name, p }: { name: string; p: number }) {
  const pct = Math.max(0, Math.min(100, p * 100));
  return (
    <div className="flex items-center" style={{ gap: 10 }}>
      <span className="mesa-label" style={{ width: 150 }}>{name.replace(/^P_/, "")}</span>
      <div className="mesa-bar flex-1" style={{ height: 9 }}>
        <span style={{ width: `${pct}%`, background: REGIME_TINT[name] ?? "var(--blue)" }} />
      </div>
      <span className="mesa-num mesa-h" style={{ width: 48, textAlign: "right", fontSize: 12 }}>
        {pct.toFixed(0)}%
      </span>
    </div>
  );
}

function RegimeCard({ regime }: { regime: MacroRegime }) {
  const global = ["P_carry", "P_riskoff", "P_stress"].filter((k) => k in regime.latest);
  const domestic = ["P_domestic_calm", "P_domestic_stress"].filter((k) => k in regime.latest);
  const other = regime.labels.filter((k) => !global.includes(k) && !domestic.includes(k));
  const dominant = Object.entries(regime.latest).sort((a, b) => b[1] - a[1])[0];
  return (
    <Panel
      title="regime · filtered (causal) HMM posterior"
      right={dominant ? <span className="mesa-label">dominant: {dominant[0].replace(/^P_/, "")}</span> : null}
    >
      <div className="flex flex-col" style={{ gap: 8 }}>
        {global.map((k) => <ProbBar key={k} name={k} p={regime.latest[k]} />)}
        {domestic.length > 0 && <div className="mesa-divider" style={{ borderTop: "1px solid var(--line)", margin: "4px 0" }} />}
        {domestic.map((k) => <ProbBar key={k} name={k} p={regime.latest[k]} />)}
        {other.map((k) => <ProbBar key={k} name={k} p={regime.latest[k]} />)}
      </div>
      <div className="mesa-label" style={{ marginTop: 10 }}>
        {regime.history.length}-mo history · filtered posterior (no look-ahead repaint)
      </div>
    </Panel>
  );
}

// ---- state vars --------------------------------------------------------------
function ZBar({ v }: { v: MacroStateVar }) {
  const clamped = Math.max(-3, Math.min(3, v.value));
  const leftPct = ((clamped + 3) / 6) * 100; // -3..+3 → 0..100
  const pos = v.value >= 0;
  return (
    <div className="flex items-center" style={{ gap: 10, padding: "5px 0" }}>
      <span className="mesa-label" style={{ width: 180 }}>{v.label}</span>
      <div style={{ position: "relative", flex: 1, height: 10, background: "var(--line)" }}>
        <span style={{ position: "absolute", left: "50%", top: 0, bottom: 0, width: 1, background: "var(--line-2)" }} />
        <span
          style={{
            position: "absolute", top: 1, bottom: 1, background: pos ? "var(--green)" : "var(--red)",
            left: pos ? "50%" : `${leftPct}%`, width: `${Math.abs(leftPct - 50)}%`,
          }}
        />
      </div>
      <span className={`mesa-num ${pos ? "mesa-pos" : "mesa-neg"}`} style={{ width: 52, textAlign: "right", fontSize: 12 }}>
        {pos ? "+" : ""}{v.value.toFixed(2)}
      </span>
    </div>
  );
}

function StateVarsCard({ vars }: { vars: MacroStateVar[] }) {
  return (
    <Panel title="state variables · z-scored macro vector" right={<span className="mesa-label">σ from trend</span>}>
      <div className="flex flex-col">{vars.map((v) => <ZBar key={v.key} v={v} />)}</div>
    </Panel>
  );
}

// ---- fx fair -----------------------------------------------------------------
function FxFairCard({ fx }: { fx: NonNullable<MacroContext["fx_fair"]> }) {
  const mis = fx.misalignment_pct;
  const verdict =
    mis == null ? null : mis < 0 ? "BRL rich vs fair" : mis > 0 ? "BRL cheap vs fair" : "at fair";
  return (
    <Panel title="FX fair value · USDBRL (BEER composite)">
      <div className="flex" style={{ gap: 34, flexWrap: "wrap" }}>
        <Meta label="fair" value={fx.fair.toFixed(3)} />
        <Meta label="spot" value={fx.spot != null ? fx.spot.toFixed(3) : "—"} />
        <div>
          <div className="mesa-label">misalignment</div>
          <div className={`mesa-num ${mis == null ? "mesa-dim" : mis < 0 ? "mesa-neg" : "mesa-pos"}`} style={{ fontSize: 16 }}>
            {mis == null ? "—" : `${mis > 0 ? "+" : ""}${mis.toFixed(1)}%`}
          </div>
          {verdict && <div className="mesa-label" style={{ marginTop: 2 }}>{verdict}</div>}
        </div>
      </div>
    </Panel>
  );
}

// ---- di curve ----------------------------------------------------------------
function DiCurveCard({ curve }: { curve: MacroCurvePoint[] }) {
  const rates = curve.map((c) => c.rate);
  return (
    <Panel title="DI curve · nominal (% p.a.)" right={<span className="mesa-label">{curve.length} tenors</span>}>
      <Spark values={rates} w={320} h={42} />
      <div className="flex" style={{ gap: 0, marginTop: 8, flexWrap: "wrap" }}>
        {curve.map((c) => (
          <div key={c.tenor} style={{ minWidth: 64 }}>
            <div className="mesa-label">{c.tenor}</div>
            <div className="mesa-num mesa-h">{c.rate.toFixed(2)}</div>
          </div>
        ))}
      </div>
    </Panel>
  );
}

function Meta({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div>
      <div className="mesa-label">{label}</div>
      <div className="mesa-num mesa-h" style={{ fontSize: 16 }}>{value}</div>
    </div>
  );
}

function MacroView({ data }: { data: WebState }) {
  const m = data.macro;
  if (!m) {
    return (
      <div className="mesa-panel" style={{ padding: 16, borderColor: "rgba(245,165,36,0.4)" }}>
        <div className="mesa-h" style={{ marginBottom: 8 }}>Macro context not yet dumped</div>
        <div className="mesa-label" style={{ lineHeight: 1.8 }}>
          The macro engine context is engine-heavy (~60s). Run{" "}
          <span className="mesa-amber">python scripts/dump_web_state.py</span> to populate r*, regime,
          state variables, FX fair value, and the DI curve.
        </div>
      </div>
    );
  }
  return (
    <div className="flex flex-col" style={{ gap: 16 }}>
      <div className="flex items-center justify-between">
        <span className="mesa-label">macro context · point-in-time snapshot</span>
        <span className="mesa-num mesa-h">{m.as_of ?? "—"}</span>
      </div>

      {m.rstar && <RStarCard rstar={m.rstar} />}
      {m.regime && <RegimeCard regime={m.regime} />}
      {m.state_vars && m.state_vars.length > 0 && <StateVarsCard vars={m.state_vars} />}
      <div className="flex" style={{ gap: 16, flexWrap: "wrap" }}>
        {m.fx_fair && <div style={{ flex: 1, minWidth: 300 }}><FxFairCard fx={m.fx_fair} /></div>}
        {m.di_curve && m.di_curve.length > 0 && <div style={{ flex: 1, minWidth: 360 }}><DiCurveCard curve={m.di_curve} /></div>}
      </div>

      {m.notes.length > 0 && (
        <div className="mesa-panel" style={{ padding: "10px 14px" }}>
          <div className="mesa-label" style={{ marginBottom: 6 }}>omitted (absent in this dump — never fabricated)</div>
          {m.notes.map((n, i) => <div key={i} className="mesa-label mesa-dim" style={{ lineHeight: 1.6 }}>· {n}</div>)}
        </div>
      )}

      <p className="mesa-label" style={{ lineHeight: 1.7 }}>
        All values are point-in-time, causal engine output — the regime is the filtered (not smoothed)
        posterior, r* and the state vector use publication-lagged data. This is macro context for the desk,
        not a strategy track record; no forward Sharpe/DSR appears here.
      </p>
    </div>
  );
}

function Loading() {
  return <div className="mesa-label" style={{ padding: 8 }}>loading macro context…</div>;
}

function BridgeOffline({ message }: { message?: string }) {
  return (
    <div className="mesa-panel" style={{ padding: 16, borderColor: "rgba(248,113,113,0.4)" }}>
      <div className="mesa-h" style={{ marginBottom: 8 }}>ARC API bridge offline</div>
      <div className="mesa-label" style={{ lineHeight: 1.8 }}>
        Start the bridge: <span className="mesa-amber">uvicorn arc.webapi.app:app --port 8787</span><br />
        Refresh context: <span className="mesa-amber">python scripts/dump_web_state.py</span>
        {message && <><br /><span className="mesa-neg">{message}</span></>}
      </div>
    </div>
  );
}

export function Macro() {
  const { data, isLoading, error } = useAutonomyState();
  if (isLoading) return <Loading />;
  if (error || !data) return <BridgeOffline message={error?.message} />;
  return <MacroView data={data} />;
}
