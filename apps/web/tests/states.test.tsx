import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MetricCard } from "../components/financial";
import { QualityBanner } from "../components/quality";
import { SignInPanel } from "../components/sign-in-panel";
import { getDemoPortfolio } from "../lib/demo-data";

describe("explicit portfolio states", () => {
  it("announces partial data and missing inputs", () => {
    const bundle = getDemoPortfolio("partial");
    render(<QualityBanner quality={bundle.quality} />);

    expect(screen.getByRole("status")).toHaveTextContent(
      "Partial portfolio data",
    );
    expect(screen.getByText(/dividend history is incomplete/i)).toBeVisible();
    expect(screen.getByText(/historical_dividends/i)).toBeVisible();
  });

  it("keeps unavailable separate from zero", () => {
    const metric = getDemoPortfolio().summary.realized_profit_loss;
    render(<MetricCard label="Realized profit / loss" metric={metric} />);

    expect(screen.getByText("Unavailable")).toBeVisible();
    expect(
      screen.getByText(/complete disposal basis is not available/i),
    ).toBeVisible();
    expect(screen.queryByText("0.00")).not.toBeInTheDocument();
  });

  it("fails closed when local demo authentication is disabled", () => {
    render(<SignInPanel demoEnabled={false} />);

    expect(screen.getByText("Authentication is not configured")).toBeVisible();
    expect(
      screen.queryByRole("button", { name: /enter demo portfolio/i }),
    ).not.toBeInTheDocument();
  });
});
