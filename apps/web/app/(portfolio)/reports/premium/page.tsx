import { Button, Notice, Surface } from "@trading212/ui";
import {
  ReportApiError,
  RiskApiError,
  ScenarioApiError,
  type PremiumReportJobStatus,
  type PremiumReportJobStatusV3,
  type PremiumReportManifest,
  type PremiumReportManifestV3,
  type PremiumReportPage,
  type PremiumReportPageV3,
} from "@trading212/api-contracts";
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
import { scenarioData } from "../../../../lib/scenario-adapter";
import { formatDateTime, titleCase } from "../../../../lib/format";
import {
  parsePremiumReportQuery,
  premiumReportHref,
  premiumReportSource,
  premiumRiskReportSourceV3,
  premiumScenarioReportSource,
  premiumSourceMatchesQuery,
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
        error instanceof ReportApiError ||
        error instanceof RiskApiError ||
        error instanceof ScenarioApiError
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
  const profile3 = query.profile === "report_sections_v3";
  const family = profile3 ? (query.family ?? "risk") : "risk";
  const label = family === "scenario" ? "scenario" : "risk";
  const clients = await reportClients();
  const premium = profile3 ? clients.premiumReportsV3 : clients.premiumReports;
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
    (family === "scenario" || scopes.includes("activity:read"));
  const canCreate = canRead && scopes.includes("reports:write");
  if (!canRead)
    return (
      <AccountView accountId={account.id}>
        <Notice title={`${titleCase(label)} reports unavailable`}>
          This session needs report and analytics read access. Risk and
          historical replay also require activity read access.
        </Notice>
      </AccountView>
    );
  const [runs, history, selectedRun, selectedJob] = await Promise.all([
    result(async () => {
      const page =
        family === "scenario"
          ? scenarioData(
              await clients.scenarios.list_scenario_runs(account.id, {
                limit: 25,
                cursor: query.runs_cursor,
              }),
            )
          : riskData(
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
      const page = reportData<PremiumReportPage | PremiumReportPageV3>(
        await premium.list_premium_reports({
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
      const source =
        family === "scenario"
          ? premiumScenarioReportSource(
              scenarioData(
                await clients.scenarios.get_scenario_run(query.run, {
                  component_limit: 1,
                }),
              ),
              account.id,
            )
          : profile3
            ? premiumRiskReportSourceV3(
                riskData(await clients.risk.get_risk_run(query.run)),
                account.id,
              )
            : premiumReportSource(
                riskData(await clients.risk.get_risk_run(query.run)),
                account.id,
              );
      if (
        source &&
        !premiumSourceMatchesQuery(source, {
          ...query,
          account: account.id,
          ...(profile3 ? { family } : {}),
        })
      )
        throw new Error("source mismatch");
      return source;
    }),
    result(async () => {
      if (!query.report) return null;
      const job = reportData<PremiumReportJobStatus | PremiumReportJobStatusV3>(
        await premium.get_premium_report_status(query.report, {
          account_id: account.id,
        }),
      );
      if (job.account_id !== account.id) throw new Error("account mismatch");
      return job;
    }),
  ]);
  const source = selectedRun.data;
  const job = selectedJob.data;
  const manifest = await result(async () => {
    if (!job?.report_id || job.state !== "succeeded") return null;
    const value = reportData<PremiumReportManifest | PremiumReportManifestV3>(
      await premium.get_premium_report_manifest(job.report_id, {
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
          title={profile3 ? "Scenario and risk reports" : "Risk reports"}
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
            aria-current={!profile3 ? "page" : undefined}
            href={premiumReportHref({ account: account.id })}
          >
            Risk reports
          </Link>
          <Link
            prefetch={false}
            aria-current={profile3 ? "page" : undefined}
            href={premiumReportHref({
              account: account.id,
              profile: "report_sections_v3",
              family: "scenario",
            })}
          >
            Scenario and risk reports
          </Link>
        </nav>
        <Surface>
          <h2>Choose an account and saved analysis</h2>
          <form action="/reports/premium" method="get" className="target-form">
            {profile3 ? (
              <input type="hidden" name="profile" value="report_sections_v3" />
            ) : null}
            {profile3 ? (
              <label>
                Saved analysis family
                <select name="family" defaultValue={family}>
                  <option value="scenario">Scenario</option>
                  <option value="risk">Risk</option>
                </select>
              </label>
            ) : null}
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
            <Notice
              title={`${titleCase(label)} analyses unavailable`}
              tone="danger"
            >
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
              {profile3 ? (
                <>
                  <input
                    type="hidden"
                    name="profile"
                    value="report_sections_v3"
                  />
                  <input type="hidden" name="family" value={family} />
                </>
              ) : null}
              <label>
                Saved {label} analysis
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
              No available completed {label} analyses on this page.{" "}
              <Link
                prefetch={false}
                href={`/${family === "scenario" ? "scenarios" : "risk"}?account=${encodeURIComponent(account.id)}`}
              >
                Open {label} analyses
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
          <Notice title={`${titleCase(label)} result unavailable`}>
            This run is incomplete, expired or no longer permitted. Choose an
            available completed analysis.
          </Notice>
        ) : null}
        {source ? (
          <PremiumReportSelection
            key={`${query.profile ?? "report_sections_v2"}:${family}:${account.id}:${source.runId}:${source.resultDigest}`}
            source={source}
            canCreate={canCreate}
          />
        ) : null}
        <Surface
          aria-label={
            profile3 ? "Premium report history" : "Risk report history"
          }
        >
          <h2>
            {profile3
              ? "Saved scenario and risk reports"
              : "Saved risk reports"}
          </h2>
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
              aria-label={
                profile3
                  ? "Saved scenario and risk reports"
                  : "Saved risk reports"
              }
            >
              <table className="data-table">
                <caption>
                  {profile3
                    ? "Saved scenario and risk reports"
                    : "Saved risk reports"}{" "}
                  for {account.display_name}
                </caption>
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
                            ...(profile3
                              ? {
                                  profile: "report_sections_v3",
                                  family,
                                  snapshot: query.snapshot,
                                  currency: query.currency,
                                  cutoff: query.cutoff,
                                  result_digest: query.result_digest,
                                }
                              : {}),
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
            <p>
              No saved {profile3 ? "scenario and risk" : "risk"} reports on this
              page.
            </p>
          ) : null}
          {history.data ? (
            <nav
              className="collection-pagination"
              aria-label={
                profile3
                  ? "Premium report pagination"
                  : "Risk report pagination"
              }
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
              key={`${query.profile ?? "report_sections_v2"}:${account.id}:${job.job_id}`}
              job={job}
            />
            <ReportArtifacts
              job={job}
              premium
              profile={profile3 ? "report_sections_v3" : undefined}
            />
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
