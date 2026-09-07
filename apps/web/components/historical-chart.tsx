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

export function HistoricalChart({
  label,
  rows,
  series,
  unit,
  tableId,
}: Readonly<{
  label: string;
  rows: readonly HistoricalChartRow[];
  series: readonly HistoricalChartSeries[];
  unit: "ratio" | string;
  tableId: string;
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
        {label} · {unit === "ratio" ? "return" : unit}
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
              stroke="#e2e7ed"
              strokeDasharray="3 4"
              vertical={false}
            />
            <XAxis
              dataKey="date"
              axisLine={false}
              tickLine={false}
              fontSize={11}
              minTickGap={28}
            />
            <YAxis
              axisLine={false}
              tickLine={false}
              fontSize={11}
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
            <ReferenceLine y={0} stroke="#9ba8b4" />
            <Tooltip
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
            <Legend />
            {series.map((column) =>
              column.kind === "bar" ? (
                <Bar
                  key={column.key}
                  dataKey={column.key}
                  name={column.label}
                  fill={column.color}
                  isAnimationActive={false}
                  maxBarSize={18}
                />
              ) : (
                <Line
                  key={column.key}
                  dataKey={column.key}
                  name={column.label}
                  stroke={column.color}
                  strokeWidth={2}
                  type="linear"
                  dot={false}
                  activeDot={{ r: 4 }}
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
