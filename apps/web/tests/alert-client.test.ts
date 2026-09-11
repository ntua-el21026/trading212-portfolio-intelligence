// @vitest-environment node
import { describe, expect, it, vi } from "vitest";
import { AlertApiClient, AlertApiError } from "@trading212/api-contracts";
import { alertAccount, alertRule } from "./alert-fixtures";

const privateHeaders = {
  "cache-control": "private, no-store",
  "content-type": "application/json",
};
function client(fetchImpl: typeof fetch) {
  return new AlertApiClient({
    baseUrl: "https://portfolio.example",
    fetchImpl,
    headers: () => ({
      "X-CSRF-Token": "ephemeral-csrf",
      Authorization: "Bearer ephemeral-session",
    }),
  });
}

describe("fixed alert transport", () => {
  it("uses only the typed command path and exact action/idempotency headers", async () => {
    const fetchImpl = vi.fn(async () =>
      Response.json(alertRule, {
        status: 201,
        headers: { ...privateHeaders, ETag: `"${alertRule.id}:1"` },
      }),
    );
    const result = await client(fetchImpl).create_alert_rule(
      {
        account_id: alertAccount,
        definition: alertRule.latest_version.definition,
      },
      { idempotencyKey: "rule:first" },
    );
    expect(result.notModified).toBe(false);
    const [url, init] = fetchImpl.mock.calls[0] as unknown as [
      URL,
      RequestInit,
    ];
    expect(url.pathname).toBe("/api/v1/alert-rules");
    expect(url.search).toBe("");
    expect(init).toMatchObject({
      method: "POST",
      cache: "no-store",
      redirect: "error",
    });
    expect(new Headers(init.headers).get("x-idempotency-key")).toBe(
      "rule:first",
    );
    expect(new Headers(init.headers).get("x-csrf-token")).toBe(
      "ephemeral-csrf",
    );
    expect(url.href).not.toContain("ephemeral");
    expect(JSON.parse(String(init.body))).toMatchObject({
      account_id: alertAccount,
    });
  });
  it("rejects unknown predicate fields before fetch and preserves exact decimal strings", async () => {
    const fetchImpl = vi.fn(async () =>
      Response.json(alertRule, { status: 201, headers: privateHeaders }),
    );
    const body = {
      account_id: alertAccount,
      definition: alertRule.latest_version.definition,
    };
    await client(fetchImpl).create_alert_rule(body, {
      idempotencyKey: "first",
    });
    expect(
      (fetchImpl.mock.calls[0] as unknown as [URL, RequestInit])[1].body,
    ).toContain('"threshold":"0.100000000000000001"');
    fetchImpl.mockClear();
    await expect(
      client(fetchImpl).create_alert_rule(
        {
          ...body,
          definition: {
            ...body.definition,
            predicate: {
              ...body.definition.predicate,
              expression: "private-expression",
            },
          },
        } as unknown as typeof body,
        { idempotencyKey: "invalid" },
      ),
    ).rejects.toBeDefined();
    expect(fetchImpl).not.toHaveBeenCalled();
  });
  it.each([
    ["REVISION_MISMATCH", 412],
    ["IDEMPOTENCY_KEY_REUSED", 409],
    ["INVALID_STATE_TRANSITION", 409],
    ["RATE_LIMITED", 429],
  ] as const)("preserves safe %s failures", async (code, status) => {
    const fetchImpl = vi.fn(async () =>
      Response.json(
        {
          error: {
            code,
            message: "private-provider-payload",
            retryable: false,
          },
        },
        { status, headers: privateHeaders },
      ),
    );
    const result = await client(fetchImpl)
      .pause_alert_rule(
        alertRule.id,
        {},
        { idempotencyKey: "pause", ifMatch: `"${alertRule.id}:1"` },
      )
      .catch((error: unknown) => error);
    expect(result).toBeInstanceOf(AlertApiError);
    expect(result).toMatchObject({ code, status });
    expect(String(result)).not.toContain("private-provider-payload");
  });
  it("binds independent version and evaluation cursors to the fixed detail query", async () => {
    const fetchImpl = vi.fn(async () =>
      Response.json(alertRule, { headers: privateHeaders }),
    );
    await client(fetchImpl).get_alert_rule(alertRule.id, {
      version_cursor: "versions",
      version_limit: 10,
      evaluation_cursor: "evaluations",
      evaluation_limit: 5,
    });
    const [url] = fetchImpl.mock.calls[0] as unknown as [URL, RequestInit];
    expect(Object.fromEntries(url.searchParams)).toEqual({
      version_cursor: "versions",
      version_limit: "10",
      evaluation_cursor: "evaluations",
      evaluation_limit: "5",
    });
    expect(url.pathname).toBe(`/api/v1/alert-rules/${alertRule.id}`);
  });
});
