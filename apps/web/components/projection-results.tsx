import type { ReactNode } from "react";
import type {
  ProjectionResultPage,
  ProjectionResultContextView,
  ProjectionPointRow,
  ProjectionGoalEstimateView,
  ProjectionQuantilesView,
  ProjectionHistogramView,
  GoalAnalysisResponse,
} from "@trading212/api-contracts";
import { Notice, Surface } from "@trading212/ui";
import { projectionHref, type ProjectionQuery } from "../lib/projection-query";
import Link from "./navigation-intent";
import styles from "./projection-workspace.module.css";
export function ProjectionMoney({
  value,
}: Readonly<{ value: { amount: string; currency: string } }>) {
  return (
    <span>
      {value.amount} {value.currency}
    </span>
  );
}
const words = (value: string) => value.replaceAll("_", " ");
function Table({
  caption,
  children,
}: Readonly<{ caption: string; children: ReactNode }>) {
  return (
    <div
      className="table-scroll"
      role="region"
      aria-label={caption}
      tabIndex={0}
    >
      <table className={`data-table ${styles.table}`}>
        <caption>{caption}</caption>
        {children}
      </table>
    </div>
  );
}
export function ProjectionQuantiles({
  value,
  label,
}: Readonly<{ value: ProjectionQuantilesView; label: string }>) {
  return (
    <Table caption={label}>
      <thead>
        <tr>
          {value.probabilities.map((probability) => (
            <th scope="col" key={probability}>
              Quantile {probability}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        <tr>
          {value.values.map((amount, i) => (
            <td key={value.probabilities[i]}>
              <ProjectionMoney value={amount} />
            </td>
          ))}
        </tr>
      </tbody>
    </Table>
  );
}
export function ProjectionGoalEstimate({
  estimate,
}: Readonly<{ estimate: ProjectionGoalEstimateView }>) {
  return (
    <section>
      <h3>Modeled goal estimate</h3>
      <dl className={styles.context}>
        <dt>Goal version</dt>
        <dd>
          <code>{estimate.goal_version_id}</code>
        </dd>
        <dt>Target ({estimate.basis})</dt>
        <dd>
          <ProjectionMoney value={estimate.target} />
        </dd>
        <dt>Successful paths</dt>
        <dd>
          {estimate.successes} / {estimate.paths}
        </dd>
        <dt>Probability (ratio)</dt>
        <dd>{estimate.probability}</dd>
        <dt>95% Wilson interval (ratio)</dt>
        <dd>
          {estimate.interval_low} to {estimate.interval_high}
        </dd>
        <dt>Probability objective (ratio)</dt>
        <dd>{estimate.probability_objective}</dd>
        <dt>Modeled objective met</dt>
        <dd>{estimate.objective_met ? "Yes" : "No"}</dd>
        <dt>Funding-failed paths</dt>
        <dd>{estimate.funding_failed_paths}</dd>
        <dt>Mean shortfall</dt>
        <dd>
          <ProjectionMoney value={estimate.mean_shortfall} />
        </dd>
      </dl>
      <p>
        This model estimate includes sampling uncertainty and does not capture
        all model uncertainty. Meeting the modeled objective does not mark the
        goal accepted or achieved.
      </p>
      <ProjectionQuantiles
        value={estimate.shortfalls}
        label="Saved goal shortfall quantiles"
      />
    </section>
  );
}
function Histogram({
  value,
  basis,
}: Readonly<{ value: ProjectionHistogramView; basis: string }>) {
  return (
    <section>
      <h4>{basis} terminal histogram</h4>
      <p>
        Observed minimum <ProjectionMoney value={value.observed_minimum} />;
        maximum <ProjectionMoney value={value.observed_maximum} />.
      </p>
      <Table
        caption={`${basis} terminal histogram counts across all saved paths`}
      >
        <thead>
          <tr>
            <th scope="col">Lower (inclusive)</th>
            <th scope="col">Upper</th>
            <th scope="col">Upper boundary</th>
            <th scope="col">Path count</th>
          </tr>
        </thead>
        <tbody>
          {value.bins.map((bin, i) => (
            <tr key={i}>
              <td>
                <ProjectionMoney value={bin.lower} />
              </td>
              <td>
                <ProjectionMoney value={bin.upper} />
              </td>
              <td>{bin.upper_inclusive ? "Inclusive" : "Exclusive"}</td>
              <td>{bin.count}</td>
            </tr>
          ))}
        </tbody>
      </Table>
      <p>Boundary rule: {value.boundary_rule}.</p>
    </section>
  );
}
export function ProjectionContext({
  context,
}: Readonly<{ context: ProjectionResultContextView }>) {
  const { selection, assumptions } = context;
  return (
    <Surface className={styles.surface}>
      <h2>Saved projection basis</h2>
      <p>
        Model estimate, not a guaranteed forecast. Quality:{" "}
        <strong>{context.quality}</strong>. Nominal and real values are
        distinct; real purchasing power uses the saved inflation assumption. All
        amounts below preserve the API’s exact decimal strings.
      </p>
      <dl className={styles.context}>
        <dt>Run</dt>
        <dd>
          <code>{context.run_id}</code>
        </dd>
        <dt>Initial basis</dt>
        <dd>
          {words(selection.initial.kind)}
          {selection.initial.snapshot_id ? (
            <>
              {" "}
              · <code>{selection.initial.snapshot_id}</code>
            </>
          ) : null}
          {selection.initial.modeled_value ? (
            <>
              {" "}
              · <ProjectionMoney value={selection.initial.modeled_value} />
            </>
          ) : null}
        </dd>
        <dt>Calendar</dt>
        <dd>
          {context.anchor_date} to {context.terminal_date}; {selection.months}{" "}
          months
        </dd>
        <dt>Snapshot valuation</dt>
        <dd>
          {context.snapshot_valuation_at ??
            "Not applicable to a modeled initial value"}
        </dd>
        <dt>Source cutoff</dt>
        <dd>
          {context.source_cutoff_at ?? "No single declared source cutoff"}
        </dd>
        <dt>Calculated at</dt>
        <dd>{context.calculated_at}</dd>
        <dt>Paths per variant</dt>
        <dd>{selection.paths}</dd>
        <dt>Seed</dt>
        <dd>{selection.seed}</dd>
        <dt>Retained months</dt>
        <dd>{selection.retained_months.join(", ")}</dd>
      </dl>
      <details>
        <summary>Immutable assumptions and dated cash flows</summary>
        <p>
          Assumption version <code>{selection.assumption_version_id}</code>
          {selection.goal_version_id ? (
            <>
              ; goal version <code>{selection.goal_version_id}</code>
            </>
          ) : null}
          .
        </p>
        <Table caption="Saved model assets">
          <thead>
            <tr>
              <th scope="col">Asset</th>
              <th scope="col">Annual mean log return</th>
              <th scope="col">Annual volatility</th>
              <th scope="col">Weight</th>
            </tr>
          </thead>
          <tbody>
            {assumptions.assets.map((asset) => (
              <tr key={asset.key}>
                <th scope="row">{asset.key}</th>
                <td>{asset.annual_mean_log_return}</td>
                <td>{asset.annual_volatility}</td>
                <td>{asset.weight}</td>
              </tr>
            ))}
          </tbody>
        </Table>
        <Table caption="Saved correlation matrix">
          <thead>
            <tr>
              <th scope="col">Asset</th>
              {assumptions.assets.map((asset) => (
                <th scope="col" key={asset.key}>
                  {asset.key}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {assumptions.correlation.map((row, i) => (
              <tr key={i}>
                <th scope="row">{assumptions.assets[i]?.key}</th>
                {row.map((cell, j) => (
                  <td key={j}>{cell}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </Table>
        <dl className={styles.context}>
          <dt>Annual inflation</dt>
          <dd>{assumptions.annual_inflation ?? "0"}</dd>
          <dt>Annual fee</dt>
          <dd>{assumptions.annual_fee ?? "0"}</dd>
          <dt>Annual modeled tax drag</dt>
          <dd>{assumptions.annual_tax_drag ?? "Not modeled"}</dd>
          <dt>Rebalancing</dt>
          <dd>{assumptions.rebalance ?? "none"}</dd>
          <dt>Base monthly contribution</dt>
          <dd>
            <ProjectionMoney value={selection.schedule.base_monthly} />
          </dd>
          <dt>Annual contribution growth</dt>
          <dd>{selection.schedule.annual_growth ?? "0"}</dd>
          <dt>Paused dates</dt>
          <dd>{selection.schedule.paused_dates?.join(", ") || "None"}</dd>
        </dl>
        {selection.schedule.entries?.length ? (
          <Table caption="Saved dated cash flows">
            <thead>
              <tr>
                <th scope="col">Key</th>
                <th scope="col">Date</th>
                <th scope="col">Kind</th>
                <th scope="col">Amount</th>
              </tr>
            </thead>
            <tbody>
              {selection.schedule.entries.map((entry) => (
                <tr key={entry.key}>
                  <th scope="row">{entry.key}</th>
                  <td>{entry.on}</td>
                  <td>{words(entry.kind)}</td>
                  <td>
                    <ProjectionMoney value={entry.value} />
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        ) : (
          <p>No additional dated cash flows.</p>
        )}
        {selection.sensitivity ? (
          <p>
            Sensitivity contribution delta:{" "}
            <ProjectionMoney value={selection.sensitivity.contribution_delta} />
            ; annual mean log return delta:{" "}
            {selection.sensitivity.annual_mean_log_delta}.
          </p>
        ) : (
          <p>Baseline only; no sensitivity variants selected.</p>
        )}
        {(assumptions.calibration_pins ?? []).map((pin) => (
          <p key={pin.subject_id}>
            Calibration pin <code>{pin.subject_id}</code> ·{" "}
            <code>{pin.content_digest}</code>
          </p>
        ))}
      </details>
      <details>
        <summary>Source evidence, warnings and calculation identity</summary>
        <p>
          Warnings: {context.warnings.items.map(words).join(", ") || "None"}.{" "}
          {context.warnings.omitted_count} additional warnings omitted from this
          preview.
        </p>
        <p>
          {context.source_evidence.omitted_count} additional source evidence
          entries omitted from this preview.
        </p>
        <ul>
          {context.source_evidence.items.map((source) => (
            <li key={`${source.role}:${source.subject_id}`}>
              {words(source.role)} · <code>{source.subject_id}</code> · quality{" "}
              {source.quality} · digest <code>{source.content_digest}</code>
              <ul>
                {source.source_reference_ids.items.map((id) => (
                  <li key={id}>
                    <code>{id}</code>
                  </li>
                ))}
              </ul>
              <p>
                {source.source_reference_ids.omitted_count} additional source
                references omitted.
              </p>
            </li>
          ))}
        </ul>
        <dl className={styles.context}>
          <dt>Result ID</dt>
          <dd>
            <code>{context.result_id}</code>
          </dd>
          <dt>Capture digest</dt>
          <dd>
            <code>{context.capture_digest}</code>
          </dd>
          <dt>Numerical input digest</dt>
          <dd>
            <code>{context.numerical_input_digest}</code>
          </dd>
          <dt>Saved result digest</dt>
          <dd>
            <code>{context.saved_result_digest}</code>
          </dd>
          <dt>Assumption version digest</dt>
          <dd>
            <code>{context.assumption_version_digest}</code>
          </dd>
          <dt>Goal version digest</dt>
          <dd>{context.goal_version_digest ?? "No goal pinned"}</dd>
          <dt>Method / version</dt>
          <dd>
            {context.method} / {context.method_version}
          </dd>
          <dt>Schema</dt>
          <dd>{context.schema_version}</dd>
          <dt>Numeric profile</dt>
          <dd>{context.numeric_profile}</dd>
          <dt>Sampler</dt>
          <dd>{context.sampler}</dd>
          <dt>Calendar rule</dt>
          <dd>{context.calendar_rule}</dd>
          <dt>Numerical zero pivots</dt>
          <dd>{context.numerical_zero_pivots.join(", ") || "None"}</dd>
        </dl>
      </details>
    </Surface>
  );
}
const pointFields = [
  ["nominal", "Nominal wealth"],
  ["real", "Real wealth"],
  ["contributions", "Cumulative contributions"],
  ["withdrawals_requested", "Requested withdrawals"],
  ["withdrawals_funded", "Funded withdrawals"],
  ["unpaid_withdrawals", "Unpaid withdrawals"],
  ["investment_effect", "Investment effect"],
  ["fees", "Cumulative fees"],
  ["tax_drag", "Modeled tax drag"],
  ["wealth_residual", "Wealth rounding residual"],
  ["allocation_residual", "Allocation rounding residual"],
  ["withdrawal_residual", "Withdrawal rounding residual"],
] as const;
export function ProjectionRetainedPoint({
  row,
}: Readonly<{ row: ProjectionPointRow }>) {
  return (
    <details className={styles.pointDetails}>
      <summary>
        Point {row.ordinal} · {words(row.variant)} · path {row.path_index} ·
        month {row.point.month} · {row.on}
      </summary>
      <p>
        Checkpoint {row.point_index + 1} of {row.path_point_count}; absolute
        path index {row.path_index}. First unpaid month:{" "}
        {row.first_unpaid_month ?? "None"}.
      </p>
      <dl className={styles.context}>
        {pointFields.map(([key, label]) => (
          <div key={key}>
            <dt>{label}</dt>
            <dd>
              <ProjectionMoney value={row.point[key]} />
            </dd>
          </div>
        ))}
        <dt>Funding failed</dt>
        <dd>{row.point.funding_failed ? "Yes" : "No"}</dd>
        <dt>Positive unpaid amount below rounding quantum</dt>
        <dd>{row.point.unpaid_positive_below_quantum ? "Yes" : "No"}</dd>
      </dl>
      <Table caption={`Asset amounts for retained point ${row.ordinal}`}>
        <thead>
          <tr>
            <th scope="col">Asset</th>
            <th scope="col">Saved amount</th>
          </tr>
        </thead>
        <tbody>
          {row.point.assets.map((asset) => (
            <tr key={asset.key}>
              <th scope="row">{asset.key}</th>
              <td>
                <ProjectionMoney value={asset.value} />
              </td>
            </tr>
          ))}
        </tbody>
      </Table>
    </details>
  );
}
export function ProjectionResults({
  value,
  query,
}: Readonly<{ value: ProjectionResultPage; query: ProjectionQuery }>) {
  const flows = [
    "contributions",
    "withdrawals_requested",
    "withdrawals_funded",
    "unpaid_withdrawals",
    "investment_effect",
    "fees",
    "tax_drag",
  ] as const;
  return (
    <>
      <ProjectionContext context={value.context} />
      {value.variants.map((variant) => (
        <Surface key={variant.variant} className={styles.surface}>
          <h2>{words(variant.variant)} · all saved paths</h2>
          <p>
            Summary distributions and cash-flow means use all{" "}
            {value.context.selection.paths} saved paths in this variant,
            independently of the point page. Quantiles use nearest ranks at the
            displayed probability ratios.
          </p>
          {variant.distributions.map((distribution) => (
            <details key={distribution.month}>
              <summary>
                Month {distribution.month} · {distribution.on} · nominal mean{" "}
                <ProjectionMoney value={distribution.nominal_mean} /> · real
                mean <ProjectionMoney value={distribution.real_mean} />
              </summary>
              <p>{distribution.funding_failed_paths} funding-failed paths.</p>
              <ProjectionQuantiles
                value={distribution.nominal}
                label={`Nominal wealth quantiles at month ${distribution.month}`}
              />
              <ProjectionQuantiles
                value={distribution.real}
                label={`Real wealth quantiles at month ${distribution.month}`}
              />
            </details>
          ))}
          <Histogram value={variant.nominal_histogram} basis="Nominal" />
          <Histogram value={variant.real_histogram} basis="Real" />
          <h3>Terminal cash flows across all saved paths</h3>
          {flows.map((key) => (
            <details key={key}>
              <summary>
                {words(key)} · mean{" "}
                <ProjectionMoney value={variant.cash_flows[key].mean} />
              </summary>
              <ProjectionQuantiles
                value={variant.cash_flows[key].quantiles}
                label={`${words(key)} terminal quantiles`}
              />
            </details>
          ))}
          <p>
            Funding-failed paths: {variant.cash_flows.funding_failed_paths};
            paths with positive unpaid money below the rounding quantum:{" "}
            {variant.cash_flows.unpaid_positive_below_quantum_paths}.
          </p>
          {variant.goal ? (
            <ProjectionGoalEstimate estimate={variant.goal} />
          ) : (
            <p>No goal version was pinned to this run.</p>
          )}
        </Surface>
      ))}
      <Surface className={styles.surface}>
        <h2>Complete retained point rows</h2>
        <p>
          Showing {value.points.items.length} points from absolute ordinal{" "}
          {value.points.start_ordinal}; {value.points.total} points across all
          retained paths and variants. Open a point for every saved financial
          amount. This page is a contiguous slice, not a sampled result.
        </p>
        {value.points.items.map((row) => (
          <ProjectionRetainedPoint key={row.ordinal} row={row} />
        ))}
        <nav
          aria-label="Retained projection point pages"
          className={styles.actions}
        >
          {query.point_cursor ? (
            <Link
              prefetch={false}
              href={projectionHref(query, { point_cursor: null })}
            >
              First points
            </Link>
          ) : null}
          {value.points.next_cursor ? (
            <Link
              prefetch={false}
              href={projectionHref(query, {
                point_cursor: value.points.next_cursor,
              })}
            >
              Next points
            </Link>
          ) : (
            <p>End of retained points.</p>
          )}
        </nav>
        <p>
          Presentation version {value.view_version}; page digest{" "}
          <code>{value.content_digest}</code>. The saved result digest above
          identifies the complete result.
        </p>
      </Surface>
    </>
  );
}
export function ProjectionGoalAnalysis({
  value,
}: Readonly<{ value: GoalAnalysisResponse }>) {
  if (value.availability !== "available" || !value.context)
    return (
      <Notice title="Goal analysis unavailable">
        {words(value.reason ?? "unavailable")}. No financial estimate is
        substituted.
      </Notice>
    );
  return (
    <>
      <ProjectionContext context={value.context} />
      {value.variants.map((variant) => (
        <Surface key={variant.variant}>
          <h2>{words(variant.variant)}</h2>
          <ProjectionGoalEstimate estimate={variant.estimate} />
          <ProjectionQuantiles
            value={variant.terminal}
            label="Saved goal-basis terminal quantiles"
          />
        </Surface>
      ))}
      <p>
        Goal view {value.view_version}; digest{" "}
        <code>{value.content_digest}</code>.
      </p>
    </>
  );
}
