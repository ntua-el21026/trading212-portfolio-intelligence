import { IntelligenceQualityPanel } from "../../../components/intelligence-quality";
import Link from "../../../components/navigation-intent";
import { readQualityNavigation } from "../../../lib/intelligence-quality-query";
import { requireWebAccess } from "../../../lib/auth";
import {
  AccountRequired,
  AccountView,
} from "../../../components/account-context";
import { loadSelectedAccount } from "../../../lib/api-adapter";
import {
  AlertTriangle,
  CheckCircle2,
  CircleHelp,
  ShieldCheck,
} from "lucide-react";

import { EmptyState, Notice, Surface } from "@trading212/ui";

import { CollectionPagination } from "../../../components/collection-pagination";
import { MoneyValue, QualityStatus } from "../../../components/financial";
import { PageHeader } from "../../../components/page-header";
import { QualityBanner } from "../../../components/quality";
import { loadQualityView, readDemoViewState } from "../../../lib/api-adapter";
import { formatDateTime, formatMoney, titleCase } from "../../../lib/format";

async function LegacyQuality({
  params,
  selectedAccountId,
}: Readonly<{
  params: Record<string, string | string[] | undefined>;
  selectedAccountId: string;
}>) {
  const navigation = readQualityNavigation(params);
  const query = navigation.legacy.query;
  if (!query) {
    const reset = new URLSearchParams({ account: selectedAccountId });
    for (const [key, value] of Object.entries({
      ...navigation.intelligence.fields,
      ...navigation.legacy.fields,
    })) {
      if (value !== undefined) reset.set(key, value);
    }
    return (
      <Notice title="Invalid reconciliation filters">
        <p>Intelligence status remains independently available above.</p>
        <Link prefetch={false} href={`/quality?${reset}`}>
          Reset invalid reconciliation filters
        </Link>
      </Notice>
    );
  }
  const bundle = await loadQualityView(
    query.cursor,
    readDemoViewState(query.state),
    selectedAccountId,
  ).catch(() => null);
  if (!bundle)
    return (
      <Notice title="Reconciliation view unavailable">
        The legacy quality read could not complete. Intelligence status remains
        independently available above.
      </Notice>
    );
  const quality = bundle.quality;
  const reconciliation = bundle.reconciliation;
  return (
    <div className="page-stack">
      <h2>Portfolio reconciliation</h2>
      <QualityBanner quality={quality} />
      <div className="quality-grid">
        <Surface className="quality-card" compact>
          <span className="feature-icon">
            <ShieldCheck aria-hidden="true" size={22} />
          </span>
          <div>
            <span>Aggregate data quality</span>
            <QualityStatus quality={quality} />
          </div>
          <dl>
            <div>
              <dt>Evaluated at</dt>
              <dd>{formatDateTime(quality.as_of)}</dd>
            </div>
            <div>
              <dt>Source cutoff</dt>
              <dd>{formatDateTime(quality.source_timestamp)}</dd>
            </div>
            <div>
              <dt>Freshness threshold</dt>
              <dd>{quality.freshness_threshold_seconds} seconds</dd>
            </div>
          </dl>
        </Surface>
        <Surface className="quality-card" compact>
          <span className="feature-icon">
            {reconciliation.status === "reconciled" ? (
              <CheckCircle2 aria-hidden="true" size={22} />
            ) : (
              <AlertTriangle aria-hidden="true" size={22} />
            )}
          </span>
          <div>
            <span>Reconciliation</span>
            <strong>{titleCase(reconciliation.status)}</strong>
          </div>
          <dl>
            <div>
              <dt>Evaluated at</dt>
              <dd>{formatDateTime(reconciliation.evaluated_at)}</dd>
            </div>
            <div>
              <dt>Algorithm</dt>
              <dd>{reconciliation.algorithm_version}</dd>
            </div>
            <div>
              <dt>Tolerance policy</dt>
              <dd>{reconciliation.tolerance_version}</dd>
            </div>
          </dl>
        </Surface>
      </div>
      <Surface className="quality-section" compact>
        <div className="section-heading-row">
          <div>
            <h2>Warnings and missing inputs</h2>
            <p>
              Nothing is silently promoted from missing or incomplete to
              available.
            </p>
          </div>
        </div>
        {quality.warnings.length === 0 &&
        quality.missing_inputs.length === 0 ? (
          <div className="inline-success">
            <CheckCircle2 aria-hidden="true" size={19} />
            No active data-quality warnings or missing material inputs.
          </div>
        ) : (
          <ul className="issue-list">
            {quality.warnings.map((warning) => (
              <li key={warning}>
                <AlertTriangle aria-hidden="true" size={17} /> {warning}
              </li>
            ))}
            {quality.missing_inputs.map((input) => (
              <li key={input}>
                <CircleHelp aria-hidden="true" size={17} /> Missing input:{" "}
                {input}
              </li>
            ))}
          </ul>
        )}
      </Surface>
      <Surface>
        <div className="section-heading-row padded-heading">
          <div>
            <h2>Reconciliation discrepancies</h2>
            <p>Open records remain versioned and auditable.</p>
          </div>
        </div>
        {bundle.discrepancies.items.length === 0 ? (
          <EmptyState
            description="All covered position and cash records are within the active tolerance policy."
            icon={<CheckCircle2 aria-hidden="true" size={22} />}
            title="No discrepancies"
          />
        ) : (
          <div
            className="table-scroll"
            role="region"
            aria-label="Reconciliation discrepancies"
            tabIndex={0}
          >
            <table className="data-table data-table--roomy">
              <caption className="ui-visually-hidden">
                Reconciliation discrepancy records
              </caption>
              <thead>
                <tr>
                  <th scope="col">Issue</th>
                  <th scope="col">Severity</th>
                  <th scope="col">Status</th>
                  <th scope="col">Expected</th>
                  <th scope="col">Observed</th>
                  <th scope="col">Residual</th>
                  <th scope="col">Tolerance</th>
                </tr>
              </thead>
              <tbody>
                {bundle.discrepancies.items.map((issue) => (
                  <tr key={issue.id}>
                    <th scope="row">
                      <strong>{issue.summary}</strong>
                      <span>{titleCase(issue.issue_type)}</span>
                    </th>
                    <td>{titleCase(issue.severity)}</td>
                    <td>{titleCase(issue.status)}</td>
                    <td>
                      {formatMoney(issue.expected_value)} {issue.currency}
                    </td>
                    <td>
                      {formatMoney(issue.observed_value)} {issue.currency}
                    </td>
                    <td>
                      {formatMoney(issue.residual)} {issue.currency}
                    </td>
                    <td>
                      {formatMoney(issue.tolerance)} {issue.currency}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <CollectionPagination
          nextCursor={bundle.discrepancies.next_cursor}
          pathname="/quality"
          preservedQuery={{
            account: selectedAccountId,
            state: query.state,
            ...navigation.intelligence.fields,
          }}
          returnedCount={bundle.discrepancies.items.length}
          total={bundle.discrepancies.total}
        />
      </Surface>
      <Surface className="availability-panel" compact>
        <div>
          <h2>Metric availability</h2>
          <p>Unavailable is distinct from a measured value of zero.</p>
        </div>
        <div className="availability-row">
          <span>Realized profit / loss</span>
          <MoneyValue metric={bundle.summary.realized_profit_loss} />
          <small>
            {bundle.summary.realized_profit_loss.unavailable_reason}
          </small>
        </div>
      </Surface>
    </div>
  );
}

export default async function QualityPage({
  searchParams,
}: Readonly<{
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}>) {
  const params = await searchParams;
  const accountSelection = await loadSelectedAccount(params.account);
  if (!accountSelection.account)
    return <AccountRequired selection={accountSelection} />;
  const access = await requireWebAccess();
  const selectedAccountId = accountSelection.account.id;
  return (
    <AccountView accountId={selectedAccountId}>
      <div className="page-stack">
        <PageHeader
          description="Recorded calculation quality, current source permissions and reconciliation."
          title="Quality & reconciliation"
        />
        <IntelligenceQualityPanel
          accountId={selectedAccountId}
          search={params}
          demo={access.isDemo}
          permitted={access.principal.scopes.includes("analytics:read")}
        />
        {access.principal.scopes.includes("activity:read") ? (
          <LegacyQuality
            params={params}
            selectedAccountId={selectedAccountId}
          />
        ) : (
          <Notice title="Reconciliation detail requires access">
            Activity read access is required for the legacy reconciliation
            detail.
          </Notice>
        )}
      </div>
    </AccountView>
  );
}
