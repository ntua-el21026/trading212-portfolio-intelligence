import Link from "next/link";
import { Notice, StatusPill, Surface } from "@trading212/ui";
import type {
  XrayMoneyMetric,
  XrayRatioMetric,
  XrayContext,
  XrayPortfolioSummary,
  XrayResidual,
  XrayEffectiveExposureResponse,
  XrayEtfOverlapResponse,
  XraySourceReference,
  XrayHeldFund,
} from "@trading212/api-contracts";
import { formatDateTime, titleCase } from "../lib/format";
import {
  formatHistoricalDecimal,
  formatHistoricalPercent,
} from "../lib/historical-format";
import { xrayHref, type XrayQuery } from "../lib/xray-query";
import { XrayFundSelection } from "./xray-fund-selection";

export function XrayValue({
  metric,
  ratio = true,
}: Readonly<{ metric: XrayMoneyMetric | XrayRatioMetric; ratio?: boolean }>) {
  const value = metric.value;
  const exact =
    value === null
      ? undefined
      : typeof value === "string"
        ? value
        : `${value.amount} ${value.currency}`;
  const display =
    value === null
      ? "Unavailable"
      : typeof value === "string"
        ? ratio
          ? formatHistoricalPercent(value)
          : formatHistoricalDecimal(value)
        : `${formatHistoricalDecimal(value.amount, 2)} ${value.currency}`;
  return (
    <span className="historical-value" title={exact}>
      <span className={value === null ? "metric-unavailable" : "numeric"}>
        {display}
      </span>
      {metric.bound === "lower_bound" ? <small>Lower bound</small> : null}
      {metric.reason ? <small>{titleCase(metric.reason)}</small> : null}
      {"positive_below_quantum" in metric && metric.positive_below_quantum ? (
        <small>Positive below display precision</small>
      ) : null}
      {metric.quality !== "fresh" ? (
        <small>{titleCase(metric.quality)}</small>
      ) : null}
    </span>
  );
}

export function XraySummary({
  summary,
}: Readonly<{ summary: XrayPortfolioSummary }>) {
  const cards = [
    { label: "Portfolio value", metric: summary.total },
    { label: "Known company coverage", metric: summary.company_known_weight },
    { label: "Unresolved exposure", metric: summary.unresolved_weight },
    { label: "Explicit cash", metric: summary.cash_weight },
    { label: "Duplicated exposure", metric: summary.duplicated_exposure },
    { label: "Company HHI", metric: summary.hhi, ratio: false },
  ];
  const quality = summary.quality_coverage;
  return (
    <Surface>
      <h2>Portfolio exposure</h2>
      <div className="historical-metrics">
        {cards.map(({ label, metric, ratio }) => (
          <div className="metric-card" key={label}>
            <span className="metric-card__label">{label}</span>
            <div className="metric-card__value">
              <XrayValue metric={metric} ratio={ratio} />
            </div>
          </div>
        ))}
      </div>
      <p>
        Cash and unresolved weight remain separate. Concentration uses absolute
        portfolio weights, including the full denominator.
      </p>
      <h3>Valuation and source quality</h3>
      <p>
        Valued original positions and cash balances: {quality.valued_root_count}{" "}
        of {quality.root_count}. These quality measures overlap and must not be
        added to portfolio value.
      </p>
      <dl>
        <dt>Direct valuation coverage</dt>
        <dd>
          <XrayValue metric={quality.direct_portfolio_value} /> ·{" "}
          <XrayValue metric={quality.direct_portfolio_weight} />
        </dd>
        <dt>
          Exposure using inferred mappings ({quality.inferred_mapping_count})
        </dt>
        <dd>
          <XrayValue metric={quality.inferred_value} /> ·{" "}
          <XrayValue metric={quality.inferred_weight} />
        </dd>
        <dt>Exposure using stale sources</dt>
        <dd>
          <XrayValue metric={quality.stale_value} /> ·{" "}
          <XrayValue metric={quality.stale_weight} />
        </dd>
      </dl>
      {summary.top_concentrations.length ? (
        <ul>
          {summary.top_concentrations.map((item) => (
            <li key={item.count}>
              Top {item.count}: <XrayValue metric={item.weight} />
            </li>
          ))}
        </ul>
      ) : null}
      <ul>
        {summary.thresholds.map((item) => (
          <li key={item.metric}>
            {titleCase(item.metric)}:{" "}
            {item.breached === null
              ? `Unavailable — ${titleCase(item.reason ?? "unconfigured")}`
              : item.breached
                ? "Configured threshold breached"
                : "Within configured threshold"}{" "}
            ({titleCase(item.bound)})
          </li>
        ))}
      </ul>
    </Surface>
  );
}

