import type {
  SourceLicense,
  SourceProvenance,
  SourceCoverage,
  SourceSeriesStatus,
  ProviderStatus,
  SourceFreshness,
  SourceSeries,
} from "@trading212/api-contracts";
import { Notice, Surface } from "@trading212/ui";
import Link from "./navigation-intent";
import { formatDateTime, titleCase } from "../lib/format";

export function SourceLicenseDetails({
  license,
}: Readonly<{ license: SourceLicense }>) {
  return (
    <div className="source-license">
      <p>{license.attribution}</p>
      <dl className="detail-grid">
        {(["store", "display", "report", "export"] as const).map((use) => (
          <div key={use}>
            <dt>{titleCase(use)}</dt>
            <dd>{titleCase(license[use])}</dd>
          </div>
        ))}
        <div>
          <dt>Retention</dt>
          <dd>
            {license.retention_days === null
              ? "Unknown"
              : `${license.retention_days} days`}
          </dd>
        </div>
        <div>
          <dt>License version</dt>
          <dd>{license.version}</dd>
        </div>
      </dl>
    </div>
  );
}

export function SourceProviderDetails({
  providers,
}: Readonly<{ providers: ProviderStatus[] }>) {
  return (
    <Surface>
      <h2>Provider availability</h2>
      {providers.map((provider) => (
        <details key={provider.id} className="source-disclosure">
          <summary>
            {provider.name} · {titleCase(provider.availability)}
            {provider.synthetic ? " · Synthetic" : ""}
          </summary>
          <p>
            {titleCase(provider.configuration_state)}
            {provider.reason && provider.reason !== provider.configuration_state
              ? ` · ${titleCase(provider.reason)}`
              : ""}
          </p>
          <p>
            Capabilities:{" "}
            {provider.capabilities?.length
              ? provider.capabilities?.map(titleCase).join(", ")
              : "None configured"}
          </p>
          {provider.supported_price_bases?.length ? (
            <p>
              Price bases:{" "}
              {provider.supported_price_bases?.map(titleCase).join(", ")}
            </p>
          ) : null}
          {provider.license ? (
            <SourceLicenseDetails license={provider.license} />
          ) : (
            <Notice title="No current license">
              Source data is unavailable until this provider is configured and
              licensed.
            </Notice>
          )}
        </details>
      ))}
    </Surface>
  );
}

export function SourceProvenanceDetails({
  provenance,
  coverage,
  digest,
  freshness,
  calendar,
}: Readonly<{
  provenance: SourceProvenance;
  coverage: SourceCoverage;
  digest: string;
  freshness: SourceFreshness;
  calendar: Pick<SourceSeries, "calendar_id" | "calendar_version">;
}>) {
  return (
    <Surface>
      <h2>Source quality and provenance</h2>
      <dl className="detail-grid">
        <div>
          <dt>Data origin</dt>
          <dd>
            {provenance.synthetic ? "Synthetic replay" : "Provider reported"}
          </dd>
        </div>
        <div>
          <dt>Coverage</dt>
          <dd>
            {coverage.available_count} of {coverage.expected_count} expected
            observations
          </dd>
        </div>
        <div>
          <dt>Quality</dt>
          <dd>
            {titleCase(coverage.quality)}
            {coverage.reason ? ` · ${titleCase(coverage.reason)}` : ""}
          </dd>
        </div>
        <div>
          <dt>Effective time</dt>
          <dd>{formatDateTime(provenance.effective_at)}</dd>
        </div>
        <div>
          <dt>Current freshness</dt>
          <dd>{titleCase(freshness.state)}</dd>
        </div>
        <div>
          <dt>First known</dt>
          <dd>{formatDateTime(provenance.first_observed_at)}</dd>
        </div>
        <div>
          <dt>Source revision</dt>
          <dd>{provenance.source_revision}</dd>
        </div>
      </dl>
      <details className="source-disclosure">
        <summary>Reproduction details</summary>
        <dl className="detail-grid">
          <div>
            <dt>Calendar identity</dt>
            <dd>{calendar.calendar_id}</dd>
          </div>
          <div>
            <dt>Calendar version</dt>
            <dd>{calendar.calendar_version}</dd>
          </div>
          <div>
            <dt>Adapter version</dt>
            <dd>{provenance.adapter_version}</dd>
          </div>
          <div>
            <dt>Schema</dt>
            <dd>{provenance.schema_version}</dd>
          </div>
          <div>
            <dt>Freshness policy</dt>
            <dd>
              {freshness.policy_version ?? "Unavailable"}
              {freshness.max_age_seconds !== null
                ? ` · ${freshness.max_age_seconds} seconds maximum age`
                : ""}
            </dd>
          </div>
          <div>
            <dt>Content digest</dt>
            <dd className="source-identifier">{digest}</dd>
          </div>
        </dl>
      </details>
    </Surface>
  );
}

export function SourceSeriesTable({
  items,
  accountId,
  kind,
}: Readonly<{
  items: SourceSeriesStatus[];
  accountId: string;
  kind: "price" | "benchmark";
}>) {
  return (
    <div className="table-scroll">
      <table className="data-table">
        <caption className="sr-only">Reference source series</caption>
        <thead>
          <tr>
            <th>Series</th>
            <th>Basis</th>
            <th>Currency</th>
            <th>Coverage</th>
            <th>State</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.series.id}>
              <td>
                {item.latest_snapshot ? (
                  <Link
                    prefetch={false}
                    href={`/sources/snapshots/${kind}/${item.latest_snapshot.id}?account=${accountId}`}
                  >
                    {item.series.provider_key}
                  </Link>
                ) : (
                  item.series.provider_key
                )}
                <details>
                  <summary>Source identity</summary>
                  <span className="source-identifier">{item.series.id}</span>
                </details>
              </td>
              <td>{titleCase(item.series.basis)}</td>
              <td>{item.series.currency}</td>
              <td>
                {item.latest_snapshot
                  ? `${item.latest_snapshot.available_count} / ${item.latest_snapshot.expected_count}`
                  : "Unavailable"}
              </td>
              <td>
                {titleCase(
                  item.latest_snapshot?.freshness.state ?? item.availability,
                )}
                {item.latest_snapshot ? (
                  <small>
                    Coverage: {titleCase(item.latest_snapshot.quality)}
                  </small>
                ) : null}
                {item.reason ? ` · ${titleCase(item.reason)}` : ""}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
