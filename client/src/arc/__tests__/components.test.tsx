// Mesa primitive component tests — rendered with react-dom/server (renderToStaticMarkup), so they run in the
// existing node vitest environment with NO new dependencies (no jsdom / RTL). These lock the contract the five
// screens depend on: sign-colouring, em-dash-for-null, %-formatting, action/readiness tag mapping, accrual bar.
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { AccrualBar, Dot, Pct, Pos, ReadinessTag, Tag, actionTag } from "../components";
import type { Readiness } from "@shared/autonomy";

const html = (node: Parameters<typeof renderToStaticMarkup>[0]) => renderToStaticMarkup(node);

describe("actionTag", () => {
  it("maps OPERATE / HALT / else", () => {
    expect(actionTag("OPERATE")).toEqual({ kind: "operate", label: "OPERATE" });
    expect(actionTag("HALT")).toEqual({ kind: "halt", label: "HALT" });
    expect(actionTag(undefined)).toEqual({ kind: "warmup", label: "WARMUP" });
    expect(actionTag("HOLD(warmup)")).toEqual({ kind: "warmup", label: "WARMUP" });
  });
});

describe("Pos", () => {
  it("signs and colours positives green", () => {
    const out = html(<Pos value={1.234} />);
    expect(out).toContain("+1.234");
    expect(out).toContain("mesa-pos");
  });
  it("colours negatives red without a +", () => {
    const out = html(<Pos value={-2} />);
    expect(out).toContain("-2.000");
    expect(out).toContain("mesa-neg");
  });
  it("renders an em-dash for null / NaN, dimmed", () => {
    expect(html(<Pos value={null} />)).toContain("—");
    expect(html(<Pos value={Number.NaN} />)).toContain("mesa-dim");
  });
  it("respects digits and signed=false", () => {
    const out = html(<Pos value={1.5} digits={2} signed={false} />);
    expect(out).toContain("1.50");
    expect(out).not.toContain("+1.50");
  });
});

describe("Pct", () => {
  it("scales by 100 and appends %", () => {
    expect(html(<Pct value={0.055} />)).toContain("5.5%");
  });
  it("em-dash for null", () => {
    expect(html(<Pct value={null} />)).toContain("—");
  });
});

describe("Tag / Dot", () => {
  it("Tag applies the kind class and renders children", () => {
    const out = html(<Tag kind="operate">OK</Tag>);
    expect(out).toContain("mesa-tag");
    expect(out).toContain("operate");
    expect(out).toContain("OK");
  });
  it("Dot applies the kind class", () => {
    expect(html(<Dot kind="halt" />)).toContain("halt");
  });
});

describe("ReadinessTag", () => {
  it("renders the state and its lowercase kind class", () => {
    const r: Readiness = { ready: false, state: "ACCRUING", message: "12 of 24" };
    const out = html(<ReadinessTag readiness={r} />);
    expect(out).toContain("ACCRUING");
    expect(out).toContain("accruing");
  });
});

describe("AccrualBar", () => {
  it("shows value/total and a non-zero fill", () => {
    const out = html(<AccrualBar value={3} total={12} />);
    expect(out).toContain("3/12");
    expect(out).toContain("width:25%");
  });
  it("marks the zero state", () => {
    const out = html(<AccrualBar value={0} total={12} />);
    expect(out).toContain("0/12");
    expect(out).toContain("zero");
  });
  it("clamps overflow to 100%", () => {
    const out = html(<AccrualBar value={30} total={12} />);
    expect(out).toContain("width:100%");
  });
});
