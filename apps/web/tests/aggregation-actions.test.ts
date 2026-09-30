import { beforeEach, describe, expect, it, vi } from "vitest";
import { AggregateApiError } from "@trading212/api-contracts";
type Adapter = typeof import("../lib/aggregation-adapter");
const mocks = vi.hoisted(() => ({
  authorize: vi.fn(),
  selection: vi.fn(),
  run: vi.fn(),
  snapshots: vi.fn(),
  refresh: vi.fn(),
}));
vi.mock("../lib/aggregation-adapter", async (original) => ({
  ...(await original<Adapter>()),
  aggregationClients: mocks.authorize,
}));
vi.mock("next/cache", () => ({ revalidatePath: mocks.refresh }));
import {
  submitAggregationCommand,
  loadAggregateSnapshotChoices,
} from "../lib/aggregation-actions";
const id = "00000000-0000-4000-8000-000000000001";
const other = "00000000-0000-4000-8000-000000000002";
const instant = "2026-09-01T00:00:00.123456Z";
const command = {
  kind: "selection",
  idempotency_key: "unchanged-key",
  body: {
    content: {
      name: "Two exact sources",
      members: [{ account_id: id, portfolio_snapshot_id: other }],
      reporting_currency: "EUR",
      source_cutoff_at: instant,
      economic_identity_policy: "canonical_instrument_v1",
    },
  },
};
const response = <T>(data: T) => ({ data, notModified: false, etag: null });
beforeEach(() => {
  vi.clearAllMocks();
  mocks.authorize.mockResolvedValue({
    aggregates: {
      create_aggregate_selection: mocks.selection,
      create_aggregate_run: mocks.run,
    },
    portfolio: { listSnapshots: mocks.snapshots },
  });
  mocks.selection.mockResolvedValue(response({ selection_id: id }));
  mocks.run.mockResolvedValue(response({ run_id: other, selection_id: id }));
});
describe("aggregate command authority", () => {
  it("authenticates before inspecting malformed caller data", async () => {
    mocks.authorize.mockRejectedValue(new Error("CSRF denied"));
    const input = {
      get kind() {
        throw new Error("untrusted data touched");
      },
    };
    await expect(submitAggregationCommand(input)).rejects.toThrow(
      "CSRF denied",
    );
    expect(mocks.selection).not.toHaveBeenCalled();
  });
  it("preserves exact saved membership, microsecond cutoff and semantic retry identity", async () => {
    await submitAggregationCommand(command);
    await submitAggregationCommand(command);
    expect(mocks.authorize.mock.calls).toEqual([[true], [true]]);
    expect(mocks.selection.mock.calls).toEqual([
      [command.body, { idempotencyKey: command.idempotency_key }],
      [command.body, { idempotencyKey: command.idempotency_key }],
    ]);
    expect(mocks.refresh).toHaveBeenCalledWith("/aggregation");
  });
  it("forwards the original revision precondition and bounded command deadline", async () => {
    const body = {
      fx_bindings: [
        { account_id: id, currency: "USD", fx_observation_id: other },
      ],
      activity_window: null,
    };
    expect(
      await submitAggregationCommand({
        kind: "run",
        selection_id: id,
        revision: 7,
        idempotency_key: "run-key",
        body,
      }),
    ).toMatchObject({ ok: true });
    expect(mocks.run).toHaveBeenCalledWith(id, body, {
      idempotencyKey: "run-key",
      ifMatch: `"${id}:7"`,
    });
  });
  it("rejects excess payload, unknown body keys and invented amounts before dispatch", async () => {
    for (const body of [
      { ...command, unexpected: "value" },
      { ...command, body: { ...command.body, amount: "1" } },
      { ...command, idempotency_key: "x".repeat(65537) },
    ])
      expect(await submitAggregationCommand(body)).toMatchObject({ ok: false });
    expect(mocks.selection).not.toHaveBeenCalled();
    expect(mocks.refresh).not.toHaveBeenCalled();
  });
  it("does not expose raw failure text or refresh a denied command", async () => {
    mocks.run.mockRejectedValue(
      new AggregateApiError("ACCESS_DENIED", 403, "secret-canary"),
    );
    const result = await submitAggregationCommand({
      kind: "run",
      selection_id: id,
      revision: 7,
      idempotency_key: "run-key",
      body: {},
    });
    expect(result).toMatchObject({ ok: false, code: "ACCESS_DENIED" });
    expect(JSON.stringify(result)).not.toContain("secret-canary");
    expect(mocks.refresh).not.toHaveBeenCalled();
  });
  it("returns only bounded snapshot choice metadata after fresh authorization", async () => {
    mocks.snapshots.mockResolvedValue({
      items: [
        {
          id: other,
          valuation_at: instant,
          source_cutoff_at: instant,
          reporting_currency: "USD",
          private_payload: "secret-canary",
        },
      ],
      next_cursor: "next-page",
    });
    expect(
      await loadAggregateSnapshotChoices({ account_id: id, cursor: null }),
    ).toEqual({
      ok: true,
      account_id: id,
      next_cursor: "next-page",
      items: [
        {
          id: other,
          valuation_at: instant,
          source_cutoff_at: instant,
          reporting_currency: "USD",
        },
      ],
    });
    expect(mocks.snapshots).toHaveBeenCalledWith(id, {
      limit: 25,
      cursor: null,
    });
    expect(mocks.authorize).toHaveBeenCalledWith(true);
    mocks.snapshots.mockClear();
    expect(
      await loadAggregateSnapshotChoices({
        account_id: id,
        cursor: "x".repeat(2049),
      }),
    ).toMatchObject({ ok: false });
    expect(mocks.snapshots).not.toHaveBeenCalled();
  });
});
