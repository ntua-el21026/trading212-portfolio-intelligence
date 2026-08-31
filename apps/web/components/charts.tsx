"use client";

import {
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { AllocationResponse, SnapshotResponse } from "../lib/contracts";
import { formatDate, formatMoney, formatPercent } from "../lib/format";

const allocationColors = [
  "#006f53",
  "#199a68",
  "#55be6b",
  "#9ad996",
  "#2d72c4",
  "#a7b0be",
];

export function AllocationChart({
  data,
}: Readonly<{ data: AllocationResponse[] }>) {
  const chartData = data
    .filter((item) => item.weight !== null)
    .map((item) => ({
      label: item.label,
      // Conversion is chart geometry only; displayed values remain canonical strings.
      value: Number(item.weight),
    }));
  return (
    <div
      aria-label="Direct allocation by holding, including cash"
      className="allocation-chart"
      role="img"
    >
      <ResponsiveContainer height="100%" width="100%">
        <PieChart>
          <Pie
            data={chartData}
            dataKey="value"
            innerRadius="61%"
            isAnimationActive={false}
            nameKey="label"
            outerRadius="90%"
            paddingAngle={1}
            stroke="#ffffff"
            strokeWidth={2}
          >
            {chartData.map((entry, index) => (
              <Cell
                fill={allocationColors[index % allocationColors.length]}
                key={entry.label}
              />
            ))}
          </Pie>
          <Tooltip
            formatter={(_value, _name, item) => [
              formatPercent(String(item.payload.value)),
              item.payload.label,
            ]}
          />
        </PieChart>
      </ResponsiveContainer>
    </div>
  );
}

export function SnapshotChart({
  snapshots,
}: Readonly<{ snapshots: SnapshotResponse[] }>) {
  const reportingCurrency = snapshots[0]?.total_value.reporting_currency ?? "";
  const chartData = snapshots.map((snapshot) => ({
    date: formatDate(snapshot.valuation_at),
    // Conversion is chart geometry only; the table exposes exact decimal strings.
    value:
      snapshot.total_value.value === null
        ? null
        : Number(snapshot.total_value.value),
  }));
  return (
    <div
      aria-label="Portfolio value by immutable snapshot"
      className="snapshot-chart"
      role="img"
    >
      <ResponsiveContainer height="100%" width="100%">
        <LineChart
          data={chartData}
          margin={{ bottom: 8, left: 8, right: 16, top: 12 }}
        >
          <CartesianGrid
            stroke="#e2e7ed"
            strokeDasharray="3 4"
            vertical={false}
          />
          <XAxis
            axisLine={false}
            dataKey="date"
            fontSize={12}
            tickLine={false}
          />
          <YAxis
            axisLine={false}
            fontSize={12}
            tickFormatter={(value: number) => `${Math.round(value / 1000)}k`}
            tickLine={false}
            width={48}
          />
          <Tooltip
            formatter={(value) => [
              `${formatMoney(String(value))} ${reportingCurrency}`.trim(),
              "Value",
            ]}
          />
          <Line
            activeDot={{ fill: "#006f53", r: 5 }}
            dataKey="value"
            dot={{ fill: "#006f53", r: 3 }}
            isAnimationActive={false}
            stroke="#006f53"
            strokeWidth={2.25}
            type="monotone"
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
