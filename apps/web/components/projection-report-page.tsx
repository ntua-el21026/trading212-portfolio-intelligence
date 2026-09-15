import { Button, Notice, Surface } from "@trading212/ui";
import {
  ReportApiError,
  ProjectionApiError,
  PortfolioApiError,
} from "@trading212/api-contracts";
import { AccountRequired, AccountView } from "./account-context";
import Link from "./navigation-intent";
import { PageHeader } from "./page-header";
import { ProjectionReportSelection } from "./projection-report-selection";
import { ReportJobStatusCard } from "./report-job-status";
import { ReportArtifacts, ReportManifestCard } from "./report-manifest";
import type { requireWebAccess } from "../lib/auth";
import { resolveAccountSelection } from "../lib/account-selection";
import { reportClients, reportData } from "../lib/report-adapter";
import { projectionData } from "../lib/projection-adapter";
import { formatDateTime } from "../lib/format";
import {
  premiumReportHref,
  type PremiumReportQuery,
} from "../lib/premium-report-query";
import {
  projectionReportSource,
  projectionReportSourceMatches,
} from "../lib/projection-report-query";

async function read<T>(
  operation: () => Promise<T>,
): Promise<{ data: T; error: null } | { data: null; error: string }> {
  try {
    return { data: await operation(), error: null };
  } catch (error) {
    return {
      data: null,
      error:
        error instanceof ReportApiError ||
        error instanceof ProjectionApiError ||
        error instanceof PortfolioApiError
          ? `${error.code}: ${error.message}`
          : "The selected report source is unavailable.",
    };
  }
}

