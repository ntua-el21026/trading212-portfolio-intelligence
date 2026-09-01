import { render, screen, within } from "@testing-library/react";
import { beforeAll, describe, expect, it, vi } from "vitest";

import { getDemoPortfolio } from "../lib/demo-data";

vi.mock("../components/charts", () => ({
  AllocationChart: () => (
    <div aria-label="Direct allocation by holding, including cash" />
  ),
  SnapshotChart: () => (
    <div aria-label="Portfolio value by immutable snapshot" />
  ),
}));

describe("Phase 1 overview", () => {
  beforeAll(() => {
    // Imported after chart stubbing so the test remains layout-engine independent.
  });

  it("presents canonical values without recalculating them", async () => {
    const { Overview } = await import("../components/overview");
    render(<Overview bundle={getDemoPortfolio()} />);

    expect(screen.getAllByText("248,431.27").length).toBeGreaterThan(0);
    expect(screen.getAllByText("12,431.27").length).toBeGreaterThan(0);
    expect(screen.getByText("236,000.00")).toBeInTheDocument();
    expect(screen.getByText("230,000.00")).toBeInTheDocument();
    expect(screen.getAllByText("Reconciled").length).toBeGreaterThan(0);
    expect(
      screen.getByText(
        "Showing 6 of 6 canonical rows, including cash when available.",
      ),
    ).toBeVisible();
    expect(
      screen.getByRole("link", { name: /explore allocation/i }),
    ).toHaveAttribute("href", "/allocation");
    expect(
      screen.getByRole("table", { name: "Largest direct holdings" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Showing 5 of 5 direct positions, ordered by market value.",
      ),
    ).toBeVisible();
    const largestHoldings = screen.getByRole("table", {
      name: "Largest direct holdings",
    });
    expect(within(largestHoldings).getAllByRole("row")[1]).toHaveTextContent(
      "VWCE",
    );
  });

  it("labels a bounded allocation preview when more than 50 rows exist", async () => {
    const previous = process.env.PORTFOLIO_E2E_LARGE_COLLECTIONS;
    process.env.PORTFOLIO_E2E_LARGE_COLLECTIONS = "1";
    try {
      const { Overview } = await import("../components/overview");
      const large = getDemoPortfolio();
      const cash = large.allocation.items.find(
        (item) => item.asset_type === "cash",
      );
      const previewItems = [
        ...large.allocation.items
          .filter((item) => item.asset_type !== "cash")
          .slice(0, 5),
        ...(cash === undefined ? [] : [cash]),
      ];
      render(
        <Overview
          bundle={{
            allocation: {
              items: previewItems,
              returned_count: previewItems.length,
              total: large.allocation.total,
              limit: 5,
              truncated: true,
            },
            positions: large.positions,
            reconciliation: large.reconciliation,
            summary: large.summary,
          }}
        />,
      );

      expect(
        screen.getByText(
          "Showing 6 of 66 canonical rows, including cash when available.",
        ),
      ).toBeVisible();
      expect(
        within(
          screen.getByRole("table", { name: "Direct allocation by holding" }),
        ).getAllByRole("row"),
      ).toHaveLength(7);
    } finally {
      if (previous === undefined) {
        delete process.env.PORTFOLIO_E2E_LARGE_COLLECTIONS;
      } else {
        process.env.PORTFOLIO_E2E_LARGE_COLLECTIONS = previous;
      }
    }
  });

  it("renders an honest empty state", async () => {
    const { Overview } = await import("../components/overview");
    render(<Overview bundle={getDemoPortfolio("empty")} />);

    const allocation = screen.getByText("No allocation data").closest("div");
    expect(allocation).not.toBeNull();
    expect(
      within(allocation!).getByText(
        /after the first successful portfolio snapshot/i,
      ),
    ).toBeVisible();
    expect(screen.getByText("No holdings yet")).toBeVisible();
  });
});
