import { beforeEach, describe, expect, it, vi } from "vitest";

import { submitPlanningCommand } from "../lib/planning-actions";

const mocks = vi.hoisted(() => ({
  clients: vi.fn(),
  create: vi.fn(),
  revise: vi.fn(),
  revalidate: vi.fn(),
}));
vi.mock("../lib/planning-adapter", () => ({
  planningClients: mocks.clients,
  planningData: (value: { data: unknown }) => value.data,
}));
vi.mock("next/cache", () => ({ revalidatePath: mocks.revalidate }));

const id = "20000000-0000-4000-8000-000000000001";
const body = {
  account_id: id,
  virtual_portfolio_id: id,
  target_version_id: id,
  snapshot_id: id,
  contribution: { amount: "20.123456789012345678", currency: "EUR" },
  mode: "global",
};

describe("planning server actions", () => {
  beforeEach(() => {
    mocks.clients.mockReset().mockResolvedValue({
      planning: {
        create_contribution_plan: mocks.create,
        create_contribution_plan_revision: mocks.revise,
      },
    });
    mocks.create.mockReset();
    mocks.revise.mockReset();
    mocks.revalidate.mockReset();
  });

  it("authorizes before inspecting caller-controlled command content", async () => {
    mocks.clients.mockRejectedValue(new Error("Authentication required"));
    const toJSON = vi.fn();
    await expect(submitPlanningCommand({ toJSON })).rejects.toThrow(
      "Authentication required",
    );
    expect(mocks.clients).toHaveBeenCalledWith(true);
    expect(toJSON).not.toHaveBeenCalled();
    expect(mocks.create).not.toHaveBeenCalled();
  });

  it("rejects oversized and unknown-key inputs without dispatch or reflecting canaries", async () => {
    const canary = "private-planning-input-canary";
    const unknown = await submitPlanningCommand({
      kind: "create",
      idempotency_key: "request-1",
      body: { ...body, [canary]: canary },
    });
    expect(unknown).toMatchObject({ ok: false, code: "VALIDATION_FAILED" });
    expect(JSON.stringify(unknown)).not.toContain(canary);
    expect(
      await submitPlanningCommand({ body: "a".repeat(65_537) }),
    ).toMatchObject({ ok: false, code: "REQUEST_TOO_LARGE" });
    expect(mocks.create).not.toHaveBeenCalled();
  });

  it("forwards exact amounts and revision identity and revalidates only after acceptance", async () => {
    const job = { plan_id: id };
    mocks.revise.mockResolvedValue({ data: job });
    expect(
      await submitPlanningCommand({
        kind: "revise",
        plan_id: id,
        if_match: `"${id}:2"`,
        idempotency_key: "request-2",
        body,
      }),
    ).toEqual({ ok: true, job });
    expect(mocks.revise).toHaveBeenCalledWith(
      id,
      expect.objectContaining({ contribution: body.contribution }),
      { idempotencyKey: "request-2", ifMatch: `"${id}:2"` },
    );
    expect(mocks.revalidate.mock.calls).toEqual([
      ["/planner"],
      [`/planner/${id}`],
    ]);
  });
});
