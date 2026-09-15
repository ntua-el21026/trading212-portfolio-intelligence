import type {
  ProjectionRunResponse,
  SnapshotDetail,
} from "@trading212/api-contracts";
import {
  account,
  id,
  other,
  instant,
  context,
  run,
  point,
  money,
} from "./projection-fixtures";
import { snapshot as baseSnapshot } from "./report-fixtures";
export { account, id, other, instant };
export const snapshot: SnapshotDetail = {
  ...baseSnapshot,
  id: other,
  valuation_at: "2026-09-14T12:00:00.654321Z",
  source_cutoff_at: "2026-09-14T11:00:00.654321Z",
  dividends_received: baseSnapshot.total_value,
  realized_profit_loss: baseSnapshot.total_value,
  unrealized_profit_loss: baseSnapshot.total_value,
};
const quantiles = {
  probabilities: ["0.05", "0.25", "0.50", "0.75", "0.95"],
  values: Array.from({ length: 5 }, () => money("100")),
};
const summary = {
  mean: money("0"),
  quantiles: {
    ...quantiles,
    values: Array.from({ length: 5 }, () => money("0")),
  },
};
const histogram = {
  observed_minimum: money("100"),
  observed_maximum: money("100"),
  bins: [
    {
      lower: money("100"),
      upper: money("100"),
      upper_inclusive: true,
      count: 2,
    },
  ],
  boundary_rule: "q18_enclosing_ceiling_v1" as const,
};
/** Typed UI fixture. It is not numerical integration evidence. */
export const saved: ProjectionRunResponse = {
  ...run,
  goal_version_id: null,
  state: "succeeded",
  result_availability: "available",
  completed_at: instant,
  result: {
    context: {
      ...context,
      snapshot_valuation_at: null,
      source_cutoff_at: null,
      source_evidence: { items: [], omitted_count: 0 },
      selection: {
        ...context.selection,
        initial: {
          kind: "modeled_value",
          snapshot_id: null,
          modeled_value: money("100"),
          modeled_anchor_date: "2026-09-15",
        },
      },
    },
    content_digest: "d".repeat(64),
    view_version: "projection_points_v1",
    points: {
      items: [point],
      next_cursor: "signed_next",
      point_limit: 1,
      start_ordinal: 2,
      total: 4,
    },
    variants: [
      {
        variant: "baseline",
        distributions: [0, 12].map((month) => ({
          month,
          on: month ? "2027-09-15" : "2026-09-15",
          nominal_mean: money("100"),
          real_mean: money("100"),
          nominal: quantiles,
          real: quantiles,
          funding_failed_paths: 0,
        })),
        nominal_histogram: histogram,
        real_histogram: histogram,
        cash_flows: {
          contributions: summary,
          withdrawals_requested: summary,
          withdrawals_funded: summary,
          unpaid_withdrawals: summary,
          investment_effect: summary,
          fees: summary,
          tax_drag: summary,
          funding_failed_paths: 0,
          unpaid_positive_below_quantum_paths: 0,
        },
        goal: null,
      },
    ],
  },
};
export const command = {
  profile_version: "report_sections_v4",
  account_id: account,
  premium_run: { family: "projection", run_id: id },
  snapshot_id: other,
  expected_result_digest: "c".repeat(64),
  expected_capture_digest: "a".repeat(64),
  expected_snapshot_valuation: snapshot.valuation_at,
  expected_snapshot_cutoff: snapshot.source_cutoff_at,
  include_goal: false,
  idempotency_key: "projection-report:one",
  formats: ["pdf", "csv", "json", "xlsx"],
  ttl_days: 7,
};