export function XrayResiduals({
  items,
}: Readonly<{ items: readonly XrayResidual[] }>) {
  return items.length ? (
    <details>
      <summary>Display rounding residuals ({items.length})</summary>
      <ul>
        {items.map((item) => (
          <li key={item.key}>
            {titleCase(item.kind)}: {formatHistoricalDecimal(item.value)}{" "}
            {item.currency ?? "weight"}; {item.child_count} children.{" "}
            <code>{item.consumer_key}</code>
          </li>
        ))}
      </ul>
      <p>
        Signed residuals describe independent display rounding. They are not
        redistributed as cash or unresolved exposure.
      </p>
    </details>
  ) : null;
}

export function constituentHref(id: string, context: XrayContext): string {
  return `/xray/sources/${encodeURIComponent(id)}?${new URLSearchParams({ account: context.account_id, run: context.run_id })}`;
}

function FundCompositionBasis({
  fund,
  context,
}: Readonly<{ fund: XrayHeldFund; context: XrayContext }>) {
  return (
    <section aria-label={`${fund.name} composition basis`}>
      <h3>{fund.name}</h3>
      <dl>
        <dt>Known unit coverage</dt>
        <dd>
          <XrayValue metric={fund.unit_coverage} />
        </dd>
        <dt>Unresolved unit weight</dt>
        <dd>
          <XrayValue metric={fund.unresolved_weight} />
        </dd>
        <dt>Cash unit weight</dt>
        <dd>
          <XrayValue metric={fund.cash_weight} />
        </dd>
        <dt>Source date</dt>
        <dd>
          {fund.source_at ? formatDateTime(fund.source_at) : "Unavailable"}
        </dd>
        <dt>Quality and confidence</dt>
        <dd>
          {titleCase(fund.quality)} ·{" "}
          {fund.confidence === null
            ? "Unknown"
            : formatHistoricalPercent(fund.confidence)}
        </dd>
        <dt>Representative position</dt>
        <dd>
          <code>{fund.composition_root_key}</code>
        </dd>
      </dl>
      <p>
        {fund.complete ? "Complete composition" : "Incomplete composition"} ·{" "}
        {fund.position_count} held positions.
      </p>
      {fund.constituent_snapshot_id ? (
        <Link
          prefetch={false}
          href={constituentHref(fund.constituent_snapshot_id, context)}
        >
          Inspect constituent source
        </Link>
      ) : null}
    </section>
  );
}

function SourceEvidence({
  source,
  context,
}: Readonly<{ source: XraySourceReference; context: XrayContext }>) {
  return (
    <li>
      <strong>{titleCase(source.kind)}</strong> ·{" "}
      {source.provider_name ?? "Owned portfolio evidence"}
      <br />
      Source:{" "}
      {source.source_at
        ? formatDateTime(source.source_at)
        : "No separate source timestamp"}{" "}
      · {titleCase(source.quality)} · Confidence:{" "}
      {source.confidence === null
        ? "Unknown"
        : formatHistoricalPercent(source.confidence)}
      {source.license_version_id ? (
        <>
          <br />
          License version: <code>{source.license_version_id}</code>
        </>
      ) : null}
      {source.kind === "constituents" ? (
        <>
          {" "}
          ·{" "}
          <Link
            prefetch={false}
            href={constituentHref(source.subject_id, context)}
          >
            Inspect constituent source
          </Link>
        </>
      ) : null}
      <details>
        <summary>Evidence identity</summary>
        <code>{source.id}</code>
        <br />
        <code>{source.content_digest}</code>
      </details>
    </li>
  );
}

