import type { ReactNode } from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AllocationChart, SnapshotChart } from "../components/charts";
import type {
  AllocationResponse,
  MetricResponse,
  SnapshotResponse,
} from "../lib/contracts";

// Capture only the geometry contract with the installed chart library.
// These tests do not claim SVG layout, pointer hit-testing or browser evidence.
const chart = vi.hoisted(() => ({
  lines: vi.fn(),
  xAxis: vi.fn(),
  yAxis: vi.fn(),
  tooltip: vi.fn(),
  series: vi.fn(),
  pie: vi.fn(),
}));
vi.mock("recharts", () => ({
  ResponsiveContainer: ({ children }: { children: ReactNode }) => (
    <div>{children}</div>
  ),
  LineChart: (props: { children: ReactNode }) => {
    chart.lines(props);
    return <div>{props.children}</div>;
  },
  PieChart: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  Pie: (props: { children: ReactNode }) => {
    chart.pie(props);
    return <div>{props.children}</div>;
  },
  Cell: () => null,
  CartesianGrid: () => null,
  XAxis: (props: unknown) => {
    chart.xAxis(props);
    return null;
  },
  YAxis: (props: unknown) => {
    chart.yAxis(props);
    return null;
  },
  Tooltip: (props: unknown) => {
    chart.tooltip(props);
    return null;
  },
  Line: (props: unknown) => {
    chart.series(props);
    return null;
  },
}));

function metric(value: string | null, currency = "EUR"): MetricResponse {
  return {
    value,
    reporting_currency: currency,
    availability: value === null ? "unavailable" : "available",
    calculation_version: "synthetic-v1",
    methodology: "Saved server total",
    provenance: ["synthetic:portfolio-source"],
    assumptions: ["No client FX conversion"],
    unavailable_reason: value === null ? "Missing valuation source" : null,
  };
}

function snapshot(
  id: string,
  time: string,
  value: string | null,
  currency = "EUR",
): SnapshotResponse {
  return {
    id,
    valuation_at: time,
    source_cutoff_at: "2026-09-01T00:00:00.123456Z",
    reporting_currency: currency,
    total_value: metric(value, currency),
    cash_value: metric("0", currency),
    invested_value: metric(value, currency),
    net_contributions: metric("0", currency),
    data_quality: {
      state: value === null ? "partial" : "fresh",
      as_of: time,
      source_timestamp: "2026-09-01T00:00:00.123456Z",
      freshness_threshold_seconds: 300,
      warnings: value === null ? ["Price missing at valuation"] : [],
      missing_inputs: value === null ? ["holding-price"] : [],
    },
  };
}

