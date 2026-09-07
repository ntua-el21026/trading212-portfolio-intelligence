import { describe, expect, it, vi } from "vitest";
import {
  HistoricalApiClient,
  HistoricalApiError,
  HistoricalMoneyMetricSchema,
  HistoricalRatioMetricSchema,
  CompositeBenchmarkSnapshotHeaderSchema,
  CompositeBenchmarkObservationPageSchema,
} from "@trading212/api-contracts";
import { z } from "zod";
import { BoundedTransport } from "../../../packages/api-contracts/src/bounded-transport";

const account = "d778f930-9d2e-4f47-b24f-5b1fa99c6eee";
const query = {
  start_date: "2026-01-01",
  end_date: "2026-01-02",
  source_cutoff_at: "2026-02-01T00:00:00Z",
  reporting_currency: "EUR",
};
const metric = {
  availability: "available",
  coverage_key: "valuation_cells",
  origin: "derived",
  quality: "fresh",
  reason_code: null,
};

describe("generated historical client", () => {
  it("keeps the previous transport deadline at eight seconds and validates the internal bound", async () => {
    const timeout = vi.spyOn(AbortSignal, "timeout");
    try {
      const policy = {
        label: "prior",
        errors: {},
        fallbackCode: "FAILED",
        error: (_code: string, _status: number, message: string) =>
          new Error(message),
      };
      const options = {
        baseUrl: "https://portfolio.example",
        fetchImpl: async () => new Response(null, { status: 304 }),
      };
      await new BoundedTransport(options, policy).request(
        "GET",
        "/api/v1/retained",
        z.unknown(),
        {},
        undefined,
        {},
      );
      expect(timeout).toHaveBeenLastCalledWith(8_000);
      for (const readTimeoutMs of [0, 30_001, 0.5, Number.NaN]) {
        expect(
          () => new BoundedTransport(options, { ...policy, readTimeoutMs }),
        ).toThrow(RangeError);
      }
    } finally {
      timeout.mockRestore();
    }
  });

  it("allows a bounded cold historical response beyond eight seconds without changing other clients", async () => {
    vi.useFakeTimers();
    const timeout = vi
      .spyOn(AbortSignal, "timeout")
      .mockImplementation((duration) => {
        const controller = new AbortController();
        setTimeout(() => controller.abort(), duration);
        return controller.signal;
      });
    try {
      const client = new HistoricalApiClient({
        baseUrl: "https://portfolio.example",
        fetchImpl: async (_url, init) =>
          new Promise<Response>((resolve, reject) => {
            init?.signal?.addEventListener("abort", () =>
              reject(new Error("private-source-canary")),
            );
            setTimeout(
              () => resolve(new Response(null, { status: 304 })),
              9_000,
            );
          }),
      });
      const result = client.get_performance_summary(account, query);
      await vi.advanceTimersByTimeAsync(9_000);
      await expect(result).resolves.toMatchObject({ notModified: true });
      expect(timeout).toHaveBeenCalledWith(30_000);
    } finally {
      timeout.mockRestore();
      vi.useRealTimers();
    }
  });

  it("converts its thirty-second abort and network failures to a safe unavailable result", async () => {
    vi.useFakeTimers();
    const timeout = vi
      .spyOn(AbortSignal, "timeout")
      .mockImplementation((duration) => {
        const controller = new AbortController();
        setTimeout(() => controller.abort(), duration);
        return controller.signal;
      });
    try {
      const client = new HistoricalApiClient({
        baseUrl: "https://portfolio.example",
        fetchImpl: async (_url, init) =>
          new Promise<Response>((_resolve, reject) => {
            init?.signal?.addEventListener("abort", () =>
              reject(new Error("private-source-canary")),
            );
          }),
      });
      const result = client
        .get_performance_summary(account, query)
        .catch((value: unknown) => value);
      await vi.advanceTimersByTimeAsync(30_000);
      const error = await result;
      expect(error).toBeInstanceOf(HistoricalApiError);
      expect(error).toMatchObject({
        code: "HISTORICAL_UNAVAILABLE",
        status: 503,
      });
      expect(String(error)).not.toContain("canary");
      const offline = new HistoricalApiClient({
        baseUrl: "https://portfolio.example",
        fetchImpl: async () => {
          throw new TypeError("private-url-canary");
        },
      });
      const networkError = await offline
        .get_performance_summary(account, query)
        .catch((value: unknown) => value);
      expect(networkError).toBeInstanceOf(HistoricalApiError);
      expect(String(networkError)).not.toContain("canary");
    } finally {
      timeout.mockRestore();
      vi.useRealTimers();
    }
  });

  it.each([
    0.1,
    true,
    "NaN",
    "Infinity",
    "1e-6",
    "0.0000000000000000001",
    "1".repeat(21),
  ])("rejects a noncanonical authoritative amount %s", (amount) => {
    expect(() =>
      HistoricalMoneyMetricSchema.parse({
        ...metric,
        value: { amount, currency: "EUR" },
      }),
    ).toThrow();
  });

  it("preserves every canonical monetary digit and distinct unavailable values", () => {
    const value = {
      amount: "99999999999999999999.000000000000000001",
      currency: "EUR",
    };
    expect(
      HistoricalMoneyMetricSchema.parse({ ...metric, value }).value,
    ).toEqual(value);
    expect(
      HistoricalRatioMetricSchema.parse({ ...metric, value: "0" }).value,
    ).toBe("0");
    expect(
      HistoricalRatioMetricSchema.parse({
        ...metric,
        availability: "unavailable",
        quality: "partial",
        reason_code: "unavailable_positive_denominator",
        value: null,
      }).value,
    ).toBeNull();
  });

  it("rejects unknown query keys before transport without reflecting private text", async () => {
    const fetchImpl = vi.fn();
    const client = new HistoricalApiClient({
      baseUrl: "https://portfolio.example",
      fetchImpl,
    });
    const error = await client
      .get_performance_summary(account, {
        ...query,
        "historical-private-canary": "private-value-canary",
      } as unknown as Parameters<
        HistoricalApiClient["get_performance_summary"]
      >[1])
      .catch((value: unknown) => value);
    expect(error).toBeInstanceOf(HistoricalApiError);
    expect(String(error)).not.toContain("canary");
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("rejects path traversal, unsupported selectors and unbounded pages before fetch", async () => {
    const fetchImpl = vi.fn();
    const client = new HistoricalApiClient({
      baseUrl: "https://portfolio.example",
      fetchImpl,
    });
    await expect(
      client.get_performance_summary("../private", query),
    ).rejects.toMatchObject({ code: "VALIDATION_FAILED" });
    await expect(
      client.get_performance_series(account, { ...query, limit: 101 }),
    ).rejects.toMatchObject({ code: "VALIDATION_FAILED" });
    await expect(
      client.get_attribution_summary(account, { ...query, top_n: 51 }),
    ).rejects.toMatchObject({ code: "VALIDATION_FAILED" });
    await expect(
      client.get_performance_summary(account, {
        ...query,
        source_cutoff_at: "2026-02-01T00:00:00",
      }),
    ).rejects.toMatchObject({ code: "VALIDATION_FAILED" });
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("sends exact capture/window pins and conditional read headers on the fixed GET route", async () => {
    const fetchImpl = vi.fn(
      async () =>
        new Response(null, {
          status: 304,
          headers: { ETag: '"representation-v2"' },
        }),
    );
    const client = new HistoricalApiClient({
      baseUrl: "https://portfolio.example",
      fetchImpl,
    });
    const result = await client.get_performance_summary(
      account,
      {
        ...query,
        knowledge_policy: "point_in_time",
        input_snapshot_id: account,
        method: "modified_dietz",
        rolling_window: "calendar_days_30",
        calendar_period: "year",
      },
      { ifNoneMatch: '"representation-v1"' },
    );
    expect(result).toEqual({
      data: null,
      etag: '"representation-v2"',
      notModified: true,
    });
    const [url, init] = fetchImpl.mock.calls[0] as unknown as [
      URL,
      RequestInit,
    ];
    expect(url.pathname).toBe(
      `/api/v1/accounts/${account}/performance/intelligence`,
    );
    expect(url.searchParams.get("input_snapshot_id")).toBe(account);
    expect(url.searchParams.get("source_cutoff_at")).toBe(
      query.source_cutoff_at,
    );
    expect(url.searchParams.get("knowledge_policy")).toBe("point_in_time");
    expect(init.method).toBe("GET");
    expect(init.body).toBeUndefined();
    expect(init.redirect).toBe("error");
    expect(new Headers(init.headers).get("If-None-Match")).toBe(
      '"representation-v1"',
    );
  });

  it("maps errors to fixed messages without echoing source payloads", async () => {
    const fetchImpl = vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            error: {
              code: "INPUT_SNAPSHOT_MISMATCH",
              message: "private-source-canary",
            },
          }),
          { status: 409 },
        ),
    );
    const client = new HistoricalApiClient({
      baseUrl: "https://portfolio.example",
      fetchImpl,
    });
    const error = await client
      .get_performance_summary(account, query)
      .catch((value: unknown) => value);
    expect(error).toMatchObject({
      code: "INPUT_SNAPSHOT_MISMATCH",
      status: 409,
    });
    expect(String(error)).not.toContain("canary");
  });

  it("requires the composite discriminator and rejects provider-shaped ambiguity", () => {
    expect(
      CompositeBenchmarkSnapshotHeaderSchema.shape.kind.safeParse(undefined)
        .success,
    ).toBe(false);
    expect(
      CompositeBenchmarkObservationPageSchema.shape.kind.safeParse(undefined)
        .success,
    ).toBe(false);
    expect(
      CompositeBenchmarkObservationPageSchema.safeParse({
        items: [],
        next_cursor: null,
        limit: 25,
        total: 0,
        snapshot_id: account,
        kind: "provider_series",
      }).success,
    ).toBe(false);
  });
});
