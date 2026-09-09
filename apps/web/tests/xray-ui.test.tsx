import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type {
  XrayHeldFundsResponse,
  XrayMoneyMetric,
  XrayRatioMetric,
} from "@trading212/api-contracts";
import { XrayResults, XrayValue } from "../components/xray-results";
import { readXrayQuery } from "../lib/xray-query";

// Presentation fixtures only; calculator correctness is exercised by the independent oracle.
const id = (value: number) =>
  `00000000-0000-4000-8000-${String(value).padStart(12, "0")}`;
const at = "2026-08-31T12:00:00Z";
function ratio(value: string | null): XrayRatioMetric {
  return {
    value,
    availability: value === null ? "unavailable" : "available",
    reason: value === null ? "zero_denominator" : null,
    quality: "fresh",
    bound: "exact",
    confidence: null,
    source_reference_ids: [],
    source_count: 0,
    source_omitted_count: 0,
    positive_below_quantum: false,
  };
}
function money(amount: string): XrayMoneyMetric {
  return {
    value: { amount, currency: "EUR" },
    availability: "available",
    reason: null,
    origin: "derived_deterministic",
    quality: "fresh",
    bound: "exact",
    confidence: null,
    source_reference_ids: [],
    source_count: 0,
    source_omitted_count: 0,
  };
}
function funds(start = 10): XrayHeldFundsResponse {
  return {
    view: "held_funds",
    context: {
      account_id: id(1),
      snapshot_id: id(2),
      run_id: id(3),
      input_snapshot_id: id(4),
      input_digest: "a".repeat(64),
      content_digest: "b".repeat(64),
      valuation_at: at,
      source_cutoff_at: at,
      calculated_at: at,
      quality_evaluated_at: at,
      reporting_currency: "EUR",
      method: {
        name: "xray_v1",
        version: "1.1.0",
        numeric_policy: "xray_decimal256_exact_q18_v1",
        traversal_policy: "xray_position_then_cash_uuid_v1",
      },
      access: { reproducibility: "reproducible", status_reference_at: null },
      policies: [],
      sources: [],
      source_count: 0,
      source_omitted_count: 0,
      warnings: [],
      warning_count: 0,
      warning_omitted_count: 0,
      residuals: [],
      residual_count: 0,
      residual_omitted_count: 0,
    },
    summary: {
      total: {
        value: { amount: "1000", currency: "EUR" },
        availability: "available",
        reason: null,
        origin: "derived_deterministic",
        quality: "fresh",
        bound: "exact",
        confidence: null,
        source_reference_ids: [],
        source_count: 0,
        source_omitted_count: 0,
      },
      company_known_weight: ratio("1"),
      cash_weight: ratio("0"),
      unresolved_weight: ratio("0"),
      duplicated_exposure: ratio("0"),
      hhi: ratio("1"),
      top_concentrations: [],
      thresholds: [],
      quality_coverage: {
        root_count: 50,
        valued_root_count: 50,
        direct_portfolio_value: money("1000"),
        direct_portfolio_weight: ratio("1"),
        inferred_mapping_count: 0,
        inferred_value: money("0"),
        inferred_weight: ratio("0"),
        stale_value: money("0"),
        stale_weight: ratio("0"),
      },
    },
    held_funds: {
      items: Array.from({ length: 25 }, (_, offset) => ({
        instrument_id: id(start + offset),
        name: `Synthetic fund ${start + offset}`,
        composition_root_key: `position:${id(start + offset)}`,
        position_count: 1,
        constituent_snapshot_id: null,
        source_at: at,
        quality: "fresh",
        confidence: null,
        complete: true,
        unit_coverage: ratio("1"),
        unresolved_weight: ratio("0"),
        cash_weight: ratio("0"),
      })),
      next_cursor: "opaque_next",
      limit: 25,
      total: 50,
    },
  };
}
const query = readXrayQuery(
  { account: id(1), view: "held_funds", run: id(3) },
  { now: new Date(at), currency: "EUR", snapshot: id(2) },
);
const linkUrl = (name: string) =>
  new URL(
    screen.getByRole("link", { name }).getAttribute("href")!,
    "https://portfolio.example",
  );

describe("X-ray exact presentation and complete fund discovery", () => {
  it("distinguishes zero, unavailable, lower bounds and positive sub-quantum mass", () => {
    const { rerender } = render(<XrayValue metric={ratio("0")} />);
    expect(screen.getByText("0.0%")).toBeInTheDocument();
    expect(screen.queryByText("Unavailable")).not.toBeInTheDocument();
    rerender(<XrayValue metric={ratio(null)} />);
    expect(screen.getByText("Unavailable")).toBeInTheDocument();
    expect(screen.getByText("Zero Denominator")).toBeInTheDocument();
    rerender(
      <XrayValue
        metric={{
          ...ratio("0"),
          bound: "lower_bound",
          positive_below_quantum: true,
          quality: "partial",
        }}
      />,
    );
    expect(screen.getByText("Lower bound")).toBeInTheDocument();
    expect(
      screen.getByText("Positive below display precision"),
    ).toBeInTheDocument();
    expect(screen.getByText("Partial")).toBeInTheDocument();
  });
  it("carries a selection across a catalogue larger than the 32-fund request bound", async () => {
    const user = userEvent.setup();
    const { rerender } = render(<XrayResults data={funds()} query={query} />);
    await user.click(
      screen.getByRole("checkbox", { name: /^Synthetic fund 10 / }),
    );
    const next = linkUrl("Next funds");
    expect(next.searchParams.getAll("fund_ids")).toEqual([id(10)]);
    expect(next.searchParams.get("run")).toBe(id(3));
    expect(next.searchParams.get("cursor")).toBe("opaque_next");
    const secondPage = { ...query, fund_ids: [id(10)], cursor: "opaque_next" };
    rerender(<XrayResults data={funds(35)} query={secondPage} />);
    await user.click(
      screen.getByRole("checkbox", { name: /^Synthetic fund 35 / }),
    );
    const compare = linkUrl("Compare selected funds");
    expect(compare.searchParams.getAll("fund_ids")).toEqual([id(10), id(35)]);
    expect(compare.searchParams.get("view")).toBe("pairs");
    expect(compare.searchParams.has("cursor")).toBe(false);
    expect(screen.getByRole("status")).toHaveTextContent("2 funds selected");
    rerender(<XrayResults data={funds()} query={query} />);
    expect(screen.getByRole("status")).toHaveTextContent("0 funds selected");
    expect(
      screen.getByRole("checkbox", { name: /^Synthetic fund 10 / }),
    ).not.toBeChecked();
  });
  it("enforces the selection bound while allowing deselection and clearing", async () => {
    const user = userEvent.setup();
    render(
      <XrayResults
        data={funds(35)}
        query={{
          ...query,
          fund_ids: Array.from({ length: 32 }, (_, offset) => id(10 + offset)),
        }}
      />,
    );
    expect(screen.getByRole("status")).toHaveTextContent("32 funds selected");
    expect(
      screen.getByRole("checkbox", { name: /^Synthetic fund 42 / }),
    ).toBeDisabled();
    await user.click(
      screen.getByRole("checkbox", { name: /^Synthetic fund 35 / }),
    );
    expect(
      screen.getByRole("checkbox", { name: /^Synthetic fund 42 / }),
    ).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "Clear selection" }));
    expect(screen.getByRole("status")).toHaveTextContent("0 funds selected");
    expect(
      screen.queryByRole("link", { name: "Compare selected funds" }),
    ).not.toBeInTheDocument();
  });
});
