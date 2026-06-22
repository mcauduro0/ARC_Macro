import { afterEach, describe, expect, it, vi } from "vitest";
import { arcApiDecide, arcApiGet } from "./autonomyRouter";

function mockFetch(status: number, body: unknown) {
  return vi.fn(async () => ({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  })) as unknown as typeof fetch;
}

afterEach(() => vi.restoreAllMocks());

describe("autonomy bridge proxy", () => {
  it("arcApiGet returns parsed JSON on 200", async () => {
    vi.stubGlobal("fetch", mockFetch(200, { meta: { n_promoted: 0 }, sleeves: [] }));
    const d = await arcApiGet<{ meta: { n_promoted: number } }>("/api/autonomy/state");
    expect(d.meta.n_promoted).toBe(0);
  });

  it("arcApiGet throws a readable error on a non-2xx", async () => {
    vi.stubGlobal("fetch", mockFetch(500, {}));
    await expect(arcApiGet("/api/autonomy/state")).rejects.toThrow(/500/);
  });

  it("arcApiDecide returns ok + decision on 200", async () => {
    vi.stubGlobal("fetch", mockFetch(200, { ok: true, decision: { action: "APPROVE" } }));
    const r = await arcApiDecide({ strategy: "momentum", month: "2026-07-31", action: "APPROVE" });
    expect(r.ok).toBe(true);
    expect((r.decision as { action: string }).action).toBe("APPROVE");
  });

  it("arcApiDecide surfaces the FastAPI detail on 409 (immutable record)", async () => {
    vi.stubGlobal("fetch", mockFetch(409, { detail: "already committed with a different choice" }));
    await expect(
      arcApiDecide({ strategy: "momentum", month: "2026-07-31", action: "SKIP" }),
    ).rejects.toThrow(/different choice/);
  });
});
