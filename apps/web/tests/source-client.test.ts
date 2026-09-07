import { describe, expect, it, vi } from "vitest";
import {
  SourceApiClient,
  SourceApiError,
  CreateBenchmarkDefinitionRequestSchema,
  BenchmarkSnapshotHeaderSchema,
} from "@trading212/api-contracts";

const source = "19751815-c671-47c4-a42c-1e619a037234";
const definition = "858c4e1b-9df6-462d-9482-08f405d7e895";
const content = {
  reporting_currency: "EUR",
  effective_at: "2026-09-07T12:00:00Z",
  return_basis: "raw_close" as const,
  calendar_id: "weekday",
  calendar_version: "v1",
  rebalance_rule: "buy_and_hold" as const,
  components: [{ source_id: source, weight: "1" }],
};

describe("generated source client", () => {
  it.each([1, true, "1e0", "NaN", "0.0000000000000000001", "1".repeat(21)])(
    "rejects noncanonical benchmark weight %s",
    (weight) => {
      expect(() =>
        CreateBenchmarkDefinitionRequestSchema.parse({
          name: "Synthetic benchmark",
          content: { ...content, components: [{ source_id: source, weight }] },
        }),
      ).toThrow();
    },
  );
  it("preserves exact fractional strings without normalizing a command", () => {
    const request = CreateBenchmarkDefinitionRequestSchema.parse({
      name: "Synthetic benchmark",
      content: {
        ...content,
        components: [{ source_id: source, weight: "0.9999999999995" }],
      },
    });
    expect(request.content.components[0].weight).toBe("0.9999999999995");
    expect(request.normalize).toBeUndefined();
  });
  it("rejects unexpected nested input before fetch without reflecting its name", async () => {
    const fetchImpl = vi.fn();
    const client = new SourceApiClient({
      baseUrl: "https://portfolio.example",
      fetchImpl,
    });
    const failure = await client
      .create_benchmark_definition(
        {
          name: "Synthetic benchmark",
          content: {
            ...content,
            components: [
              {
                ...content.components[0],
                "source-private-canary": "private-value",
              },
            ],
          },
        } as unknown as Parameters<
          SourceApiClient["create_benchmark_definition"]
        >[0],
        { idempotencyKey: "source-one" },
      )
      .catch((error: unknown) => error);
    expect(failure).toBeInstanceOf(SourceApiError);
    expect(String(failure)).not.toContain("source-private-canary");
    expect(String(failure)).not.toContain("private-value");
    expect(fetchImpl).not.toHaveBeenCalled();
  });
  it("rejects path traversal and oversized page limits before fetch", async () => {
    const fetchImpl = vi.fn();
    const client = new SourceApiClient({
      baseUrl: "https://portfolio.example",
      fetchImpl,
    });
    await expect(
      client.get_price_snapshot("../private", {}),
    ).rejects.toMatchObject({ code: "VALIDATION_FAILED" });
    await expect(
      client.list_price_observations(source, { limit: 101 }),
    ).rejects.toMatchObject({ code: "VALIDATION_FAILED" });
    expect(fetchImpl).not.toHaveBeenCalled();
  });
  it("keeps benchmark revision and idempotency identity in headers on the fixed route", async () => {
    const fetchImpl = vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            error: {
              code: "REVISION_MISMATCH",
              message: "private-source-message",
            },
          }),
          { status: 412 },
        ),
    );
    const client = new SourceApiClient({
      baseUrl: "https://portfolio.example",
      fetchImpl,
    });
    await expect(
      client.create_benchmark_version(
        definition,
        { content },
        { idempotencyKey: "source-version-one", ifMatch: `"${definition}:1"` },
      ),
    ).rejects.toMatchObject({ code: "REVISION_MISMATCH", status: 412 });
    const [url, init] = fetchImpl.mock.calls[0] as unknown as [
      URL,
      RequestInit,
    ];
    expect(url.pathname).toBe(
      `/api/v1/benchmark-definitions/${definition}/versions`,
    );
    expect(new Headers(init.headers).get("If-Match")).toBe(`"${definition}:1"`);
    expect(new Headers(init.headers).get("X-Idempotency-Key")).toBe(
      "source-version-one",
    );
    expect(JSON.parse(init.body as string)).toEqual({ content });
    expect(init.redirect).toBe("error");
  });
  it.each(["PROVIDER_UNAVAILABLE", "private-source-code"])(
    "sanitizes error %s",
    async (code) => {
      const client = new SourceApiClient({
        baseUrl: "https://portfolio.example",
        fetchImpl: async () =>
          new Response(
            JSON.stringify({
              error: { code, message: "source-private-canary" },
            }),
            { status: 503 },
          ),
      });
      const failure = await client
        .get_benchmark_definition(definition, {})
        .catch((error: unknown) => error);
      expect(failure).toBeInstanceOf(SourceApiError);
      expect(String(failure)).not.toContain("source-private-canary");
      expect(String(failure)).not.toContain("private-source-code");
    },
  );
  it("preserves conditional response metadata without fabricating snapshot data", async () => {
    const client = new SourceApiClient({
      baseUrl: "https://portfolio.example",
      fetchImpl: async () =>
        new Response(null, {
          status: 304,
          headers: { etag: '"source-representation"' },
        }),
    });
    await expect(
      client.get_price_snapshot(
        source,
        {},
        { ifNoneMatch: '"source-representation"' },
      ),
    ).resolves.toEqual({
      data: null,
      notModified: true,
      etag: '"source-representation"',
    });
  });
  it("does not accept a fake composite branch in the raw benchmark snapshot schema", () => {
    expect(
      BenchmarkSnapshotHeaderSchema.shape.kind.safeParse("composite").success,
    ).toBe(false);
    expect(
      BenchmarkSnapshotHeaderSchema.shape.benchmark_version_id.safeParse(
        definition,
      ).success,
    ).toBe(false);
  });
  it("cancels an oversized response before JSON parsing", async () => {
    const cancel = vi.fn();
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(new Uint8Array(2 * 1024 * 1024 + 1));
      },
      cancel,
    });
    const client = new SourceApiClient({
      baseUrl: "https://portfolio.example",
      fetchImpl: async () => new Response(stream),
    });
    await expect(client.get_price_snapshot(source, {})).rejects.toMatchObject({
      code: "RESULT_TOO_LARGE",
      status: 502,
    });
    expect(cancel).toHaveBeenCalledOnce();
  });
});
