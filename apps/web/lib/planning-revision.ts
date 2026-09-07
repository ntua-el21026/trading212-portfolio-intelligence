import type {
  CreateContributionPlanRequest,
  PersistedPlanningRequest,
} from "@trading212/api-contracts";

export interface PlanningRevisionSelection {
  account_id: string;
  virtual_portfolio_id: string;
  target_version_id: string;
  snapshot_id: string;
  reporting_currency: string;
}

export type PlanningRevisionResult =
  | { status: "ready"; request: CreateContributionPlanRequest }
  | {
      status: "reset_required";
      reasons: ("target_changed" | "currency_changed")[];
    }
  | { status: "scope_mismatch"; code: "IMMUTABLE_PLAN_SCOPE" };

/** Prepare editable inputs without remapping identities or converting any amount. */
export function buildPlanningRevision(
  previous: Readonly<PersistedPlanningRequest>,
  selected: Readonly<PlanningRevisionSelection>,
  reset: boolean = false,
): PlanningRevisionResult {
  if (
    previous.account_id !== selected.account_id ||
    previous.virtual_portfolio_id !== selected.virtual_portfolio_id
  ) {
    return { status: "scope_mismatch", code: "IMMUTABLE_PLAN_SCOPE" };
  }
  const targetChanged =
    previous.target_version_id !== selected.target_version_id;
  const currencyChanged =
    previous.options.contribution.currency !== selected.reporting_currency;
  if ((targetChanged || currencyChanged) && !reset) {
    const reasons: ("target_changed" | "currency_changed")[] = [];
    if (targetChanged) reasons.push("target_changed");
    if (currencyChanged) reasons.push("currency_changed");
    return { status: "reset_required", reasons };
  }
  const pins = {
    account_id: selected.account_id,
    virtual_portfolio_id: selected.virtual_portfolio_id,
    target_version_id: selected.target_version_id,
    snapshot_id: selected.snapshot_id,
  };
  // A stale reset flag must not erase options on a snapshot-only change.
  if (!targetChanged && !currencyChanged) {
    return {
      status: "ready",
      request: { ...structuredClone(previous.options), ...pins },
    };
  }
  return {
    status: "ready",
    request: {
      ...pins,
      contribution: {
        amount: currencyChanged ? "" : previous.options.contribution.amount,
        currency: selected.reporting_currency,
      },
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
  };
}
