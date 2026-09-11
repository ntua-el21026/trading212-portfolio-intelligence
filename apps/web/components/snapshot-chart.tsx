"use client";

import { useId } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { SnapshotResponse } from "../lib/contracts";
import { titleCase } from "../lib/format";
import styles from "./snapshot-chart.module.css";

interface PlotRow {
  time: number;
  value: number | null;
  fraction: string;
  original: SnapshotResponse;
}

function compareRows(left: PlotRow, right: PlotRow): number {
  const secondDifference =
    Math.floor(left.time / 1000) - Math.floor(right.time / 1000);
  if (secondDifference !== 0) return secondDifference;
  // Date has millisecond resolution. Keep the actual sub-millisecond ordering
  // separately; equivalent instants with different offsets/precision tie by ID.
  const digits = Math.max(left.fraction.length, right.fraction.length);
  const leftFraction = left.fraction.padEnd(digits, "0");
  const rightFraction = right.fraction.padEnd(digits, "0");
  if (leftFraction !== rightFraction) {
    return leftFraction < rightFraction ? -1 : 1;
  }
  return left.original.id < right.original.id
    ? -1
    : left.original.id > right.original.id
      ? 1
      : 0;
}

function plotValue(value: string | null): number | null {
  if (value === null) return null;
  const coordinate = Number(value);
  // A value outside display range is not an observed zero.
  return Number.isFinite(coordinate) &&
    !(coordinate === 0 && /[1-9]/u.test(value))
    ? coordinate
    : null;
}

function fullValue(snapshot: SnapshotResponse): string {
  const metric = snapshot.total_value;
  return `${metric.value ?? "Unavailable"} ${metric.reporting_currency}`;
}

function QualityText({ snapshot }: Readonly<{ snapshot: SnapshotResponse }>) {
  const quality = snapshot.data_quality;
  return (
    <>
      <span>{titleCase(quality.state)}</span>
      {quality.warnings.length > 0 ? (
        <p>Warnings: {quality.warnings.join("; ")}</p>
      ) : null}
      {quality.missing_inputs.length > 0 ? (
        <p>Missing inputs: {quality.missing_inputs.join(", ")}</p>
      ) : null}
    </>
  );
}

