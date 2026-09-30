import { beforeEach, describe, expect, it, vi } from "vitest";
import { AggregateApiError, SourceApiError } from "@trading212/api-contracts";
import { id, other, snapshot, at, selection } from "./aggregation-ui-fixtures";
type Adapter = typeof import("../lib/aggregation-adapter");
const mocks = vi.hoisted(() => ({
  authorize: vi.fn(),
  selection: vi.fn(),
  snapshot: vi.fn(),
  status: vi.fn(),
  observations: vi.fn(),
}));
vi.mock("../lib/aggregation-adapter", async (original) => ({
  ...(await original<Adapter>()),
  aggregationClients: mocks.authorize,
}));
import { loadAggregateFxChoices } from "../lib/aggregation-fx-actions";
const response = <T>(data: T) => ({ data, notModified: false, etag: null });
const request = {
  kind: "snapshots",
  selection_id: id,
  revision: 7,
  account_id: id,
  currency: "USD",
  direction: "direct",
  cursor: null,
};
const page = {
  account_id: id,
  snapshot_id: other,
  content_digest: "f".repeat(64),
  base: "USD",
  quote: "EUR",
  source_cutoff_at: at,
  effective_at_lte: "2026-09-01T00:00:00.123455Z",
  first_observed_at: "2026-09-01T00:00:00Z",
  expires_at: "2026-09-15T00:00:00Z",
  items: [
    {
      observation_id: snapshot,
      session_date: "2026-09-01",
      effective_at: "2026-09-01T00:00:00Z",
      rate: "0.900000000000000001",
      state: "available",
    },
  ],
  next_cursor: "older-page",
  limit: 25,
};
beforeEach(() => {
  vi.resetAllMocks();
  mocks.authorize.mockResolvedValue({
    aggregates: { get_aggregate_selection: mocks.selection },
    portfolio: { getSnapshot: mocks.snapshot },
    sources: {
      get_fx_source_status: mocks.status,
      list_fx_observation_references: mocks.observations,
    },
  });
  mocks.selection.mockResolvedValue(response(selection));
  mocks.snapshot.mockResolvedValue({
    id: snapshot,
    valuation_at: page.effective_at_lte,
  });
  mocks.observations.mockResolvedValue(response(page));
  mocks.status.mockResolvedValue(
    response({
      account_id: id,
      providers: [{ id: other, name: "Synthetic FX", secret: "not-returned" }],
      pairs: {
        items: [
          {
            provider_id: other,
            base: "USD",
            quote: "EUR",
            availability: "available",
            latest_snapshot: {
              id: other,
              first_observed_at: at,
              effective_at: at,
              available_count: 31,
              secret: "not-returned",
            },
          },
        ],
        next_cursor: "next-source",
        total: 1,
        limit: 25,
      },
    }),
  );
});
describe("bounded aggregate FX choices", () => {
  it("authenticates the form before inspecting its input", async () => {
    mocks.authorize.mockRejectedValue(new Error("CSRF denied"));
    await expect(
      loadAggregateFxChoices({
        get kind() {
          throw new Error("input touched");
        },
      }),
    ).rejects.toThrow("CSRF denied");
    expect(mocks.selection).not.toHaveBeenCalled();
  });
  it("loads only the explicit pair, minimizes metadata and rechecks all-member authority", async () => {
    expect(await loadAggregateFxChoices(request)).toEqual({
      ok: true,
      kind: "snapshots",
      account_id: id,
      base: "USD",
      quote: "EUR",
      items: [
        {
          snapshot_id: other,
          provider: "Synthetic FX",
          first_observed_at: at,
          effective_at: at,
          available_count: 31,
          availability: "available",
        },
      ],
      next_cursor: "next-source",
    });
    expect(mocks.status).toHaveBeenCalledExactlyOnceWith(id, {
      base: "USD",
      quote: "EUR",
      source_cutoff_at: at,
      limit: 25,
      cursor: null,
    });
    expect(mocks.selection.mock.calls).toEqual([[id], [id]]);
    expect(mocks.observations).not.toHaveBeenCalled();
  });
  it.each([
    "foreign-member",
    "same-currency",
    "wrong-revision",
    "unknown-field",
    "oversized-cursor",
  ])("rejects %s before source dispatch", async (reason) => {
    const changed = {
      ...request,
      ...(reason === "foreign-member"
        ? { account_id: other }
        : reason === "same-currency"
          ? { currency: "EUR" }
          : reason === "wrong-revision"
            ? { revision: 9 }
            : reason === "unknown-field"
              ? { source_cutoff_at: at }
              : { cursor: "x".repeat(2049) }),
    };
    expect(await loadAggregateFxChoices(changed)).toMatchObject({ ok: false });
    expect(mocks.status).not.toHaveBeenCalled();
    expect(mocks.observations).not.toHaveBeenCalled();
  });
  it("preserves a one-microsecond earlier saved valuation and exact rates", async () => {
    const result = await loadAggregateFxChoices({
      ...request,
      kind: "observations",
      snapshot_id: other,
      cursor: "prior-page",
    });
    expect(result).toEqual({ ok: true, kind: "observations", page });
    expect(mocks.snapshot).toHaveBeenCalledExactlyOnceWith(id, snapshot);
    expect(mocks.observations).toHaveBeenCalledExactlyOnceWith(other, {
      account_id: id,
      base: "USD",
      quote: "EUR",
      source_cutoff_at: at,
      effective_at_lte: page.effective_at_lte,
      limit: 25,
      cursor: "prior-page",
    });
  });
  it("caps a later valuation at the selection cutoff and requests the inverse pair explicitly", async () => {
    mocks.snapshot.mockResolvedValue({
      id: snapshot,
      valuation_at: "2026-09-01T00:00:00.123457Z",
    });
    mocks.observations.mockResolvedValue(
      response({
        ...page,
        base: "EUR",
        quote: "USD",
        effective_at_lte: "2026-09-01T03:00:00.123456+03:00",
      }),
    );
    expect(
      await loadAggregateFxChoices({
        ...request,
        kind: "observations",
        direction: "inverse",
        snapshot_id: other,
      }),
    ).toMatchObject({ ok: true });
    expect(mocks.observations).toHaveBeenCalledExactlyOnceWith(other, {
      account_id: id,
      base: "EUR",
      quote: "USD",
      source_cutoff_at: at,
      effective_at_lte: at,
      limit: 25,
      cursor: null,
    });
  });
  it("withholds returned rates when another member loses access during the read", async () => {
    mocks.selection
      .mockResolvedValueOnce(response(selection))
      .mockRejectedValueOnce(
        new AggregateApiError("ACCESS_DENIED", 403, "secret-canary"),
      );
    const result = await loadAggregateFxChoices({
      ...request,
      kind: "observations",
      snapshot_id: other,
    });
    expect(result).toMatchObject({ ok: false, code: "ACCESS_DENIED" });
    expect(JSON.stringify(result)).not.toMatch(
      /0\.900|secret-canary|observation_id/,
    );
  });
  it.each(["account", "snapshot", "cutoff", "effective"])(
    "denies inconsistent %s response context",
    async (field) => {
      mocks.observations.mockResolvedValue(
        response({
          ...page,
          ...(field === "account"
            ? { account_id: other }
            : field === "snapshot"
              ? { snapshot_id: id }
              : field === "cutoff"
                ? { source_cutoff_at: page.effective_at_lte }
                : { effective_at_lte: at }),
        }),
      );
      expect(
        await loadAggregateFxChoices({
          ...request,
          kind: "observations",
          snapshot_id: other,
        }),
      ).toMatchObject({ ok: false, code: "INVALID_RESPONSE" });
    },
  );
  it("redacts source denials and never falls back to a different source", async () => {
    mocks.observations.mockRejectedValue(
      new SourceApiError("ACCESS_DENIED", 403, "secret-canary"),
    );
    const result = await loadAggregateFxChoices({
      ...request,
      kind: "observations",
      snapshot_id: other,
    });
    expect(result).toMatchObject({ ok: false, code: "ACCESS_DENIED" });
    expect(JSON.stringify(result)).not.toContain("secret-canary");
    expect(mocks.observations).toHaveBeenCalledOnce();
    expect(mocks.status).not.toHaveBeenCalled();
  });
});