type CapturedRow = {
  time: number;
  value: number | null;
  original: SnapshotResponse;
};
function rows(): CapturedRow[] {
  return chart.lines.mock.lastCall![0].data as CapturedRow[];
}
function openTable() {
  fireEvent.click(screen.getByText(/^Exact snapshot values and sources/));
  return screen.getByRole("table", {
    name: "Snapshot chart: exact server values in original page order",
  });
}
function renderTooltip(row: CapturedRow) {
  const content = chart.tooltip.mock.lastCall![0].content as (props: {
    active: boolean;
    payload: { payload: CapturedRow }[];
  }) => ReactNode;
  render(
    <div data-testid="tooltip-content">
      {content({ active: true, payload: [{ payload: row }] })}
    </div>,
  );
  return screen.getByTestId("tooltip-content");
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("snapshot geometry and canonical alternatives", () => {
  it("plots actual UTC intervals ascending without changing original page membership/order", () => {
    const input = Object.freeze([
      snapshot("latest", "2026-09-03T09:00:00Z", "12"),
      snapshot("middle", "2026-09-01T10:00:00Z", "11"),
      snapshot("earliest", "2026-09-01T09:00:00Z", "10"),
    ]);
    const before = JSON.stringify(input);
    render(<SnapshotChart snapshots={input} />);
    expect(rows().map((row) => row.original.id)).toEqual([
      "earliest",
      "middle",
      "latest",
    ]);
    const origin = rows()[0].time;
    expect(rows().map((row) => row.time - origin)).toEqual([
      0, 3_600_000, 172_800_000,
    ]);
    expect(rows()).toHaveLength(3);
    expect(JSON.stringify(input)).toBe(before);
    expect(chart.xAxis.mock.lastCall![0]).toMatchObject({
      type: "number",
      scale: "utc",
      dataKey: "time",
      domain: ["dataMin", "dataMax"],
    });
    const dataRows = within(openTable()).getAllByRole("row").slice(1);
    expect(dataRows).toHaveLength(3);
    ["latest", "middle", "earliest"].forEach((id, index) => {
      expect(dataRows[index]).toHaveTextContent(`Snapshot: ${id}`);
    });
  });

  it("retains equivalent instants and sub-millisecond identities without elapsed-time connections", () => {
    render(
      <SnapshotChart
        snapshots={[
          snapshot("z", "2026-09-01T11:00:00.123456+02:00", "9"),
          snapshot("micro-later", "2026-09-01T09:00:00.123999Z", "10"),
          snapshot("a", "2026-09-01T09:00:00.123456Z", "8"),
          snapshot("micro-earlier", "2026-09-01T09:00:00.123001Z", "7"),
        ]}
      />,
    );
    expect(rows().map((row) => row.original.id)).toEqual([
      "micro-earlier",
      "a",
      "z",
      "micro-later",
    ]);
    expect(new Set(rows().map((row) => row.time)).size).toBe(1);
    expect(chart.series.mock.lastCall![0].stroke).toBe("none");
    expect(
      screen.getByText(/connections are omitted on this page/),
    ).toBeVisible();
    const tooltip = renderTooltip(rows()[1]);
    for (const row of rows()) {
      expect(
        within(tooltip).getByText(`Snapshot: ${row.original.id}`),
      ).toBeVisible();
      expect(
        within(tooltip).getByText(row.original.valuation_at),
      ).toBeVisible();
    }
    expect(within(openTable()).getAllByRole("row")).toHaveLength(5);
  });

  it("shows original decimal boundary values in tooltip and table, never geometry round-trips", () => {
    const canonical = "12345678901234567890.123456789012345678";
    render(
      <SnapshotChart
        snapshots={[
          snapshot("precise", "2026-09-01T09:00:00.123456Z", canonical, "CHF"),
        ]}
      />,
    );
    const tooltip = renderTooltip(rows()[0]);
    expect(within(tooltip).getByText(`${canonical} CHF`)).toBeVisible();
    expect(
      within(tooltip).getByText("2026-09-01T09:00:00.123456Z"),
    ).toBeVisible();
    expect(within(openTable()).getByText(`${canonical} CHF`)).toBeVisible();
  });

  it("keeps null breaks, observed zero and partial values with actual quality details", () => {
    const partial = snapshot("partial", "2026-09-01T09:00:00Z", "0.000001");
    partial.total_value.availability = "partial";
    partial.data_quality.state = "stale";
    partial.data_quality.warnings = ["Source is stale"];
    render(
      <SnapshotChart
        snapshots={[
          partial,
          snapshot("gap", "2026-09-02T09:00:00Z", null),
          snapshot("zero", "2026-09-03T09:00:00Z", "0"),
        ]}
      />,
    );
    expect(rows().map((row) => row.value)).toEqual([0.000001, null, 0]);
    expect(chart.series.mock.lastCall![0]).toMatchObject({
      connectNulls: false,
      type: "linear",
      isAnimationActive: false,
    });
    const table = openTable();
    expect(within(table).getByText("0 EUR")).toBeVisible();
    expect(within(table).getByText("Unavailable EUR")).toBeVisible();
    expect(within(table).getByText("0.000001 EUR")).toBeVisible();
    expect(within(table).getByText("Stale")).toBeVisible();
    expect(within(table).getByText("Warnings: Source is stale")).toBeVisible();
    expect(
      within(table).getByText("Missing inputs: holding-price"),
    ).toBeVisible();
    expect(within(table).getByText("Missing valuation source")).toBeVisible();
  });

  it("refuses a mixed-currency series while preserving every metric's own currency", () => {
    const gbp = snapshot("gbp", "2026-09-02T09:00:00Z", "200", "GBP");
    gbp.reporting_currency = "EUR";
    render(
      <SnapshotChart
        snapshots={[
          snapshot("eur", "2026-09-01T09:00:00Z", "100", "EUR"),
          gbp,
          snapshot("usd-missing", "2026-09-03T09:00:00Z", null, "USD"),
        ]}
      />,
    );
    expect(chart.lines).not.toHaveBeenCalled();
    expect(
      screen.getByText(/different currencies \(EUR, GBP, USD\)/),
    ).toBeVisible();
    const table = openTable();
    for (const label of ["100 EUR", "200 GBP", "Unavailable USD"]) {
      expect(within(table).getByText(label)).toBeVisible();
    }
    expect(within(table).getAllByRole("row")).toHaveLength(4);
  });

  it("does not supply fabricated zero points for empty or entirely unavailable pages", () => {
    const { rerender } = render(<SnapshotChart snapshots={[]} />);
    expect(
      screen.getByText("No snapshot observations on this page."),
    ).toBeVisible();
    expect(chart.lines).not.toHaveBeenCalled();
    rerender(
      <SnapshotChart
        snapshots={[snapshot("missing", "2026-09-01T09:00:00Z", null)]}
      />,
    );
    expect(screen.getByText(/No plottable values on this page/)).toBeVisible();
    expect(chart.lines).not.toHaveBeenCalled();
    expect(within(openTable()).getByText("Unavailable EUR")).toBeVisible();
  });

  it("replaces the component page without retaining earlier point identities", () => {
    const { rerender } = render(
      <SnapshotChart
        snapshots={[snapshot("first-page", "2026-09-01T09:00:00Z", "1")]}
      />,
    );
    openTable();
    rerender(
      <SnapshotChart
        snapshots={[snapshot("second-page", "2026-09-02T09:00:00Z", "2")]}
      />,
    );
    expect(rows().map((row) => row.original.id)).toEqual(["second-page"]);
    expect(screen.queryByText("Snapshot: first-page")).not.toBeInTheDocument();
    expect(screen.getByText("Snapshot: second-page")).toBeVisible();
  });

  it("offers a native disclosure and named keyboard-scrollable table without a focus trap", async () => {
    const user = userEvent.setup();
    render(
      <SnapshotChart
        snapshots={[snapshot("one", "2026-09-01T09:00:00Z", "1")]}
      />,
    );
    const summary = screen.getByText("Exact snapshot values and sources (1)");
    await user.tab();
    expect(summary).toHaveFocus();
    // Installed user-event does not emulate summary's native Enter activation.
    // Browser Enter/Space and arrow scrolling remain explicit handoff checks.
    await user.click(summary);
    const region = screen.getByRole("region", {
      name: "Exact snapshot values and sources (1)",
    });
    await user.tab();
    expect(region).toHaveFocus();
    expect(region).toHaveAttribute("tabindex", "0");
    await user.tab();
    const sourceSummary = screen.getByText("Method and provenance");
    expect(sourceSummary).toHaveFocus();
    await user.click(sourceSummary);
    expect(screen.getByText("Saved server total")).toBeVisible();
    expect(screen.getByText("synthetic:portfolio-source")).toBeVisible();
    expect(screen.getByText("No client FX conversion")).toBeVisible();
    await user.tab({ shift: true });
    expect(region).toHaveFocus();
  });

  it("keeps a zero baseline and formats time ticks explicitly in UTC", () => {
    render(
      <SnapshotChart
        snapshots={[snapshot("one", "2026-09-01T09:00:00Z", "1")]}
      />,
    );
    const axis = chart.yAxis.mock.lastCall![0];
    expect(axis.domain[0](12)).toBe(0);
    expect(axis.domain[1](-12)).toBe(0);
    expect(axis.domain[0](-12)).toBe(-12);
    expect(axis.domain[1](12)).toBe(12);
    const tick = chart.xAxis.mock.lastCall![0].tickFormatter(
      Date.UTC(2026, 8, 1, 9),
    );
    expect(tick).toContain("09:00");
    expect(tick).toMatch(/01 Sep(?:t)?/u);
  });

  it("uses the canonical allocation weight rather than the converted pie geometry", () => {
    const item: AllocationResponse = {
      id: "holding",
      label: "Precise holding",
      asset_type: "equity",
      market_value: metric("1"),
      weight: "0.123456789012345678",
      weight_availability: "available",
    };
    render(<AllocationChart data={[item]} />);
    const row = chart.pie.mock.lastCall![0].data[0];
    const formatter = chart.tooltip.mock.lastCall![0].formatter;
    expect(formatter(999, "geometry", { payload: row })).toEqual([
      "12.3456789012345678%",
      "Precise holding",
    ]);
    expect(item.weight).toBe("0.123456789012345678");
  });
});
