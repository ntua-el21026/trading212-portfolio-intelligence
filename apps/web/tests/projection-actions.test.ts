import { beforeEach, describe, expect, it, vi } from "vitest";
import { ProjectionApiError } from "@trading212/api-contracts";
import {
  account,
  id,
  other,
  assumption,
  definition,
  goal,
  run,
  schedule,
} from "./projection-fixtures";
type AdapterModule = typeof import("../lib/projection-adapter");
const mocks = vi.hoisted(() => ({
  authorize: vi.fn(),
  create: vi.fn(),
  version: vi.fn(),
  getVersion: vi.fn(),
  getSet: vi.fn(),
  getGoal: vi.fn(),
  getGoalVersion: vi.fn(),
  goal: vi.fn(),
  goalVersion: vi.fn(),
  getRun: vi.fn(),
  run: vi.fn(),
  cancel: vi.fn(),
  snapshot: vi.fn(),
  refresh: vi.fn(),
}));
vi.mock("server-only", () => ({}));
vi.mock("../lib/projection-adapter", async (original) => ({
  ...(await original<AdapterModule>()),
  projectionClients: mocks.authorize,
}));
vi.mock("next/cache", () => ({ revalidatePath: mocks.refresh }));
import { submitProjectionCommand } from "../lib/projection-actions";
const response = <T>(data: T) => ({ data, notModified: false, etag: null });
const command = {
  kind: "create_set",
  account_id: account,
  idempotency_key: "projection-test",
  body: { metadata: assumption.metadata, content: assumption.content },
};
const runCommand = {
  kind: "create_run",
  account_id: account,
  idempotency_key: "projection-run-test",
  body: {
    assumption_version_id: id,
    goal_version_id: other,
    initial_basis: {
      kind: "modeled_value",
      snapshot_id: null,
      modeled_value: { amount: "100.000000000000000001", currency: "EUR" },
      modeled_anchor_date: "2026-09-15",
    },
    schedule,
    months: 12,
    paths: 2,
    seed: 0,
    retained_months: [0, 12],
    allocation: [{ key: "portfolio", weight: "1" }],
    sensitivity: null,
  },
};
beforeEach(() => {
  vi.clearAllMocks();
  mocks.authorize.mockResolvedValue({
    projections: {
      create_assumption_set: mocks.create,
      create_assumption_version: mocks.version,
      get_assumption_set: mocks.getSet,
      get_assumption_version: mocks.getVersion,
      create_goal: mocks.goal,
      create_goal_version: mocks.goalVersion,
      get_goal: mocks.getGoal,
      get_goal_version: mocks.getGoalVersion,
      get_projection_run: mocks.getRun,
      create_projection_run: mocks.run,
      cancel_projection_run: mocks.cancel,
    },
    portfolio: { getSnapshot: mocks.snapshot },
  });
  mocks.create.mockResolvedValue(response(definition));
  mocks.version.mockResolvedValue(response(assumption));
  mocks.getVersion.mockResolvedValue(response(assumption));
  mocks.getSet.mockResolvedValue(response(definition));
  mocks.getGoal.mockResolvedValue(response({ ...definition, id: other }));
  mocks.getGoalVersion.mockResolvedValue(response(goal));
  mocks.goal.mockResolvedValue(response({ ...definition, id: other }));
  mocks.goalVersion.mockResolvedValue(response(goal));
  mocks.getRun.mockResolvedValue(response(run));
  mocks.run.mockResolvedValue(response(run));
  mocks.cancel.mockResolvedValue(response(run));
  mocks.snapshot.mockResolvedValue({ id: other });
});
describe("projection command authority and exact semantics", () => {
  it("authenticates every call and preserves exact decimal strings and retry identity", async () => {
    await submitProjectionCommand(command);
    await submitProjectionCommand(command);
    expect(mocks.authorize.mock.calls).toEqual([[true], [true]]);
    expect(mocks.create.mock.calls[0]).toEqual([
      account,
      command.body,
      { idempotencyKey: command.idempotency_key },
    ]);
    expect(mocks.create.mock.calls[1]).toEqual(mocks.create.mock.calls[0]);
    expect(mocks.refresh).toHaveBeenCalledWith("/projections", "page");
  });
  it("checks session and CSRF before touching untrusted body properties", async () => {
    const body = {
      get kind(): string {
        throw new Error("body touched");
      },
    };
    mocks.authorize.mockRejectedValue(new Error("CSRF denied"));
    await expect(submitProjectionCommand(body)).rejects.toThrow("CSRF denied");
    expect(mocks.create).not.toHaveBeenCalled();
  });
  it("pins the current aggregate account and forwards the original revision precondition", async () => {
    const version = {
      ...command,
      kind: "create_assumption_version",
      set_id: id,
      if_match: `"${id}:2"`,
    };
    await submitProjectionCommand(version);
    expect(mocks.version).toHaveBeenCalledWith(id, command.body, {
      idempotencyKey: command.idempotency_key,
      ifMatch: `"${id}:2"`,
    });
    mocks.getSet.mockResolvedValue(
      response({ ...definition, account_id: other }),
    );
    mocks.version.mockClear();
    expect(await submitProjectionCommand(version)).toMatchObject({
      ok: false,
      code: "NOT_FOUND",
    });
    expect(mocks.version).not.toHaveBeenCalled();
  });
  it("rejects foreign or mismatched goal pins before run admission", async () => {
    mocks.getGoalVersion.mockResolvedValue(
      response({ ...goal, account_id: other }),
    );
    expect(await submitProjectionCommand(runCommand)).toMatchObject({
      ok: false,
      code: "NOT_FOUND",
    });
    expect(mocks.run).not.toHaveBeenCalled();
    mocks.getGoalVersion.mockResolvedValue(
      response({
        ...goal,
        content: { ...goal.content, assumption_version_id: other },
      }),
    );
    expect(await submitProjectionCommand(runCommand)).toMatchObject({
      ok: false,
      code: "CONFLICT",
    });
    expect(mocks.run).not.toHaveBeenCalled();
  });
  it("loads observed snapshots through the selected account route and never accepts caller money as observed", async () => {
    const observed = {
      ...runCommand,
      body: {
        ...runCommand.body,
        initial_basis: {
          kind: "observed_snapshot",
          snapshot_id: other,
          modeled_value: null,
          modeled_anchor_date: null,
        },
      },
    };
    expect(await submitProjectionCommand(observed)).toMatchObject({ ok: true });
    expect(mocks.snapshot).toHaveBeenCalledWith(account, other);
    expect(mocks.run.mock.calls[0][1].initial_basis).toEqual(
      observed.body.initial_basis,
    );
    mocks.snapshot.mockRejectedValue(
      new ProjectionApiError("NOT_FOUND", 404, "Unavailable"),
    );
    mocks.run.mockClear();
    expect(await submitProjectionCommand(observed)).toMatchObject({
      ok: false,
    });
    expect(mocks.run).not.toHaveBeenCalled();
  });
  it("reauthorizes both goal definitions and their assumption version for immutable goal revisions", async () => {
    const revised = {
      kind: "create_goal_version",
      account_id: account,
      idempotency_key: "goal-version",
      goal_id: other,
      if_match: `"${other}:2"`,
      body: { metadata: goal.metadata, content: goal.content },
    };
    expect(await submitProjectionCommand(revised)).toMatchObject({
      ok: true,
      kind: "goal_version",
    });
    expect(mocks.getVersion).toHaveBeenCalledWith(id);
    expect(mocks.getGoal).toHaveBeenCalledWith(other);
    expect(mocks.goalVersion.mock.calls[0][2]).toEqual({
      idempotencyKey: "goal-version",
      ifMatch: `"${other}:2"`,
    });
  });
  it("never cancels a run returned for another account", async () => {
    mocks.getRun.mockResolvedValue(response({ ...run, account_id: other }));
    expect(
      await submitProjectionCommand({
        kind: "cancel_run",
        account_id: account,
        run_id: id,
        idempotency_key: "cancel",
      }),
    ).toMatchObject({ ok: false, code: "NOT_FOUND" });
    expect(mocks.cancel).not.toHaveBeenCalled();
  });
  it("rejects numeric money and oversized bodies without dispatch", async () => {
    expect(
      await submitProjectionCommand({
        ...runCommand,
        body: {
          ...runCommand.body,
          schedule: {
            ...schedule,
            base_monthly: { amount: 1.5, currency: "EUR" },
          },
        },
      }),
    ).toMatchObject({ ok: false, code: "VALIDATION_FAILED" });
    expect(
      await submitProjectionCommand({ ...command, extra: "x".repeat(65536) }),
    ).toMatchObject({ ok: false, code: "REQUEST_TOO_LARGE" });
    expect(mocks.create).not.toHaveBeenCalled();
    expect(mocks.run).not.toHaveBeenCalled();
  });
});
