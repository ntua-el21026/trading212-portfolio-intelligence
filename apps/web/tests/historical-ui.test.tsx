import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type {
  CurrencyCashFlowTotals,
  HistoricalMoneyMetric,
  HistoricalRatioMetric,
} from "@trading212/api-contracts";
import {
  CashCurrencyTotals,
  CashFlowTable,
  HistoricalValue,
} from "../components/historical-results";
import {
  HistoricalSelectionForm,
  HistoricalTabs,
} from "../components/historical-selection";
import { readHistoricalQuery } from "../lib/historical-query";
import {
  formatHistoricalDecimal,
  formatHistoricalPercent,
} from "../lib/historical-format";

function money(amount: string | null, currency = "EUR"): HistoricalMoneyMetric {
  return {
    value: amount === null ? null : { amount, currency },
    availability: amount === null ? "unavailable" : "available",
    reason_code: amount === null ? "unavailable_fx" : null,
    coverage_key: "valuation_cells",
    quality: amount === null ? "partial" : "fresh",
    origin: "derived",
  };
}
function ratio(value: string | null): HistoricalRatioMetric {
  return {
    value,
    availability: value === null ? "unavailable" : "available",
    reason_code: value === null ? "unavailable_positive_denominator" : null,
    coverage_key: "valuation_cells",
    quality: value === null ? "partial" : "fresh",
    origin: "derived",
  };
}
function totals(currency: string, amount: string): CurrencyCashFlowTotals {
  return {
    currency,
    deposits: money(amount, currency),
    withdrawals: money("0", currency),
    external_net: money(amount, currency),
    purchases: money("-5", currency),
    sales: money("2", currency),
    internal_net: money("-3", currency),
    income: money("0.000001", currency),
    fees: money("-0.01", currency),
    taxes: money(null, currency),
    unresolved_amount: money(null, currency),
    external_count: 1,
    internal_count: 4,
    unresolved_count: 1,
  };
}
const account = "d778f930-9d2e-4f47-b24f-5b1fa99c6eee";
const capture = "2f34c23a-3798-4d4a-9133-9cd47639dd37";
const query = readHistoricalQuery(
  {
    account,
    capture,
    view: "series",
    cutoff: "2026-08-31T12:34:56.123456Z",
    cursor: "signed_cursor",
  },
  {
    now: new Date("2026-09-07T12:00:00Z"),
    currency: "EUR",
    pathname: "/performance",
  },
);

