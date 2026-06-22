// A frank "coming in a later phase" stub for the IA areas not yet built. Honest about scope.
export function Placeholder({ area, note }: { area: string; note: string }) {
  return (
    <div className="mesa-panel" style={{ padding: 18 }}>
      <div className="mesa-h" style={{ fontSize: 14, marginBottom: 6 }}>{area}</div>
      <div className="mesa-label" style={{ lineHeight: 1.7 }}>{note}</div>
      <div className="mesa-label" style={{ marginTop: 12 }}>
        Built on the same autonomy bridge as Command — coming in a later phase.
      </div>
    </div>
  );
}
