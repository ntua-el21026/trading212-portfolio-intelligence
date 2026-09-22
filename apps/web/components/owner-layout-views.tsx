import type { CSSProperties } from "react";
import type { OwnerLayoutView } from "@trading212/api-contracts";
import { Notice, Surface } from "@trading212/ui";
import type { MetricResponse, OverviewBundle } from "../lib/contracts";
import { savedLayoutSelectionHref } from "../lib/owner-layout-query";
import { formatDateTime } from "../lib/format";
import { MetricCard } from "./financial";
import { QualityBanner } from "./quality";
import Link from "./navigation-intent";
import styles from "./owner-layouts.module.css";

function ExactMetric({
  label,
  metric,
}: Readonly<{ label: string; metric: MetricResponse }>) {
  return (
    <div>
      <MetricCard label={label} metric={metric} />
      <details>
        <summary>Exact value and method</summary>
        <p className={styles.identity} data-layout-metric={label}>
          {metric.value ?? "Unavailable"} {metric.reporting_currency}
        </p>
        <p>{metric.unavailable_reason ?? metric.availability}</p>
        <p>
          {metric.methodology} · {metric.calculation_version}
        </p>
        {metric.provenance.map((source, index) => (
          <p key={index}>{source}</p>
        ))}
        {metric.assumptions.map((assumption, index) => (
          <p key={index}>{assumption}</p>
        ))}
      </details>
    </div>
  );
}
export function OwnerLayoutDisplay({
  value,
  bundle,
  unavailable,
}: Readonly<{
  value: OwnerLayoutView;
  bundle: OverviewBundle | null;
  unavailable?: string;
}>) {
  return (
    <div className={styles.stack}>
      {bundle ? (
        <>
          <QualityBanner quality={bundle.summary.data_quality} />
          <p>
            Current portfolio as of{" "}
            {formatDateTime(bundle.summary.data_quality.as_of)}. Original source
            timestamp:{" "}
            {formatDateTime(bundle.summary.data_quality.source_timestamp)}.
          </p>
        </>
      ) : null}
      <div
        className={styles.grid}
        data-density={value.content.density}
        style={{ "--layout-columns": value.content.columns } as CSSProperties}
      >
        {value.content.widgets.map((widget, index) => (
          <Surface key={widget.id}>
            <h2>{widget.label || widget.kind.replaceAll("_", " ")}</h2>
            {widget.selection ? (
              <>
                <p>
                  Saved {widget.selection.kind.replaceAll("_", " ")} selection.
                  The destination checks current account access and source
                  availability.
                </p>
                <Link
                  prefetch={false}
                  href={savedLayoutSelectionHref(
                    widget.selection,
                    value.content.account_id,
                  )}
                >
                  Open saved view {index + 1}
                </Link>
              </>
            ) : !bundle ? (
              <Notice
                title={
                  value.content.account_id
                    ? "Portfolio preview unavailable"
                    : "Choose an account"
                }
              >
                {unavailable ??
                  "Edit this owner template and bind an account to display its portfolio previews."}
              </Notice>
            ) : widget.kind === "portfolio_summary" ? (
              <div className={styles.stack}>
                <ExactMetric
                  label="Total portfolio value"
                  metric={bundle.summary.total_value}
                />
                <ExactMetric
                  label="Cash"
                  metric={bundle.summary.cash_balance}
                />
                <ExactMetric
                  label="Invested value"
                  metric={bundle.summary.invested_value}
                />
                <ExactMetric
                  label="Net contributions"
                  metric={bundle.summary.net_contributions}
                />
              </div>
            ) : widget.kind === "direct_allocation" ? (
              <>
                <p>
                  {bundle.allocation.returned_count} of{" "}
                  {bundle.allocation.total} canonical allocation rows.
                </p>
                <div
                  className="table-scroll"
                  role="region"
                  aria-label="Saved layout allocation preview"
                  tabIndex={0}
                >
                  <table className="data-table">
                    <caption>Exact direct allocation preview</caption>
                    <thead>
                      <tr>
                        <th scope="col">Holding</th>
                        <th scope="col">Value</th>
                        <th scope="col">Weight ratio</th>
                      </tr>
                    </thead>
                    <tbody>
                      {bundle.allocation.items.map((row) => (
                        <tr key={row.id}>
                          <th scope="row">{row.label}</th>
                          <td>
                            {row.market_value.value ?? "Unavailable"}{" "}
                            {row.market_value.reporting_currency}
                            {row.market_value.unavailable_reason ? (
                              <p>{row.market_value.unavailable_reason}</p>
                            ) : null}
                          </td>
                          <td>{row.weight ?? "Unavailable"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            ) : widget.kind === "holdings_preview" ? (
              <>
                <p>
                  {bundle.positions.items.length} of {bundle.positions.total}{" "}
                  direct positions, ordered by market value.
                </p>
                <div
                  className="table-scroll"
                  role="region"
                  aria-label="Saved layout holdings preview"
                  tabIndex={0}
                >
                  <table className="data-table">
                    <caption>Exact holdings preview</caption>
                    <thead>
                      <tr>
                        <th scope="col">Holding</th>
                        <th scope="col">Quantity</th>
                        <th scope="col">Price</th>
                        <th scope="col">Market value</th>
                      </tr>
                    </thead>
                    <tbody>
                      {bundle.positions.items.map((row) => (
                        <tr key={row.id}>
                          <th scope="row">
                            {row.ticker} · {row.name}
                          </th>
                          <td>{row.quantity}</td>
                          <td>
                            {row.current_price ?? "Unavailable"}{" "}
                            {row.trading_currency}
                          </td>
                          <td>
                            {row.market_value.value ?? "Unavailable"}{" "}
                            {row.market_value.reporting_currency}
                            {row.market_value.unavailable_reason ? (
                              <p>{row.market_value.unavailable_reason}</p>
                            ) : null}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            ) : (
              <>
                <p>Quality: {bundle.summary.data_quality.state}</p>
                <p>
                  Reconciliation: {bundle.reconciliation.status}; discrepancies:{" "}
                  {bundle.reconciliation.discrepancy_count}.
                </p>
                <p>
                  Freshness threshold:{" "}
                  {bundle.summary.data_quality.freshness_threshold_seconds}{" "}
                  seconds.
                </p>
                <ul>
                  {bundle.summary.data_quality.warnings.map((warning, i) => (
                    <li key={`warning-${i}`}>{warning}</li>
                  ))}
                  {bundle.summary.data_quality.missing_inputs.map(
                    (missing, i) => (
                      <li key={`missing-${i}`}>Missing: {missing}</li>
                    ),
                  )}
                </ul>
              </>
            )}
          </Surface>
        ))}
      </div>
    </div>
  );
}