export function SnapshotChart({
  snapshots,
}: Readonly<{ snapshots: readonly SnapshotResponse[] }>) {
  const id = useId();
  const descriptionId = `${id}-description`;
  const tableId = `${id}-table`;
  const summaryId = `${id}-summary`;
  const chartData: PlotRow[] = snapshots
    .map((snapshot) => ({
      // Only screen coordinates use binary numbers. Labels use original fields.
      time: Date.parse(snapshot.valuation_at),
      value: plotValue(snapshot.total_value.value),
      fraction: snapshot.valuation_at.match(/\.(\d+)/u)?.[1] ?? "",
      original: snapshot,
    }))
    .sort(compareRows);
  const currencies = [
    ...new Set(
      snapshots.map((snapshot) => snapshot.total_value.reporting_currency),
    ),
  ].sort();
  const mixedCurrencies = currencies.length > 1;
  const invalidTimes = chartData.some((row) => !Number.isFinite(row.time));
  const hasCoincidentPoints = chartData.some(
    (row, index) => index > 0 && row.time === chartData[index - 1].time,
  );
  const outsideDisplayRange = chartData.some(
    (row) => row.original.total_value.value !== null && row.value === null,
  );
  const hasValues = chartData.some((row) => row.value !== null);
  const chartMessage =
    snapshots.length === 0
      ? "No snapshot observations on this page."
      : mixedCurrencies
        ? `Values use different currencies (${currencies.join(", ")}). A comparable monetary chart is unavailable.`
        : invalidTimes
          ? "A valuation time cannot be plotted. Original records remain in the table."
          : !hasValues
            ? "No plottable values on this page. Unavailable values remain unavailable."
            : null;

  return (
    <figure className={styles.figure}>
      <figcaption>
        Snapshot observations
        {currencies.length === 1 ? ` · ${currencies[0]}` : ""} · UTC
      </figcaption>
      <p id={descriptionId} className={styles.description}>
        Only the {snapshots.length} records on this page are shown, in ascending
        valuation time. No daily observations are inferred.{" "}
        {hasCoincidentPoints
          ? "Points sharing a display time remain separate records; connections are omitted on this page."
          : "Straight connections are visual guides between observations, not values between them. Unavailable observations break the line."}{" "}
        Original timestamps, currencies, quality and sources are in the table
        below.
      </p>
      {outsideDisplayRange ? (
        <p className={styles.description}>
          Some exact values are outside chart display range; they remain in the
          table and are not plotted as zero.
        </p>
      ) : null}
      {chartMessage ? (
        <p className={styles.message}>{chartMessage}</p>
      ) : (
        <div
          aria-label="Portfolio value by immutable snapshot"
          aria-describedby={descriptionId}
          className={`snapshot-chart ${styles.plot}`}
          role="img"
        >
          <ResponsiveContainer height="100%" width="100%">
            <LineChart
              data={chartData}
              accessibilityLayer={false}
              margin={{ bottom: 12, left: 8, right: 20, top: 12 }}
            >
              <CartesianGrid
                stroke="#e2e7ed"
                strokeDasharray="3 4"
                vertical={false}
              />
              <XAxis
                type="number"
                scale="utc"
                dataKey="time"
                domain={["dataMin", "dataMax"]}
                padding={{ left: 8, right: 8 }}
                axisLine={false}
                tickLine={false}
                fontSize={11}
                minTickGap={40}
                tickFormatter={(time: number) =>
                  new Intl.DateTimeFormat("en-GB", {
                    day: "2-digit",
                    month: "short",
                    hour: "2-digit",
                    minute: "2-digit",
                    hour12: false,
                    timeZone: "UTC",
                  }).format(new Date(time))
                }
              />
              <YAxis
                axisLine={false}
                tickLine={false}
                fontSize={11}
                width={76}
                padding={{ top: 8, bottom: 8 }}
                domain={[
                  (minimum: number) => Math.min(0, minimum),
                  (maximum: number) => Math.max(0, maximum),
                ]}
                tickFormatter={(coordinate: number) =>
                  new Intl.NumberFormat("en-GB", {
                    notation: "compact",
                    maximumSignificantDigits: 3,
                  }).format(coordinate)
                }
              />
              <Tooltip
                isAnimationActive={false}
                filterNull={false}
                content={({ active, payload }) => {
                  const hovered = payload?.[0]?.payload as PlotRow | undefined;
                  if (!active || !hovered) return null;
                  // Recharts may return only one row at an overlapping coordinate.
                  // Expose every actual record there, without jitter/aggregation.
                  const records = chartData.filter(
                    (row) => row.time === hovered.time,
                  );
                  return (
                    <div className={styles.tooltip}>
                      {records.map(({ original: snapshot }) => (
                        <div key={snapshot.id} className={styles.tooltipRecord}>
                          <strong>{fullValue(snapshot)}</strong>
                          <p>
                            <time dateTime={snapshot.valuation_at}>
                              {snapshot.valuation_at}
                            </time>
                          </p>
                          <p>Snapshot: {snapshot.id}</p>
                          <p>Source cutoff: {snapshot.source_cutoff_at}</p>
                          <p>
                            {titleCase(snapshot.total_value.availability)} value
                          </p>
                          {snapshot.total_value.unavailable_reason ? (
                            <p>{snapshot.total_value.unavailable_reason}</p>
                          ) : null}
                          <QualityText snapshot={snapshot} />
                        </div>
                      ))}
                    </div>
                  );
                }}
              />
              <Line
                dataKey="value"
                name="Total value"
                type="linear"
                connectNulls={false}
                isAnimationActive={false}
                stroke={hasCoincidentPoints ? "none" : "#006f53"}
                strokeWidth={2}
                dot={{
                  fill: "#006f53",
                  stroke: "#ffffff",
                  strokeWidth: 1,
                  r: 4,
                }}
                activeDot={{ fill: "#006f53", stroke: "#ffffff", r: 5 }}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
      <details className={styles.details}>
        <summary id={summaryId}>
          Exact snapshot values and sources ({snapshots.length})
        </summary>
        <div
          id={tableId}
          className={`table-scroll ${styles.tableRegion}`}
          role="region"
          aria-labelledby={summaryId}
          tabIndex={0}
        >
          <table className="data-table">
            <caption>
              Snapshot chart: exact server values in original page order
            </caption>
            <thead>
              <tr>
                <th scope="col">Snapshot / original valuation time</th>
                <th scope="col">Original source cutoff</th>
                <th scope="col">Total value / currency</th>
                <th scope="col">Availability</th>
                <th scope="col">Quality and source details</th>
              </tr>
            </thead>
            <tbody>
              {snapshots.map((snapshot) => (
                <tr key={snapshot.id}>
                  <th scope="row">
                    <time dateTime={snapshot.valuation_at}>
                      {snapshot.valuation_at}
                    </time>
                    <p>Snapshot: {snapshot.id}</p>
                  </th>
                  <td>
                    <time dateTime={snapshot.source_cutoff_at}>
                      {snapshot.source_cutoff_at}
                    </time>
                  </td>
                  <td>{fullValue(snapshot)}</td>
                  <td>
                    {titleCase(snapshot.total_value.availability)}
                    {snapshot.total_value.unavailable_reason ? (
                      <p>{snapshot.total_value.unavailable_reason}</p>
                    ) : null}
                  </td>
                  <td>
                    <QualityText snapshot={snapshot} />
                    <details>
                      <summary>Method and provenance</summary>
                      <dl>
                        <dt>Snapshot reporting currency</dt>
                        <dd>{snapshot.reporting_currency}</dd>
                        <dt>Calculation version</dt>
                        <dd>{snapshot.total_value.calculation_version}</dd>
                        <dt>Method</dt>
                        <dd>{snapshot.total_value.methodology}</dd>
                        <dt>Provenance</dt>
                        <dd>
                          {snapshot.total_value.provenance.join(", ") ||
                            "None reported"}
                        </dd>
                        <dt>Assumptions</dt>
                        <dd>
                          {snapshot.total_value.assumptions.join("; ") ||
                            "None reported"}
                        </dd>
                        <dt>Quality as of</dt>
                        <dd>{snapshot.data_quality.as_of}</dd>
                        <dt>Source timestamp</dt>
                        <dd>{snapshot.data_quality.source_timestamp}</dd>
                        <dt>Freshness threshold (seconds)</dt>
                        <dd>
                          {snapshot.data_quality.freshness_threshold_seconds}
                        </dd>
                      </dl>
                    </details>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </figure>
  );
}
