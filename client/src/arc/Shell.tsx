// The ARC 2.0 navigation shell: a top bar + the autonomy-first left nav (the 7 areas of the IA).
import type { ReactNode } from "react";
import { Link, useLocation } from "wouter";
import { Dot } from "./components";

const NAV: { href: string; label: string }[] = [
  { href: "/", label: "Command" },
  { href: "/co-pilot", label: "Co-pilot" },
  { href: "/holdout", label: "Holdout" },
  { href: "/risk", label: "Risk" },
  { href: "/macro", label: "Macro" },
  { href: "/research", label: "Research" },
  { href: "/ledger", label: "Ledger" },
];

export function Shell({ asOf, children }: { asOf?: string | null; children: ReactNode }) {
  const [loc] = useLocation();
  return (
    <div className="arc-mesa flex flex-col min-h-screen">
      <header className="flex items-center justify-between px-4 border-b mesa-divider" style={{ height: 44 }}>
        <div className="flex items-center gap-2">
          <span className="mesa-h" style={{ fontWeight: 700, letterSpacing: "0.18em" }}>ARC</span>
          <span className="mesa-label">Macro · Risk OS</span>
          <span className="mesa-tag" style={{ marginLeft: 8 }}>2.0</span>
        </div>
        <div className="flex items-center gap-3">
          <span className="mesa-label mesa-num">{asOf ?? "—"}</span>
          <span className="flex items-center gap-1">
            <Dot kind="live" />
            <span className="mesa-label">LIVE</span>
          </span>
        </div>
      </header>
      <div className="flex flex-1" style={{ minHeight: 0 }}>
        <nav className="border-r mesa-divider" style={{ width: 152, flexShrink: 0 }}>
          <div className="py-2">
            {NAV.map((n) => {
              const active = n.href === "/" ? loc === "/" : loc.startsWith(n.href);
              return (
                <Link key={n.href} href={n.href} className={`mesa-navlink ${active ? "active" : ""}`}>
                  {n.label}
                </Link>
              );
            })}
          </div>
        </nav>
        <main className="flex-1 overflow-auto" style={{ padding: 18 }}>{children}</main>
      </div>
    </div>
  );
}
