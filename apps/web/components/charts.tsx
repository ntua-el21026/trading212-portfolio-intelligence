"use client";

import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";

import type { AllocationResponse } from "../lib/contracts";
import { formatHistoricalPercent } from "../lib/historical-format";

export { SnapshotChart } from "./snapshot-chart";

const allocationColors = [
  "var(--pi-chart-allocation-1)",
  "var(--pi-chart-allocation-2)",
  "var(--pi-chart-allocation-3)",
  "var(--pi-chart-allocation-4)",
  "var(--pi-chart-allocation-5)",
  "var(--pi-chart-allocation-6)",
];

export function AllocationChart({
  data,
}: Readonly<{ data: AllocationResponse[] }>) {
  const chartData = data
    .map((item, index) => ({
      // Keep the table's source-row color when an unavailable weight is omitted.
      color: allocationColors[index % allocationColors.length],
      label: item.label,
      original: item,
      // Conversion is chart geometry only; displayed values remain canonical strings.
      value: item.weight === null ? null : Number(item.weight),
    }))
    .filter((item) => item.value !== null);
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
            stroke="var(--color-surface)"
            strokeWidth={2}
          >
            {chartData.map((entry) => (
              <Cell fill={entry.color} key={entry.original.id} />
            ))}
          </Pie>
          <Tooltip
            isAnimationActive={false}
            contentStyle={{
              backgroundColor: "var(--pi-chart-tooltip-bg)",
              borderColor: "var(--pi-chart-tooltip-border)",
              borderRadius: 12,
              color: "var(--pi-chart-tooltip-text)",
              fontSize: "0.8rem",
            }}
            itemStyle={{ color: "var(--pi-chart-tooltip-text)" }}
            formatter={(_value, _name, item) => {
              const original = item.payload.original as AllocationResponse;
              return [formatHistoricalPercent(original.weight), original.label];
            }}
          />
        </PieChart>
      </ResponsiveContainer>
    </div>
  );
}
