"use client";

import { useState } from "react";
import type {
  RiskRunResponse,
  RiskResultResponse,
} from "@trading212/api-contracts";
import { Button, Notice, StatusPill, Surface } from "@trading212/ui";
import { HistoricalChart } from "./historical-chart";
import { HistoricalValue } from "./historical-results";
import {
  formatHistoricalDecimal,
  formatHistoricalPercent,
} from "../lib/historical-format";
import { formatDateTime, titleCase } from "../lib/format";

type Metric = RiskResultResponse["observed"]["volatility_annualized"];
export function RiskValue({
  metric,
  unit = "ratio",
}: Readonly<{ metric: Metric; unit?: "ratio" | "decimal" }>) {
  return (
    <span className="historical-value" title={metric.value ?? undefined}>
      <span
        className={metric.value === null ? "metric-unavailable" : "numeric"}
      >
        {metric.value === null
          ? "Unavailable"
          : unit === "ratio"
            ? formatHistoricalPercent(metric.value)
            : formatHistoricalDecimal(metric.value)}
      </span>
      {metric.reason ? <small>{titleCase(metric.reason)}</small> : null}
    </span>
  );
}

function RiskMatrix({
  data,
  labels,
}: Readonly<{
  data: RiskResultResponse;
  labels: Readonly<Record<string, string>>;
}>) {
  const [kind, setKind] = useState<
    "correlation" | "covariance_periodic" | "regularized_covariance_periodic"
  >("correlation");
  const matrix = data.matrix;
  return (
    <Surface>
      <h2>Asset matrix</h2>
      <p>
        {matrix.used_intervals} complete-case intervals used;{" "}
        {matrix.omitted_intervals} omitted of {matrix.requested_intervals}{" "}
        requested. Missing intervals are not filled.
      </p>
      <label>
        Matrix measure{" "}
        <select
          value={kind}
          onChange={(event) => setKind(event.target.value as typeof kind)}
        >
          <option value="correlation">Correlation</option>
          <option value="covariance_periodic">Periodic covariance</option>
          <option value="regularized_covariance_periodic">
            Explicitly regularized covariance
          </option>
        </select>
      </label>
      {!matrix.keys.length ? (
        <Notice title="No asset universe selected">
          Observed portfolio statistics remain separate from asset-matrix and
          modeled-portfolio risk.
        </Notice>
      ) : (
        <div
          className="table-scroll"
          role="region"
          tabIndex={0}
          aria-label="Risk asset matrix"
        >
          <table className="data-table">
            <caption>
              {titleCase(kind)} · {data.definition.frequency} intervals
            </caption>
            <thead>
              <tr>
                <th scope="col">Asset</th>
                {matrix.keys.map((key) => (
                  <th scope="col" key={key} title={key}>
                    {labels[key] ?? key}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {matrix.keys.map((key, row) => (
                <tr key={key}>
                  <th scope="row" title={key}>
                    {labels[key] ?? key}
                  </th>
                  {matrix[kind][row].map((metric, column) => (
                    <td key={matrix.keys[column]}>
                      <RiskValue metric={metric} unit="decimal" />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="muted">
        Sample covariance uses {data.covariance_degrees_of_freedom} degree of
        freedom correction. Regularization:{" "}
        {titleCase(data.definition.regularization ?? "unavailable")}; shrinkage{" "}
        {data.definition.shrinkage}. Numerical zero pivots:{" "}
        {matrix.numerical_zero_pivots.length}.
      </p>
    </Surface>
  );
}

function RollingRisk({ data }: Readonly<{ data: RiskResultResponse }>) {
  const [page, setPage] = useState(0);
  const points = data.observed.rolling;
  const rows = points.slice(page * 50, (page + 1) * 50);
  return (
    <Surface>
      <h2>Rolling annualized volatility</h2>
      <p>
        Window: {data.definition.rolling_window} {data.definition.frequency}{" "}
        observations. Gaps remain visible.
      </p>
      <HistoricalChart
        label="Rolling estimates"
        rows={points.map((point) => ({
          date: point.end_at.slice(0, 10),
          values: { volatility: point.volatility.value },
        }))}
        series={[{ key: "volatility", label: "Volatility", color: "#345a95" }]}
        unit="ratio"
        ratioLabel="annualized volatility"
        tableId="risk-rolling-table"
      />
      <div
        className="table-scroll"
        role="region"
        tabIndex={0}
        aria-label="Rolling volatility table"
      >
        <table id="risk-rolling-table" className="data-table">
          <caption>
            Canonical rolling estimates · {rows.length} of {points.length} rows
          </caption>
          <thead>
            <tr>
              <th scope="col">Window end</th>
              <th scope="col">Observations</th>
              <th scope="col">Annualized volatility</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((point) => (
              <tr key={point.end_at}>
                <th scope="row">{formatDateTime(point.end_at)}</th>
                <td>{point.observations}</td>
                <td>
                  <RiskValue metric={point.volatility} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <nav className="form-actions" aria-label="Rolling risk pagination">
        <Button
          variant="secondary"
          disabled={page === 0}
          onClick={() => setPage(page - 1)}
        >
          Previous estimates
        </Button>
        <Button
          variant="secondary"
          disabled={(page + 1) * 50 >= points.length}
          onClick={() => setPage(page + 1)}
        >
          Next estimates
        </Button>
      </nav>
    </Surface>
  );
}

export function RiskResults({
  run,
  labels = {},
}: Readonly<{
  run: RiskRunResponse;
  labels?: Readonly<Record<string, string>>;
}>) {
  const data = run.result;
  if (!data)
    return (
      <Notice
        title={`Risk result: ${titleCase(run.result_availability)}`}
        tone={run.state === "failed" ? "warning" : "neutral"}
      >
        Job state: {titleCase(run.state)}.{" "}
        {run.failure_code
          ? titleCase(run.failure_code)
          : "No financial result is available in this response."}
      </Notice>
    );
  const observed = data.observed;
  const context = data.historical_context;
  const cards: { label: string; metric: Metric; unit?: "ratio" | "decimal" }[] =
    [
      {
        label: "Annualized volatility",
        metric: observed.volatility_annualized,
      },
      { label: "Downside deviation", metric: observed.downside_annualized },
      { label: "Periodic mean return", metric: observed.mean_periodic_return },
      { label: "Periodic volatility", metric: observed.volatility_periodic },
      { label: "Benchmark beta", metric: observed.beta, unit: "decimal" },
      { label: "Annualized alpha", metric: observed.alpha_annualized },
    ];
  return (
    <div className="page-stack historical-page">
      <Surface>
        <div className="section-heading">
          <h2>Observed historical estimates</h2>
          <StatusPill
            tone={context.quality === "fresh" ? "positive" : "warning"}
          >
            {titleCase(context.quality)}
          </StatusPill>
        </div>
        <p>
          {observed.used_observations} observations used of{" "}
          {observed.requested_observations}; {observed.omitted_observations}{" "}
          omitted; {observed.outlier_observations} outliers retained. Benchmark
          pairs: {observed.benchmark_pairs}.
        </p>
        <div className="historical-metrics">
          {cards.map((card) => (
            <div className="metric-card" key={card.label}>
              <span className="metric-card__label">{card.label}</span>
              <div className="metric-card__value">
                <RiskValue metric={card.metric} unit={card.unit} />
              </div>
            </div>
          ))}
          <div className="metric-card">
            <span className="metric-card__label">
              Historical maximum drawdown
            </span>
            <div className="metric-card__value">
              <HistoricalValue metric={data.maximum_drawdown} />
            </div>
          </div>
        </div>
      </Surface>
      <RollingRisk key={`rolling:${run.id}`} data={data} />
      <Surface>
        <h2>Tail loss estimates</h2>
        <p>
          Positive values mean loss; negative values mean gain. Historical
          estimates use overlapping compounded windows. The parametric model
          assumes independent identically distributed log returns.
        </p>
        <div
          className="table-scroll"
          role="region"
          tabIndex={0}
          aria-label="Tail risk estimates"
        >
          <table className="data-table">
            <caption>Historical and parametric tail estimates</caption>
            <thead>
              <tr>
                <th scope="col">Method</th>
                <th scope="col">Confidence / horizon</th>
                <th scope="col">VaR</th>
                <th scope="col">Expected Shortfall</th>
                <th scope="col">Observations / tail mass</th>
              </tr>
            </thead>
            <tbody>
              {[data.historical_tail, data.parametric_tail].map((tail) => (
                <tr key={tail.method}>
                  <th scope="row">{titleCase(tail.method)}</th>
                  <td>
                    {formatHistoricalPercent(tail.confidence)} / {tail.horizon}{" "}
                    {data.definition.frequency} periods
                  </td>
                  <td>
                    <RiskValue metric={tail.value_at_risk} />
                  </td>
                  <td>
                    <RiskValue metric={tail.expected_shortfall} />
                  </td>
                  <td>
                    {tail.observations} / {tail.tail_mass ?? "Not applicable"}
                    <small>{titleCase(tail.quantile)}</small>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Surface>
      <RiskMatrix key={`matrix:${run.id}`} data={data} labels={labels} />
      <Surface>
        <h2>Modeled risk at current weights</h2>
        <p>
          This estimate applies historical covariance to the selected
          valuation's weights. It is separate from the observed historical
          portfolio path.
        </p>
        <dl className="detail-list">
          <div>
            <dt>Covered universe</dt>
            <dd>
              <RiskValue metric={data.modeled.coverage} />
            </dd>
          </div>
          <div>
            <dt>Annualized volatility</dt>
            <dd>
              <RiskValue metric={data.modeled.volatility_annualized} />
            </dd>
          </div>
          <div>
            <dt>Diversification ratio</dt>
            <dd>
              <RiskValue
                metric={data.modeled.diversification_ratio}
                unit="decimal"
              />
            </dd>
          </div>
        </dl>
        {!data.modeled.complete_universe ? (
          <Notice title="Incomplete modeled universe" tone="warning">
            Uncovered positions and cash are not assigned zero risk or silently
            renormalized.
          </Notice>
        ) : null}
        <div
          className="table-scroll"
          role="region"
          tabIndex={0}
          aria-label="Risk contributions"
        >
          <table className="data-table">
            <caption>Modeled current-weight risk contributions</caption>
            <thead>
              <tr>
                <th scope="col">Asset</th>
                <th scope="col">Weight</th>
                <th scope="col">Marginal risk</th>
                <th scope="col">Component risk</th>
              </tr>
            </thead>
            <tbody>
              {data.modeled.components.map((row) => (
                <tr key={row.instrument_id}>
                  <th scope="row">
                    {labels[row.instrument_id] ?? row.instrument_id}
                  </th>
                  <td>
                    <RiskValue metric={row.weight} />
                  </td>
                  <td>
                    <RiskValue metric={row.marginal_annualized} />
                  </td>
                  <td>
                    <RiskValue metric={row.component_annualized} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p>
          Component sum: <RiskValue metric={data.modeled.component_sum} />.
          Display residual:{" "}
          <RiskValue metric={data.modeled.component_display_residual} />. Weight
          display residual:{" "}
          <RiskValue metric={data.modeled.weight_display_residual} />.
        </p>
        <p>
          Modeled valuation:{" "}
          {data.modeled_valuation_at
            ? formatDateTime(data.modeled_valuation_at)
            : "Unavailable"}
          .
        </p>
      </Surface>
      <Surface>
        <h2>Economic issuer concentration</h2>
        <StatusPill
          tone={data.concentration.lower_bound ? "warning" : "neutral"}
        >
          {titleCase(data.concentration.quality)}
        </StatusPill>
        <p>
          {data.concentration.hhi.value === null
            ? "No covered issuer concentration estimate is available for these inputs. See the metric reasons below."
            : data.concentration.lower_bound
              ? "Known issuer contribution only: HHI is a lower bound."
              : "The canonical X-ray issuer partition determines concentration."}{" "}
          Wrappers and constituents are not counted twice.
        </p>
        <dl className="detail-list">
          <div>
            <dt>HHI</dt>
            <dd>
              <RiskValue metric={data.concentration.hhi} unit="decimal" />
            </dd>
          </div>
          <div>
            <dt>Effective holdings</dt>
            <dd>
              <RiskValue
                metric={data.concentration.effective_holdings}
                unit="decimal"
              />
            </dd>
          </div>
          <div>
            <dt>Known issuer weight</dt>
            <dd>
              <RiskValue metric={data.concentration.company_known_weight} />
            </dd>
          </div>
          <div>
            <dt>Cash</dt>
            <dd>
              <RiskValue metric={data.concentration.cash_weight} />
            </dd>
          </div>
          <div>
            <dt>Unresolved</dt>
            <dd>
              <RiskValue metric={data.concentration.unresolved_weight} />
            </dd>
          </div>
        </dl>
      </Surface>
      <Surface>
        <h2>Assumptions, sources and reproducibility</h2>
        <p>
          {data.definition.name} · {data.definition.frequency}{" "}
          {data.definition.return_kind} returns · {data.annualization_factor}{" "}
          periods per year.
        </p>
        <p>
          Calendar: {data.definition.calendar_id} /{" "}
          {data.definition.calendar_version}. Annual risk-free rate:{" "}
          {formatHistoricalPercent(data.definition.annual_risk_free ?? null)}.
          Annual minimum acceptable return:{" "}
          {formatHistoricalPercent(
            data.definition.annual_minimum_acceptable_return ?? null,
          )}
          .
        </p>
        <p>
          Window: {context.window.start_date} – {context.window.end_date};{" "}
          {context.window.reporting_currency}. Source cutoff:{" "}
          {formatDateTime(context.window.source_cutoff_at)}.{" "}
          {titleCase(context.window.knowledge_policy)} ·{" "}
          {titleCase(context.window.coverage_policy)}.
        </p>
        <p>
          Method {data.method_version}; schema {data.schema_version}; numerical
          profile {data.numerical_profile}. Finite-precision estimates retain
          their declared rounding and unavailable states.
        </p>
        <details>
          <summary>Canonical identity and source evidence</summary>
          <p className="risk-digest">Result digest: {data.content_digest}</p>
          <p className="risk-digest">Input digest: {run.input_digest}</p>
          <p>
            {context.sources.length} source references shown;{" "}
            {data.omitted_sources} omitted. {context.warnings.length} warnings
            shown; {data.omitted_warnings} omitted.
          </p>
          <ul className="historical-source-list">
            {context.sources.map((source) => (
              <li key={`${source.kind}:${source.id}`}>
                {titleCase(source.kind)} · {source.id} ·{" "}
                {formatDateTime(source.effective_at)}
              </li>
            ))}
          </ul>
          <ul>
            {context.warnings.map((warning, index) => (
              <li key={index}>{titleCase(warning.reason_code)}</li>
            ))}
          </ul>
        </details>
      </Surface>
    </div>
  );
}
