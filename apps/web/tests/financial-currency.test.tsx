import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  DividendsTable,
  PositionsTable,
  SnapshotsTable,
} from "../components/portfolio-tables";
import { getDemoPortfolio } from "../lib/demo-data";

describe("canonical metric currencies", () => {
  it("keeps a missing dividend quantity distinct from canonical zero", () => {
    const dividend = getDemoPortfolio().dividends.items[0]!;
    const view = render(
      <DividendsTable dividends={[{ ...dividend, quantity: null }]} />,
    );
    expect(screen.getByText("Unavailable")).toBeVisible();
    view.rerender(
      <DividendsTable dividends={[{ ...dividend, quantity: "0" }]} />,
    );
    expect(screen.queryByText("Unavailable")).not.toBeInTheDocument();
    expect(
      view.container.querySelector('[data-canonical-value="0"]'),
    ).toHaveAttribute("title", "0");
  });

  it("renders each metric's declared currency instead of assuming EUR", () => {
    const bundle = getDemoPortfolio();
    const position = bundle.positions.items[0]!;
    const dividend = bundle.dividends.items[0]!;
    const snapshot = bundle.snapshots.items[0]!;

    render(
      <>
        <PositionsTable
          accountId={bundle.summary.account.id}
          positions={[
            {
              ...position,
              market_value: {
                ...position.market_value,
                reporting_currency: "GBP",
              },
              provider_cost_basis: {
                ...position.provider_cost_basis,
                reporting_currency: "GBP",
              },
              provider_unrealized_profit_loss: {
                ...position.provider_unrealized_profit_loss,
                reporting_currency: "GBP",
              },
            },
          ]}
        />
        <DividendsTable
          dividends={[
            {
              ...dividend,
              gross_amount: {
                ...dividend.gross_amount,
                reporting_currency: "USD",
              },
              withholding_tax: {
                ...dividend.withholding_tax,
                reporting_currency: "USD",
              },
              net_amount: {
                ...dividend.net_amount,
                reporting_currency: "USD",
              },
            },
          ]}
        />
        <SnapshotsTable
          snapshots={[
            {
              ...snapshot,
              total_value: {
                ...snapshot.total_value,
                reporting_currency: "CHF",
              },
              cash_value: {
                ...snapshot.cash_value,
                reporting_currency: "CHF",
              },
              invested_value: {
                ...snapshot.invested_value,
                reporting_currency: "CHF",
              },
              net_contributions: {
                ...snapshot.net_contributions,
                reporting_currency: "CHF",
              },
            },
          ]}
        />
      </>,
    );

    expect(screen.getAllByText(/ GBP$/)).toHaveLength(3);
    expect(screen.getAllByText(/ USD$/)).toHaveLength(3);
    expect(screen.getAllByText(/ CHF$/)).toHaveLength(4);
  });
});
