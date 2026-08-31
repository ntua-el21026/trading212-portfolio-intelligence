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
      screen.getByRole("table", { name: "Largest direct holdings" }),
    ).toBeInTheDocument();
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
