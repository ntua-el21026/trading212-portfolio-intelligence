import {
  AlertTriangle,
  CheckCircle2,
  CircleHelp,
  ShieldCheck,
} from "lucide-react";

import { EmptyState, Surface } from "@trading212/ui";

import { MoneyValue, QualityStatus } from "../../../components/financial";
import { PageHeader } from "../../../components/page-header";
import { QualityBanner } from "../../../components/quality";
import {
  loadPortfolioBundle,
  readDemoViewState,
} from "../../../lib/api-adapter";
import { formatDateTime, formatMoney, titleCase } from "../../../lib/format";

export default async function QualityPage({
  searchParams,
}: Readonly<{ searchParams: Promise<{ state?: string | string[] }> }>) {
  const bundle = await loadPortfolioBundle(
    readDemoViewState((await searchParams).state),
  );
  const quality = bundle.quality;
  const reconciliation = bundle.reconciliation;
  return (
    <div className="page-stack">
      <PageHeader
        description="Freshness, missing inputs, reconciliation, and metric availability are first-class portfolio facts."
        title="Quality & reconciliation"
      />
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
        {reconciliation.issues.length === 0 ? (
          <EmptyState
            description="All covered position and cash records are within the active tolerance policy."
            icon={<CheckCircle2 aria-hidden="true" size={22} />}
            title="No discrepancies"
          />
        ) : (
          <div className="table-scroll">
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
                {reconciliation.issues.map((issue) => (
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
