import { beforeEach, describe, expect, it, vi } from "vitest";
import { AlertApiError } from "@trading212/api-contracts";
import { submitAlertCommand } from "../lib/alert-actions";
import { alertAccount, alertEvent, alertRule } from "./alert-fixtures";

const mocks = vi.hoisted(() => ({
  clients: vi.fn(),
  create: vi.fn(),
  activate: vi.fn(),
  acknowledge: vi.fn(),
  revalidate: vi.fn(),
}));
vi.mock("../lib/alert-adapter", () => ({
  alertClients: mocks.clients,
  alertData: (result: { data: unknown }) => result.data,
}));
vi.mock("next/cache", () => ({ revalidatePath: mocks.revalidate }));

describe("authenticated alert server actions", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    mocks.clients.mockResolvedValue({
      alerts: {
        create_alert_rule: mocks.create,
        activate_alert_rule: mocks.activate,
        acknowledge_alert_event: mocks.acknowledge,
      },
    });
  });
  it("reauthorizes before reading any command payload", async () => {
    mocks.clients.mockRejectedValue(new Error("private authentication detail"));
    const toJSON = vi.fn();
    const result = await submitAlertCommand({ toJSON });
    expect(result.ok).toBe(false);
    expect(JSON.stringify(result)).not.toContain(
      "private authentication detail",
    );
    expect(toJSON).not.toHaveBeenCalled();
    expect(mocks.create).not.toHaveBeenCalled();
    expect(mocks.clients).toHaveBeenCalledWith(true);
  });
  it("sends exactly the typed immutable creation and never autoactivates", async () => {
    mocks.create.mockResolvedValue({ data: alertRule });
    const result = await submitAlertCommand({
      kind: "create_rule",
      idempotency_key: "one",
      body: {
        account_id: alertAccount,
        definition: alertRule.latest_version.definition,
      },
    });
    expect(result).toMatchObject({ ok: true, kind: "rule" });
    expect(mocks.create).toHaveBeenCalledWith(
      {
        account_id: alertAccount,
        definition: alertRule.latest_version.definition,
      },
      { idempotencyKey: "one" },
    );
    expect(mocks.activate).not.toHaveBeenCalled();
    expect(mocks.revalidate).toHaveBeenCalledWith("/alerts");
  });
  it("keeps activation's reviewed version, aggregate revision and retry identity", async () => {
    mocks.activate.mockRejectedValue(
      new AlertApiError("REVISION_MISMATCH", 412, "Current revision changed."),
    );
    const command = {
      kind: "activate",
      rule_id: alertRule.id,
      if_match: `"${alertRule.id}:1"`,
      idempotency_key: "same",
      body: { version_id: alertRule.latest_version.id },
    };
    for (let attempt = 0; attempt < 2; attempt++)
      expect(await submitAlertCommand(command)).toMatchObject({
        ok: false,
        code: "REVISION_MISMATCH",
      });
    expect(mocks.activate.mock.calls[0]).toEqual(mocks.activate.mock.calls[1]);
    expect(mocks.revalidate).not.toHaveBeenCalled();
  });
  it.each([
    { kind: "request", method: "POST", path: "/arbitrary" },
    {
      kind: "resolve",
      event_id: alertEvent.id,
      idempotency_key: "x",
      body: {},
    },
    {
      kind: "create_rule",
      idempotency_key: "x",
      body: {
        account_id: alertAccount,
        definition: alertRule.latest_version.definition,
        owner_id: alertAccount,
      },
    },
  ])(
    "rejects unsupported or incomplete commands before transport",
    async (input) => {
      expect(await submitAlertCommand(input)).toMatchObject({
        ok: false,
        code: "VALIDATION_FAILED",
      });
      expect(mocks.create).not.toHaveBeenCalled();
      expect(mocks.activate).not.toHaveBeenCalled();
      expect(mocks.acknowledge).not.toHaveBeenCalled();
    },
  );
});
