import { beforeEach, describe, expect, it, vi } from "vitest";
import { RiskApiError } from "@trading212/api-contracts";
const mocks = vi.hoisted(() => ({
  authorize: vi.fn(),
  create: vi.fn(),
  version: vi.fn(),
  run: vi.fn(),
  cancel: vi.fn(),
  refresh: vi.fn(),
}));
vi.mock("../lib/risk-adapter", () => ({
  riskClients: mocks.authorize,
  riskData: (value: { data: unknown }) => value.data,
}));
vi.mock("next/cache", () => ({ revalidatePath: mocks.refresh }));
import { submitRiskCommand } from "../lib/risk-actions";
const id = "2f34c23a-3798-4d4a-9133-9cd47639dd37";
const command = {
  kind: "create_definition",
  account_id: id,
  idempotency_key: "risk-fixture",
  body: {
    content: {
      name: "Risk",
      calendar_id: "synthetic",
      calendar_version: "v1",
      annual_risk_free: "0.012345678901234567",
    },
  },
};
beforeEach(() => {
  vi.clearAllMocks();
  mocks.authorize.mockResolvedValue({
    risk: {
      create_risk_definition: mocks.create,
      create_risk_version: mocks.version,
      create_risk_run: mocks.run,
      cancel_risk_run: mocks.cancel,
    },
  });
  mocks.create.mockResolvedValue({ data: { id } });
});
describe("risk server command boundary", () => {
  it("reauthenticates each invocation before parsing and preserves request identity", async () => {
    expect(await submitRiskCommand(command)).toEqual({
      ok: true,
      kind: "definition",
      value: { id },
    });
    await submitRiskCommand(command);
    expect(mocks.authorize.mock.calls).toEqual([[true], [true]]);
    expect(mocks.create.mock.calls[0]).toEqual([
      id,
      command.body,
      { idempotencyKey: "risk-fixture" },
    ]);
    expect(mocks.refresh).toHaveBeenCalledWith("/risk", "page");
  });
  it("never dispatches when authentication or origin validation fails", async () => {
    mocks.authorize.mockRejectedValue(new Error("session unavailable"));
    await expect(submitRiskCommand({ kind: "arbitrary" })).rejects.toThrow(
      "session unavailable",
    );
    expect(mocks.create).not.toHaveBeenCalled();
    expect(mocks.cancel).not.toHaveBeenCalled();
  });
  it.each([
    { ...command, url: "https://private-canary" },
    { ...command, owner_id: id },
    { ...command, kind: "execute_order" },
    { ...command, body: { ...command.body, returns: [0.1] } },
    {
      ...command,
      body: { content: { ...command.body.content, annual_risk_free: 0.02 } },
    },
  ])("rejects untyped fields, floats and destinations", async (value) => {
    const result = await submitRiskCommand(value);
    expect(result).toMatchObject({ ok: false, code: "VALIDATION_FAILED" });
    expect(JSON.stringify(result)).not.toContain("private-canary");
    expect(mocks.create).not.toHaveBeenCalled();
  });
  it("bounds requests before schema errors and never echoes oversized content", async () => {
    const result = await submitRiskCommand({
      ...command,
      body: {
        content: {
          ...command.body.content,
          description: "private-canary".repeat(6000),
        },
      },
    });
    expect(result).toMatchObject({ ok: false, code: "REQUEST_TOO_LARGE" });
    expect(JSON.stringify(result)).not.toContain("private-canary");
    expect(mocks.create).not.toHaveBeenCalled();
  });
  it("keeps safe API failures and masks unexpected transport errors", async () => {
    mocks.create.mockRejectedValue(
      new RiskApiError("ACCESS_DENIED", 403, "Access denied."),
    );
    expect(await submitRiskCommand(command)).toMatchObject({
      ok: false,
      code: "ACCESS_DENIED",
      message: "Access denied.",
    });
    mocks.create.mockRejectedValue(new Error("private-canary"));
    expect(JSON.stringify(await submitRiskCommand(command))).not.toContain(
      "private-canary",
    );
    expect(mocks.refresh).not.toHaveBeenCalled();
  });
});