export async function ProjectionReportsPage({
  query,
  access,
}: Readonly<{
  query: PremiumReportQuery;
  access: Awaited<ReturnType<typeof requireWebAccess>>;
}>) {
  if (access.isDemo)
    return (
      <Notice title="Projection reports require the connected runtime">
        Sign in to use saved projections.
      </Notice>
    );
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
    scopes.includes("reports:read") && scopes.includes("analytics:read");
  const canCreate = canRead && scopes.includes("reports:write");
  if (!canRead)
    return (
      <AccountView accountId={account.id}>
        <Notice title="Projection reports unavailable">
          This session needs report and analytics read access.
        </Notice>
      </AccountView>
    );
  const fixed = {
    profile: "report_sections_v4" as const,
    family: "projection" as const,
    account: account.id,
  };
  const [runs, snapshots, history, selectedRun, selectedSnapshot, selectedJob] =
    await Promise.all([
      read(async () => {
        const page = projectionData(
          await clients.projections.list_projection_runs(account.id, {
            limit: 25,
            cursor: query.runs_cursor,
          }),
        );
        if (page.items.some((run) => run.account_id !== account.id))
          throw new Error("account mismatch");
        return page;
      }),
      read(() =>
        clients.portfolio.listSnapshots(account.id, {
          limit: 25,
          cursor: query.snapshots_cursor,
        }),
      ),
      read(async () => {
        const page = reportData(
          await clients.premiumReportsV4.list_premium_reports({
            account_id: account.id,
            limit: 25,
            cursor: query.cursor,
            sort: "created_desc",
          }),
        );
        if (
          page.profile_version !== fixed.profile ||
          page.items.some(
            (job) =>
              job.account_id !== account.id ||
              job.profile_version !== fixed.profile,
          )
        )
          throw new Error("profile or account mismatch");
        return page;
      }),
      read(async () => {
        if (!query.run) return null;
        const run = projectionData(
          await clients.projections.get_projection_run(query.run, {
            point_limit: 1,
          }),
        );
        if (run.account_id !== account.id || run.id !== query.run)
          throw new Error("account mismatch");
        return run;
      }),
      read(async () => {
        if (!query.snapshot) return null;
        const snapshot = await clients.portfolio.getSnapshot(
          account.id,
          query.snapshot,
        );
        if (snapshot.id !== query.snapshot)
          throw new Error("snapshot mismatch");
        return snapshot;
      }),
      read(async () => {
        if (!query.report) return null;
        const job = reportData(
          await clients.premiumReportsV4.get_premium_report_status(
            query.report,
            { account_id: account.id },
          ),
        );
        if (
          job.account_id !== account.id ||
          job.profile_version !== fixed.profile
        )
          throw new Error("profile or account mismatch");
        return job;
      }),
    ]);
  const source =
    selectedRun.data && selectedSnapshot.data
      ? projectionReportSource(
          selectedRun.data,
          account.id,
          selectedSnapshot.data,
        )
      : null;
  const compatible =
    source !== null &&
    projectionReportSourceMatches(source, { ...query, account: account.id });
  const job = selectedJob.data;
  const manifest = await read(async () => {
    if (job?.state !== "succeeded" || !job.report_id) return null;
    const value = reportData(
      await clients.premiumReportsV4.get_premium_report_manifest(
        job.report_id,
        { account_id: account.id },
      ),
    );
    if (
      value.document.selection.account_id !== account.id ||
      value.document.document_schema_version !== "4.0.0"
    )
      throw new Error("manifest mismatch");
    return value;
  });
  const available =
    runs.data?.items.filter(
      (run) =>
        run.state === "succeeded" &&
        ["available", "not_loaded"].includes(run.result_availability),
    ) ?? [];
  const current = selectedRun.data;
  const choices =
    current?.state === "succeeded" &&
    current.result_availability === "available" &&
    !available.some((run) => run.id === current.id)
      ? [...available, current]
      : available;
  const snapshotChoices = snapshots.data?.items ?? [];
  const currentSnapshot = selectedSnapshot.data;
  const actualSnapshots =
    currentSnapshot &&
    !snapshotChoices.some((snapshot) => snapshot.id === currentSnapshot.id)
      ? [...snapshotChoices, currentSnapshot]
      : snapshotChoices;
  return (
    <AccountView accountId={account.id}>
      <div className="page-stack">
        <PageHeader
          title="Projection and goal reports"
          description="Copy complete saved projections into private reports using a separately selected portfolio snapshot for context."
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
            href={premiumReportHref({ account: account.id })}
          >
            Risk reports
          </Link>
          <Link
            prefetch={false}
            href={premiumReportHref({
              account: account.id,
              profile: "report_sections_v3",
              family: "scenario",
            })}
          >
            Scenario and risk reports
          </Link>
          <Link
            prefetch={false}
            aria-current="page"
            href={premiumReportHref(fixed)}
          >
            Projection and goal reports
          </Link>
        </nav>
        <Surface>
          <h2>Choose an account, saved projection and report context</h2>
          <form action="/reports/premium" method="get" className="target-form">
            <input type="hidden" name="profile" value={fixed.profile} />
            <input type="hidden" name="family" value={fixed.family} />
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
            <Notice title="Saved projections unavailable" tone="danger">
              {runs.error}
            </Notice>
          ) : null}
          {snapshots.error ? (
            <Notice title="Owned snapshots unavailable" tone="danger">
              {snapshots.error}
            </Notice>
          ) : null}
          {choices.length && actualSnapshots.length ? (
            <form
              action="/reports/premium"
              method="get"
              className="target-form"
            >
              <input type="hidden" name="profile" value={fixed.profile} />
              <input type="hidden" name="family" value={fixed.family} />
              <input type="hidden" name="account" value={account.id} />
              <label>
                Saved projection
                <select name="run" defaultValue={query.run ?? ""} required>
                  <option value="" disabled>
                    Choose a completed projection
                  </option>
                  {choices.map((run) => (
                    <option key={run.id} value={run.id}>
                      {formatDateTime(run.created_at)} · {run.id}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Report-context snapshot
                <select
                  name="snapshot"
                  defaultValue={query.snapshot ?? ""}
                  required
                >
                  <option value="" disabled>
                    Choose an owned snapshot
                  </option>
                  {actualSnapshots.map((snapshot) => (
                    <option key={snapshot.id} value={snapshot.id}>
                      {formatDateTime(snapshot.valuation_at)} ·{" "}
                      {snapshot.reporting_currency} · {snapshot.id}
                    </option>
                  ))}
                </select>
              </label>
              <p>
                This snapshot supplies ordinary portfolio context. The saved
                projection keeps its own original source clocks and model dates.
              </p>
              <Button type="submit" variant="secondary">
                Use saved projection and snapshot
              </Button>
            </form>
          ) : (
            <p>
              A completed available projection and an owned snapshot are needed.{" "}
              <Link
                prefetch={false}
                href={`/projections?account=${encodeURIComponent(account.id)}`}
              >
                Open projections and goals
              </Link>
              .
            </p>
          )}
          <nav
            className="collection-pagination"
            aria-label="Saved projection pages"
          >
            {runs.data?.next_cursor ? (
              <Link
                prefetch={false}
                href={premiumReportHref({
                  ...query,
                  ...fixed,
                  runs_cursor: runs.data.next_cursor,
                })}
              >
                Next saved projections
              </Link>
            ) : null}
            {query.runs_cursor ? (
              <Link
                prefetch={false}
                href={premiumReportHref({
                  ...query,
                  ...fixed,
                  runs_cursor: undefined,
                })}
              >
                First saved projections
              </Link>
            ) : null}
          </nav>
          <nav
            className="collection-pagination"
            aria-label="Owned snapshot pages"
          >
            {snapshots.data?.next_cursor ? (
              <Link
                prefetch={false}
                href={premiumReportHref({
                  ...query,
                  ...fixed,
                  snapshots_cursor: snapshots.data.next_cursor,
                })}
              >
                Next owned snapshots
              </Link>
            ) : null}
            {query.snapshots_cursor ? (
              <Link
                prefetch={false}
                href={premiumReportHref({
                  ...query,
                  ...fixed,
                  snapshots_cursor: undefined,
                })}
              >
                First owned snapshots
              </Link>
            ) : null}
          </nav>
        </Surface>
        {selectedRun.error || selectedSnapshot.error ? (
          <Notice title="Selected report basis unavailable" tone="danger">
            {selectedRun.error ?? selectedSnapshot.error}
          </Notice>
        ) : null}
        {source && !compatible ? (
          <Notice title="Saved report basis changed" tone="danger">
            Choose the projection and owned snapshot again to inspect their
            current retained identities.
          </Notice>
        ) : null}
        {query.run &&
        query.snapshot &&
        !source &&
        !selectedRun.error &&
        !selectedSnapshot.error ? (
          <Notice title="Projection result unavailable">
            The selected run is incomplete, expired or no longer readable.
          </Notice>
        ) : null}
        {source && compatible ? (
          <ProjectionReportSelection
            key={`${source.accountId}:${source.runId}:${source.resultDigest}:${source.snapshotId}:${source.sourceCutoff}`}
            source={source}
            canCreate={canCreate}
          />
        ) : null}
        <Surface aria-label="Projection report history">
          <h2>Saved projection reports</h2>
          {history.error ? (
            <Notice title="Report history unavailable" tone="danger">
              {history.error}
            </Notice>
          ) : null}
          {history.data?.items.length ? (
            <ul>
              {history.data.items.map((item) => (
                <li key={item.job_id}>
                  <Link
                    prefetch={false}
                    href={premiumReportHref({ ...fixed, report: item.job_id })}
                  >
                    {formatDateTime(item.requested_at)} · {item.state} ·{" "}
                    {item.job_id}
                  </Link>
                </li>
              ))}
            </ul>
          ) : !history.error ? (
            <p>No projection reports on this page.</p>
          ) : null}
          {history.data?.next_cursor ? (
            <Link
              prefetch={false}
              href={premiumReportHref({
                ...query,
                ...fixed,
                cursor: history.data.next_cursor,
              })}
            >
              Next projection reports
            </Link>
          ) : null}
          {query.cursor ? (
            <Link
              prefetch={false}
              href={premiumReportHref({
                ...query,
                ...fixed,
                cursor: undefined,
              })}
            >
              First projection reports
            </Link>
          ) : null}
        </Surface>
        {selectedJob.error ? (
          <Notice title="Report status unavailable" tone="danger">
            {selectedJob.error}
          </Notice>
        ) : null}
        {job ? (
          <ReportJobStatusCard key={`${account.id}:${job.job_id}`} job={job} />
        ) : null}
        {job ? (
          <ReportArtifacts job={job} premium profile="report_sections_v4" />
        ) : null}
        {manifest.error ? (
          <Notice title="Manifest unavailable" tone="danger">
            {manifest.error}
          </Notice>
        ) : null}
        {manifest.data ? <ReportManifestCard manifest={manifest.data} /> : null}
      </div>
    </AccountView>
  );
}
