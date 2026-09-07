import Link from "next/link";
import { Notice, StatusPill, Surface } from "@trading212/ui";
import type {
  AttributionSummaryResponse,
  BenchmarkComparisonResponse,
  CashFlowIntelligenceResponse,
  CurrencyCashFlowTotals,
  CurrencyIncomeTotals,
  DividendIntelligenceResponse,
  HistoricalCashFlowPoint,
  HistoricalBenchmarkPeriodReturn,
  HistoricalMoneyMetric,
  HistoricalPeriodReturn,
  HistoricalRatioMetric,
  HistoricalRunContext,
  PerformanceMetrics,
  PerformancePoint,
} from "@trading212/api-contracts";
import { formatDateTime, titleCase } from "../lib/format";
import { HistoricalChart } from "./historical-chart";
import {
  formatHistoricalDecimal,
  formatHistoricalPercent,
} from "../lib/historical-format";

type HistoricalMetric = HistoricalMoneyMetric | HistoricalRatioMetric;

export function HistoricalValue({
  metric,
  unit = "ratio",
}: Readonly<{ metric: HistoricalMetric; unit?: "ratio" | "multiple" }>) {
  const value = metric.value;
  const display =
    value === null
      ? "Unavailable"
      : typeof value === "string"
        ? unit === "multiple"
          ? `${formatHistoricalDecimal(value)}×`
          : formatHistoricalPercent(value)
        : `${formatHistoricalDecimal(value.amount, 2)} ${value.currency}`;
  const exact =
    value === null
      ? undefined
      : typeof value === "string"
        ? value
        : `${value.amount} ${value.currency}`;
  return (
    <span className="historical-value" title={exact}>
      <span className={value === null ? "metric-unavailable" : "numeric"}>
        {display}
      </span>
      {metric.availability === "partial" ? <small>Known subtotal</small> : null}
      {metric.reason_code ? (
        <small>{titleCase(metric.reason_code)}</small>
      ) : null}
    </span>
  );
}

export function HistoricalCards({
  cards,
}: Readonly<{
  cards: readonly { label: string; metric: HistoricalMetric; note?: string }[];
}>) {
  return (
    <div className="historical-metrics">
      {cards.map(({ label, metric, note }) => (
        <div className="metric-card" key={label}>
          <span className="metric-card__label">{label}</span>
          <div className="metric-card__value">
            <HistoricalValue metric={metric} />
          </div>
          {note ? <small className="muted">{note}</small> : null}
        </div>
      ))}
    </div>
  );
}

