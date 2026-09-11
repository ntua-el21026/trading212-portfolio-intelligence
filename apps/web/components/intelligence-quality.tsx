import styles from "./intelligence-quality.module.css";
import Link from "./navigation-intent";
import { Notice, Surface } from "@trading212/ui";
import {
  SourceApiError,
  type IntelligenceDataQuality,
  type get_intelligence_data_qualityResponse,
} from "@trading212/api-contracts";

import { sourceClients, sourceData } from "../lib/source-adapter";
import {
  intelligenceKinds,
  intelligenceQualityHref,
  readQualityNavigation,
  type IntelligenceQualityQuery,
  type LegacyQualityFields,
} from "../lib/intelligence-quality-query";
import { formatDateTime, titleCase } from "../lib/format";

function QualitySelection({
  accountId,
  query,
  legacy,
}: Readonly<{
  accountId: string;
  query: IntelligenceQualityQuery;
  legacy: LegacyQualityFields;
}>) {
  return (
    <form action="/quality" method="get" className="collection-filters">
      <input type="hidden" name="account" value={accountId} />
      {legacy.state !== undefined ? (
        <input type="hidden" name="state" value={legacy.state} />
      ) : null}
      {legacy.cursor ? (
        <input type="hidden" name="cursor" value={legacy.cursor} />
      ) : null}
      {/* Submitting a kind/limit selection starts a new source traversal. */}
      <label>
        <span>Intelligence kind</span>
        <select name="analytics_kind" defaultValue={query.analytics_kind}>
          {intelligenceKinds.map((kind) => (
            <option key={kind} value={kind}>
              {titleCase(kind)}
            </option>
          ))}
        </select>
      </label>
      <label>
        <span>Sources per page</span>
        <select name="sources_limit" defaultValue={String(query.limit)}>
          {[25, 50, 100].includes(query.limit) ? null : (
            <option value={query.limit}>{query.limit}</option>
          )}
          {[25, 50, 100].map((limit) => (
            <option key={limit} value={limit}>
              {limit}
            </option>
          ))}
        </select>
      </label>
      <button type="submit">Inspect intelligence quality</button>
    </form>
  );
}

