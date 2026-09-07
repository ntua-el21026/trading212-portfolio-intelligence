import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DriftTotals } from "../components/planning-results";
import { formatPlanningMoney } from "../lib/planning-format";

describe("lossless planning money display", () => {
  it.each([
    [null, "Unavailable"],
    ["0", "0.00"],
    ["0.000000000000000000", "0.00"],
    ["-0.000", "0.00"],
    ["20", "20.00"],
    ["1.2", "1.20"],
    ["12.340000000000000000", "12.34"],
    ["0.000001", "0.000001"],
    ["-0.000001000000000000", "−0.000001"],
    ["0.000000000000000001", "0.000000000000000001"],
    ["0.100000000000000001", "0.100000000000000001"],
    [
      "99999999999999999999.123456789012345678",
      "99,999,999,999,999,999,999.123456789012345678",
    ],
    [
      "-12345678901234567890.000000000000000001",
      "−12,345,678,901,234,567,890.000000000000000001",
    ],
  ])("renders %s as %s without changing value", (value, expected) => {
    expect(formatPlanningMoney(value)).toBe(expected);
  });

  it.each([
    "1e-6",
    "+1",
    " 1",
    "01",
    "1.",
    "NaN",
    "Infinity",
    "0.0000000000000000001",
    "100000000000000000000",
  ])("rejects malformed or out-of-contract amount %s", (value) => {
    expect(() => formatPlanningMoney(value)).toThrow(
      "Planning amount must be a canonical decimal string.",
    );
  });

  it("keeps sub-cent cash and unclassified values distinct from unavailable totals", () => {
    render(
      <DriftTotals
        totals={{
          value: null,
          cash: { amount: "0.000001", currency: "EUR" },
          unclassified: { amount: "0.000000000000000001", currency: "EUR" },
          l1_drift: null,
          weighted_squared_drift: null,
          effective_weight_rounding_residual: null,
          frontier_keys: [],
          group_count: 0,
          holding_count: 0,
          unclassified_count: 1,
        }}
      />,
    );
    expect(screen.getByText("EUR 0.000001", { exact: true })).toBeVisible();
    expect(
      screen.getByText("EUR 0.000000000000000001", { exact: true }),
    ).toBeVisible();
    expect(
      screen.queryByText("EUR 0.00", { exact: true }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText("Portfolio value").nextElementSibling,
    ).toHaveTextContent("Unavailable");
  });
});
