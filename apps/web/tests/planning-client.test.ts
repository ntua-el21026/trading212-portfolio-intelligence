import { describe, expect, it, vi } from "vitest";
import {
  PlanningApiClient,
  PlanningApiError,
  CreateContributionPlanRequestSchema,
} from "@trading212/api-contracts";

const account = "d778f930-9d2e-4f47-b24f-5b1fa99c6eee";
const portfolio = "aef0bdf3-3613-4cfe-b15f-bc1f8b9c4119";
const target = "19a8b590-9c18-4c43-8dce-d622cb6ae033";
const snapshot = "5dd1049e-7433-43f4-bf5b-3a73c24c0568";
const plan = "b7e267ab-9f80-4cda-8f5e-e5c28a7f72b9";
const body = {
  account_id: account,
  virtual_portfolio_id: portfolio,
  target_version_id: target,
  snapshot_id: snapshot,
  contribution: { amount: "10", currency: "EUR" },
  mode: "global" as const,
};

describe("generated planning transport", () => {
  it.each([
    1,
    true,
    "-1",
    "NaN",
    "1e2",
    "0.0000000000000000001",
    "1".repeat(21),
  ])("rejects invalid contribution representation %s", (amount) => {
    expect(() =>
      CreateContributionPlanRequestSchema.parse({
        ...body,
        contribution: { amount, currency: "EUR" },
      }),
    ).toThrow();
  });
  it("preserves exact values and full retained holding override identities", () => {
    const request = {
      ...body,
      contribution: { amount: "0.000000000000000001", currency: "EUR" },
      holding_constraints: [
        {
          holding_id: target,
          minimum_amount: "0",
          value_increment: "0.01",
          maximum_post_weight: "1",
        },
      ],
    };
    expect(
      CreateContributionPlanRequestSchema.parse(request).holding_constraints,
    ).toEqual(request.holding_constraints);
    expect(
      CreateContributionPlanRequestSchema.parse(request).contribution.amount,
    ).toBe(request.contribution.amount);
    expect(() =>
      CreateContributionPlanRequestSchema.parse({
        ...request,
        owner_id: account,
      }),
    ).toThrow();
  });
  it("rejects unknown nested execution fields", () => {
    expect(() =>
      CreateContributionPlanRequestSchema.parse({
        ...body,
        contribution: { ...body.contribution, order_side: "buy" },
      }),
    ).toThrow();
  });
  it("rejects a path traversal before invoking fetch", async () => {
    const fetchImpl = vi.fn();
    const client = new PlanningApiClient({
      baseUrl: "https://portfolio.example",
      fetchImpl,
    });
    await expect(
      client.get_contribution_plan("../private", {}),
    ).rejects.toThrow();
    expect(fetchImpl).not.toHaveBeenCalled();
  });
  it("keeps recalculation identity and revision token in headers", async () => {
    const fetchImpl = vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            error: {
              code: "REVISION_MISMATCH",
              message: "private-upstream-message",
            },
          }),
          { status: 412 },
        ),
    );
    const client = new PlanningApiClient({
      baseUrl: "https://portfolio.example",
      fetchImpl,
    });
    await expect(
      client.create_contribution_plan_revision(plan, body, {
        idempotencyKey: "recalculate:one",
        ifMatch: `"${plan}:1"`,
      }),
    ).rejects.toMatchObject({ code: "REVISION_MISMATCH", status: 412 });
    const [url, init] = fetchImpl.mock.calls[0] as unknown as [
      URL,
      RequestInit,
    ];
    expect(url.pathname).toBe(`/api/v1/contribution-plans/${plan}/revisions`);
    expect(new Headers(init.headers).get("If-Match")).toBe(`"${plan}:1"`);
    expect(new Headers(init.headers).get("X-Idempotency-Key")).toBe(
      "recalculate:one",
    );
    expect(JSON.parse(init.body as string)).toEqual(body);
    expect(init.redirect).toBe("error");
  });
  it.each(["PLANNING_UNAVAILABLE", "unexpected-private-code"])(
    "sanitizes %s upstream failures",
    async (code) => {
      const client = new PlanningApiClient({
        baseUrl: "https://portfolio.example",
        fetchImpl: async () =>
          new Response(
            JSON.stringify({
              error: { code, message: "planning-secret-canary" },
            }),
            { status: 503 },
          ),
      });
      const failure = await client
        .get_contribution_plan(plan, {})
        .catch((error: unknown) => error);
      expect(failure).toBeInstanceOf(PlanningApiError);
      expect(String(failure)).not.toContain("planning-secret-canary");
      expect(String(failure)).not.toContain("unexpected-private-code");
    },
  );
  it("cancels output streams beyond two MiB", async () => {
    const cancel = vi.fn();
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(new Uint8Array(2 * 1024 * 1024 + 1));
      },
      cancel,
    });
    const client = new PlanningApiClient({
      baseUrl: "https://portfolio.example",
      fetchImpl: async () => new Response(stream),
    });
    await expect(client.get_contribution_plan(plan, {})).rejects.toMatchObject({
      code: "RESULT_TOO_LARGE",
      status: 502,
    });
    expect(cancel).toHaveBeenCalledOnce();
  });
  it("preserves conditional 304 independently of body revision tokens", async () => {
    const client = new PlanningApiClient({
      baseUrl: "https://portfolio.example",
      fetchImpl: async () =>
        new Response(null, {
          status: 304,
          headers: { etag: '"representation-digest"' },
        }),
    });
    await expect(
      client.get_contribution_plan(
        plan,
        {},
        { ifNoneMatch: '"representation-digest"' },
      ),
    ).resolves.toEqual({
      data: null,
      notModified: true,
      etag: '"representation-digest"',
    });
  });
});
