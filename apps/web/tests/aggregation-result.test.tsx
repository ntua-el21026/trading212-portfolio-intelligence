import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ComponentProps } from "react";
import { AggregateResult } from "../components/aggregation-result";
import {
  response,
  account,
  context,
  exact,
  id,
  other,
  receipt,
} from "./aggregation-ui-fixtures";
import type { AggregationQuery } from "../lib/aggregation-query";
vi.mock("../components/navigation-intent", () => ({
  default: ({
    prefetch: _prefetch,
    ...props
  }: ComponentProps<"a"> & { prefetch?: boolean }) => {
    void _prefetch;
    return <a {...props} />;
  },
}));
const query: AggregationQuery = {
  view: "result",
  selection: id,
  run: other,
  table: "holdings",
  cursor: "old-page",
};
describe("canonical aggregate presentation", () => {
  it("retains exact authoritative values beyond binary float precision and complete source context", () => {
    const { container } = render(
      <AggregateResult
        value={response}
        query={query}
        accounts={[account]}
        canReadActivity
      />,
    );
    expect(container.querySelector("[data-money-value]")).toHaveAttribute(
      "data-money-value",
      exact,
    );
    expect(screen.getAllByTitle(exact).length).toBeGreaterThan(0);
    expect(screen.getByTitle("1.000000000000000001")).toBeInTheDocument();
    expect(screen.getByText(/Rounding residual:/)).toHaveTextContent(
      "0.000000000000000001 EUR",
    );
    expect(screen.getByText(/Input digest:/)).toHaveTextContent(
      context.input_digest,
    );
    const href = screen
      .getByRole("link", { name: "Components" })
      .getAttribute("href")!;
    const url = new URL(href, "https://local.test");
    expect(url.searchParams.has("cursor")).toBe(false);
    expect(url.searchParams.get("run")).toBe(other);
  });
  it("labels known subtotals while leaving incomplete aggregate values unavailable", () => {
    const partial = {
      ...context.total,
      value: null,
      known_count: 1,
      total_count: 2,
      quality: "partial" as const,
      reason: "fx_missing" as const,
    };
    const { container } = render(
      <AggregateResult
        value={{
          ...response,
          page: {
            view: "accounts",
            context: { ...context, total: partial },
            items: [{ account_id: id, money: partial }],
            total: 1,
            next_cursor: null,
          },
        }}
        query={query}
        accounts={[account]}
        canReadActivity={false}
      />,
    );
    expect(
      container.querySelector('[data-money-value="unavailable"]'),
    ).toBeInTheDocument();
    expect(screen.getAllByText(/Known subtotal:/).length).toBe(2);
    expect(screen.getAllByText("fx missing").length).toBe(2);
    expect(
      screen.queryByRole("link", { name: "Transfers" }),
    ).not.toBeInTheDocument();
  });
  it("shows unrequested transfer coverage without inventing zero cash flows", () => {
    render(
      <AggregateResult
        value={{
          run: receipt,
          view_digest: "e".repeat(64),
          page: {
            view: "transfers",
            holdings_input_digest: receipt.holdings_input_digest,
            input_digest: null,
            result_digest: null,
            window: null,
            items: [],
            currency_totals: [],
            complete: false,
            reasons: ["not_requested"],
            candidate_count: 0,
            selected_count: 0,
            total: 0,
            next_cursor: null,
          },
        }}
        query={{ ...query, table: "transfers" }}
        accounts={[account]}
        canReadActivity
      />,
    );
    expect(
      screen.getByText("Activity was not requested for this calculation."),
    ).toBeVisible();
    expect(screen.getByText(/Matching transfer legs alone/)).toBeVisible();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
  it("shows an expired receipt without financial rows", () => {
    render(
      <AggregateResult
        value={{
          ...response,
          run: { ...receipt, state: "expired" },
          page: null,
        }}
        query={query}
        accounts={[account]}
        canReadActivity
      />,
    );
    expect(screen.getByText("Aggregate expired")).toBeVisible();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.queryByText(exact)).not.toBeInTheDocument();
  });
});
