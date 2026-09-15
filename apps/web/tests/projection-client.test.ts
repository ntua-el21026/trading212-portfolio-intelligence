import { describe, expect, it, vi } from "vitest";
import {
  ProjectionApiClient,
  ProjectionApiError,
} from "@trading212/api-contracts";
import { account, id, assumption, run } from "./projection-fixtures";
const response = (body: unknown) =>
  new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
describe("projection generated-client integration", () => {
  it("uses the fixed creation route and sends exact financial strings and command headers", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(response({ ...run, result: null }));
    const client = new ProjectionApiClient({
      baseUrl: "https://local.test",
      fetchImpl,
    });
    const body = {
      assumption_version_id: id,
      goal_version_id: null,
      initial_basis: {
        kind: "modeled_value" as const,
        snapshot_id: null,
        modeled_value: { amount: "1.000000000000000001", currency: "EUR" },
        modeled_anchor_date: "2026-09-15",
      },
      schedule: {
        base_monthly: { amount: "0.000000000000000001", currency: "EUR" },
        annual_growth: "0",
        entries: [],
        paused_dates: [],
      },
      months: 12,
      paths: 2,
      seed: 0,
      retained_months: [0, 12],
      allocation: assumption.content.assets.map(({ key, weight }) => ({
        key,
        weight,
      })),
      sensitivity: null,
    };
    await client.create_projection_run(account, body, {
      idempotencyKey: "projection-key",
    });
    const [url, init] = fetchImpl.mock.calls[0];
    expect(String(url)).toBe(
      `https://local.test/api/v1/accounts/${account}/projection-runs`,
    );
    expect(JSON.parse(init.body)).toEqual(body);
    expect(new Headers(init.headers).get("X-Idempotency-Key")).toBe(
      "projection-key",
    );
  });
  it("binds saved point queries to the exact run and fixed page size", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(response(run));
    const client = new ProjectionApiClient({
      baseUrl: "https://local.test",
      fetchImpl,
    });
    await client.get_projection_run(id, {
      point_limit: 25,
      point_cursor: "signed_cursor",
    });
    const url = new URL(String(fetchImpl.mock.calls[0][0]));
    expect(url.pathname).toBe(`/api/v1/projection-runs/${id}`);
    expect(url.searchParams.get("point_cursor")).toBe("signed_cursor");
    expect(url.searchParams.get("point_limit")).toBe("25");
  });
  it("rejects oversized cursors locally and preserves fixed safe transport errors", async () => {
    const fetchImpl = vi.fn();
    const client = new ProjectionApiClient({
      baseUrl: "https://local.test",
      fetchImpl,
    });
    await expect(
      client.get_projection_run(id, {
        point_limit: 25,
        point_cursor: "x".repeat(2049),
      }),
    ).rejects.toBeInstanceOf(ProjectionApiError);
    expect(fetchImpl).not.toHaveBeenCalled();
    fetchImpl.mockRejectedValue(new Error("PRIVATE_SERVER_PATH_OR_SECRET"));
    await expect(client.get_goal_analysis(id)).rejects.toMatchObject({
      code: "PROJECTION_UNAVAILABLE",
    });
    try {
      await client.get_goal_analysis(id);
    } catch (error) {
      expect(String(error)).not.toContain("PRIVATE_SERVER_PATH_OR_SECRET");
    }
  });
});
