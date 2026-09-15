import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type {
  ProjectionResultPage,
  ProjectionQuantilesView,
} from "@trading212/api-contracts";
import {
  ProjectionMoney,
  ProjectionRetainedPoint,
  ProjectionContext,
  ProjectionGoalEstimate,
  ProjectionResults,
} from "../components/projection-results";
import { readProjectionQuery } from "../lib/projection-query";
import {
  account,
  id,
  other,
  point,
  context,
  money,
} from "./projection-fixtures";
vi.mock("../components/navigation-intent", () => ({
  default: ({
    prefetch: _prefetch,
    ...props
  }: import("react").ComponentProps<"a"> & { prefetch?: boolean }) => {
    void _prefetch;
    return <a {...props} />;
  },
}));
const quantiles = (amount: string): ProjectionQuantilesView => ({
  probabilities: ["0.05", "0.25", "0.50", "0.75", "0.95"],
  values: Array.from({ length: 5 }, () => money(amount)),
});
describe("exact retained projection presentation", () => {
  it("renders signed sub-cent amounts with their full saved decimal quantum", () => {
    render(<ProjectionMoney value={money("-0.000000000000000001")} />);
    expect(screen.getByText("-0.000000000000000001 EUR")).toBeInTheDocument();
  });
  it("retains every point amount, asset and absolute path/checkpoint identity", () => {
    const row = {
      ...point,
      ordinal: 3,
      point_index: 1,
      first_unpaid_month: 12,
      on: "2027-09-15",
      point: {
        ...point.point,
        month: 12,
        investment_effect: money("-0.000000000000000001"),
        funding_failed: true,
        unpaid_positive_below_quantum: true,
      },
    };
    render(<ProjectionRetainedPoint row={row} />);
    expect(
      screen.getByText(/Point 3 · baseline · path 1 · month 12/),
    ).toBeInTheDocument();
    expect(screen.getByText(/Checkpoint 2 of 2/)).toHaveTextContent(
      "First unpaid month: 12",
    );
    for (const label of [
      "Nominal wealth",
      "Real wealth",
      "Cumulative contributions",
      "Requested withdrawals",
      "Funded withdrawals",
      "Unpaid withdrawals",
      "Investment effect",
      "Cumulative fees",
      "Modeled tax drag",
      "Wealth rounding residual",
      "Allocation rounding residual",
      "Withdrawal rounding residual",
      "Positive unpaid amount below rounding quantum",
    ])
      expect(screen.getByText(label)).toBeInTheDocument();
    expect(screen.getByText("-0.000000000000000001 EUR")).toBeInTheDocument();
    expect(screen.getAllByText("100.000000000000000001 EUR")).toHaveLength(3);
  });
  it("shows original microsecond source clocks, omitted evidence and distinct saved/capture/numerical identities", () => {
    render(<ProjectionContext context={context} />);
    expect(screen.getByText("2026-09-15T11:59:59.123456Z")).toBeInTheDocument();
    expect(
      screen.getByText(/2 additional source evidence entries omitted/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/7 additional source references omitted/),
    ).toBeInTheDocument();
    for (const digest of [
      context.capture_digest,
      context.numerical_input_digest,
      context.saved_result_digest,
    ])
      expect(screen.getAllByText(digest).length).toBeGreaterThan(0);
  });
  it("keeps probability ratios and uncertainty visible without claiming goal acceptance", () => {
    render(
      <ProjectionGoalEstimate
        estimate={{
          goal_version_id: other,
          basis: "real",
          target: money("100"),
          paths: 2,
          successes: 1,
          probability: "0.500000000000000000",
          interval_low: "0.094531205734230740",
          interval_high: "0.905468794265769260",
          probability_objective: "0.5",
          objective_met: true,
          mean_shortfall: money("0.000000000000000001"),
          shortfalls: quantiles("0"),
          funding_failed_paths: 0,
          method: "goal_analysis_v1",
          interval_method: "wilson_95_v1",
          automatic_goal_acceptance: false,
        }}
      />,
    );
    expect(screen.getByText("0.500000000000000000")).toBeInTheDocument();
    expect(
      screen.getByText(/does not mark the goal accepted or achieved/),
    ).toBeInTheDocument();
    expect(screen.getByText("0.000000000000000001 EUR")).toBeInTheDocument();
  });
  it("displays complete common summaries independently from a one-point page and preserves signed continuation", () => {
    const summary = { mean: money("100"), quantiles: quantiles("100") };
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
    const value: ProjectionResultPage = {
      context,
      variants: [
        {
          variant: "baseline",
          distributions: [0, 12].map((month) => ({
            month,
            on: month ? "2027-09-15" : "2026-09-15",
            nominal_mean: money("100"),
            real_mean: money("100"),
            nominal: quantiles("100"),
            real: quantiles("100"),
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
      points: {
        items: [point],
        point_limit: 25,
        next_cursor: "signed_next",
        start_ordinal: 2,
        total: 4,
      },
      content_digest: "d".repeat(64),
      view_version: "projection_points_v1",
    };
    // UI-only supplied data: these checks verify presentation, not numerical calculation.
    render(
      <ProjectionResults
        value={value}
        query={readProjectionQuery({
          account,
          run: id,
          view: "result",
          point_cursor: "signed_current",
        })}
      />,
    );
    expect(
      screen.getByText(/all 2 saved paths in this variant/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Showing 1 points from absolute ordinal 2/),
    ).toBeInTheDocument();
    const next = new URL(
      screen.getByRole("link", { name: "Next points" }).getAttribute("href")!,
      "https://local.test",
    );
    expect(next.searchParams.get("run")).toBe(id);
    expect(next.searchParams.get("account")).toBe(account);
    expect(next.searchParams.get("point_cursor")).toBe("signed_next");
    expect(
      screen.getByRole("link", { name: "First points" }).getAttribute("href"),
    ).not.toContain("point_cursor");
  });
});
