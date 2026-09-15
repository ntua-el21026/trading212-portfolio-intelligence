import type {
  ScenarioMoneyView,
  ScenarioResultContextView,
  ScenarioRunResponse,
} from "@trading212/api-contracts";
export const id = "d778f930-9d2e-4f47-b24f-5b1fa99c6eee",
  other = "2f34c23a-3798-4d4a-9133-9cd47639dd37";
const preview = { items: [], omitted_count: 0 };
function money(amount: string | null, currency = "EUR"): ScenarioMoneyView {
  return {
    value: amount === null ? null : { amount, currency },
    quality: amount === null ? "partial" : "fresh",
    reason: amount === null ? "incompatible_basis" : null,
    confidence: amount === null ? null : "0.9",
    source_reference_ids: preview,
  };
}
// Synthetic public presentation fixture: values are supplied, never calculated in the UI.
export function scenarioContext(
  currency = "EUR",
  runId = other,
): ScenarioResultContextView {
  const zero = money("0", currency),
    total = money("0", currency);
  const ratio = { value: "0", quality: "fresh", reason: null } as const;
  return {
    run_id: runId,
    result_id: runId,
    input_digest: "a".repeat(64),
    saved_result_digest: "b".repeat(64),
    valuation_at: "2026-09-07T12:00:00Z",
    definition: { name: "Saved assumptions", mode: "compounded" },
    pins: {
      account_id: id,
      owner_id: id,
      scenario_id: id,
      scenario_version_id: id,
      scenario_version_digest: "c".repeat(64),
      portfolio_snapshot_id: id,
      portfolio_snapshot_digest: "d".repeat(64),
      xray_run_id: id,
      xray_input_id: id,
      xray_input_digest: "e".repeat(64),
      xray_result_digest: "f".repeat(64),
      reporting_currency: currency,
      source_cutoff_at: "2026-09-07T12:00:00.123456Z",
    },
    summary: {
      terminal_pre_value: total,
      covered_pre_value: total,
      uncovered_pre_value: zero,
      excluded_pre_value: zero,
      covered_count: 0,
      uncovered_count: 0,
      excluded_count: 0,
      missing_pre_value_count: 0,
      uncertain_money_count: 0,
      covered_post_value: total,
      excluded_post_value: zero,
      provably_unchanged_uncovered_value: zero,
      post_value: total,
      impact: zero,
      rounding_residual: zero,
      component_sum_residual: zero,
      effects: {
        price: zero,
        factor: zero,
        fx: zero,
        interaction: zero,
        price_ratio: ratio,
        factor_ratio: ratio,
        fx_ratio: ratio,
      },
    },
    upstream_portfolio_value: total,
    upstream_partition_difference: zero,
    upstream_residual_keys: preview,
    replay: null,
    diagnostics: preview,
    assumptions: ["canonical_terminal_basis"],
    sensitivity_source_row_count: 0,
    method_version: "1.0.0",
    schema_version: "1.0.0",
    numerical_profile: "premium_decimal96_q18_v1",
  };
}

export function scenarioRun(): ScenarioRunResponse {
  const context = scenarioContext();
  return {
    id: context.run_id,
    account_id: id,
    scenario_version_id: context.pins.scenario_version_id,
    portfolio_snapshot_id: context.pins.portfolio_snapshot_id,
    xray_run_id: context.pins.xray_run_id,
    job_id: context.run_id,
    state: "succeeded",
    failure_code: null,
    created_at: "2026-09-07T12:00:01Z",
    completed_at: "2026-09-07T12:00:02Z",
    expires_at: "2026-09-14T12:00:01Z",
    input_digest: context.input_digest,
    result_availability: "available",
    result: {
      context,
      components: {
        items: [],
        next_cursor: null,
        component_limit: 1,
        total: 0,
        start_ordinal: 0,
      },
      content_digest: "9".repeat(64),
      view_version: "scenario_compact_v1",
    },
  };
}
