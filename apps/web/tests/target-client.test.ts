import { describe, expect, it, vi } from "vitest";
import {
  TargetApiClient,
  TargetApiError,
  TargetContentSchema,
} from "@trading212/api-contracts";

const portfolioId = "72f00000-0000-4000-8000-000000000001";
const node = {
  key: "cash",
  kind: "cash" as const,
  name: "EUR cash",
  weight: "1",
  order: 0,
};

describe("generated target client boundaries", () => {
  it.each(["INTERNAL_ERROR", "unrecognized-private-code"])(
    "never exposes upstream private messages for %s",
    async (code) => {
      const canary = "target-upstream-private-value";
      const client = new TargetApiClient({
        baseUrl: "https://portfolio.example",
        fetchImpl: async () =>
          new Response(JSON.stringify({ error: { code, message: canary } }), {
            status: 500,
          }),
      });
      const error = await client
        .get_virtual_portfolio(portfolioId)
        .catch((failure: unknown) => failure);
      expect(error).toBeInstanceOf(TargetApiError);
      expect(String(error)).not.toContain(canary);
      expect(String(error)).not.toContain("unrecognized-private-code");
    },
  );

  it("does not include malformed response content in parser failures", async () => {
    const canary = "target-parser-private-value";
    const client = new TargetApiClient({
      baseUrl: "https://portfolio.example",
      fetchImpl: async () => new Response(canary),
    });
    const error = await client
      .get_virtual_portfolio(portfolioId)
      .catch((failure: unknown) => failure);
    expect(error).toBeInstanceOf(TargetApiError);
    expect(String(error)).not.toContain(canary);
  });
  it.each([
    0.1,
    NaN,
    Infinity,
    "1e-2",
    "100000000000000000000",
    "0.0000000000000000001",
  ])("rejects unsafe financial representation %s", (weight) => {
    expect(() =>
      TargetContentSchema.parse({ nodes: [{ ...node, weight }] }),
    ).toThrow();
  });

  it("forbids unknown nested fields while preserving exact decimal text", () => {
    const content = { nodes: [{ ...node, weight: "0.123456789012345678" }] };
    expect(TargetContentSchema.parse(content).nodes[0].weight).toBe(
      "0.123456789012345678",
    );
    expect(() =>
      TargetContentSchema.parse({ nodes: [{ ...node, broker_order: true }] }),
    ).toThrow();
  });

  it("validates opaque IDs before any request dispatch", async () => {
    const fetchImpl = vi.fn();
    const client = new TargetApiClient({
      baseUrl: "https://portfolio.example",
      fetchImpl,
    });
    await expect(client.get_virtual_portfolio("../secrets")).rejects.toThrow();
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("forwards authorized conditional requests and preserves a 304", async () => {
    const fetchImpl = vi.fn(
      async () =>
        new Response(null, {
          status: 304,
          headers: { etag: `"${portfolioId}:4"` },
        }),
    );
    const client = new TargetApiClient({
      baseUrl: "https://portfolio.example",
      fetchImpl,
    });
    expect(
      await client.get_virtual_portfolio(portfolioId, {
        ifNoneMatch: `"${portfolioId}:4"`,
      }),
    ).toEqual({ data: null, notModified: true, etag: `"${portfolioId}:4"` });
    const [url, init] = fetchImpl.mock.calls[0] as unknown as [
      URL,
      RequestInit,
    ];
    expect(url.pathname).toBe(`/api/v1/virtual-portfolios/${portfolioId}`);
    expect(new Headers(init.headers).get("If-None-Match")).toBe(
      `"${portfolioId}:4"`,
    );
    expect(init.redirect).toBe("error");
  });

  it("keeps mutation identity and optimistic precondition out of the JSON body", async () => {
    const fetchImpl = vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            error: {
              code: "REVISION_MISMATCH",
              message: "The revision changed.",
            },
          }),
          { status: 412 },
        ),
    );
    const client = new TargetApiClient({
      baseUrl: "https://portfolio.example",
      fetchImpl,
    });
    await expect(
      client.update_virtual_portfolio(
        portfolioId,
        { name: "Renamed" },
        { idempotencyKey: "rename:1", ifMatch: `"${portfolioId}:3"` },
      ),
    ).rejects.toMatchObject({ code: "REVISION_MISMATCH", status: 412 });
    const [, init] = fetchImpl.mock.calls[0] as unknown as [URL, RequestInit];
    expect(init.body).toBe('{"name":"Renamed"}');
    expect(new Headers(init.headers).get("X-Idempotency-Key")).toBe("rename:1");
    expect(new Headers(init.headers).get("If-Match")).toBe(
      `"${portfolioId}:3"`,
    );
  });

  it("cancels a streamed response above the 2 MiB boundary", async () => {
    const cancel = vi.fn();
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(new Uint8Array(2 * 1024 * 1024 + 1));
      },
      cancel,
    });
    const client = new TargetApiClient({
      baseUrl: "https://portfolio.example",
      fetchImpl: async () => new Response(stream),
    });
    await expect(
      client.get_virtual_portfolio(portfolioId),
    ).rejects.toBeInstanceOf(TargetApiError);
    expect(cancel).toHaveBeenCalledOnce();
  });

  it("rejects oversized UTF-8 requests before dispatch", async () => {
    const fetchImpl = vi.fn();
    const client = new TargetApiClient({
      baseUrl: "https://portfolio.example",
      fetchImpl,
    });
    const nodes = Array.from({ length: 256 }, (_, index) => ({
      ...node,
      key: `node-${index}`,
      name: "界".repeat(100),
      order: index,
    }));
    await expect(
      client.create_target_version(
        portfolioId,
        { effective_at: "2026-09-07T00:00:00Z", content: { nodes } },
        { idempotencyKey: "oversized-target" },
      ),
    ).rejects.toMatchObject({ code: "REQUEST_TOO_LARGE", status: 413 });
    expect(fetchImpl).not.toHaveBeenCalled();
  });
});
