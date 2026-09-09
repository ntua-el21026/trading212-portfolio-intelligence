import { describe, expect, it, vi } from "vitest";
import {
  XrayApiClient,
  XrayApiError,
  XrayMoneyMetricSchema,
  XrayRatioMetricSchema,
} from "@trading212/api-contracts";

const account = "00000000-0000-4000-8000-000000000001";
const fund = "00000000-0000-4000-8000-000000000002";
const query = {
  snapshot_id: account,
  source_cutoff_at: "2026-09-07T12:00:00Z",
  reporting_currency: "EUR",
};

describe("generated X-ray client", () => {
  it("encodes repeated fund selectors and uses GET with private no-store reads", async () => {
    const fetchImpl = vi.fn(
      async () =>
        new Response(null, { status: 304, headers: { etag: "retained" } }),
    );
    const client = new XrayApiClient({
      baseUrl: "https://portfolio.example",
      fetchImpl,
    });
    const result = await client.get_etf_overlap(account, {
      ...query,
      fund_ids: [account, fund],
    });
    expect(result.notModified).toBe(true);
    const [url, init] = fetchImpl.mock.calls[0] as unknown as [
      URL,
      RequestInit,
    ];
    expect(url.searchParams.getAll("fund_ids")).toEqual([account, fund]);
    expect(init.method).toBe("GET");
    expect(init.cache).toBe("no-store");
    expect(init.redirect).toBe("error");
  });
  it("rejects unknown fields and excessive selections before dispatch", async () => {
    const fetchImpl = vi.fn();
    const client = new XrayApiClient({
      baseUrl: "https://portfolio.example",
      fetchImpl,
    });
    for (const extra of [
      { private_key: "canary" },
      { fund_ids: Array(33).fill(fund) },
    ]) {
      const error = await client
        .get_etf_overlap(account, {
          ...query,
          fund_ids: [account, fund],
          ...extra,
        })
        .catch((value: unknown) => value);
      expect(error).toBeInstanceOf(XrayApiError);
      expect(String(error)).not.toContain("canary");
    }
    expect(fetchImpl).not.toHaveBeenCalled();
  });
  it("retains 38-digit decimal strings and rejects hidden coefficients", () => {
    const metric = {
      reason: null,
      quality: "fresh",
      bound: "exact",
      availability: "available",
      confidence: null,
      source_reference_ids: [],
      source_count: 0,
      source_omitted_count: 0,
    };
    const money = XrayMoneyMetricSchema.parse({
      ...metric,
      origin: "derived_deterministic",
      value: {
        amount: "99999999999999999999.999999999999999999",
        currency: "EUR",
      },
    });
    expect(money.value?.amount).toBe("99999999999999999999.999999999999999999");
    expect(() =>
      XrayRatioMetricSchema.parse({
        ...metric,
        value: "0",
        positive_below_quantum: true,
        coefficient: "1",
      }),
    ).toThrow();
  });
  it("redacts network exceptions", async () => {
    const client = new XrayApiClient({
      baseUrl: "https://portfolio.example",
      fetchImpl: async () => {
        throw new Error("private-header-canary");
      },
    });
    const error = await client
      .get_effective_exposure(account, query)
      .catch((value: unknown) => value);
    expect(error).toMatchObject({ code: "XRAY_UNAVAILABLE", status: 503 });
    expect(String(error)).not.toContain("canary");
  });
});
