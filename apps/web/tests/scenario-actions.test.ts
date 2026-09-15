import { beforeEach, describe, expect, it, vi } from "vitest";
import { ScenarioApiError } from "@trading212/api-contracts";
type AdapterModule = typeof import("../lib/scenario-adapter");
const mocks = vi.hoisted(() => ({
  authorize: vi.fn(),
  create: vi.fn(),
  version: vi.fn(),
  getVersion: vi.fn(),
  getDefinition: vi.fn(),
  getRun: vi.fn(),
  run: vi.fn(),
  cancel: vi.fn(),
  pins: vi.fn(),
  refresh: vi.fn(),
}));
vi.mock("server-only", () => ({}));
vi.mock("../lib/scenario-adapter", async (original) => ({
  ...(await original<AdapterModule>()),
  scenarioClients: mocks.authorize,
  savedScenarioXray: mocks.pins,
}));
vi.mock("next/cache", () => ({ revalidatePath: mocks.refresh }));
import { submitScenarioCommand } from "../lib/scenario-actions";
const account = "d778f930-9d2e-4f47-b24f-5b1fa99c6eee",
  id = "2f34c23a-3798-4d4a-9133-9cd47639dd37";
const content = {
  name: "Currency test",
  mode: "compounded",
  shocks: [
    {
      kind: "fx",
      selector: { kind: "economic_currency", currency: "USD" },
      size: "-0.000000000000000001",
    },
  ],
};
const command = {
  kind: "create_definition",
  account_id: account,
  idempotency_key: "scenario-fixture",
  body: { content },
};
const run = {
  kind: "create_run",
  account_id: account,
  idempotency_key: "run-fixture",
  body: {
    scenario_version_id: id,
    portfolio_snapshot_id: id,
    xray_run_id: id,
    reporting_currency: "EUR",
    source_cutoff_at: "2026-09-07T12:00:00.123456Z",
    replay: null,
  },
};
beforeEach(() => {
  vi.clearAllMocks();
  mocks.authorize.mockResolvedValue({
    scenarios: {
      create_scenario: mocks.create,
      get_scenario: mocks.getDefinition,
      create_scenario_version: mocks.version,
      get_scenario_version: mocks.getVersion,
      get_scenario_run: mocks.getRun,
      create_scenario_run: mocks.run,
      cancel_scenario_run: mocks.cancel,
    },
  });
  const response = {
    data: { id, account_id: account },
    notModified: false,
    etag: null,
  };
  mocks.create.mockResolvedValue(response);
  mocks.version.mockResolvedValue(response);
  mocks.run.mockResolvedValue(response);
  mocks.cancel.mockResolvedValue(response);
  mocks.getDefinition.mockResolvedValue(response);
  mocks.getRun.mockResolvedValue(response);
  mocks.getVersion.mockResolvedValue({
    ...response,
    data: { id, account_id: account, content },
  });
  mocks.pins.mockResolvedValue({ run_id: id });
});
describe("scenario server actions", () => {
  it("reauthenticates every invocation and preserves exact shock strings and retry keys", async () => {
    await submitScenarioCommand(command);
    await submitScenarioCommand(command);
    expect(mocks.authorize.mock.calls).toEqual([[true], [true]]);
    expect(mocks.create.mock.calls[0]).toEqual([
      account,
      command.body,
      { idempotencyKey: "scenario-fixture" },
    ]);
    expect(mocks.create.mock.calls[1]).toEqual(mocks.create.mock.calls[0]);
    expect(mocks.refresh).toHaveBeenCalledWith("/scenarios", "page");
  });
  it("does not parse or dispatch when authentication or CSRF fails", async () => {
    mocks.authorize.mockRejectedValue(new Error("session unavailable"));
    await expect(submitScenarioCommand({ kind: "arbitrary" })).rejects.toThrow(
      "session unavailable",
    );
    expect(mocks.create).not.toHaveBeenCalled();
    expect(mocks.run).not.toHaveBeenCalled();
  });
  it.each([
    { ...command, owner_id: id },
    { ...command, url: "https://private-canary" },
    { ...command, kind: "execute_order" },
    { ...command, body: { content: { ...content, coefficients: ["0.1"] } } },
    {
      ...command,
      body: {
        content: { ...content, shocks: [{ ...content.shocks[0], size: 0.1 }] },
      },
    },
    { ...run, body: { ...run.body, exposures: [] } },
  ])(
    "rejects caller financial arrays, numeric shocks and extra destinations",
    async (input) => {
      expect(await submitScenarioCommand(input)).toMatchObject({
        ok: false,
        code: "VALIDATION_FAILED",
      });
      expect(mocks.create).not.toHaveBeenCalled();
      expect(mocks.run).not.toHaveBeenCalled();
    },
  );
  it("bounds the encoded request before dispatch and masks oversized input", async () => {
    const response = await submitScenarioCommand({
      ...command,
      body: {
        content: { ...content, description: "private-canary".repeat(6000) },
      },
    });
    expect(response).toMatchObject({ ok: false, code: "REQUEST_TOO_LARGE" });
    expect(JSON.stringify(response)).not.toContain("private-canary");
    expect(mocks.create).not.toHaveBeenCalled();
  });
  it("re-reads the immutable version and saved X-ray before creating a run", async () => {
    expect(await submitScenarioCommand(run)).toMatchObject({
      ok: true,
      kind: "run",
    });
    expect(mocks.getVersion).toHaveBeenCalledWith(id);
    expect(mocks.pins).toHaveBeenCalledWith(
      expect.anything(),
      account,
      run.body,
    );
    expect(mocks.pins.mock.invocationCallOrder[0]).toBeLessThan(
      mocks.run.mock.invocationCallOrder[0],
    );
    expect(mocks.run).toHaveBeenCalledWith(account, run.body, {
      idempotencyKey: "run-fixture",
    });
  });
  it("rejects cross-account versions before checking sources or admitting work", async () => {
    mocks.getVersion.mockResolvedValue({
      data: { id, account_id: id, content },
      notModified: false,
    });
    expect(await submitScenarioCommand(run)).toMatchObject({
      ok: false,
      code: "NOT_FOUND",
    });
    expect(mocks.pins).not.toHaveBeenCalled();
    expect(mocks.run).not.toHaveBeenCalled();
  });
  it("keeps pin conflicts explicit and does not submit an unverified run", async () => {
    mocks.pins.mockRejectedValue(
      new ScenarioApiError("CONFLICT", 409, "Saved pins differ."),
    );
    expect(await submitScenarioCommand(run)).toMatchObject({
      ok: false,
      code: "CONFLICT",
    });
    expect(mocks.run).not.toHaveBeenCalled();
  });
  it("rejects replay with simultaneous hypothetical shocks", async () => {
    const replay = {
      historical_input_snapshot_id: id,
      start_date: "2025-01-01",
      end_date: "2025-01-31",
      market_knowledge_cutoff_at: run.body.source_cutoff_at,
      holdings_basis: "current_holdings",
      knowledge_basis: "point_in_time",
    };
    expect(
      await submitScenarioCommand({ ...run, body: { ...run.body, replay } }),
    ).toMatchObject({ ok: false, code: "VALIDATION_FAILED" });
    expect(mocks.pins).not.toHaveBeenCalled();
    expect(mocks.run).not.toHaveBeenCalled();
  });
  it("uses the selected definition revision and authorizes cancellation against its account", async () => {
    await submitScenarioCommand({
      ...command,
      kind: "create_version",
      definition_id: id,
      if_match: `"${id}:2"`,
    });
    expect(mocks.version).toHaveBeenCalledWith(id, command.body, {
      idempotencyKey: "scenario-fixture",
      ifMatch: `"${id}:2"`,
    });
    await submitScenarioCommand({
      kind: "cancel_run",
      run_id: id,
      account_id: account,
      idempotency_key: "cancel-fixture",
    });
    expect(mocks.getRun).toHaveBeenCalledWith(id, { component_limit: 1 });
    expect(mocks.cancel).toHaveBeenCalledWith(
      id,
      {},
      { idempotencyKey: "cancel-fixture" },
    );
  });
  it("does not echo unexpected transport failures", async () => {
    mocks.create.mockRejectedValue(new Error("private-canary"));
    expect(JSON.stringify(await submitScenarioCommand(command))).not.toContain(
      "private-canary",
    );
    expect(mocks.refresh).not.toHaveBeenCalled();
  });
});
