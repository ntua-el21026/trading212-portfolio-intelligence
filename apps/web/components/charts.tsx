"use client";

import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";

import type { AllocationResponse } from "../lib/contracts";
import { formatHistoricalPercent } from "../lib/historical-format";

export { SnapshotChart } from "./snapshot-chart";

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
      original: item,
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
                key={entry.original.id}
              />
            ))}
          </Pie>
          <Tooltip
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