export function IntelligenceQualityView({
  data,
  query,
  legacy = {},
}: Readonly<{
  data: IntelligenceDataQuality;
  query: IntelligenceQualityQuery;
  legacy?: LegacyQualityFields;
}>) {
  return (
    <>
      <p>
        Checked at {formatDateTime(data.checked_at)}. Recorded calculation
        quality and current source usability are reported separately.
      </p>
      {data.selection ? (
        <dl className={"settings-list " + styles.metadata}>
          <div>
            <dt>Selected {titleCase(data.selection.kind)}</dt>
            <dd>{data.selection.id}</dd>
          </div>
          <div>
            <dt>Method version</dt>
            <dd>{data.selection.method_version}</dd>
          </div>
          <div>
            <dt>Valuation / source cutoff</dt>
            <dd>
              {formatDateTime(data.selection.valuation_at)} /{" "}
              {formatDateTime(data.selection.source_cutoff_at)}
            </dd>
          </div>
          <div>
            <dt>Currency</dt>
            <dd>{data.selection.reporting_currency}</dd>
          </div>
          {data.selection.period_start && data.selection.period_end ? (
            <div>
              <dt>Period</dt>
              <dd>
                {data.selection.period_start} – {data.selection.period_end}
              </dd>
            </div>
          ) : null}
        </dl>
      ) : (
        <Notice
          title={
            data.selection_state === "not_available"
              ? "No retained calculation"
              : "Calculation unavailable"
          }
        >
          No scope-eligible retained result is available for this kind. This
          read does not calculate a new result.
        </Notice>
      )}
      <div
        className="table-scroll"
        role="region"
        aria-label="Intelligence metric status"
        tabIndex={0}
      >
        <table className="data-table">
          <caption>
            Complete metric status inventory for{" "}
            {titleCase(data.analytics_kind)}
          </caption>
          <thead>
            <tr>
              <th scope="col">Metric</th>
              <th scope="col">Recorded availability</th>
              <th scope="col">Recorded quality</th>
              <th scope="col">Quality basis</th>
              <th scope="col">Current usability</th>
              <th scope="col">Current freshness</th>
              <th scope="col">Missing inputs</th>
              <th scope="col">License applicability</th>
              <th scope="col">Reasons</th>
            </tr>
          </thead>
          <tbody>
            {data.metrics.map((metric) => (
              <tr key={metric.key}>
                <th scope="row">{titleCase(metric.key)}</th>
                <td>
                  {metric.recorded_availability
                    ? titleCase(metric.recorded_availability)
                    : "Not recorded"}
                </td>
                <td>
                  {metric.recorded_quality
                    ? titleCase(metric.recorded_quality)
                    : "Not recorded"}
                </td>
                <td>{titleCase(metric.quality_basis)}</td>
                <td>{titleCase(metric.current_usability)}</td>
                <td>
                  {titleCase(metric.freshness)} ·{" "}
                  {titleCase(metric.freshness_basis)}
                </td>
                <td>{titleCase(metric.missing_input)}</td>
                <td>{titleCase(metric.license_applicability)}</td>
                <td>
                  {metric.reasons.length
                    ? metric.reasons.map(titleCase).join("; ")
                    : "None reported"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <details>
        <summary>Pinned reconciliation and field visibility</summary>
        {data.reconciliation.visibility === "permission_required" ? (
          <p>Reconciliation detail requires activity read access.</p>
        ) : (
          <dl className="settings-list">
            <div>
              <dt>Reconciliation</dt>
              <dd>{data.reconciliation.id ?? "No pinned reconciliation"}</dd>
            </div>
            <div>
              <dt>Recorded status</dt>
              <dd>
                {data.reconciliation.status
                  ? titleCase(data.reconciliation.status)
                  : "Unavailable"}
              </dd>
            </div>
            <div>
              <dt>Complete coverage</dt>
              <dd>
                {data.reconciliation.complete === null
                  ? "Unknown"
                  : data.reconciliation.complete
                    ? "Yes"
                    : "No"}
              </dd>
            </div>
            <div>
              <dt>Discrepancies</dt>
              <dd>{data.reconciliation.discrepancy_count ?? "Unknown"}</dd>
            </div>
            {data.reconciliation.reason ? (
              <div>
                <dt>Reason</dt>
                <dd>{titleCase(data.reconciliation.reason)}</dd>
              </div>
            ) : null}
          </dl>
        )}
        <p>
          Activity detail: {titleCase(data.activity_visibility)}. Target detail:{" "}
          {titleCase(data.targets_visibility)}.
        </p>
      </details>
      <h3>Visible source references</h3>
      <p>
        {data.sources.items.length} sources on this page of{" "}
        {data.sources.exact_total} visible references. This count does not
        describe economic coverage.
      </p>
      <div
        className="table-scroll"
        role="region"
        aria-label="Intelligence source quality"
        tabIndex={0}
      >
        <table className="data-table">
          <caption>Current status of the pinned visible sources</caption>
          <thead>
            <tr>
              <th scope="col">Source</th>
              <th scope="col">Recorded quality</th>
              <th scope="col">Freshness</th>
              <th scope="col">Current usability</th>
              <th scope="col">Retention</th>
              <th scope="col">Details</th>
            </tr>
          </thead>
          <tbody>
            {data.sources.items.map((source) => (
              <tr
                key={`${source.identity.kind}:${source.identity.id}:${source.identity.parent_id ?? ""}`}
              >
                <th scope="row">
                  {titleCase(source.identity.kind)}
                  <p>{source.identity.id}</p>
                </th>
                <td>
                  {source.recorded_quality
                    ? titleCase(source.recorded_quality)
                    : "Not recorded"}
                </td>
                <td>{titleCase(source.freshness.state)}</td>
                <td>{titleCase(source.current_usability)}</td>
                <td>{titleCase(source.retention)}</td>
                <td>
                  <details>
                    <summary>Source dates, license and coverage</summary>
                    <dl className="settings-list">
                      <div>
                        <dt>Provider</dt>
                        <dd>
                          {source.provider_id ??
                            "Not applicable or unavailable"}
                        </dd>
                      </div>
                      <div>
                        <dt>Parent source</dt>
                        <dd>{source.identity.parent_id ?? "None reported"}</dd>
                      </div>
                      <div>
                        <dt>License applicability</dt>
                        <dd>{titleCase(source.license_applicability)}</dd>
                      </div>
                      <div>
                        <dt>Pinned license</dt>
                        <dd>
                          {source.license_version_id ??
                            "Not applicable or unavailable"}
                        </dd>
                      </div>
                      <div>
                        <dt>Effective at</dt>
                        <dd>
                          {source.effective_at
                            ? formatDateTime(source.effective_at)
                            : "Unknown"}
                        </dd>
                      </div>
                      <div>
                        <dt>First observed at</dt>
                        <dd>
                          {source.first_observed_at
                            ? formatDateTime(source.first_observed_at)
                            : "Unknown"}
                        </dd>
                      </div>
                      <div>
                        <dt>Expires at</dt>
                        <dd>
                          {source.expires_at
                            ? formatDateTime(source.expires_at)
                            : "No expiry reported"}
                        </dd>
                      </div>
                      <div>
                        <dt>Freshness policy</dt>
                        <dd>
                          {source.freshness.policy_version ?? "Unavailable"}
                        </dd>
                      </div>
                      <div>
                        <dt>Freshness reference</dt>
                        <dd>
                          {source.freshness.reference_at
                            ? formatDateTime(source.freshness.reference_at)
                            : "Unknown"}
                        </dd>
                      </div>
                      <div>
                        <dt>Maximum age</dt>
                        <dd>
                          {source.freshness.max_age_seconds === null
                            ? "Unknown"
                            : `${source.freshness.max_age_seconds} seconds`}
                        </dd>
                      </div>
                      <div>
                        <dt>Available / expected source coverage</dt>
                        <dd>
                          {source.available_count ?? "Unknown"} /{" "}
                          {source.expected_count ?? "Unknown"}
                        </dd>
                      </div>
                      <div>
                        <dt>Reasons</dt>
                        <dd>
                          {source.reasons.length
                            ? source.reasons.map(titleCase).join("; ")
                            : "None reported"}
                        </dd>
                      </div>
                    </dl>
                  </details>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <nav
        className="collection-pagination"
        aria-label="Intelligence source pagination"
      >
        {query.cursor ? (
          <Link
            prefetch={false}
            href={intelligenceQualityHref(data.account_id, query, null, legacy)}
          >
            First source page
          </Link>
        ) : null}
        {data.sources.next_cursor ? (
          <Link
            prefetch={false}
            href={intelligenceQualityHref(
              data.account_id,
              query,
              data.sources.next_cursor,
              legacy,
            )}
          >
            Next source page
          </Link>
        ) : null}
      </nav>
    </>
  );
}

export async function IntelligenceQualityPanel({
  accountId,
  search,
  demo,
  permitted,
}: Readonly<{
  accountId: string;
  search: Record<string, string | string[] | undefined>;
  demo: boolean;
  permitted: boolean;
}>) {
  if (demo)
    return (
      <Surface className={styles.panel}>
        <h2>Intelligence data quality</h2>
        <Notice title="Retained intelligence requires the connected runtime">
          Sign in to the local API to inspect persisted calculations and their
          current source permissions.
        </Notice>
      </Surface>
    );
  if (!permitted)
    return (
      <Surface className={styles.panel}>
        <h2>Intelligence data quality</h2>
        <Notice title="Analytics access required">
          The current session needs analytics read access for this status
          inventory.
        </Notice>
      </Surface>
    );
  const navigation = readQualityNavigation(search);
  const query = navigation.intelligence.query;
  const legacy = navigation.legacy.fields;
  if (!query) {
    const reset = new URLSearchParams({ account: accountId });
    for (const [key, value] of Object.entries({
      ...navigation.intelligence.fields,
      ...legacy,
    })) {
      if (value !== undefined) reset.set(key, value);
    }
    return (
      <Surface className={styles.panel}>
        <h2>Intelligence data quality</h2>
        <Notice title="Invalid intelligence filters">
          <Link prefetch={false} href={`/quality?${reset}`}>
            Reset invalid intelligence filters
          </Link>
        </Notice>
      </Surface>
    );
  }
  let data: get_intelligence_data_qualityResponse | undefined;
  let failure = "The status read could not complete.";
  try {
    const { sources } = await sourceClients();
    const response = sourceData(
      await sources.get_intelligence_data_quality(accountId, query),
    );
    if (
      response.account_id !== accountId ||
      response.analytics_kind !== query.analytics_kind
    )
      throw new Error("Quality selection mismatch.");
    data = response;
  } catch (error) {
    if (error instanceof SourceApiError)
      failure = error.code.replaceAll("_", " ");
  }
  const content = !data ? (
    <Notice title="Intelligence data quality unavailable">
      {failure} Your selection remains available for retry.
    </Notice>
  ) : data.state === "permission_required" ? (
    <Notice title="Additional access required">
      {data.missing_scope} is required for this intelligence kind.
    </Notice>
  ) : (
    <IntelligenceQualityView data={data} query={query} legacy={legacy} />
  );
  return (
    <Surface className={styles.panel}>
      <h2>Intelligence data quality</h2>
      <QualitySelection accountId={accountId} query={query} legacy={legacy} />
      {content}
    </Surface>
  );
}
