import type { PersistedPlanningRequest } from "@trading212/api-contracts";
import { describe, expect, it } from "vitest";

import {
  buildPlanningRevision,
  type PlanningRevisionSelection,
} from "../lib/planning-revision";

const ids = {
  account: "10000000-0000-4000-8000-000000000001",
  pie: "10000000-0000-4000-8000-000000000002",
  target: "10000000-0000-4000-8000-000000000003",
  snapshot: "10000000-0000-4000-8000-000000000004",
  nextTarget: "10000000-0000-4000-8000-000000000005",
  nextSnapshot: "10000000-0000-4000-8000-000000000006",
  holding: "10000000-0000-4000-8000-000000000007",
  excluded: "10000000-0000-4000-8000-000000000008",
  group: "10000000-0000-4000-8000-000000000009",
  node: "10000000-0000-4000-8000-000000000010",
  listing: "10000000-0000-4000-8000-000000000011",
};

function previous(): PersistedPlanningRequest {
  return {
    account_id: ids.account,
    virtual_portfolio_id: ids.pie,
    target_version_id: ids.target,
    snapshot_id: ids.snapshot,
    options: {
      contribution: {
        amount: "99999999999999999999.123456789012345678",
        currency: "EUR",
      },
      mode: "restricted",
      coverage_policy: "allow_degraded",
      eligible_holding_ids: [ids.holding],
      excluded_holding_ids: [ids.excluded],
      restricted_group_ids: [ids.group],
      listing_preferences: [
        { holding_id: ids.holding, listing_id: ids.listing },
      ],
      allocation_constraints: [
        {
          key: "exact-increment",
          kind: "amount_increment",
          node_id: ids.node,
          amount: "0.000000000000000001",
          currency: "EUR",
        },
      ],
      holding_constraints: [
        {
          holding_id: ids.holding,
          minimum_amount: "0.000000000000000001",
          value_increment: "0.000000000000000001",
          maximum_post_weight: "0.500000000000000001",
        },
      ],
      cash_reserve: "100.000000000000000001",
      monetary_quantum: "0.000000000000000001",
    },
  };
}

function selected(
  overrides: Partial<PlanningRevisionSelection> = {},
): PlanningRevisionSelection {
  return {
    account_id: ids.account,
    virtual_portfolio_id: ids.pie,
    target_version_id: ids.target,
    snapshot_id: ids.nextSnapshot,
    reporting_currency: "EUR",
    ...overrides,
  };
}

describe("explicit contribution revision source changes", () => {
  it.each([false, true])(
    "preserves every exact option on a snapshot-only change, reset=%s",
    (reset) => {
      const source = previous();
      const result = buildPlanningRevision(source, selected(), reset);
      expect(result.status).toBe("ready");
      if (result.status !== "ready") throw new Error("Expected ready inputs");
      expect(result.request).toEqual({
        ...source.options,
        account_id: ids.account,
        virtual_portfolio_id: ids.pie,
        target_version_id: ids.target,
        snapshot_id: ids.nextSnapshot,
      });
      expect(result.request.holding_constraints).toEqual(
        source.options.holding_constraints,
      );
      expect(source.snapshot_id).toBe(ids.snapshot);
    },
  );

  it.each([null, []])(
    "retains the semantic difference between unrestricted and empty eligibility: %s",
    (eligible) => {
      const source = previous();
      source.options.eligible_holding_ids = eligible;
      const result = buildPlanningRevision(source, selected());
      expect(result.status).toBe("ready");
      if (result.status !== "ready") throw new Error("Expected ready inputs");
      expect(result.request.eligible_holding_ids).toEqual(eligible);
    },
  );

  it.each([
    [{ target_version_id: ids.nextTarget }, ["target_changed"]],
    [{ reporting_currency: "USD" }, ["currency_changed"]],
    [
      { target_version_id: ids.nextTarget, reporting_currency: "USD" },
      ["target_changed", "currency_changed"],
    ],
  ] as const)(
    "requires explicit reset for incompatible selections %j",
    (pins, reasons) => {
      const source = previous();
      const snapshot = structuredClone(source);
      expect(buildPlanningRevision(source, selected(pins))).toEqual({
        status: "reset_required",
        reasons,
      });
      expect(source).toEqual(snapshot);
    },
  );

  it("resets scoped and monetary options only after explicit target reset", () => {
    const source = previous();
    const result = buildPlanningRevision(
      source,
      selected({ target_version_id: ids.nextTarget }),
      true,
    );
    expect(result).toEqual({
      status: "ready",
      request: {
        account_id: ids.account,
        virtual_portfolio_id: ids.pie,
        target_version_id: ids.nextTarget,
        snapshot_id: ids.nextSnapshot,
        contribution: source.options.contribution,
        mode: "global",
        coverage_policy: "require_complete",
        eligible_holding_ids: null,
        excluded_holding_ids: [],
        restricted_group_ids: [],
        listing_preferences: [],
        allocation_constraints: [],
        holding_constraints: [],
        cash_reserve: null,
        monetary_quantum: null,
      },
    });
  });

  it("does not reinterpret old money when the reporting currency changes", () => {
    const result = buildPlanningRevision(
      previous(),
      selected({
        target_version_id: ids.nextTarget,
        reporting_currency: "USD",
      }),
      true,
    );
    expect(result.status).toBe("ready");
    if (result.status !== "ready") throw new Error("Expected reset inputs");
    expect(result.request.contribution).toEqual({
      amount: "",
      currency: "USD",
    });
    expect(result.request.cash_reserve).toBeNull();
    expect(result.request.monetary_quantum).toBeNull();
    expect(result.request.allocation_constraints).toEqual([]);
    expect(result.request.holding_constraints).toEqual([]);
  });

  it.each([
    { account_id: ids.excluded },
    { virtual_portfolio_id: ids.excluded },
  ])("rejects aggregate scope changes, even with reset: %j", (pins) => {
    for (const reset of [false, true]) {
      expect(buildPlanningRevision(previous(), selected(pins), reset)).toEqual({
        status: "scope_mismatch",
        code: "IMMUTABLE_PLAN_SCOPE",
      });
    }
  });

  it("gives the editor independent nested data without modifying the prior request", () => {
    const source = previous();
    const saved = structuredClone(source);
    const result = buildPlanningRevision(source, selected());
    if (result.status !== "ready") throw new Error("Expected ready inputs");
    result.request.contribution.amount = "0";
    result.request.excluded_holding_ids?.push(ids.holding);
    result.request.allocation_constraints![0].amount = "1";
    result.request.holding_constraints![0].minimum_amount = "1";
    result.request.listing_preferences![0].listing_id = ids.excluded;
    expect(source).toEqual(saved);
  });
});
