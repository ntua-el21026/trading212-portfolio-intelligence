import { describe, expect, it, vi } from "vitest";
import {
  AggregateApiClient,
  AggregateApiError,
  AggregateMoneySchema,
} from "@trading212/api-contracts";
import { AggregateTransport } from "../../../packages/api-contracts/src/aggregate-transport";
import { z } from "zod";

const id = "00000000-0000-4000-8000-000000000001";
const at = "2026-09-15T12:00:00Z";
const run = {
  run_id: id,
  selection_id: id,
  selection_revision: 2,
  holdings_input_digest: "a".repeat(64),
  holdings_result_digest: "b".repeat(64),
  activity_input_digest: null,
  activity_result_digest: null,
  activity_requested: false,
  state: "succeeded",
  created_at: at,
  expires_at: "2026-10-15T12:00:00Z",
};

describe("fixed aggregate generated client", () => {
  it("sends exact command identity and selection revision without numeric money conversion", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify(run), { status: 201 }));
    const client = new AggregateApiClient({
      baseUrl: "https://example.test",
      fetchImpl,
    });
    const result = await client.create_aggregate_run(
      id,
      { fx_bindings: [], activity_window: null },
      { idempotencyKey: "aggregate-create", ifMatch: `"${id}:1"` },
    );
    expect(result.data).toEqual(run);
    const [url, options] = fetchImpl.mock.calls[0];
    expect(String(url)).toBe(
      `https://example.test/api/v1/aggregate-selections/${id}/runs`,
    );
    expect(options.method).toBe("POST");
    expect(options.headers.get("If-Match")).toBe(`"${id}:1"`);
    expect(options.headers.get("X-Idempotency-Key")).toBe("aggregate-create");
    expect(
      AggregateMoneySchema.safeParse({
        currency: "EUR",
        value: 1,
        known_value: "1",
        known_count: 1,
        total_count: 1,
        quality: "fresh",
      }).success,
    ).toBe(false);
  });

  it("allows the bounded synchronous run while keeping reads at eight seconds", async () => {
    const timeout = vi.spyOn(AbortSignal, "timeout");
    const fetchImpl = vi
      .fn()
      .mockImplementation(async () => new Response(JSON.stringify(run)));
    try {
      const client = new AggregateApiClient({
        baseUrl: "https://example.test",
        fetchImpl,
      });
      await client.create_aggregate_run(
        id,
        { fx_bindings: [], activity_window: null },
        { idempotencyKey: "bounded-run", ifMatch: `"${id}:1"` },
      );
      expect(timeout).toHaveBeenLastCalledWith(30_000);
      const transport = new AggregateTransport({
        baseUrl: "https://example.test",
        fetchImpl,
      });
      await transport.request(
        "GET",
        `/api/v1/aggregate-selections/${id}`,
        z.unknown(),
        undefined,
        undefined,
        {},
      );
      expect(timeout).toHaveBeenLastCalledWith(8_000);
    } finally {
      timeout.mockRestore();
    }
  });

  it("rejects unknown direct internal transport methods and paths before any fetch", async () => {
    const fetchImpl = vi.fn();
    const transport = new AggregateTransport({
      baseUrl: "https://example.test",
      fetchImpl,
    });
    for (const [method, path] of [
      ["DELETE", `/api/v1/aggregate-runs/${id}`],
      ["GET", "https://outside.test/private"],
      ["POST", `/api/v1/aggregate-runs/${id}`],
      ["GET", "/api/v1/accounts"],
    ] as const) {
      await expect(
        transport.request(method, path, z.unknown(), undefined, undefined, {}),
      ).rejects.toBeInstanceOf(AggregateApiError);
    }
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("maps failed reads to safe aggregate errors without echoing provider text", async () => {
    const fetchImpl = vi
      .fn()
      .mockRejectedValue(new Error("secret-query-canary"));
    const client = new AggregateApiClient({
      baseUrl: "https://example.test",
      fetchImpl,
    });
    await expect(client.get_aggregate_selection(id)).rejects.toMatchObject({
      code: "SOURCE_UNAVAILABLE",
      status: 503,
    });
  });
});