export function XrayContextDetails({
  context,
  query,
}: Readonly<{ context: XrayContext; query: XrayQuery }>) {
  return (
    <Surface className="historical-context">
      <h2>Methodology and source evidence</h2>
      <p>
        {context.method.name} {context.method.version} · Valuation{" "}
        {formatDateTime(context.valuation_at)} · {context.reporting_currency}
      </p>
      <p>
        Knowledge cutoff {formatDateTime(context.source_cutoff_at)} · Calculated{" "}
        {formatDateTime(context.calculated_at)} · Quality assessed{" "}
        {formatDateTime(context.quality_evaluated_at)}
      </p>
      <StatusPill
        tone={
          context.access.reproducibility === "reproducible"
            ? "positive"
            : "warning"
        }
      >
        {titleCase(context.access.reproducibility)}
      </StatusPill>
      <p>
        <Link
          prefetch={false}
          href={xrayHref(query, { run: context.run_id, cursor: undefined })}
        >
          Replay this retained calculation
        </Link>
      </p>
      {context.warnings.length ? (
        <Notice title="X-ray warnings" tone="warning">
          <ul>
            {context.warnings.map((warning, index) => (
              <li key={`${warning.code}-${index}`}>
                {titleCase(warning.code)}
                {warning.reason ? `: ${titleCase(warning.reason)}` : ""};{" "}
                {warning.path_count > 0
                  ? `${warning.path_count} affected paths`
                  : warning.source_count > 0
                    ? "Source-level warning"
                    : "Calculation-level warning"}
                .
              </li>
            ))}
          </ul>
        </Notice>
      ) : null}
      <p>
        {context.warning_count} warnings; {context.warning_omitted_count}{" "}
        omitted from this preview.
      </p>
      <details>
        <summary>Sources, policies and reproducibility</summary>
        <p>
          {context.source_count} source references;{" "}
          {context.source_omitted_count} omitted from this preview. Path detail
          includes its complete bounded source proof.
        </p>
        <ul>
          {context.sources.map((source) => (
            <SourceEvidence key={source.id} source={source} context={context} />
          ))}
        </ul>
        <ul>
          {context.policies.map((policy) => (
            <li key={policy.kind}>
              {titleCase(policy.kind)} {policy.version} ·{" "}
              <code>{policy.id}</code>
            </li>
          ))}
        </ul>
        <p>
          Run <code>{context.run_id}</code>
          <br />
          Input <code>{context.input_digest}</code>
          <br />
          Result <code>{context.content_digest}</code>
        </p>
      </details>
      <XrayResiduals items={context.residuals} />
      <p>
        {context.residual_omitted_count} additional residuals omitted from the
        global preview.
      </p>
    </Surface>
  );
}

function Pagination({
  page,
  query,
}: Readonly<{
  page: {
    items: readonly unknown[];
    total: number;
    next_cursor: string | null;
  };
  query: XrayQuery;
}>) {
  return (
    <nav className="collection-pagination" aria-label="X-ray pagination">
      <p>
        {page.items.length} rows on this page of {page.total} matching rows.
      </p>
      {page.next_cursor ? (
        <Link
          prefetch={false}
          href={xrayHref(query, { cursor: page.next_cursor })}
        >
          Next page
        </Link>
      ) : null}
      {query.cursor ? (
        <Link prefetch={false} href={xrayHref(query, { cursor: undefined })}>
          First page
        </Link>
      ) : null}
    </nav>
  );
}