export function HistoricalContextDetails({
  context,
  replayHref,
}: Readonly<{ context: HistoricalRunContext; replayHref?: string }>) {
  const warning =
    context.quality !== "fresh" || context.availability !== "available";
  const sourceKinds: Readonly<Record<string, string>> = {
    price_snapshot: "price",
    fx_snapshot: "fx",
    provider_benchmark_snapshot: "benchmark",
  };
  return (
    <Surface className="historical-context">
      <div className="section-heading">
        <h2>Quality and methodology</h2>
        <StatusPill tone={warning ? "warning" : "positive"}>
          {titleCase(context.quality)} · {titleCase(context.availability)}
        </StatusPill>
      </div>
      <p>
        {context.method.name} {context.method.version} ·{" "}
        {context.reconstruction === "restated"
          ? "Restated with knowledge available at the selected cutoff"
          : "Evidence known at each historical valuation"}
      </p>
      <p className="muted">
        {context.window.start_date} through {context.window.end_date} ·{" "}
        {context.window.reporting_currency}
        <br />
        Knowledge cutoff: {formatDateTime(context.window.source_cutoff_at)}
        <br />
        Calculated: {formatDateTime(context.calculated_at)}
      </p>
      {context.access.reproducibility !== "reproducible" ? (
        <Notice title="Replay inputs are restricted" tone="warning">
          {titleCase(context.access.reproducibility)}
        </Notice>
      ) : null}
      {replayHref ? (
        <Link prefetch={false} className="text-link" href={replayHref}>
          Replay these exact inputs
        </Link>
      ) : null}
      <details>
        <summary>Coverage, assumptions and source evidence</summary>
        <div
          className="table-scroll"
          tabIndex={0}
          role="region"
          aria-label="Historical coverage table"
        >
          <table className="data-table" aria-label="Historical coverage">
            <thead>
              <tr>
                <th>Input</th>
                <th>Covered / expected</th>
                <th>State</th>
                <th>Missing evidence</th>
              </tr>
            </thead>
            <tbody>
              {context.coverage.measures.map((row) => (
                <tr key={row.key}>
                  <th scope="row">{titleCase(row.key)}</th>
                  <td>
                    {row.available_count} / {row.expected_count}
                  </td>
                  <td>{row.complete ? "Complete" : "Incomplete"}</td>
                  <td>
                    {row.reasons?.map(titleCase).join("; ") || "None reported"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {context.assumptions.length ? (
          <ul>
            {context.assumptions.map((value) => (
              <li key={value}>{titleCase(value)}</li>
            ))}
          </ul>
        ) : null}
        {context.warnings.length ? (
          <ul>
            {context.warnings.map((value, index) => (
              <li key={`${value.reason_code}-${index}`}>
                {titleCase(value.reason_code)}
              </li>
            ))}
          </ul>
        ) : null}
        <p>
          {context.warning_count} warnings; {context.warning_omitted_count}{" "}
          beyond this preview. {context.source_count} source references;{" "}
          {context.source_omitted_count} beyond this preview.
        </p>
        <ul className="historical-source-list">
          {context.sources.map((source) => (
            <li key={`${source.kind}-${source.id}`}>
              {sourceKinds[source.kind] ? (
                <Link
                  prefetch={false}
                  href={`/sources/snapshots/${sourceKinds[source.kind]}/${source.id}?account=${context.account_id}`}
                >
                  {titleCase(source.kind)}
                </Link>
              ) : (
                titleCase(source.kind)
              )}{" "}
              · {formatDateTime(source.effective_at)} · known{" "}
              {formatDateTime(source.first_observed_at)}
            </li>
          ))}
        </ul>
        <dl className="historical-identities">
          <dt>Input capture</dt>
          <dd>
            <code>{context.input_snapshot_id}</code>
          </dd>
          <dt>Input digest</dt>
          <dd>
            <code>{context.input_digest}</code>
          </dd>
          <dt>Result digest</dt>
          <dd>
            <code>{context.content_digest}</code>
          </dd>
        </dl>
      </details>
    </Surface>
  );
}

export function PerformanceMetricCards({
  summary,
}: Readonly<{ summary: PerformanceMetrics }>) {
  return (
    <>
      <HistoricalCards
        cards={[
          { label: "Ending value", metric: summary.ending_value },
          {
            label: "Investment gain",
            metric: summary.investment_gain,
            note: "After external deposits and withdrawals",
          },
          {
            label: "Time-weighted return",
            metric: summary.time_weighted_return,
          },
          {
            label: "Money-weighted return",
            metric: summary.money_weighted_return,
            note: "XIRR · annualized ACT/365",
          },
          { label: "Modified Dietz", metric: summary.modified_dietz_return },
        ]}
      />
      <Surface>
        <details>
          <summary>Values, cash flows, income and cost-covered P/L</summary>
          <HistoricalCards
            cards={[
              { label: "Beginning value", metric: summary.beginning_value },
              { label: "Deposits", metric: summary.deposits },
              { label: "Withdrawals", metric: summary.withdrawals },
              { label: "Net contributions", metric: summary.net_contributions },
              { label: "Income", metric: summary.income },
              { label: "Fees", metric: summary.fees },
              { label: "Withholding taxes", metric: summary.withholding_taxes },
              { label: "Realized P/L", metric: summary.realized_profit_loss },
              {
                label: "Unrealized P/L",
                metric: summary.unrealized_profit_loss,
              },
              {
                label: "Annualized TWR",
                metric: summary.annualized_time_weighted_return,
              },
              {
                label: "Annualized Modified Dietz",
                metric: summary.annualized_modified_dietz_return,
              },
              {
                label: "Maximum drawdown",
                metric: summary.maximum_drawdown,
                note: "Flow-neutral TWR wealth",
              },
            ]}
          />
        </details>
      </Surface>
    </>
  );
}

export function PerformanceSeriesResult({
  points,
  currency,
  showFlows,
  detailed = false,
}: Readonly<{
  points: readonly PerformancePoint[];
  currency: string;
  showFlows: boolean;
  detailed?: boolean;
}>) {
  const chartRows = points.map((row) => ({
    date: row.date,
    values: {
      value: row.portfolio_value.value?.amount ?? null,
      flows: row.external_flow.value?.amount ?? null,
      return: row.cumulative_return.value,
      drawdown: row.drawdown.value,
    },
  }));
  return (
    <Surface>
      <h2>
        {detailed ? "Historical value details" : "Value and return history"}
      </h2>
      {points.length ? (
        <>
          <HistoricalChart
            label="Portfolio value with external flows"
            rows={chartRows}
            unit={currency}
            tableId="performance-series-table"
            series={[
              { key: "value", label: "Portfolio value", color: "#006f53" },
              ...(showFlows
                ? [
                    {
                      key: "flows",
                      label: "External flow",
                      color: "#547ba9",
                      kind: "bar" as const,
                    },
                  ]
                : []),
            ]}
          />
          <HistoricalChart
            label="Cumulative return and flow-neutral drawdown"
            rows={chartRows}
            unit="ratio"
            tableId="performance-series-table"
            series={[
              {
                key: "return",
                label: "Selected return method",
                color: "#006f53",
              },
              { key: "drawdown", label: "TWR drawdown", color: "#ad5825" },
            ]}
          />
        </>
      ) : (
        <p>No historical points are available for this period.</p>
      )}
      <div
        className="table-scroll"
        tabIndex={0}
        role="region"
        aria-label="Historical performance table"
      >
        <table id="performance-series-table" className="data-table">
          <caption>
            Exact server values for every plotted point. Hover a value for its
            full canonical precision.
          </caption>
          <thead>
            <tr>
              <th>Date</th>
              <th>Portfolio value</th>
              <th>External flow</th>
              <th>Net contributions</th>
              <th>Income</th>
              <th>Period return</th>
              <th>Cumulative return</th>
              <th>TWR drawdown</th>
              {detailed ? (
                <>
                  <th>Invested</th>
                  <th>Cash</th>
                  <th>Deposits</th>
                  <th>Withdrawals</th>
                  <th>Fees</th>
                  <th>Withholding</th>
                </>
              ) : null}
            </tr>
          </thead>
          <tbody>
            {points.map((row) => (
              <tr key={row.ordinal}>
                <th scope="row">{row.date}</th>
                <td>
                  <HistoricalValue metric={row.portfolio_value} />
                </td>
                <td>
                  <HistoricalValue metric={row.external_flow} />
                </td>
                <td>
                  <HistoricalValue metric={row.net_contributions} />
                </td>
                <td>
                  <HistoricalValue metric={row.income} />
                </td>
                <td>
                  <HistoricalValue metric={row.interval_return} />
                </td>
                <td>
                  <HistoricalValue metric={row.cumulative_return} />
                </td>
                <td>
                  <HistoricalValue metric={row.drawdown} />
                </td>
                {detailed ? (
                  <>
                    <td>
                      <HistoricalValue metric={row.invested_value} />
                    </td>
                    <td>
                      <HistoricalValue metric={row.cash_value} />
                    </td>
                    <td>
                      <HistoricalValue metric={row.deposits} />
                    </td>
                    <td>
                      <HistoricalValue metric={row.withdrawals} />
                    </td>
                    <td>
                      <HistoricalValue metric={row.fees} />
                    </td>
                    <td>
                      <HistoricalValue metric={row.withholding_taxes} />
                    </td>
                  </>
                ) : null}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Surface>
  );
}

export function PeriodReturnsResult({
  rows,
  title,
}: Readonly<{ rows: readonly HistoricalPeriodReturn[]; title: string }>) {
  return (
    <Surface>
      <h2>{title}</h2>
      {rows.length === 0 ? (
        <p>No eligible periods were requested or covered.</p>
      ) : null}
      <div
        className="table-scroll"
        tabIndex={0}
        role="region"
        aria-label={`${title} table`}
      >
        <table className="data-table" aria-label={title}>
          <thead>
            <tr>
              <th>Start</th>
              <th>End</th>
              <th>Method</th>
              <th>Return</th>
              <th>Annualized return</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={`${row.kind}-${row.period_start_at}-${row.period_end_at}`}
              >
                <td>{formatDateTime(row.period_start_at)}</td>
                <td>{formatDateTime(row.period_end_at)}</td>
                <td>{titleCase(row.method)}</td>
                <td>
                  <HistoricalValue metric={row.value} />
                </td>
                <td>
                  <HistoricalValue metric={row.annualized_value} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Surface>
  );
}

export function BenchmarkResult({
  data,
}: Readonly<{ data: BenchmarkComparisonResponse }>) {
  return (
    <>
      <HistoricalCards
        cards={[
          { label: "Portfolio return", metric: data.summary.portfolio_return },
          { label: "Benchmark return", metric: data.summary.benchmark_return },
          {
            label: "Excess / tracking difference",
            metric: data.summary.tracking_difference,
          },
          {
            label: "Tracking error",
            metric: data.summary.tracking_error,
            note: `${data.summary.paired_observation_count} paired returns`,
          },
          {
            label: "Annualized tracking difference",
            metric: data.summary.annualized_tracking_difference,
          },
        ]}
      />
      <Surface>
        <h2>Aligned benchmark comparison</h2>
        <p>
          {data.summary.comparable_total_return_basis
            ? "Comparable total-return basis"
            : "Return bases require the disclosed comparison assumptions"}{" "}
          ·{" "}
          {data.composite_snapshot
            ? titleCase(data.composite_snapshot.rebalance_rule)
            : "Composite unavailable"}
        </p>
        {data.series.length ? (
          <HistoricalChart
            label="Portfolio and benchmark returns"
            rows={data.series.map((row) => ({
              date: row.date,
              values: {
                portfolio: row.portfolio_return.value,
                benchmark: row.benchmark_return.value,
                excess: row.excess_return.value,
              },
            }))}
            unit="ratio"
            tableId="benchmark-series-table"
            series={[
              { key: "portfolio", label: "Portfolio", color: "#006f53" },
              { key: "benchmark", label: "Benchmark", color: "#416bb0" },
              { key: "excess", label: "Excess", color: "#986229" },
            ]}
          />
        ) : null}
        <div
          className="table-scroll"
          tabIndex={0}
          role="region"
          aria-label="Benchmark comparison table"
        >
          <table id="benchmark-series-table" className="data-table">
            <caption>
              Aligned dates and reporting currency; missing components remain
              unavailable.
            </caption>
            <thead>
              <tr>
                <th>Date</th>
                <th>Portfolio</th>
                <th>Benchmark</th>
                <th>Excess</th>
                <th>Relative wealth</th>
              </tr>
            </thead>
            <tbody>
              {data.series.map((row) => (
                <tr key={row.ordinal}>
                  <th scope="row">{row.date}</th>
                  <td>
                    <HistoricalValue metric={row.portfolio_return} />
                  </td>
                  <td>
                    <HistoricalValue metric={row.benchmark_return} />
                  </td>
                  <td>
                    <HistoricalValue metric={row.excess_return} />
                  </td>
                  <td>
                    <HistoricalValue
                      metric={row.relative_wealth}
                      unit="multiple"
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {data.composite_snapshot ? (
          <Link
            prefetch={false}
            href={`/sources/snapshots/benchmark/${data.composite_snapshot.id}?account=${data.context.account_id}`}
          >
            Inspect immutable composite inputs and levels
          </Link>
        ) : null}
      </Surface>
      {data.rolling_returns.length ? (
        <BenchmarkPeriodReturns
          title="Rolling benchmark comparisons"
          rows={data.rolling_returns}
        />
      ) : null}
      {data.calendar_returns.length ? (
        <BenchmarkPeriodReturns
          title="Calendar benchmark comparisons"
          rows={data.calendar_returns}
        />
      ) : null}
    </>
  );
}

export function BenchmarkPeriodReturns({
  title,
  rows,
}: Readonly<{
  title: string;
  rows: readonly HistoricalBenchmarkPeriodReturn[];
}>) {
  return (
    <Surface>
      <h2>{title}</h2>
      <div
        className="table-scroll"
        tabIndex={0}
        role="region"
        aria-label={title}
      >
        <table className="data-table" aria-label={title}>
          <thead>
            <tr>
              <th>Period</th>
              <th>Portfolio return</th>
              <th>Benchmark return</th>
              <th>Excess return</th>
              <th>Relative wealth return</th>
              <th>Annualized portfolio</th>
              <th>Annualized benchmark</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={`${row.kind}-${row.period_start_at}-${row.period_end_at}`}
              >
                <th scope="row">
                  {formatDateTime(row.period_start_at)} to{" "}
                  {formatDateTime(row.period_end_at)}
                </th>
                <td>
                  <HistoricalValue metric={row.portfolio_return} />
                </td>
                <td>
                  <HistoricalValue metric={row.benchmark_return} />
                </td>
                <td>
                  <HistoricalValue metric={row.excess_return} />
                </td>
                <td>
                  <HistoricalValue metric={row.relative_wealth_return} />
                </td>
                <td>
                  <HistoricalValue metric={row.annualized_portfolio_return} />
                </td>
                <td>
                  <HistoricalValue metric={row.annualized_benchmark_return} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Surface>
  );
}

export function AttributionResult({
  data,
}: Readonly<{ data: AttributionSummaryResponse }>) {
  return (
    <>
      <HistoricalCards
        cards={[
          { label: "Investment gain", metric: data.summary.investment_gain },
          {
            label: "Attributed amount",
            metric: data.summary.attributed_amount,
          },
          { label: "Residual", metric: data.summary.residual },
          {
            label: "Cash drag",
            metric: data.summary.cash_drag,
            note: "Benchmark-relative counterfactual",
          },
        ]}
      />
      <Surface>
        <h2>Contribution by selected grouping</h2>
        <p>
          Showing {data.rows.length} of {data.eligible_count} components;{" "}
          {data.omitted_count} omitted from this ranked preview. Totals cover
          the complete calculation.
        </p>
        <div
          className="table-scroll"
          tabIndex={0}
          role="region"
          aria-label="Attribution components table"
        >
          <table className="data-table" aria-label="Attribution components">
            <thead>
              <tr>
                <th>Component</th>
                <th>Amount</th>
                <th>Return contribution</th>
                <th>Coverage</th>
              </tr>
            </thead>
            <tbody>
              {data.rows.map((row) => (
                <tr key={row.key}>
                  <th scope="row">{row.label}</th>
                  <td>
                    <HistoricalValue metric={row.amount} />
                  </td>
                  <td>
                    <HistoricalValue metric={row.return_contribution} />
                  </td>
                  <td>
                    {row.unresolved ? "Unresolved classification" : "Assigned"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Surface>
      <Surface>
        <h2>Effects and reconciliation</h2>
        <p>
          These effects explain the same gain as the component grouping. They
          are alternative decompositions.
        </p>
        <div
          className="table-scroll"
          tabIndex={0}
          role="region"
          aria-label="Attribution effects table"
        >
          <table className="data-table" aria-label="Attribution effects">
            <thead>
              <tr>
                <th>Effect</th>
                <th>Amount</th>
                <th>Return contribution</th>
              </tr>
            </thead>
            <tbody>
              {data.effects.map((row) => (
                <tr key={row.kind}>
                  <th scope="row">{titleCase(row.kind)}</th>
                  <td>
                    <HistoricalValue metric={row.amount} />
                  </td>
                  <td>
                    <HistoricalValue metric={row.return_contribution} />
                  </td>
                </tr>
              ))}
              <tr>
                <th scope="row">Uncovered residual</th>
                <td>
                  <HistoricalValue metric={data.summary.uncovered_residual} />
                </td>
                <td>
                  <HistoricalValue metric={data.summary.residual_return} />
                </td>
              </tr>
              <tr>
                <th scope="row">Output rounding residual</th>
                <td>
                  <HistoricalValue
                    metric={data.summary.quantization_residual}
                  />
                </td>
                <td>Included in the disclosed total residual</td>
              </tr>
            </tbody>
          </table>
        </div>
      </Surface>
    </>
  );
}

export function IncomeCurrencyTable({
  rows,
  label,
}: Readonly<{ rows: readonly CurrencyIncomeTotals[]; label: string }>) {
  return (
    <div className="table-scroll" tabIndex={0} role="region" aria-label={label}>
      <table className="data-table">
        <caption>{label}</caption>
        <thead>
          <tr>
            <th>Currency</th>
            <th>Gross</th>
            <th>Withholding</th>
            <th>Net</th>
            <th>Negative corrections</th>
            <th>Events</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.currency}>
              <th scope="row">{row.currency}</th>
              <td>
                <HistoricalValue metric={row.gross} />
              </td>
              <td>
                <HistoricalValue metric={row.withholding} />
              </td>
              <td>
                <HistoricalValue metric={row.net} />
              </td>
              <td>
                <HistoricalValue metric={row.negative_corrections} />
              </td>
              <td>{row.event_count}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function IncomeResult({
  data,
}: Readonly<{ data: DividendIntelligenceResponse }>) {
  return (
    <>
      <HistoricalCards
        cards={[
          { label: "Net income", metric: data.summary.net_income },
          {
            label: "Income yield",
            metric: data.summary.income_yield,
            note: "Time-weighted invested value, excluding cash",
          },
          {
            label: "Dividend growth",
            metric: data.summary.dividend_growth,
            note: "Previous comparable calendar period",
          },
          { label: "Withholding", metric: data.summary.withholding },
          {
            label: "Negative corrections",
            metric: data.summary.negative_corrections,
          },
        ]}
      />
      <Surface>
        <h2>Income by original currency</h2>
        <IncomeCurrencyTable
          rows={data.native_currency_totals}
          label="Original currency totals"
        />
        <IncomeCurrencyTable
          rows={[data.reporting_totals]}
          label="Sourced reporting-currency totals"
        />
      </Surface>
      <Surface>
        <h2>Income sources and concentration</h2>
        <p>
          Positive income defines concentration; negative corrections remain
          separate. Showing {data.rows.length} of {data.eligible_count}{" "}
          components ({data.omitted_count} omitted).
        </p>
        <div
          className="table-scroll"
          tabIndex={0}
          role="region"
          aria-label="Income components table"
        >
          <table className="data-table" aria-label="Income components">
            <thead>
              <tr>
                <th>Instrument or group</th>
                <th>Net</th>
                <th>Positive income</th>
                <th>Concentration</th>
                <th>Negative corrections</th>
              </tr>
            </thead>
            <tbody>
              {data.rows.map((row) => (
                <tr key={row.key}>
                  <th scope="row">
                    {row.label}
                    {row.unresolved ? " · Unresolved" : ""}
                  </th>
                  <td>
                    <HistoricalValue metric={row.net} />
                  </td>
                  <td>
                    <HistoricalValue metric={row.positive_income} />
                  </td>
                  <td>
                    <HistoricalValue metric={row.concentration} />
                  </td>
                  <td>
                    <HistoricalValue metric={row.negative_corrections} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Surface>
      <Surface>
        <h2>Income timeline</h2>
        {data.period_rows.length ? (
          <HistoricalChart
            label="Income by period"
            unit={data.context.window.reporting_currency}
            tableId="income-period-table"
            series={[
              {
                key: "income",
                label: "Net income",
                color: "#006f53",
                kind: "bar",
              },
            ]}
            rows={data.period_rows.map((row) => ({
              date: row.end_date,
              values: { income: row.reporting_net.value?.amount ?? null },
            }))}
          />
        ) : null}
        <div
          className="table-scroll"
          tabIndex={0}
          role="region"
          aria-label="Income period table"
        >
          <table
            id="income-period-table"
            className="data-table"
            aria-label="Income periods"
          >
            <thead>
              <tr>
                <th>Period start</th>
                <th>Period end</th>
                <th>Reporting net income</th>
              </tr>
            </thead>
            <tbody>
              {data.period_rows.map((row) => (
                <tr key={row.start_date}>
                  <td>{row.start_date}</td>
                  <td>{row.end_date}</td>
                  <td>
                    <HistoricalValue metric={row.reporting_net} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Surface>
      <Surface>
        <h2>Payments and corrections</h2>
        <p>
          Showing {data.event_preview.items.length} of{" "}
          {data.event_preview.total_count} events;{" "}
          {data.event_preview.omitted_count} outside this preview. The cash-flow
          view provides the paged timeline.
        </p>
        <CashFlowTable rows={data.event_preview.items} />
      </Surface>
    </>
  );
}

export function CashFlowTable({
  rows,
}: Readonly<{ rows: readonly HistoricalCashFlowPoint[] }>) {
  return (
    <div
      className="table-scroll"
      tabIndex={0}
      role="region"
      aria-label="Cash-flow event table"
    >
      <table className="data-table" aria-label="Cash-flow events">
        <thead>
          <tr>
            <th>Economic time</th>
            <th>Kind</th>
            <th>Classification</th>
            <th>Original amount</th>
            <th>Reporting amount</th>
            <th>Evidence references</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.event_revision_id}>
              <td>{formatDateTime(row.economic_at)}</td>
              <th scope="row">{titleCase(row.kind)}</th>
              <td>{titleCase(row.classification)}</td>
              <td>
                <HistoricalValue metric={row.native_amount} />
              </td>
              <td>
                <HistoricalValue metric={row.reporting_amount} />
              </td>
              <td>
                {row.source_ref_ids.length} retained references;{" "}
                {row.source_ref_omitted_count ?? 0} beyond preview
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function CashFlowResult({
  data,
}: Readonly<{ data: CashFlowIntelligenceResponse }>) {
  return (
    <>
      <Surface>
        <h2>External and internal flows</h2>
        <p>
          {data.summary.external_count} external · {data.summary.internal_count}{" "}
          internal · {data.summary.unresolved_count} unresolved events. Full
          totals remain unfiltered; the timeline has {data.filtered_count}{" "}
          events matching the selected kind.
        </p>
        <HistoricalCards
          cards={[
            { label: "Deposits", metric: data.reporting_totals.deposits },
            { label: "Withdrawals", metric: data.reporting_totals.withdrawals },
            {
              label: "Net external flow",
              metric: data.reporting_totals.external_net,
            },
            {
              label: "Internal purchases / sales",
              metric: data.reporting_totals.internal_net,
            },
          ]}
        />
      </Surface>
      <Surface>
        <h2>Native and reporting-currency cash totals</h2>
        <p>
          Native currencies remain separate. Reporting totals use the pinned FX
          evidence for each economic event.
        </p>
        <CashCurrencyTotals
          rows={data.native_currency_totals}
          label="Native cash totals"
        />
        <CashCurrencyTotals
          rows={[data.reporting_totals]}
          label="Reporting cash totals"
        />
      </Surface>
      <Surface>
        <h2>Cash flows by period</h2>
        <HistoricalChart
          label="External contributions and withdrawals"
          tableId="cash-flow-period-table"
          unit={data.context.window.reporting_currency}
          rows={data.period_rows.map((row) => ({
            date: row.start_date,
            values: {
              external: row.reporting_totals.external_net.value?.amount ?? null,
              internal: row.reporting_totals.internal_net.value?.amount ?? null,
            },
          }))}
          series={[
            {
              key: "external",
              label: "Net external flow",
              color: "#047857",
              kind: "bar",
            },
            {
              key: "internal",
              label: "Internal purchases / sales",
              color: "#475569",
              kind: "bar",
            },
          ]}
        />
        <div
          className="table-scroll"
          tabIndex={0}
          role="region"
          aria-label="Cash-flow periods"
        >
          <table
            className="data-table"
            id="cash-flow-period-table"
            aria-label="Cash-flow periods"
          >
            <thead>
              <tr>
                <th>Period</th>
                <th>External flow</th>
                <th>Internal purchases / sales</th>
                <th>Income</th>
                <th>Fees</th>
                <th>Taxes</th>
                <th>Unresolved</th>
                <th>Native currency details</th>
              </tr>
            </thead>
            <tbody>
              {data.period_rows.map((row) => (
                <tr key={`${row.start_date}-${row.end_date}`}>
                  <td>
                    {row.start_date} to {row.end_date}
                  </td>
                  <td>
                    <HistoricalValue
                      metric={row.reporting_totals.external_net}
                    />
                  </td>
                  <td>
                    <HistoricalValue
                      metric={row.reporting_totals.internal_net}
                    />
                  </td>
                  <td>
                    <HistoricalValue metric={row.reporting_totals.income} />
                  </td>
                  <td>
                    <HistoricalValue metric={row.reporting_totals.fees} />
                  </td>
                  <td>
                    <HistoricalValue metric={row.reporting_totals.taxes} />
                  </td>
                  <td>
                    <HistoricalValue
                      metric={row.reporting_totals.unresolved_amount}
                    />
                  </td>
                  <td>
                    <details>
                      <summary>Inspect currencies</summary>
                      <CashCurrencyTotals
                        rows={row.native_totals}
                        label={`Native flows ${row.start_date}`}
                      />
                    </details>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Surface>
      <Surface>
        <h2>Cash-flow timeline</h2>
        <CashFlowTable rows={data.events.items} />
      </Surface>
    </>
  );
}

export function CashCurrencyTotals({
  rows,
  label,
}: Readonly<{ rows: readonly CurrencyCashFlowTotals[]; label: string }>) {
  const fields = [
    "deposits",
    "withdrawals",
    "external_net",
    "purchases",
    "sales",
    "internal_net",
    "income",
    "fees",
    "taxes",
    "unresolved_amount",
  ] as const;
  return (
    <div className="table-scroll" tabIndex={0} role="region" aria-label={label}>
      <table className="data-table">
        <caption>{label}</caption>
        <thead>
          <tr>
            <th>Currency</th>
            {fields.map((field) => (
              <th key={field}>{titleCase(field)}</th>
            ))}
            <th>External events</th>
            <th>Internal events</th>
            <th>Unresolved events</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.currency}>
              <th scope="row">{row.currency}</th>
              {fields.map((field) => (
                <td key={field}>
                  <HistoricalValue metric={row[field]} />
                </td>
              ))}
              <td>{row.external_count}</td>
              <td>{row.internal_count}</td>
              <td>{row.unresolved_count}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length === 0 ? <p>No covered cash-flow currencies.</p> : null}
    </div>
  );
}
