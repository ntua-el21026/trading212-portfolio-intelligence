import type {
  Account,
  AggregateSelectionResponse,
  AggregateRunReceipt,
  AggregateMoney,
  AggregateHoldingsContext,
  AggregateRunResponse,
} from "@trading212/api-contracts";
export const id = "00000000-0000-4000-8000-000000000001";
export const other = "00000000-0000-4000-8000-000000000002";
export const snapshot = "00000000-0000-4000-8000-000000000003";
export const at = "2026-09-01T00:00:00.123456Z";
export const account: Account = {
  id,
  display_name: "Synthetic custody",
  provider: "synthetic_custody",
  environment: "synthetic",
  account_type: "invest",
  reporting_currency: "EUR",
  connection_state: "connected",
  last_refresh_at: at,
};
export const selection: AggregateSelectionResponse = {
  selection_id: id,
  revision: 7,
  created_at: at,
  content_digest: "a".repeat(64),
  content: {
    name: "Exact aggregate",
    members: [{ account_id: id, portfolio_snapshot_id: snapshot }],
    reporting_currency: "EUR",
    source_cutoff_at: at,
    economic_identity_policy: "canonical_instrument_v1",
  },
};
export const receipt: AggregateRunReceipt = {
  run_id: other,
  selection_id: id,
  selection_revision: 7,
  holdings_input_digest: "b".repeat(64),
  holdings_result_digest: "c".repeat(64),
  activity_input_digest: null,
  activity_result_digest: null,
  activity_requested: false,
  state: "succeeded",
  created_at: at,
  expires_at: "2026-09-15T00:00:00Z",
};
export const exact = "9007199254740993.123456789012345678";
export const money: AggregateMoney = {
  currency: "EUR",
  value: exact,
  known_value: exact,
  known_count: 1,
  total_count: 1,
  quality: "fresh",
  reason: null,
  origin: "derived_deterministic",
};
export const context: AggregateHoldingsContext = {
  input_digest: receipt.holdings_input_digest,
  result_digest: receipt.holdings_result_digest,
  reporting_currency: "EUR",
  source_cutoff_at: at,
  snapshots: [
    {
      account_id: id,
      portfolio_snapshot_id: snapshot,
      calculation_run_id: other,
      calculation_version: "phase1_v1",
      valuation_at: at,
      source_cutoff_at: at,
      reporting_currency: "EUR",
      quality: "fresh",
      content_digest: "d".repeat(64),
    },
  ],
  securities: money,
  cash: {
    ...money,
    value: "0",
    known_value: "0",
    known_count: 0,
    total_count: 0,
  },
  total: money,
  rounding_residual: "0.000000000000000001",
  method: "account_aggregation_v1",
  method_version: "1.0.0",
  schema_version: "1.0.0",
  numeric_profile: "premium_decimal96_q18_v1",
};
export const response: AggregateRunResponse = {
  run: receipt,
  view_digest: "e".repeat(64),
  page: {
    view: "holdings",
    context,
    items: [
      {
        instrument_id: other,
        quantity: "1.000000000000000001",
        money,
        account_totals: [{ account_id: id, money }],
      },
    ],
    total: 1,
    next_cursor: null,
  },
};