export function XrayResults({
  data,
  query,
}: Readonly<{
  data: XrayEffectiveExposureResponse | XrayEtfOverlapResponse;
  query: XrayQuery;
}>) {
  const pinned = { ...query, run: data.context.run_id };
  if (data.view === "held_funds")
    return (
      <XrayFundSelection
        key={`${pinned.run}:${pinned.fund_ids.join(",")}`}
        data={data}
        query={pinned}
      />
    );
  if (data.view === "exposures")
    return (
      <Surface>
        <h2>
          Effective {titleCase(data.dimension_summary.dimension)} exposure
        </h2>
        <p>
          Known coverage{" "}
          <XrayValue metric={data.dimension_summary.known_weight} /> ·
          Unresolved{" "}
          <XrayValue metric={data.dimension_summary.unresolved_weight} />
        </p>
        {data.normalized_known_only ? (
          <p>
            Known-only weights use known non-cash exposure in this dimension.
            Absolute portfolio weights and concentration are unchanged.
          </p>
        ) : null}
        <div
          className="table-wrap"
          tabIndex={0}
          role="region"
          aria-label="Effective exposure table"
        >
          <table className="data-table" aria-label="Effective exposure">
            <thead>
              <tr>
                <th scope="col">Exposure</th>
                <th scope="col">Direct</th>
                <th scope="col">Indirect</th>
                <th scope="col">Effective</th>
                <th scope="col">Absolute weight</th>
                {data.normalized_known_only ? (
                  <th scope="col">Known-only weight</th>
                ) : null}
                <th scope="col">Confidence</th>
                <th scope="col">Evidence</th>
              </tr>
            </thead>
            <tbody>
              {data.exposures.items.map((row) => (
                <tr key={row.id}>
                  <td>{row.name}</td>
                  <td>
                    <XrayValue metric={row.direct} />
                  </td>
                  <td>
                    <XrayValue metric={row.indirect} />
                  </td>
                  <td>
                    <XrayValue metric={row.effective} />
                  </td>
                  <td>
                    <XrayValue metric={row.absolute_weight} />
                  </td>
                  {data.normalized_known_only ? (
                    <td>
                      {row.normalized_known_weight ? (
                        <XrayValue metric={row.normalized_known_weight} />
                      ) : (
                        "Unavailable"
                      )}
                    </td>
                  ) : null}
                  <td>
                    {row.confidence === null
                      ? "Unknown"
                      : formatHistoricalPercent(row.confidence)}
                  </td>
                  <td>
                    <Link
                      prefetch={false}
                      href={xrayHref(pinned, {
                        view: "paths",
                        exposure: row.id,
                      })}
                    >
                      {row.path_count} paths
                    </Link>
                    <XrayResiduals items={row.residuals} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!data.exposures.total ? (
          <p>
            No resolved exposure rows for this dimension. Inspect unresolved
            coverage and paths.
          </p>
        ) : null}
        <XrayResiduals items={data.dimension_residuals} />
        <Pagination query={pinned} page={data.exposures} />
      </Surface>
    );
  if (data.view === "paths")
    return (
      <Surface>
        <h2>Exposure paths</h2>
        {data.normalized_known_only ? (
          <p>
            Known-only weights use known non-cash exposure in this dimension.
            Absolute portfolio weights and concentration are unchanged.
          </p>
        ) : null}
        {data.paths.items.map((path) => (
          <details key={path.id}>
            <summary>
              {path.name} · <XrayValue metric={path.reporting_value} /> ·{" "}
              {path.explicit_cash
                ? "Cash"
                : path.unresolved_reason
                  ? titleCase(path.unresolved_reason)
                  : "Resolved"}
            </summary>
            <p>
              Root <code>{path.root_key}</code> · Absolute weight{" "}
              <XrayValue metric={path.absolute_weight} /> · Root-relative weight{" "}
              <XrayValue metric={path.relative_weight} />
            </p>
            {data.normalized_known_only ? (
              <p>
                Known-only weight{" "}
                {path.normalized_known_weight ? (
                  <XrayValue metric={path.normalized_known_weight} />
                ) : (
                  "Unavailable"
                )}
              </p>
            ) : null}
            <p>
              Confidence{" "}
              {path.confidence === null
                ? "Unknown"
                : formatHistoricalPercent(path.confidence)}{" "}
              · {titleCase(path.quality)}
            </p>
            <ol>
              {path.fund_edges.map((edge, index) => (
                <li key={`${edge.candidate_id}-${index}`}>
                  Fund <code>{edge.fund_instrument_id}</code> · Constituent
                  weight {formatHistoricalPercent(edge.weight)} ·{" "}
                  <Link
                    prefetch={false}
                    href={constituentHref(edge.candidate_id, data.context)}
                  >
                    Constituent source
                  </Link>
                </li>
              ))}
            </ol>
            {path.classification ? (
              <p>
                {titleCase(path.classification.dimension)}:{" "}
                {path.classification.bucket_key ??
                  titleCase(path.classification.reason ?? "unavailable")}{" "}
                · Decision{" "}
                <code>{path.classification.decision_key ?? "Unavailable"}</code>
              </p>
            ) : null}
            <p>
              {path.identity_decision_ids.length} explicit identity decisions:{" "}
              {path.identity_decision_ids.map((id) => (
                <code key={id}>{id} </code>
              ))}
            </p>
            <ul>
              {path.sources.map((source) => (
                <SourceEvidence
                  key={source.id}
                  source={source}
                  context={data.context}
                />
              ))}
            </ul>
            <XrayResiduals items={path.residuals} />
          </details>
        ))}
        <XrayResiduals items={data.dimension_residuals} />
        <Pagination query={pinned} page={data.paths} />
      </Surface>
    );
  if (data.view === "pairs")
    return (
      <Surface>
        <h2>Fund overlap</h2>
        <p>
          Pair overlap excludes cash and unknown entities. Incomplete
          compositions produce a lower bound.
        </p>
        <div
          className="table-wrap"
          tabIndex={0}
          role="region"
          aria-label="Fund overlap pairs"
        >
          <table className="data-table" aria-label="Fund overlap pairs">
            <thead>
              <tr>
                <th scope="col">Funds</th>
                <th scope="col">Overlap</th>
                <th scope="col">Unit coverage</th>
                <th scope="col">Sources</th>
                <th scope="col">Common entities</th>
              </tr>
            </thead>
            <tbody>
              {data.pairs.items.map((pair) => (
                <tr key={pair.id}>
                  <td>
                    {pair.left.name} / {pair.right.name}
                  </td>
                  <td>
                    <XrayValue metric={pair.overlap} />
                  </td>
                  <td>
                    <XrayValue metric={pair.left.unit_coverage} /> /{" "}
                    <XrayValue metric={pair.right.unit_coverage} />
                  </td>
                  <td>
                    {pair.left.source_at
                      ? formatDateTime(pair.left.source_at)
                      : "Unavailable"}
                    <br />
                    {pair.right.source_at
                      ? formatDateTime(pair.right.source_at)
                      : "Unavailable"}
                  </td>
                  <td>
                    <Link
                      prefetch={false}
                      href={xrayHref(pinned, {
                        view: "common_entities",
                        left: pair.left.instrument_id,
                        right: pair.right.instrument_id,
                      })}
                    >
                      {pair.common_entity_count} common entities
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <Pagination query={pinned} page={data.pairs} />
      </Surface>
    );
  return (
    <Surface>
      <h2>
        {data.pair.left.name} / {data.pair.right.name}
      </h2>
      <p>
        Overlap <XrayValue metric={data.pair.overlap} />
      </p>
      <p>
        Each fund uses its representative held position. Unit weights describe
        its composition, including cash and unresolved holdings; they are
        separate from portfolio weights.
      </p>
      <FundCompositionBasis fund={data.pair.left} context={data.context} />
      <FundCompositionBasis fund={data.pair.right} context={data.context} />
      <div
        className="table-wrap"
        tabIndex={0}
        role="region"
        aria-label="Common fund entities"
      >
        <table className="data-table" aria-label="Common fund entities">
          <thead>
            <tr>
              <th scope="col">Entity</th>
              <th scope="col">Left weight</th>
              <th scope="col">Right weight</th>
              <th scope="col">Common weight</th>
            </tr>
          </thead>
          <tbody>
            {data.common_entities.items.map((row) => (
              <tr key={row.id}>
                <td>{row.name}</td>
                <td>
                  <XrayValue metric={row.left_weight} />
                </td>
                <td>
                  <XrayValue metric={row.right_weight} />
                </td>
                <td>
                  <XrayValue metric={row.common_weight} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Pagination query={pinned} page={data.common_entities} />
    </Surface>
  );
}
