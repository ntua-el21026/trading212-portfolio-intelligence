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
    ).toHaveAttribute(
      "href",
      "/allocation?account=" + getDemoPortfolio().summary.account.id,
    );
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

  it.each([
    {
      status: "unreconciled",
      count: 0,
      label: "Unreconciled",
      text: "0 discrepancy records.",
    },
    {
      status: "unreconciled",
      count: 1,
      label: "Unreconciled",
      text: "1 discrepancy record.",
    },
    {
      status: "unreconciled",
      count: 251,
      label: "Unreconciled",
      text: "251 discrepancy records.",
    },
    {
      status: "partial",
      count: 0,
      label: "Partial",
      text: "0 discrepancy records.",
    },
    {
      status: "not_evaluated",
      count: 0,
      label: "Not Evaluated",
      text: "0 discrepancy records.",
    },
  ])(
    "keeps $status status distinct from $count discrepancy records in both layouts",
    async ({ status, count, label, text }) => {
      const { Overview } = await import("../components/overview");
      const bundle = getDemoPortfolio();
      const { container } = render(
        <Overview
          bundle={{
            ...bundle,
            reconciliation: {
              ...bundle.reconciliation,
              status,
              // The API summary does not embed the separately paged issue records.
              issues: [],
              discrepancy_count: count,
            },
          }}
        />,
      );
      const mobile = container.querySelector<HTMLElement>(
        ".mobile-trust-summary",
      );
      expect(mobile).not.toBeNull();
      expect(
        within(mobile!).getByText(label, { exact: true }),
      ).toBeInTheDocument();
      expect(
        within(mobile!).getByText(text, { exact: true }),
      ).toBeInTheDocument();
      const desktop = screen.getByRole("complementary", {
        name: "Portfolio trust details",
      });
      expect(
        within(desktop).getByText(label, { exact: true }),
      ).toBeInTheDocument();
      expect(
        within(desktop).getByText(text, { exact: true }),
      ).toBeInTheDocument();
      expect(
        screen.queryByText("Open discrepancies are present."),
      ).not.toBeInTheDocument();
    },
  );

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
