import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MetricCard, MoneyValue } from "../components/financial";
import { NumberValue } from "../components/number-value";
import type { MetricResponse } from "../lib/contracts";

function metric(value: string | null, currency = "EUR"): MetricResponse {
  return {
    value,
    reporting_currency: currency,
    availability: value === null ? "unavailable" : "available",
    calculation_version: "synthetic-display-v1",
    methodology: "Synthetic server metric; no client calculation",
    provenance: ["synthetic-source"],
    assumptions: [],
    unavailable_reason:
      value === null ? "Complete source is unavailable" : null,
  };
}

describe("canonical number and metric presentation", () => {
  it.each([
    ["248431.27", "248,431.27"],
    ["1.005000000000000001", "1.005000000000000001"],
    ["-0.000000000000000001", "−0.000000000000000001"],
    ["0.000000000000000001", "0.000000000000000001"],
    [
      "12345678901234567890.123456789012345678",
      "12,345,678,901,234,567,890.123456789012345678",
    ],
  ])("retains every significant digit of %s", (canonical, visible) => {
    const { container } = render(<NumberValue value={canonical} unit="CHF" />);
    expect(screen.getByText(visible)).toBeVisible();
    expect(screen.getByTitle(`${canonical} CHF`)).toHaveAttribute(
      "data-canonical-value",
      canonical,
    );
    expect(container.querySelector(".ui-visually-hidden")).toHaveTextContent(
      `${canonical} CHF`,
    );
    expect(screen.getByText("CHF")).toBeVisible();
  });

  it("preserves original trailing digits in full-value text and tooltip", () => {
    const { container } = render(<NumberValue value="1.230000" unit="GBP" />);
    expect(screen.getByText("1.23")).toBeVisible();
    expect(screen.getByTitle("1.230000 GBP")).toBeInTheDocument();
    expect(container.querySelector(".ui-visually-hidden")?.textContent).toBe(
      "1.230000 GBP",
    );
  });

  it("keeps zero, unavailable and partial values distinct", () => {
    const { rerender } = render(
      <MetricCard label="Cash" metric={metric("0")} />,
    );
    expect(screen.getByText("0.00")).toBeVisible();
    expect(screen.queryByText("Unavailable")).not.toBeInTheDocument();

    rerender(<MetricCard label="Cash" metric={metric(null)} />);
    expect(screen.getByText("Unavailable")).toBeVisible();
    expect(screen.getByText("Complete source is unavailable")).toBeVisible();
    expect(screen.queryByText("0.00")).not.toBeInTheDocument();

    rerender(
      <MetricCard
        label="Cash"
        metric={{
          ...metric("0.000001", "USD"),
          availability: "partial",
          unavailable_reason: "Covered subtotal; missing settlement source",
        }}
      />,
    );
    expect(screen.getByText("0.000001")).toBeVisible();
    expect(screen.getByText("USD")).toBeVisible();
    expect(screen.getByText("Partial value")).toBeVisible();
    expect(
      screen.getByText("Covered subtotal; missing settlement source"),
    ).toBeVisible();
  });

  it("shows each card's own currency, including secondary and unavailable cards", () => {
    render(
      <>
        <MetricCard label="Total" metric={metric("10", "EUR")} primary />
        <MetricCard label="Cash" metric={metric("7", "GBP")} />
        <MetricCard label="Invested" metric={metric(null, "CHF")} />
      </>,
    );
    for (const currency of ["EUR", "GBP", "CHF"]) {
      expect(screen.getByText(currency)).toBeVisible();
    }
  });

  it("retains MoneyValue's contextual currency option without losing its full unit", () => {
    const { container } = render(
      <MoneyValue metric={metric("12.000001", "JPY")} />,
    );
    expect(screen.getByText("12.000001")).toBeVisible();
    expect(screen.queryByText("JPY")).not.toBeInTheDocument();
    expect(container.querySelector(".ui-visually-hidden")).toHaveTextContent(
      "12.000001 JPY",
    );
    expect(screen.getByTitle("12.000001 JPY")).toBeInTheDocument();
  });
});
