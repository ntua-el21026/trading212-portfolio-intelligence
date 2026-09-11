import Link from "./navigation-intent";
import type {
  PlanningCompanyWeight,
  PlanningCompanyBinding,
  XrayContext,
} from "@trading212/api-contracts";
import { Notice, Surface } from "@trading212/ui";
import { titleCase } from "../lib/format";
import { xrayHref, type XrayQuery } from "../lib/xray-query";
import { XrayValue, XrayContextDetails } from "./xray-results";

export function CompanyWeight({
  value,
}: Readonly<{ value: PlanningCompanyWeight | null | undefined }>) {
  if (!value) return <span>Company basis not selected</span>;
  return (
    <div>
      {value.metric ? (
        <XrayValue metric={value.metric} />
      ) : (
        <span>{titleCase(value.reason)}</span>
      )}
      {value.entity_id ? (
        <details>
          <summary>Company identity and paths</summary>
          <p>
            Entity <code>{value.entity_id}</code>
          </p>
          <p>
            {value.identity_count} identity decisions and {value.path_count}{" "}
            paths. Preview omits {value.identity_omitted_count} decisions and{" "}
            {value.path_omitted_count} paths.
          </p>
          <ul>
            {value.identity_decision_ids.map((id) => (
              <li key={id}>
                <code>{id}</code>
              </li>
            ))}
          </ul>
          <ul>
            {value.path_keys.map((key) => (
              <li key={key}>
                <code>{key}</code>
              </li>
            ))}
          </ul>
          <p>
            Proof <code>{value.proof_digest}</code>
          </p>
        </details>
      ) : null}
    </div>
  );
}

export function PlanningCompanyContext({
  basis,
  context,
  projectionDigest,
}: Readonly<{
  basis: PlanningCompanyBinding;
  context: XrayContext;
  projectionDigest: string;
}>) {
  const query: XrayQuery = {
    account: context.account_id,
    snapshot: context.snapshot_id,
    cutoff: context.source_cutoff_at,
    currency: context.reporting_currency,
    view: "exposures",
    dimension: "company",
    normalized: false,
    fund_ids: [],
    run: context.run_id,
    limit: 25,
  };
  return (
    <>
      <Surface>
        <h2>Company actual-weight basis</h2>
        <Notice title="Full portfolio company exposure">
          The same company weight can appear beside several listings. Each cell
          contains that company's complete portfolio weight; these repeated
          cells must not be added together. Company weights include sourced
          indirect exposure. Listing targets do not define company targets, so
          company drift remains unavailable.
        </Notice>
        <dl className="planning-facts">
          <div>
            <dt>Known company weight</dt>
            <dd>
              <XrayValue metric={basis.company_partition.known_weight} />
            </dd>
          </div>
          <div>
            <dt>Unresolved weight</dt>
            <dd>
              <XrayValue metric={basis.company_partition.unresolved_weight} />
            </dd>
          </div>
          <div>
            <dt>Cash weight</dt>
            <dd>
              <XrayValue metric={basis.company_partition.cash_weight} />
            </dd>
          </div>
          <div>
            <dt>Projection version</dt>
            <dd>{basis.version}</dd>
          </div>
          <div>
            <dt>Projection digest</dt>
            <dd>
              <code>{projectionDigest}</code>
            </dd>
          </div>
        </dl>
        <p>
          <Link prefetch={false} href={xrayHref(query)}>
            Inspect the retained company calculation
          </Link>
        </p>
        <p>
          <Link prefetch={false} href={xrayHref(query, { view: "paths" })}>
            Inspect complete exposure paths
          </Link>
        </p>
      </Surface>
      <XrayContextDetails context={context} query={query} />
    </>
  );
}
