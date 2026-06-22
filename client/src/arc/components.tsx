// Mesa primitives — the small, dense building blocks of the ARC 2.0 terminal UI.
import type { ReactNode } from "react";
import type { Readiness } from "@shared/autonomy";

export function Label({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`mesa-label ${className}`}>{children}</div>;
}

export function Panel({
  title,
  right,
  children,
  className = "",
}: {
  title?: ReactNode;
  right?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`mesa-panel ${className}`}>
      {(title || right) && (
        <header className="flex items-center justify-between px-3 py-2 border-b mesa-divider">
          <div className="mesa-label">{title}</div>
          {right}
        </header>
      )}
      <div>{children}</div>
    </section>
  );
}

export function AccrualBar({ value, total }: { value: number; total: number }) {
  const pct = total > 0 ? Math.min(100, Math.max(0, (value / total) * 100)) : 0;
  return (
    <div className="flex items-center gap-2 w-full">
      <div className={`mesa-bar flex-1 ${value === 0 ? "zero" : ""}`} aria-label={`${value} of ${total}`}>
        <span style={{ width: `${pct}%` }} />
      </div>
      <span className="mesa-num mesa-h" style={{ fontSize: 11, minWidth: 42, textAlign: "right" }}>
        {value}/{total}
      </span>
    </div>
  );
}

export function Dot({ kind = "live" }: { kind?: "live" | "halt" | "warn" | "idle" }) {
  return <span className={`mesa-dot ${kind}`} />;
}

export function Tag({ kind, children }: { kind: string; children: ReactNode }) {
  return <span className={`mesa-tag ${kind}`}>{children}</span>;
}

/** Signed, sign-coloured, monospace number. Renders an em-dash for null/NaN. */
export function Pos({
  value,
  digits = 3,
  signed = true,
}: {
  value: number | null | undefined;
  digits?: number;
  signed?: boolean;
}) {
  if (value == null || Number.isNaN(value)) {
    return <span className="mesa-num mesa-dim">—</span>;
  }
  const cls = value > 0 ? "mesa-pos" : value < 0 ? "mesa-neg" : "mesa-dim";
  const sign = signed && value > 0 ? "+" : "";
  return <span className={`mesa-num ${cls}`}>{`${sign}${value.toFixed(digits)}`}</span>;
}

export function Pct({ value, digits = 1 }: { value: number | null | undefined; digits?: number }) {
  if (value == null || Number.isNaN(value)) return <span className="mesa-num mesa-dim">—</span>;
  return <span className="mesa-num">{`${(value * 100).toFixed(digits)}%`}</span>;
}

/** Map a proposal action to a Mesa tag. */
export function actionTag(action: string | undefined): { kind: string; label: string } {
  if (action === "OPERATE") return { kind: "operate", label: "OPERATE" };
  if (action === "HALT") return { kind: "halt", label: "HALT" };
  return { kind: "warmup", label: "WARMUP" };
}

export function ReadinessTag({ readiness }: { readiness: Readiness }) {
  return <Tag kind={readiness.state.toLowerCase()}>{readiness.state}</Tag>;
}
