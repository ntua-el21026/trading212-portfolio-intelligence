import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type {
  ScenarioMoneyView,
  ScenarioResultContextView,
  ScenarioComparisonPage,
} from "@trading212/api-contracts";
import {
  ScenarioMoneyValue,
  ScenarioComparison,
} from "../components/scenario-results";
import { readScenarioQuery } from "../lib/scenario-query";
vi.mock("../components/navigation-intent", () => ({
  default: ({
    prefetch: _prefetch,
    ...props
  }: import("react").ComponentProps<"a"> & { prefetch?: boolean }) => {
    void _prefetch;
    return <a {...props} />;
  },
}));
const id = "d778f930-9d2e-4f47-b24f-5b1fa99c6eee",
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
function context(currency: string, runId: string): ScenarioResultContextView {
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
describe("canonical scenario money presentation", () => {
  it("distinguishes zero, unavailable and tiny signed nonzero amounts without rounding", () => {
    const { rerender } = render(<ScenarioMoneyValue metric={money("0")} />);
    expect(screen.getByText("0 EUR")).toBeInTheDocument();
    rerender(<ScenarioMoneyValue metric={money(null)} />);
    expect(screen.getByText("Unavailable")).toBeInTheDocument();
    expect(screen.getByText(/Incompatible Basis/)).toBeInTheDocument();
    expect(screen.queryByText("0 EUR")).not.toBeInTheDocument();
    rerender(<ScenarioMoneyValue metric={money("-0.000000000000000001")} />);
    expect(screen.getByText("-0.000000000000000001 EUR")).toBeInTheDocument();
  });
  it("shows omitted source references and unknown confidence explicitly", () => {
    render(
      <ScenarioMoneyValue
        metric={{
          ...money("1"),
          confidence: null,
          source_reference_ids: { items: [id], omitted_count: 22 },
        }}
      />,
    );
    expect(screen.getByText("Confidence: Unavailable")).toBeInTheDocument();
    expect(
      screen.getByText(/22 additional references retained/),
    ).toBeInTheDocument();
    expect(screen.getByText(id)).toBeInTheDocument();
  });
  it("keeps both currencies visible and leaves every incompatible difference unavailable", () => {
    const before = context("EUR", id),
      after = context("USD", other);
    const post = {
      before: before.summary.post_value,
      after: after.summary.post_value,
      difference: money(null),
    };
    const impact = {
      before: before.summary.impact,
      after: after.summary.impact,
      difference: money(null),
    };
    const value: ScenarioComparisonPage = {
      before,
      after,
      compatible: false,
      mismatches: [{ field: "currency", left: "EUR", right: "USD" }],
      post_value: post,
      impact,
      components: {
        items: [],
        next_cursor: null,
        component_limit: 25,
        total: 0,
        start_ordinal: 0,
      },
      content_digest: "a".repeat(64),
      view_version: "scenario_compact_v1",
    };
    const query = readScenarioQuery(
      { account: id, view: "compare", before: id, after: other },
      { now: new Date("2026-09-15T12:00:00Z"), currency: "EUR" },
    );
    render(<ScenarioComparison value={value} query={query} />);
    expect(
      screen.getByText("These saved results have incompatible bases"),
    ).toBeInTheDocument();
    const totals = screen.getByRole("table", {
      name: "Scenario comparison totals",
    });
    expect(within(totals).getAllByText("0 EUR")[0]).toBeInTheDocument();
    expect(within(totals).getAllByText("0 USD")[0]).toBeInTheDocument();
    expect(within(totals).getAllByText("Unavailable")).toHaveLength(2);
    expect(
      screen.queryByRole("link", { name: "Next components" }),
    ).not.toBeInTheDocument();
  });
});
