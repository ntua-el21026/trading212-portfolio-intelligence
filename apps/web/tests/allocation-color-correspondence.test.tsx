import type { ReactNode } from "react";
import { render, screen, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { Overview } from "../components/overview";
import type { AllocationResponse } from "../lib/contracts";
import { getDemoPortfolio } from "../lib/demo-data";

const chart = vi.hoisted(() => ({
  pie: vi.fn(),
  cell: vi.fn(),
  tooltip: vi.fn(),
}));

// Capture the chart contract; SVG layout and resolved theme colors need a browser.
vi.mock("recharts", () => ({
  ResponsiveContainer: ({ children }: { children: ReactNode }) => (
    <div>{children}</div>
  ),
  PieChart: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  Pie: (props: { children: ReactNode }) => {
    chart.pie(props);
    return <div>{props.children}</div>;
  },
  Cell: (props: { fill: string }) => {
    chart.cell(props);
    return null;
  },
  Tooltip: (props: unknown) => {
    chart.tooltip(props);
    return null;
  },
}));

it("keeps chart colors aligned with table rows after an unavailable allocation weight", () => {
  const demo = getDemoPortfolio();
  const items: AllocationResponse[] = demo.allocation.items
    .slice(0, 3)
    .map((item, index) => ({
      ...item,
      label: [
        "Synthetic unavailable allocation",
        "Synthetic allocation A",
        "Synthetic allocation B",
      ][index],
      weight: [null, "0.600000000000000001", "0.4"][index],
      weight_availability: index === 0 ? "unavailable" : "available",
    }));
  const bundle = {
    ...demo,
    allocation: {
      ...demo.allocation,
      items,
      returned_count: items.length,
      total: items.length,
      truncated: false,
    },
  };
  const original = structuredClone(bundle);

  render(<Overview bundle={bundle} />);

  const table = screen.getByRole("table", {
    name: "Direct allocation by holding",
  });
  const tableRows = within(table).getAllByRole("row").slice(1);
  expect(tableRows).toHaveLength(3);
  for (const [index, row] of tableRows.entries()) {
    expect(row.querySelector(".allocation-key")).toHaveClass(
      `allocation-key--${index + 1}`,
    );
    expect(
      within(row).getByTitle(
        `Canonical ratio: ${items[index].weight ?? "Unavailable"}`,
      ),
    ).toBeInTheDocument();
  }
  expect(within(tableRows[0]).getByText("Unavailable")).toBeVisible();

  const plotted = chart.pie.mock.lastCall![0].data;
  expect(
    plotted.map((row: { original: AllocationResponse }) => row.original),
  ).toEqual(items.slice(1));
  expect(chart.cell.mock.calls.map(([props]) => props.fill)).toEqual([
    "var(--pi-chart-allocation-2)",
    "var(--pi-chart-allocation-3)",
  ]);
  expect(
    chart.tooltip.mock.lastCall![0].formatter(999, "geometry", {
      payload: plotted[0],
    }),
  ).toEqual(["60.0000000000000001%", "Synthetic allocation A"]);
  expect(bundle).toEqual(original);
});
