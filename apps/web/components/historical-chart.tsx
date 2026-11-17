"use client";

import { useId } from "react";
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { formatMoney, formatPercent } from "../lib/format";
import {
  formatHistoricalDecimal,
  formatHistoricalPercent,
} from "../lib/historical-format";

export interface HistoricalChartSeries {
  key: string;
  label: string;
  color: string;
  kind?: "line" | "bar";
}

export interface HistoricalChartRow {
  date: string;
  values: Readonly<Record<string, string | null>>;
}

interface GeometryRow {
  date: string;
  original: HistoricalChartRow;
  [key: string]: string | number | null | HistoricalChartRow;
}

// Translate the existing application palette at the chart boundary. Callers keep
// their series contract; custom colors continue to pass through unchanged.
const themedSeriesColors: Readonly<Record<string, string>> = {
  "#006f53": "var(--pi-chart-portfolio)",
  "#047857": "var(--pi-chart-portfolio)",
  "#345a95": "var(--pi-chart-benchmark)",
  "#416bb0": "var(--pi-chart-benchmark)",
  "#547ba9": "var(--pi-chart-benchmark)",
  "#475569": "var(--pi-chart-auxiliary)",
  "#986229": "var(--pi-chart-warning)",
  "#ad5825": "var(--pi-chart-negative)",
};

export function HistoricalChart({
  label,
  rows,
  series,
  unit,
  tableId,
  ratioLabel = "return",
}: Readonly<{
  label: string;
  rows: readonly HistoricalChartRow[];
  series: readonly HistoricalChartSeries[];
  unit: "ratio" | string;
  tableId: string;
  ratioLabel?: string;
}>) {
  const descriptionId = useId();
  const data: GeometryRow[] = rows.map((row) => {
    const result: GeometryRow = { date: row.date, original: row };
    for (const column of series) {
      const value = row.values[column.key];
      // Binary conversion affects screen coordinates only. Tooltip and table
      // values retain the server's canonical decimal strings.
      result[column.key] =
        value === null || value === undefined ? null : Number(value);
    }
    return result;
  });
  return (
    <figure className="historical-figure">
      <figcaption>
        {label} · {unit === "ratio" ? ratioLabel : unit}
      </figcaption>
      <div
        className="historical-chart"
        role="img"
        aria-label={label}
        aria-describedby={descriptionId}
      >
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart
            data={data}
            margin={{ top: 16, right: 20, bottom: 8, left: 4 }}
          >
            <CartesianGrid
              stroke="var(--pi-chart-grid)"
              strokeDasharray="3 4"
              vertical={false}
            />
            <XAxis
              dataKey="date"
              axisLine={false}
              tickLine={false}
              fontSize={11}
              tick={{ fill: "var(--pi-chart-axis)" }}
              minTickGap={28}
            />
            <YAxis
              axisLine={false}
              tickLine={false}
              fontSize={11}
              tick={{ fill: "var(--pi-chart-axis)" }}
              width={70}
              domain={[
                (minimum: number) => Math.min(0, minimum),
                (maximum: number) => Math.max(0, maximum),
              ]}
              tickFormatter={(value: number) =>
                unit === "ratio"
                  ? formatPercent(String(value))
                  : formatMoney(String(value), 0)
              }
            />
            <ReferenceLine y={0} stroke="var(--pi-chart-axis)" />
            <Tooltip
              isAnimationActive={false}
              cursor={{ stroke: "var(--pi-chart-axis)" }}
              contentStyle={{
                backgroundColor: "var(--pi-chart-tooltip-bg)",
                borderColor: "var(--pi-chart-tooltip-border)",
                borderRadius: 12,
                color: "var(--pi-chart-tooltip-text)",
                fontSize: "0.8rem",
              }}
              itemStyle={{ color: "var(--pi-chart-tooltip-text)" }}
              labelStyle={{ color: "var(--pi-chart-tooltip-text)" }}
              formatter={(_value, name, item) => {
                const row = item.payload as GeometryRow;
                const key = String(item.dataKey);
                const value = row.original.values[key] ?? null;
                return [
                  unit === "ratio"
                    ? formatHistoricalPercent(value)
                    : `${formatHistoricalDecimal(value, 2)} ${unit}`,
                  name,
                ];
              }}
            />
            <Legend
              position="top"
              iconSize={12}
              labelStyle={{ color: "var(--pi-chart-axis)" }}
              wrapperStyle={{ fontSize: "0.75rem", paddingBottom: 12 }}
            />
            {series.map((column) =>
              column.kind === "bar" ? (
                <Bar
                  key={column.key}
                  dataKey={column.key}
                  name={column.label}
                  fill={themedSeriesColors[column.color] ?? column.color}
                  isAnimationActive={false}
                  maxBarSize={18}
                  radius={[3, 3, 0, 0]}
                />
              ) : (
                <Line
                  key={column.key}
                  dataKey={column.key}
                  name={column.label}
                  stroke={themedSeriesColors[column.color] ?? column.color}
                  strokeWidth={2.5}
                  type="linear"
                  dot={false}
                  activeDot={{
                    r: 4,
                    stroke: "var(--color-surface)",
                    strokeWidth: 2,
                  }}
                  isAnimationActive={false}
                  connectNulls={false}
                />
              ),
            )}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <p id={descriptionId} className="muted">
        Gaps remain disconnected.{" "}
        <a href={`#${tableId}`}>Read the equivalent server-value table</a>.
      </p>
    </figure>
  );
}