describe("historical value and selection presentation", () => {
  it("distinguishes available zero from unavailable and partial covered subtotal", () => {
    const { rerender } = render(<HistoricalValue metric={money("0")} />);
    expect(screen.getByText("0.00 EUR")).toBeInTheDocument();
    expect(screen.queryByText("Unavailable")).not.toBeInTheDocument();
    rerender(<HistoricalValue metric={money(null)} />);
    expect(screen.getByText("Unavailable")).toBeInTheDocument();
    expect(screen.getByText("Unavailable Fx")).toBeInTheDocument();
    rerender(
      <HistoricalValue
        metric={{
          ...money("3"),
          availability: "partial",
          reason_code: "partial_covered_subtotal",
          quality: "partial",
        }}
      />,
    );
    expect(screen.getByText("3.00 EUR")).toBeInTheDocument();
    expect(screen.getByText("Known subtotal")).toBeInTheDocument();
  });
  it("does not visually erase a positive sub-cent amount or tiny nonzero return", () => {
    const { container, rerender } = render(
      <HistoricalValue metric={money("0.000001")} />,
    );
    expect(screen.getByText("0.000001 EUR")).toBeInTheDocument();
    expect(container.querySelector("[title]")).toHaveAttribute(
      "title",
      "0.000001 EUR",
    );
    rerender(<HistoricalValue metric={ratio("0.000001")} />);
    expect(screen.getByText("0.0001%")).toBeInTheDocument();
    rerender(<HistoricalValue metric={ratio(null)} />);
    expect(screen.getByText("Unavailable")).toBeInTheDocument();
  });
  it("preserves signed tiny values and every digit at the canonical monetary bound", () => {
    expect(formatHistoricalDecimal("-0.000000000000000001", 2)).toBe(
      "−0.000000000000000001",
    );
    expect(
      formatHistoricalDecimal("99999999999999999999.123456789012345678", 2),
    ).toBe("99,999,999,999,999,999,999.123456789012345678");
    expect(formatHistoricalPercent("-0.000000000000000001")).toBe(
      "−0.0000000000000001%",
    );
    expect(formatHistoricalDecimal("0", 2)).toBe("0.00");
    expect(formatHistoricalDecimal(null, 2)).toBe("Unavailable");
  });
  it("keeps every original-currency total distinct from the sourced reporting total", () => {
    render(
      <>
        <CashCurrencyTotals
          rows={[totals("USD", "12.000001"), totals("GBP", "7")]}
          label="Original currency totals"
        />
        <CashCurrencyTotals
          rows={[totals("EUR", "19.123456")]}
          label="Sourced reporting totals"
        />
      </>,
    );
    const native = screen.getByRole("table", {
      name: "Original currency totals",
    });
    const reporting = screen.getByRole("table", {
      name: "Sourced reporting totals",
    });
    expect(within(native).getAllByText("12.000001 USD")).toHaveLength(2);
    expect(within(native).getAllByText("7.00 GBP")).toHaveLength(2);
    expect(within(native).queryByText("19.123456 EUR")).not.toBeInTheDocument();
    expect(within(reporting).getAllByText("19.123456 EUR")).toHaveLength(2);
    expect(within(reporting).getAllByText("Unavailable")).toHaveLength(2);
  });
  it("shows event classification and unavailable conversion without treating an original amount as converted", () => {
    render(
      <CashFlowTable
        rows={[
          {
            ordinal: 0,
            event_revision_id: capture,
            economic_key: "synthetic-dividend",
            economic_at: "2025-06-01T12:00:00Z",
            kind: "dividend",
            classification: "internal",
            native_amount: money("3", "USD"),
            reporting_amount: money(null),
            instrument_id: null,
            listing_id: null,
            group_key: null,
            correction_of: null,
            source_ref_ids: [account],
            source_ref_omitted_count: 4,
          },
        ]}
      />,
    );
    expect(screen.getByText("Internal")).toBeInTheDocument();
    expect(screen.getByText("3.00 USD")).toBeInTheDocument();
    expect(screen.getByText("Unavailable")).toBeInTheDocument();
    expect(
      screen.getByText("1 retained references; 4 beyond preview"),
    ).toBeInTheDocument();
  });
  it("retains UTC microseconds in the form and discards stale capture/cursor on filter submission", () => {
    const { container } = render(
      <HistoricalSelectionForm
        pathname="/performance"
        query={query}
        accounts={[{ id: account, label: "Owned account" }]}
        benchmarks={[]}
        benchmarkTotal={0}
        nextBenchmarkCursor={null}
        targets={[]}
        targetTotal={0}
      />,
    );
    expect(screen.getByLabelText(/^Knowledge cutoff \(UTC\)/)).toHaveValue(
      "2026-08-31T12:34:56.123456Z",
    );
    expect(screen.getByLabelText("Account")).toHaveValue(account);
    expect(container.querySelector("form")).toHaveAttribute("method", "get");
    expect(container.querySelector('[name="capture"]')).not.toBeInTheDocument();
    expect(container.querySelector('[name="cursor"]')).not.toBeInTheDocument();
  });
  it("links rolling and calendar views with actual selectors and clears an incompatible capture", () => {
    render(<HistoricalTabs pathname="/performance" query={query} />);
    const rolling = new URL(
      screen.getByRole("link", { name: "Rolling" }).getAttribute("href")!,
      "https://portfolio.example",
    );
    expect(rolling.searchParams.get("rolling")).toBe("calendar_days_30");
    expect(rolling.searchParams.has("capture")).toBe(false);
    expect(rolling.searchParams.has("cursor")).toBe(false);
    const calendar = new URL(
      screen.getByRole("link", { name: "Calendar" }).getAttribute("href")!,
      "https://portfolio.example",
    );
    expect(calendar.searchParams.get("calendar")).toBe("month");
  });
});
