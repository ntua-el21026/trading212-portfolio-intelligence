import { formatPlanningMoney } from "../lib/planning-format";
import type {
  PlanningDriftRow,
  PlanningDriftTotals,
  PlanningResultContext,
  PlanningObjective,
} from "@trading212/api-contracts";
import { Notice, StatusPill, Surface } from "@trading212/ui";

import {
  formatDateTime,
  formatDecimal,
  formatPercent,
  titleCase,
} from "../lib/format";

export function PlanningContext({
  context,
}: Readonly<{ context: PlanningResultContext }>) {
  return (
    <Surface>
      <div className="target-actions">
        <h2>Sources and coverage</h2>
        <StatusPill
          tone={
            context.availability === "available" && context.coverage.complete
              ? "positive"
              : "warning"
          }
        >
          {titleCase(context.availability)} ·{" "}
          {titleCase(context.data_quality.state)}
        </StatusPill>
      </div>
      <dl className="planning-facts">
        <div>
          <dt>Valuation</dt>
          <dd>{formatDateTime(context.as_of)}</dd>
        </div>
        <div>
          <dt>Financial source cutoff</dt>
          <dd>{formatDateTime(context.source_cutoff_at)}</dd>
        </div>
        <div>
          <dt>Matched exposure</dt>
          <dd>{formatPercent(context.coverage.matched_weight)}</dd>
        </div>
        <div>
          <dt>Unclassified exposure</dt>
          <dd>{formatPercent(context.coverage.unclassified_weight)}</dd>
        </div>
        <div>
          <dt>Unresolved target weight</dt>
          <dd>{formatPercent(context.coverage.unresolved_target_weight)}</dd>
        </div>
        <div>
          <dt>Method</dt>
          <dd>
            {context.method.name} · {context.method.version}
          </dd>
        </div>
      </dl>
      {context.reason_code ? (
        <Notice title="Result availability">
          {titleCase(context.reason_code)}
        </Notice>
      ) : null}
      {context.data_quality.missing_inputs.length ? (
        <p>
          Missing inputs:{" "}
          {context.data_quality.missing_inputs.map(titleCase).join(", ")}
        </p>
      ) : null}
      {[...context.warnings, ...context.assumptions].map((item, index) => (
        <Notice
          key={`${item.code}:${index}`}
          title={titleCase(item.code)}
          tone={item.severity === "error" ? "danger" : "warning"}
        >
          {item.message}
        </Notice>
      ))}
      <details className="target-details">
        <summary>Snapshot, target and provenance</summary>
        <dl className="planning-identities">
          <dt>Snapshot</dt>
          <dd>{context.snapshot_id}</dd>
          <dt>Target version</dt>
          <dd>{context.target_version_id}</dd>
          <dt>Input digest</dt>
          <dd>{context.input_digest}</dd>
          <dt>Calculated</dt>
          <dd>{formatDateTime(context.calculated_at)}</dd>
        </dl>
        <ul>
          {context.sources.map((item, index) => (
            <li key={`${item.kind}:${item.id}:${index}`}>
              {titleCase(item.kind)} · {item.id} · effective{" "}
              {formatDateTime(item.effective_at)} · observed{" "}
              {formatDateTime(item.first_observed_at)} · {item.version}
            </li>
          ))}
        </ul>
      </details>
    </Surface>
  );
}

export function DriftTotals({
  totals,
}: Readonly<{ totals: PlanningDriftTotals }>) {
  return (
    <dl className="planning-facts">
      <div>
        <dt>Portfolio value</dt>
        <dd>
          {totals.value
            ? `${totals.value.currency} ${formatPlanningMoney(totals.value.amount)}`
            : "Unavailable"}
        </dd>
      </div>
      <div>
        <dt>Existing cash</dt>
        <dd>
          {totals.cash
            ? `${totals.cash.currency} ${formatPlanningMoney(totals.cash.amount)}`
            : "Unavailable"}
        </dd>
      </div>
      <div>
        <dt>Unclassified value</dt>
        <dd>
          {totals.unclassified.currency}{" "}
          {formatPlanningMoney(totals.unclassified.amount)}
        </dd>
      </div>
      <div>
        <dt>L1 drift</dt>
        <dd>{formatPercent(totals.l1_drift)}</dd>
      </div>
      <div>
        <dt>Weighted squared drift</dt>
        <dd>{formatDecimal(totals.weighted_squared_drift, 8)}</dd>
      </div>
    </dl>
  );
}

export function DriftTable({
  rows,
  caption,
  basis = "direct",
}: Readonly<{
  rows: PlanningDriftRow[];
  caption: string;
  basis?: "direct" | "effective";
}>) {
  if (!rows.length)
    return <p className="muted">No rows are available for this selection.</p>;
  return (
    <div
      className="table-scroll"
      tabIndex={0}
      role="region"
      aria-label={caption}
    >
      <table className="data-table planning-table">
        <caption>{caption}</caption>
        <thead>
          <tr>
            <th scope="col">Exposure</th>
            <th scope="col">Value</th>
            <th scope="col">Target</th>
            <th scope="col">
              {basis === "direct" ? "Actual direct" : "Effective"}
            </th>
            <th scope="col">Signed drift</th>
            <th scope="col">Absolute drift</th>
            <th scope="col">Relative drift</th>
            <th scope="col">Monetary gap</th>
            <th scope="col">Quality</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.key}>
              <th scope="row">
                <strong>{row.name}</strong>
                <span>
                  {titleCase(row.kind)} ·{" "}
                  {row.classification
                    ? titleCase(row.classification)
                    : "Classification unavailable"}
                </span>
              </th>
              <td>
                {row.actual_value
                  ? `${row.actual_value.currency} ${formatPlanningMoney(row.actual_value.amount)}`
                  : "Unavailable"}
              </td>
              <td>{formatPercent(row.target_weight)}</td>
              <td
                title={
                  basis === "effective"
                    ? titleCase(row.effective_weight_reason)
                    : undefined
                }
              >
                {formatPercent(
                  basis === "direct"
                    ? row.actual_direct_weight
                    : row.effective_weight,
                )}
              </td>
              <td>{formatPercent(row.signed_drift)}</td>
              <td>{formatPercent(row.absolute_drift)}</td>
              <td
                title={
                  row.relative_drift_reason
                    ? titleCase(row.relative_drift_reason)
                    : undefined
                }
              >
                {formatPercent(row.relative_drift)}
                {row.relative_drift === null && row.relative_drift_reason ? (
                  <span className="planning-metric-reason">
                    {titleCase(row.relative_drift_reason)}
                  </span>
                ) : null}
              </td>
              <td>
                {row.monetary_gap
                  ? `${row.monetary_gap.currency} ${formatPlanningMoney(row.monetary_gap.amount)}`
                  : "Unavailable"}
              </td>
              <td>{titleCase(row.quality)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Objective({
  value,
}: Readonly<{ value: PlanningObjective | null }>) {
  if (!value) return <>Unavailable</>;
  return (
    <span
      title={`${value.rounding}; quantum ${value.quantum}; error bound ${value.rounding_error_bound}`}
    >
      {value.scores.join(" / ")}
    </span>
  );
}
