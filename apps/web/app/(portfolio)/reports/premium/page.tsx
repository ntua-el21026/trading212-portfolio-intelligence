import { Button, Notice, Surface } from "@trading212/ui";
import { ReportApiError, RiskApiError } from "@trading212/api-contracts";
import {
  AccountRequired,
  AccountView,
} from "../../../../components/account-context";
import Link from "../../../../components/navigation-intent";
import { PageHeader } from "../../../../components/page-header";
import { PremiumReportSelection } from "../../../../components/premium-report-selection";
import { ReportJobStatusCard } from "../../../../components/report-job-status";
import {
  ReportArtifacts,
  ReportManifestCard,
} from "../../../../components/report-manifest";
import { requireWebAccess } from "../../../../lib/auth";
import { resolveAccountSelection } from "../../../../lib/account-selection";
import { reportClients, reportData } from "../../../../lib/report-adapter";
import { riskData } from "../../../../lib/risk-adapter";
import { formatDateTime, titleCase } from "../../../../lib/format";
import {
  parsePremiumReportQuery,
  premiumReportHref,
  premiumReportSource,
  type PremiumReportQuery,
} from "../../../../lib/premium-report-query";
import type { ReportSearch } from "../../../../lib/report-query";

async function result<T>(
  operation: () => Promise<T>,
): Promise<{ data: T; error: null } | { data: null; error: string }> {
  try {
    return { data: await operation(), error: null };
  } catch (error) {
    return {
      data: null,
      error:
        error instanceof ReportApiError || error instanceof RiskApiError
          ? `${error.code}: ${error.message}`
          : "The selected report source is temporarily unavailable.",
    };
  }
}

