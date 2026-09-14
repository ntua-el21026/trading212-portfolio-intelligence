import { describe, expect, it, vi } from "vitest";
import {
  RiskApiClient,
  RiskApiError,
  RiskAvailableMetricSchema,
  RiskUnavailableMetricSchema,
  CreateRiskRunRequestSchema,
} from "@trading212/api-contracts";

const account = "d778f930-9d2e-4f47-b24f-5b1fa99c6eee";
const definition = "45f8f732-2e9d-4ca2-a811-21671202a683";
const version = "b8532ba7-36e4-43ef-aee4-a4e67c75ef9d";
const run = "e42d5fa3-cd19-44ea-890a-e892845b685a";
const content = {
  name: "Risk",
  calendar_id: "synthetic-utc",
  calendar_version: "v1",
  annual_risk_free: "0.012345678901234567",
};
const saved = {
  id: definition,
  account_id: account,
  name: "Risk",
  revision: 1,
  archived: false,
  current_version_id: version,
  created_at: "2026-09-14T12:00:00Z",
  updated_at: "2026-09-14T12:00:00Z",
};

function client(fetchImpl: typeof fetch) {
  return new RiskApiClient({ baseUrl: "https://portfolio.example", fetchImpl });
}

describe("generated closed risk client", () => {
  it("exposes exactly eleven fixed operations and encodes canonical selectors", async () => {
    const requests: string[] = [];
    const api = client(async (url, init) => {
      const parsed = new URL(String(url));
      requests.push(parsed.pathname);
      expect(init?.cache).toBe("no-store");
      expect(init?.redirect).toBe("error");
      return new Response(null, { status: 304 });
    });
    expect(Object.getOwnPropertyNames(RiskApiClient.prototype).sort()).toEqual(
      [
        "constructor",
        "list_risk_definitions",
        "create_risk_definition",
        "get_risk_definition",
        "list_risk_versions",
        "create_risk_version",
        "get_risk_version",
        "list_risk_runs",
        "create_risk_run",
        "get_risk_run",
        "get_risk_matrix",
        "cancel_risk_run",
      ].sort(),
    );
    await api.list_risk_definitions(account, { limit: 25 });
    await api.get_risk_definition(definition);
    await api.list_risk_versions(definition, { limit: 25 });
    await api.get_risk_version(version);
    await api.list_risk_runs(account, { limit: 25 });
    await api.get_risk_run(run);
    await api.get_risk_matrix(run);
    expect(requests).toEqual([
      `/api/v1/accounts/${account}/risk-definitions`,
      `/api/v1/risk-definitions/${definition}`,
      `/api/v1/risk-definitions/${definition}/versions`,
      `/api/v1/risk-definition-versions/${version}`,
      `/api/v1/accounts/${account}/risk-runs`,
      `/api/v1/risk-runs/${run}`,
      `/api/v1/risk-runs/${run}/matrix`,
    ]);
  });

  it("preserves decimal strings and command identity headers without broker dispatch", async () => {
    const fetchImpl = vi.fn<typeof fetch>(async (url, init) => {
      expect(String(url)).toBe(
        `https://portfolio.example/api/v1/accounts/${account}/risk-definitions`,
      );
      expect(init?.method).toBe("POST");
      expect(new Headers(init?.headers).get("X-Idempotency-Key")).toBe(
        "risk.create.one",
      );
      expect(JSON.parse(String(init?.body)).content.annual_risk_free).toBe(
        content.annual_risk_free,
      );
      return new Response(JSON.stringify(saved), {
        status: 201,
        headers: { ETag: `"${definition}:1"` },
      });
    });
    const response = await client(fetchImpl).create_risk_definition(
      account,
      { content },
      { idempotencyKey: "risk.create.one" },
    );
    expect(response).toMatchObject({
      data: saved,
      notModified: false,
      etag: `"${definition}:1"`,
    });
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it("rejects invalid identity, bounds, floats and private extension fields before fetch", async () => {
    const fetchImpl = vi.fn<typeof fetch>();
    const api = client(fetchImpl);
    const invalid = [
      api.get_risk_run("../private-canary"),
      api.list_risk_runs(account, { limit: 101 }),
      api.create_risk_definition(
        account,
        { content },
        { idempotencyKey: "private-canary/invalid" },
      ),
      api.create_risk_definition(
        account,
        // @ts-expect-error The generated schema also rejects financial binary numbers at runtime.
        { content: { ...content, annual_risk_free: 0.1 } },
        { idempotencyKey: "one" },
      ),
      // @ts-expect-error Unknown fields remain forbidden after type erasure.
      api.list_risk_definitions(account, { "private-canary": "hidden" }),
    ];
    for (const result of invalid)
      await expect(result).rejects.toMatchObject({
        code: "VALIDATION_FAILED",
        status: 422,
      });
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("cannot invent zero or a reasonless missing metric", () => {
    expect(
      RiskAvailableMetricSchema.parse({ value: "0", reason: null }).value,
    ).toBe("0");
    expect(
      RiskUnavailableMetricSchema.parse({
        value: null,
        reason: "insufficient_history",
      }).value,
    ).toBeNull();
    for (const value of [null, 0, 0.1, "NaN", "Infinity"])
      expect(
        RiskAvailableMetricSchema.safeParse({ value, reason: null }).success,
      ).toBe(false);
    expect(
      RiskUnavailableMetricSchema.safeParse({ value: null, reason: null })
        .success,
    ).toBe(false);
    expect(
      CreateRiskRunRequestSchema.safeParse({ returns: ["0.1"] }).success,
    ).toBe(false);
  });

  it("redacts untrusted server and network failure messages", async () => {
    const api = client(
      async () =>
        new Response(
          JSON.stringify({
            error: {
              code: "SOURCE_UNAVAILABLE",
              message: "private-canary",
              correlation_id: "trace",
              retryable: true,
              details: {},
            },
          }),
          { status: 503 },
        ),
    );
    await expect(api.get_risk_run(run)).rejects.toMatchObject({
      code: "SOURCE_UNAVAILABLE",
      status: 503,
    });
    try {
      await api.get_risk_run(run);
    } catch (error) {
      expect(error).toBeInstanceOf(RiskApiError);
      expect(String(error)).not.toContain("private-canary");
    }
    const offline = client(async () => {
      throw new Error("private-canary");
    });
    await expect(offline.get_risk_run(run)).rejects.toMatchObject({
      code: "RISK_UNAVAILABLE",
      message: "The risk result or service is temporarily unavailable.",
    });
  });
});
