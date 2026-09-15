import type { ReactNode } from "react";
import type {
  ScenarioMoneyView,
  ScenarioRatioMetric,
  ScenarioComponentView,
  ScenarioResultContextView,
  ScenarioRunResponse,
  ScenarioComparisonPage,
} from "@trading212/api-contracts";
import { Notice, Surface } from "@trading212/ui";
import { titleCase } from "../lib/format";
import { scenarioHref, type ScenarioQuery } from "../lib/scenario-query";
import Link from "./navigation-intent";
import {
  premiumScenarioReportSource,
  premiumReportSourceHref,
} from "../lib/premium-report-query";
import styles from "./scenario-workspace.module.css";

type Preview<T> = { items: readonly T[]; omitted_count: number };
export function ScenarioMoneyValue({
  metric,
}: Readonly<{ metric: ScenarioMoneyView }>) {
  return (
    <div className={styles.metric}>
      <span
        className={metric.value === null ? "metric-unavailable" : "numeric"}
      >
        {metric.value === null
          ? "Unavailable"
          : `${metric.value.amount} ${metric.value.currency}`}
      </span>
      <small>
        {titleCase(metric.quality)}
        {metric.reason ? ` · ${titleCase(metric.reason)}` : ""}
      </small>
      <small>Confidence: {metric.confidence ?? "Unavailable"}</small>
      <details>
        <summary>Value source references</summary>
        <References value={metric.source_reference_ids} />
      </details>
    </div>
  );
}
function Ratio({ metric }: Readonly<{ metric: ScenarioRatioMetric }>) {
  return (
    <span className={styles.metric}>
      <span className="numeric">{metric.value ?? "Unavailable"}</span>
      <small>
        {titleCase(metric.quality)}
        {metric.reason ? ` · ${titleCase(metric.reason)}` : ""}
      </small>
    </span>
  );
}
function PreviewList<T>({
  value,
  label,
  render,
}: Readonly<{
  value: Preview<T>;
  label: string;
  render: (item: T) => ReactNode;
}>) {
  return (
    <div className={styles.preview}>
      <p>
        {label}: {value.items.length} shown
        {value.omitted_count
          ? `; ${value.omitted_count} additional references retained`
          : ""}
        .
      </p>
      {value.items.length ? (
        <ul>
          {value.items.map((item, index) => (
            <li key={index}>{render(item)}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
function References({
  value,
  label = "Source references",
}: Readonly<{ value: Preview<string>; label?: string }>) {
  return (
    <PreviewList
      value={value}
      label={label}
      render={(item) => <code>{item}</code>}
    />
  );
}
function Table({
  label,
  children,
  layout = "summaryTable",
}: Readonly<{
  label: string;
  children: ReactNode;
  layout?: "summaryTable" | "effectsTable" | "componentsTable";
}>) {
  return (
    <div className="table-scroll" role="region" tabIndex={0} aria-label={label}>
      <table className={`data-table ${styles.table} ${styles[layout]}`}>
        <caption>{label}</caption>
        {children}
      </table>
    </div>
  );
}
function Diagnostics({
  context,
}: Readonly<{ context: ScenarioResultContextView }>) {
  return (
    <PreviewList
      value={context.diagnostics}
      label="Diagnostic preview"
      render={(item) => (
        <>
          {titleCase(item.reason)}
          {item.path_key ? <code> · {item.path_key}</code> : null}
          {item.upstream_xray_reason || item.upstream_historical_reason ? (
            <p>
              Upstream:{" "}
              {titleCase(
                item.upstream_xray_reason ??
                  item.upstream_historical_reason ??
                  "",
              )}
            </p>
          ) : null}
          <References value={item.source_reference_ids} />
          <References value={item.source_use_keys} label="Source uses" />
        </>
      )}
    />
  );
}
function Effects({
  value,
}: Readonly<{ value: ScenarioComponentView["effects"] }>) {
  return (
    <Table label="Scenario effect channels" layout="effectsTable">
      <thead>
        <tr>
          <th scope="col">Channel</th>
          <th scope="col">Simple effect ratio</th>
          <th scope="col">Monetary effect</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <th scope="row">Price</th>
          <td>
            <Ratio metric={value.price_ratio} />
          </td>
          <td>
            <ScenarioMoneyValue metric={value.price} />
          </td>
        </tr>
        <tr>
          <th scope="row">Rate / factor</th>
          <td>
            <Ratio metric={value.factor_ratio} />
          </td>
          <td>
            <ScenarioMoneyValue metric={value.factor} />
          </td>
        </tr>
        <tr>
          <th scope="row">FX</th>
          <td>
            <Ratio metric={value.fx_ratio} />
          </td>
          <td>
            <ScenarioMoneyValue metric={value.fx} />
          </td>
        </tr>
        <tr>
          <th scope="row">Interaction</th>
          <td>Defined by calculation mode</td>
          <td>
            <ScenarioMoneyValue metric={value.interaction} />
          </td>
        </tr>
      </tbody>
    </Table>
  );
}

export function ScenarioContext({
  context,
  label = "Scenario summary",
}: Readonly<{ context: ScenarioResultContextView; label?: string }>) {
  const summary = context.summary;
  const metrics = [
    ["Terminal pre-value", summary.terminal_pre_value],
    ["Post-value", summary.post_value],
    ["Impact", summary.impact],
    ["Covered pre-value", summary.covered_pre_value],
    ["Uncovered pre-value", summary.uncovered_pre_value],
    ["Excluded pre-value", summary.excluded_pre_value],
    ["Covered post-value", summary.covered_post_value],
    ["Excluded post-value", summary.excluded_post_value],
    [
      "Provably unchanged uncovered value",
      summary.provably_unchanged_uncovered_value,
    ],
    ["Output rounding residual", summary.rounding_residual],
    ["Component sum residual", summary.component_sum_residual],
    ["Upstream portfolio value", context.upstream_portfolio_value],
    ["Upstream partition difference", context.upstream_partition_difference],
  ] as const;
  return (
    <Surface className={styles.surface}>
      <h2>{label}</h2>
      <p>
        {context.definition.name} · {titleCase(context.definition.mode)} ·
        Valuation {context.valuation_at}
      </p>
      <p>
        {summary.covered_count} covered, {summary.uncovered_count} uncovered and{" "}
        {summary.excluded_count} excluded terminal components. Missing
        pre-value: {summary.missing_pre_value_count}; uncertain money:{" "}
        {summary.uncertain_money_count}.
      </p>
      <p>
        Subtotals describe the known partition. An unavailable full value is
        never replaced with a subtotal.
      </p>
      <Table label={`${label} values`}>
        <thead>
          <tr>
            <th scope="col">Measure</th>
            <th scope="col">Exact value and quality</th>
          </tr>
        </thead>
        <tbody>
          {metrics.map(([name, value]) => (
            <tr key={name}>
              <th scope="row">{name}</th>
              <td>
                <ScenarioMoneyValue metric={value} />
              </td>
            </tr>
          ))}
        </tbody>
      </Table>
      <details>
        <summary>Channels, assumptions and retained source context</summary>
        <Effects value={summary.effects} />
        <dl className={styles.context}>
          <dt>Run</dt>
          <dd>{context.run_id}</dd>
          <dt>Saved result</dt>
          <dd>{context.result_id}</dd>
          <dt>Saved result digest</dt>
          <dd>{context.saved_result_digest}</dd>
          <dt>Input digest</dt>
          <dd>{context.input_digest}</dd>
          <dt>Snapshot</dt>
          <dd>{context.pins.portfolio_snapshot_id}</dd>
          <dt>X-ray run</dt>
          <dd>{context.pins.xray_run_id}</dd>
          <dt>X-ray input digest</dt>
          <dd>{context.pins.xray_input_digest}</dd>
          <dt>X-ray result digest</dt>
          <dd>{context.pins.xray_result_digest}</dd>
          <dt>Source cutoff</dt>
          <dd>{context.pins.source_cutoff_at}</dd>
          <dt>Reporting currency</dt>
          <dd>{context.pins.reporting_currency}</dd>
          <dt>Method / schema</dt>
          <dd>
            {context.method_version} / {context.schema_version}
          </dd>
          <dt>Numerical profile</dt>
          <dd>{context.numerical_profile}</dd>
          <dt>Sensitivity source rows</dt>
          <dd>{context.sensitivity_source_row_count}</dd>
        </dl>
        <h3>Assumptions</h3>
        <ul>
          {context.assumptions.map((item) => (
            <li key={item}>{titleCase(item)}</li>
          ))}
        </ul>
        <References
          value={context.upstream_residual_keys}
          label="Upstream residual references"
        />
        <Diagnostics context={context} />
        {context.replay ? (
          <section>
            <h3>Historical replay context</h3>
            <dl className={styles.context}>
              <dt>Historical capture</dt>
              <dd>{context.replay.selection.historical_input_snapshot_id}</dd>
              <dt>Market window</dt>
              <dd>
                {context.replay.window.start_date} –{" "}
                {context.replay.window.end_date}
              </dd>
              <dt>Market knowledge cutoff</dt>
              <dd>{context.replay.selection.market_knowledge_cutoff_at}</dd>
              <dt>Holdings / knowledge basis</dt>
              <dd>
                {titleCase(context.replay.selection.holdings_basis)} /{" "}
                {titleCase(context.replay.selection.knowledge_basis)}
              </dd>
              <dt>Holdings evidence / knowledge</dt>
              <dd>
                {context.replay.holdings_evidence_at} /{" "}
                {context.replay.holdings_knowledge_cutoff_at}
              </dd>
              <dt>Availability / quality</dt>
              <dd>
                {context.replay.availability} / {context.replay.quality}
              </dd>
              <dt>Source uses / conversions</dt>
              <dd>
                {context.replay.source_use_count} /{" "}
                {context.replay.conversion_count}
              </dd>
            </dl>
            <p>
              This is a counterfactual replay of saved holdings. Historical gaps
              and unavailable currency decomposition remain explicit.
            </p>
            <Table label="Historical replay coverage">
              <thead>
                <tr>
                  <th scope="col">Measure</th>
                  <th scope="col">Available / expected</th>
                  <th scope="col">Completeness</th>
                  <th scope="col">Reasons</th>
                </tr>
              </thead>
              <tbody>
                {context.replay.coverage.measures.map((item) => (
                  <tr key={item.key}>
                    <th scope="row">{titleCase(item.key)}</th>
                    <td>
                      {item.available_count} / {item.expected_count}
                    </td>
                    <td>{item.complete ? "Complete" : "Incomplete"}</td>
                    <td>
                      {(item.reasons ?? []).map(titleCase).join(", ") ||
                        "None recorded"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
            <p>
              Reconstruction: {titleCase(context.replay.reconstruction)}. Replay
              assumptions:{" "}
              {context.replay.assumptions.map(titleCase).join(", ")}.
            </p>
            <References
              value={context.replay.source_reference_ids}
              label="Historical source references"
            />
            <PreviewList
              value={context.replay.warnings}
              label="Historical warning preview"
              render={(item) => (
                <>
                  {titleCase(item.reason_code)}
                  <References value={item.reference_ids} />
                </>
              )}
            />
          </section>
        ) : null}
      </details>
    </Surface>
  );
}

function ComponentProof({ value }: Readonly<{ value: ScenarioComponentView }>) {
  const exposure = value.exposure;
  return (
    <details>
      <summary>Identity, effects and source proof</summary>
      <dl className={styles.context}>
        <dt>Root</dt>
        <dd>
          {exposure.root_kind}: {exposure.root_key}
        </dd>
        <dt>Instrument</dt>
        <dd>
          {exposure.instrument.subject_id ??
            titleCase(exposure.instrument.state)}
          {exposure.instrument.reason
            ? ` · ${titleCase(exposure.instrument.reason)}`
            : ""}
        </dd>
        <dt>Entity</dt>
        <dd>
          {exposure.entity.subject_id ?? titleCase(exposure.entity.state)}
          {exposure.entity.reason
            ? ` · ${titleCase(exposure.entity.reason)}`
            : ""}
        </dd>
        <dt>Economic currency</dt>
        <dd>
          {exposure.economic_currency.currency ?? "Unavailable"} ·{" "}
          {titleCase(exposure.economic_currency.basis)}
          {exposure.economic_currency.reason
            ? ` · ${titleCase(exposure.economic_currency.reason)}`
            : ""}
        </dd>
        <dt>Pre-value confidence</dt>
        <dd>{exposure.confidence ?? "Unavailable"}</dd>
        <dt>Money basis</dt>
        <dd>{titleCase(value.money_basis)}</dd>
        <dt>Price rule</dt>
        <dd>{value.winning_price_rule_key ?? "No selected price rule"}</dd>
        <dt>Rounding residual</dt>
        <dd>
          <ScenarioMoneyValue metric={value.rounding_residual} />
        </dd>
      </dl>
      {[exposure.sector, exposure.region].map((item) => (
        <div key={item.dimension}>
          <h4>{titleCase(item.dimension)}</h4>
          <p>
            {item.bucket_key ?? titleCase(item.state)} ·{" "}
            {item.taxonomy_id ?? "No taxonomy"} ·{" "}
            {item.taxonomy_version ?? "No taxonomy version"}
            {item.reason ? ` · ${titleCase(item.reason)}` : ""}
          </p>
          <References value={item.source_reference_ids} />
          <References
            value={item.evidence_ids}
            label="Classification evidence"
          />
        </div>
      ))}
      <References value={exposure.source_reference_ids} />
      <References
        value={exposure.instrument.identity_decision_ids}
        label="Instrument identity decisions"
      />
      <References
        value={exposure.entity.identity_decision_ids}
        label="Entity identity decisions"
      />
      <References
        value={exposure.economic_currency.source_reference_ids}
        label="Economic currency sources"
      />
      <Effects value={value.effects} />
      <h4>Exclusion matches</h4>
      {value.matching_exclusion_keys.length ? (
        <ul>
          {value.matching_exclusion_keys.map((key) => (
            <li key={key}>
              <code>{key}</code>
            </li>
          ))}
        </ul>
      ) : (
        <p>None recorded.</p>
      )}
      <h4>Uncertain rule matches</h4>
      {value.uncertain_rule_keys.length ? (
        <ul>
          {value.uncertain_rule_keys.map((key) => (
            <li key={key}>
              <code>{key}</code>
            </li>
          ))}
        </ul>
      ) : (
        <p>None recorded.</p>
      )}
      {value.sensitivity_uses.map((use) => (
        <section key={use.rule_key}>
          <h4>{titleCase(use.driver_kind)} sensitivity</h4>
          <dl className={styles.context}>
            <dt>Source version</dt>
            <dd>{use.version_id}</dd>
            <dt>Driver definition</dt>
            <dd>{use.driver_definition_version_id}</dd>
            <dt>Selected observation</dt>
            <dd>{use.observation_id ?? "Unavailable"}</dd>
            <dt>Coefficient</dt>
            <dd>{use.coefficient ?? "Unavailable"}</dd>
            <dt>Shock size</dt>
            <dd>
              {use.shock_size} · {titleCase(use.shock_unit)}
            </dd>
            <dt>Effect ratio</dt>
            <dd>
              <Ratio metric={use.effect_ratio} />
            </dd>
            <dt>Reason</dt>
            <dd>{use.reason ? titleCase(use.reason) : "Resolved"}</dd>
          </dl>
          <References
            value={use.candidate_observation_ids}
            label="Candidate observation preview"
          />
          <References
            value={use.driver_evidence_reference_ids}
            label="Driver evidence"
          />
        </section>
      ))}
      {value.replay_change ? (
        <section>
          <h4>Replay change</h4>
          <p>Basis: {titleCase(value.replay_change.basis)}</p>
          <dl className={styles.context}>
            <dt>Local return</dt>
            <dd>
              <Ratio metric={value.replay_change.local_return} />
            </dd>
            <dt>FX return</dt>
            <dd>
              <Ratio metric={value.replay_change.fx_return} />
            </dd>
            <dt>Reporting return</dt>
            <dd>
              <Ratio metric={value.replay_change.reporting_return} />
            </dd>
          </dl>
          <References
            value={value.replay_change.source_use_keys}
            label="Historical source uses"
          />
          <References
            value={value.replay_change.conversion_keys}
            label="FX conversions"
          />
        </section>
      ) : null}
      <References value={value.diagnostic_keys} label="Diagnostic keys" />
    </details>
  );
}

function ComponentPages({
  query,
  page,
}: Readonly<{
  query: ScenarioQuery;
  page: {
    items: readonly unknown[];
    total: number;
    start_ordinal: number;
    next_cursor: string | null;
  };
}>) {
  return (
    <nav
      className="collection-pagination"
      aria-label="Scenario component pages"
    >
      <p>
        {page.items.length
          ? `${page.start_ordinal + 1}–${page.start_ordinal + page.items.length}`
          : "0"}{" "}
        of {page.total} retained components.
      </p>
      {page.next_cursor ? (
        <Link
          prefetch={false}
          href={scenarioHref(query, { component_cursor: page.next_cursor })}
        >
          Next components
        </Link>
      ) : null}
      {query.component_cursor ? (
        <Link
          prefetch={false}
          href={scenarioHref(query, { component_cursor: null })}
        >
          First components
        </Link>
      ) : null}
    </nav>
  );
}

export function ScenarioResults({
  run,
  query,
}: Readonly<{ run: ScenarioRunResponse; query: ScenarioQuery }>) {
  if (!run.result)
    return (
      <Notice title="Scenario result unavailable">
        Result state: {titleCase(run.result_availability)}.{" "}
        {run.failure_code
          ? titleCase(run.failure_code)
          : "A complete financial result is not available for this run."}
      </Notice>
    );
  const result = run.result;
  const reportSource = query.account
    ? premiumScenarioReportSource(run, query.account)
    : null;
  return (
    <>
      {reportSource ? (
        <Link prefetch={false} href={premiumReportSourceHref(reportSource)}>
          Create a report from this saved scenario
        </Link>
      ) : null}
      <ScenarioContext context={result.context} />
      <Surface className={styles.surface}>
        <h2>Terminal component values</h2>
        <Table
          label="Saved scenario terminal components"
          layout="componentsTable"
        >
          <thead>
            <tr>
              <th scope="col">Terminal path / partition</th>
              <th scope="col">Pre-value</th>
              <th scope="col">Post-value</th>
              <th scope="col">Impact</th>
              <th scope="col">Evidence</th>
            </tr>
          </thead>
          <tbody>
            {result.components.items.map((item) => (
              <tr key={item.exposure.path_key}>
                <th scope="row">
                  <code>{item.exposure.path_key}</code>
                  <p>{titleCase(item.partition)}</p>
                </th>
                <td>
                  <ScenarioMoneyValue metric={item.exposure.pre_value} />
                </td>
                <td>
                  <ScenarioMoneyValue metric={item.post_value} />
                </td>
                <td>
                  <ScenarioMoneyValue metric={item.impact} />
                </td>
                <td>
                  <ComponentProof value={item} />
                </td>
              </tr>
            ))}
          </tbody>
        </Table>
        <ComponentPages query={query} page={result.components} />
        <p>
          Public view {result.view_version}. Page digest:{" "}
          <code>{result.content_digest}</code>. Source previews state how many
          retained references are omitted from this view.
        </p>
      </Surface>
    </>
  );
}

export function ScenarioComparison({
  value,
  query,
}: Readonly<{ value: ScenarioComparisonPage; query: ScenarioQuery }>) {
  return (
    <>
      {!value.compatible ? (
        <Notice title="These saved results have incompatible bases">
          <p>
            Both saved sides remain visible. Monetary differences are
            unavailable.
          </p>
          <ul>
            {value.mismatches.map((item) => (
              <li key={item.field}>
                {titleCase(item.field)}: <code>{item.left}</code> →{" "}
                <code>{item.right}</code>
              </li>
            ))}
          </ul>
        </Notice>
      ) : (
        <Notice title="Compatible saved bases">
          Differences show the second selected result minus the first.
        </Notice>
      )}
      <div className={styles.comparison}>
        <ScenarioContext context={value.before} label="First saved result" />
        <ScenarioContext context={value.after} label="Second saved result" />
      </div>
      <Surface className={styles.surface}>
        <h2>Saved result differences</h2>
        <Table label="Scenario comparison totals" layout="effectsTable">
          <thead>
            <tr>
              <th scope="col">Measure</th>
              <th scope="col">First</th>
              <th scope="col">Second</th>
              <th scope="col">Difference</th>
            </tr>
          </thead>
          <tbody>
            {(
              [
                ["Post-value", value.post_value],
                ["Impact", value.impact],
              ] as const
            ).map(([label, delta]) => (
              <tr key={label}>
                <th scope="row">{label}</th>
                <td>
                  <ScenarioMoneyValue metric={delta.before} />
                </td>
                <td>
                  <ScenarioMoneyValue metric={delta.after} />
                </td>
                <td>
                  <ScenarioMoneyValue metric={delta.difference} />
                </td>
              </tr>
            ))}
          </tbody>
        </Table>
        <Table
          label="Scenario comparison terminal components"
          layout="componentsTable"
        >
          <thead>
            <tr>
              <th scope="col">Terminal path</th>
              <th scope="col">First post-value</th>
              <th scope="col">Second post-value</th>
              <th scope="col">Post-value difference</th>
              <th scope="col">Impact difference</th>
              <th scope="col">Retained sides</th>
            </tr>
          </thead>
          <tbody>
            {value.components.items.map((item) => (
              <tr key={`${item.root_key}:${item.path_key}`}>
                <th scope="row">
                  <code>{item.path_key}</code>
                </th>
                <td>
                  <ScenarioMoneyValue metric={item.post_value.before} />
                </td>
                <td>
                  <ScenarioMoneyValue metric={item.post_value.after} />
                </td>
                <td>
                  <ScenarioMoneyValue metric={item.post_value.difference} />
                </td>
                <td>
                  <ScenarioMoneyValue metric={item.impact.difference} />
                </td>
                <td>
                  {item.before ? (
                    <details>
                      <summary>
                        First component · {item.before.partition}
                      </summary>
                      <ComponentProof value={item.before} />
                    </details>
                  ) : (
                    <p>Absent from first saved result.</p>
                  )}
                  {item.after ? (
                    <details>
                      <summary>
                        Second component · {item.after.partition}
                      </summary>
                      <ComponentProof value={item.after} />
                    </details>
                  ) : (
                    <p>Absent from second saved result.</p>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </Table>
        <ComponentPages query={query} page={value.components} />
        <p>
          Comparison page digest: <code>{value.content_digest}</code>
        </p>
      </Surface>
    </>
  );
}