export default async function PremiumReportsPage({
  searchParams,
}: Readonly<{ searchParams: Promise<ReportSearch> }>) {
  const access = await requireWebAccess();
  if (access.isDemo)
    return (
      <div className="page-stack">
        <PageHeader
          title="Risk reports"
          description="Private reports from saved risk analyses."
        />
        <Notice title="Reports require the connected runtime">
          Sign in to generate private reports from retained risk analyses.
        </Notice>
      </div>
    );
  let query: PremiumReportQuery;
  try {
    query = parsePremiumReportQuery(await searchParams);
  } catch {
    return (
      <Notice title="Invalid risk report selection" tone="danger">
        <Link href="/reports/premium">Reset the report selection</Link>
      </Notice>
    );
  }
  const clients = await reportClients();
  const accounts = await clients.portfolio.listAccounts();
  const selected = resolveAccountSelection(
    accounts,
    query.account,
    process.env.T212PI_ACCOUNT_ID,
  );
  const account = selected.account;
  if (!account) return <AccountRequired selection={selected} />;
  const scopes = access.principal.scopes;
  const canRead =
    scopes.includes("reports:read") &&
    scopes.includes("analytics:read") &&
    scopes.includes("activity:read");
  const canCreate = canRead && scopes.includes("reports:write");
  if (!canRead)
    return (
      <AccountView accountId={account.id}>
        <Notice title="Risk reports unavailable">
          This session needs report, analytics and activity read access.
        </Notice>
      </AccountView>
    );
  const [runs, history, selectedRun, selectedJob] = await Promise.all([
    result(async () => {
      const page = riskData(
        await clients.risk.list_risk_runs(account.id, {
          limit: 25,
          cursor: query.runs_cursor,
        }),
      );
      if (page.items.some((run) => run.account_id !== account.id))
        throw new Error("account mismatch");
      return page;
    }),
    result(async () => {
      const page = reportData(
        await clients.premiumReports.list_premium_reports({
          account_id: account.id,
          limit: 25,
          cursor: query.cursor,
          sort: "created_desc",
        }),
      );
      if (page.items.some((job) => job.account_id !== account.id))
        throw new Error("account mismatch");
      return page;
    }),
    result(async () => {
      if (!query.run) return null;
      const run = riskData(await clients.risk.get_risk_run(query.run));
      if (run.account_id !== account.id) throw new Error("account mismatch");
      return run;
    }),
    result(async () => {
      if (!query.report) return null;
      const job = reportData(
        await clients.premiumReports.get_premium_report_status(query.report, {
          account_id: account.id,
        }),
      );
      if (job.account_id !== account.id) throw new Error("account mismatch");
      return job;
    }),
  ]);
  const source = selectedRun.data
    ? premiumReportSource(selectedRun.data, account.id)
    : null;
  const job = selectedJob.data;
  const manifest = await result(async () => {
    if (!job?.report_id || job.state !== "succeeded") return null;
    const value = reportData(
      await clients.premiumReports.get_premium_report_manifest(job.report_id, {
        account_id: account.id,
      }),
    );
    if (value.document.selection.account_id !== account.id)
      throw new Error("account mismatch");
    return value;
  });
  const choices =
    runs.data?.items.filter(
      (run) =>
        run.state === "succeeded" &&
        ["available", "not_loaded"].includes(run.result_availability),
    ) ?? [];
  return (
    <AccountView accountId={account.id}>
      <div className="page-stack">
        <PageHeader
          title="Risk reports"
          description="Copy a saved analysis and its source evidence into private downloadable reports."
        />
        <nav className="historical-tabs" aria-label="Report collections">
          <Link
            prefetch={false}
            href={`/reports?account=${encodeURIComponent(account.id)}`}
          >
            Portfolio reports and exports
          </Link>
          <Link
            prefetch={false}
            aria-current="page"
            href={premiumReportHref({ account: account.id })}
          >
            Risk reports
          </Link>
        </nav>
        <Surface>
          <h2>Choose an account and saved analysis</h2>
          <form action="/reports/premium" method="get" className="target-form">
            <label>
              Account
              <select name="account" defaultValue={account.id}>
                {accounts.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.display_name}
                  </option>
                ))}
              </select>
            </label>
            <Button type="submit" variant="secondary">
              Choose account
            </Button>
          </form>
          {runs.error ? (
            <Notice title="Risk analyses unavailable" tone="danger">
              {runs.error}
            </Notice>
          ) : null}
          {choices.length ? (
            <form
              action="/reports/premium"
              method="get"
              className="target-form"
            >
              <input type="hidden" name="account" value={account.id} />
              <label>
                Saved risk analysis
                <select name="run" defaultValue={query.run ?? ""} required>
                  <option value="" disabled>
                    Choose an analysis
                  </option>
                  {choices.map((run) => (
                    <option key={run.id} value={run.id}>
                      {formatDateTime(run.created_at)} · {run.id}
                    </option>
                  ))}
                </select>
              </label>
              <Button type="submit" variant="secondary">
                Use saved analysis
              </Button>
            </form>
          ) : (
            <p>
              No available completed risk analyses on this page.{" "}
              <Link
                prefetch={false}
                href={`/risk?account=${encodeURIComponent(account.id)}`}
              >
                Open risk analyses
              </Link>
              .
            </p>
          )}
          {runs.data ? (
            <nav
              className="collection-pagination"
              aria-label="Saved analyses pagination"
            >
              <p>
                {runs.data.items.length} of {runs.data.total} retained analyses
                on this page; only available completed analyses can be selected.
              </p>
              {runs.data.next_cursor ? (
                <Link
                  prefetch={false}
                  href={premiumReportHref({
                    ...query,
                    account: account.id,
                    runs_cursor: runs.data.next_cursor,
                  })}
                >
                  Next analyses
                </Link>
              ) : null}
              {query.runs_cursor ? (
                <Link
                  prefetch={false}
                  href={premiumReportHref({
                    ...query,
                    account: account.id,
                    runs_cursor: undefined,
                  })}
                >
                  First analyses
                </Link>
              ) : null}
            </nav>
          ) : null}
        </Surface>
        {selectedRun.error ? (
          <Notice title="Selected analysis unavailable" tone="danger">
            {selectedRun.error}
          </Notice>
        ) : null}
        {query.run && !source && !selectedRun.error ? (
          <Notice title="Risk result unavailable">
            This run is incomplete, expired or no longer permitted. Choose an
            available completed analysis.
          </Notice>
        ) : null}
        {source ? (
          <PremiumReportSelection
            key={`${account.id}:${source.runId}`}
            source={source}
            canCreate={canCreate}
          />
        ) : null}
        <Surface aria-label="Risk report history">
          <h2>Saved risk reports</h2>
          {history.error ? (
            <Notice title="Report history unavailable" tone="danger">
              {history.error}
            </Notice>
          ) : null}
          {history.data?.items.length ? (
            <div
              className="table-scroll"
              role="region"
              tabIndex={0}
              aria-label="Saved risk reports"
            >
              <table className="data-table">
                <caption>Saved risk reports for {account.display_name}</caption>
                <thead>
                  <tr>
                    <th scope="col">Requested</th>
                    <th scope="col">State</th>
                    <th scope="col">Formats</th>
                    <th scope="col">Expires</th>
                  </tr>
                </thead>
                <tbody>
                  {history.data.items.map((item) => (
                    <tr key={item.job_id}>
                      <th scope="row">
                        <Link
                          prefetch={false}
                          href={premiumReportHref({
                            account: account.id,
                            report: item.job_id,
                            run: query.run,
                          })}
                        >
                          {formatDateTime(item.requested_at)}
                        </Link>
                      </th>
                      <td>{titleCase(item.state)}</td>
                      <td>
                        {item.formats
                          .map((format) => format.toUpperCase())
                          .join(", ")}
                      </td>
                      <td>{formatDateTime(item.expires_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : history.data ? (
            <p>No saved risk reports on this page.</p>
          ) : null}
          {history.data ? (
            <nav
              className="collection-pagination"
              aria-label="Risk report pagination"
            >
              <p>
                {history.data.items.length} of {history.data.total} reports.
              </p>
              {history.data.next_cursor ? (
                <Link
                  prefetch={false}
                  href={premiumReportHref({
                    ...query,
                    account: account.id,
                    cursor: history.data.next_cursor,
                  })}
                >
                  Next reports
                </Link>
              ) : null}
              {query.cursor ? (
                <Link
                  prefetch={false}
                  href={premiumReportHref({
                    ...query,
                    account: account.id,
                    cursor: undefined,
                  })}
                >
                  First reports
                </Link>
              ) : null}
            </nav>
          ) : null}
        </Surface>
        {selectedJob.error ? (
          <Notice title="Selected report unavailable" tone="danger">
            {selectedJob.error}
          </Notice>
        ) : null}
        {job ? (
          <>
            <ReportJobStatusCard
              key={`${account.id}:${job.job_id}`}
              job={job}
            />
            <ReportArtifacts job={job} premium />
          </>
        ) : null}
        {manifest.error ? (
          <Notice title="Report evidence unavailable" tone="danger">
            {manifest.error}
          </Notice>
        ) : null}
        {manifest.data ? <ReportManifestCard manifest={manifest.data} /> : null}
      </div>
    </AccountView>
  );
}
