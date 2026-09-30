import { describe, expect, it, vi } from "vitest";
import { SourceApiClient } from "@trading212/api-contracts";
const id = "00000000-0000-4000-8000-000000000001";
const point = "00000000-0000-4000-8000-000000000002";
const cutoff = "2026-09-07T12:00:00.123456Z";
const effective = "2026-09-06T12:00:00.123455Z";
const query = {
  account_id: id,
  base: "EUR",
  quote: "USD",
  source_cutoff_at: cutoff,
  effective_at_lte: effective,
  limit: 25,
};
const payload = {
  account_id: id,
  snapshot_id: id,
  content_digest: "b".repeat(64),
  base: "EUR",
  quote: "USD",
  source_cutoff_at: cutoff,
  effective_at_lte: effective,
  first_observed_at: cutoff,
  expires_at: "2026-09-08T12:00:00Z",
  limit: 25,
  next_cursor: null,
  items: [
    {
      observation_id: point,
      session_date: "2026-09-06",
      effective_at: effective,
      rate: "1.123456789123456789",
      state: "available",
    },
  ],
};
describe("saved FX observation references", () => {
  it("keeps exact clocks and rates on the fixed bounded source read", async () => {
    const fetchImpl = vi.fn(
      async (_input: RequestInfo | URL, _init?: RequestInit) => {
        void _input;
        void _init;
        return new Response(JSON.stringify(payload), { status: 200 });
      },
    );
    const client = new SourceApiClient({
      baseUrl: "https://local.test",
      fetchImpl,
    });
    const result = await client.list_fx_observation_references(id, query);
    expect(result.notModified).toBe(false);
    if (!result.notModified)
      expect(result.data.items[0]).toEqual(payload.items[0]);
    const url = new URL(String(fetchImpl.mock.calls[0][0]));
    expect(url.pathname).toBe(
      `/api/v1/fx-snapshots/${id}/observation-references`,
    );
    expect(url.searchParams.get("source_cutoff_at")).toBe(cutoff);
    expect(url.searchParams.get("effective_at_lte")).toBe(effective);
  });
  it("rejects path traversal and excess limits before fetch", async () => {
    const fetchImpl = vi.fn();
    const client = new SourceApiClient({
      baseUrl: "https://local.test",
      fetchImpl,
    });
    await expect(
      client.list_fx_observation_references("../private", query),
    ).rejects.toMatchObject({ code: "VALIDATION_FAILED" });
    await expect(
      client.list_fx_observation_references(id, { ...query, limit: 26 }),
    ).rejects.toMatchObject({ code: "VALIDATION_FAILED" });
    expect(fetchImpl).not.toHaveBeenCalled();
  });
  it("does not expose unknown backend error text", async () => {
    const fetchImpl = vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            error: {
              code: "ACCESS_DENIED",
              message: "private-rate-canary",
            },
          }),
          { status: 403 },
        ),
    );
    const client = new SourceApiClient({
      baseUrl: "https://local.test",
      fetchImpl,
    });
    const error: unknown = await client
      .list_fx_observation_references(id, query)
      .catch((value: unknown) => value);
    expect(error).toMatchObject({ code: "ACCESS_DENIED" });
    expect(String(error)).not.toContain("private-rate-canary");
  });
});
