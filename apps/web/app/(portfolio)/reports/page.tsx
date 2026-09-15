import {
  AccountRequired,
  AccountView,
} from "../../../components/account-context";
import { resolveAccountSelection } from "../../../lib/account-selection";
import Link from "../../../components/navigation-intent";
import { Button, Notice, Surface } from "@trading212/ui";
import {
  ReportApiError,
  type ExportJobStatus,
  type ReportJobStatus,
} from "@trading212/api-contracts";

import { PageHeader } from "../../../components/page-header";
import {
  ReportSelectionForm,
  type ReportChoices,
} from "../../../components/report-selection";
import { ReportHistory } from "../../../components/report-history";
import { ReportJobStatusCard } from "../../../components/report-job-status";
import {
  ReportArtifacts,
  ReportManifestCard,
} from "../../../components/report-manifest";
import { requireWebAccess } from "../../../lib/auth";
import { reportClients, reportData } from "../../../lib/report-adapter";
import { planningData } from "../../../lib/planning-adapter";
import { sourceData } from "../../../lib/source-adapter";
import { targetData } from "../../../lib/target-adapter";
import {
  parseReportQuery,
  reportHref,
  REPORT_STATES,
  REPORT_TYPES,
  EXPORT_DATASETS,
  type ReportQuery,
  type ReportSearch,
} from "../../../lib/report-query";
import { formatDateTime, titleCase } from "../../../lib/format";

async function choicesFor(
  clients: Awaited<ReturnType<typeof reportClients>>,
  accountId: string,
): Promise<ReportChoices> {
  const choices: ReportChoices = {
    targets: [],
    plans: [],
    benchmarks: [],
    warnings: [],
  };
  const scopes = clients.access.principal.scopes;
  if (scopes.includes("targets:read")) {
    try {
      const page = targetData(
        await clients.targets.list_virtual_portfolios({
          account_id: accountId,
          state: "all",
          sort: "name_asc",
          limit: 25,
        }),
      );
      choices.targets = page.items.flatMap((pie) =>
        pie.active_version_id
          ? [{ id: pie.active_version_id, label: pie.name }]
          : [],
      );
      if (page.next_cursor)
        choices.warnings.push(
          "The first 25 virtual Pies are shown. Open Pies to inspect the remaining published targets.",
        );
    } catch {
      choices.warnings.push(
        "Published targets could not be loaded. Other report selections remain available.",
      );
    }
    if (scopes.includes("analytics:read")) {
      try {
        const page = planningData(
          await clients.planning.list_contribution_plans({
            account_id: accountId,
            state: "succeeded",
            limit: 25,
          }),
        );
        choices.plans = page.items.flatMap((plan) =>
          plan.job.plan_revision_id
            ? [
                {
                  id: plan.job.plan_revision_id,
                  label: `Plan ${formatDateTime(plan.job.requested_at)} · revision ${plan.job.request_revision}`,
                  snapshotId: plan.snapshot_id,
                  targetVersionId: plan.target_version_id,
                },
              ]
            : [],
        );
        if (page.next_cursor)
          choices.warnings.push(
            "The first 25 finalized plans are shown. Open Planner for earlier saved revisions.",
          );
      } catch {
        choices.warnings.push(
          "Finalized plans could not be loaded. Other report selections remain available.",
        );
      }
    }
  }
  if (scopes.includes("analytics:read")) {
    try {
      const page = sourceData(
        await clients.sources.list_benchmark_definitions({
          state: "active",
          sort: "name_asc",
          limit: 25,
        }),
      );
      choices.benchmarks = page.items.flatMap((benchmark) =>
        benchmark.latest_version_id
          ? [
              {
                id: benchmark.latest_version_id,
                label: `${benchmark.name} · ${benchmark.reporting_currency}`,
              },
            ]
          : [],
      );
      if (page.next_cursor)
        choices.warnings.push(
          "The first 25 benchmark definitions are shown. Open Sources for additional definitions.",
        );
    } catch {
      choices.warnings.push(
        "Benchmark definitions could not be loaded. Other report selections remain available.",
      );
    }
  }
  return choices;
}

export default async function ReportsPage({
  searchParams,
}: Readonly<{ searchParams: Promise<ReportSearch> }>) {
  const access = await requireWebAccess();
  if (access.isDemo)
    return (
      <div className="page-stack">
        <PageHeader
          title="Reports"
          description="Private reports and exports with saved source provenance."
        />
        <Notice title="Reports require the connected runtime">
          Sign in to the local API to generate and retrieve private portfolio
          artifacts.
        </Notice>
      </div>
    );
  let query: ReportQuery;
  try {
    query = parseReportQuery(await searchParams);
  } catch {
    return (
      <div className="page-stack">
        <PageHeader
          title="Reports"
          description="Private reports and exports with saved source provenance."
        />
        <Notice title="Invalid report selection" tone="danger">
          <Link href="/reports">Reset the report selection</Link>
        </Notice>
      </div>
    );
  }
  const clients = await reportClients();
  try {
    return await renderReportPage(clients, access, query);
  } catch {
    return (
      <div className="page-stack">
        <PageHeader
          title="Reports"
          description="Private reports and exports with saved source provenance."
        />
        <Notice title="Report sources unavailable" tone="danger">
          The selected account or snapshot could not be loaded. Your URL
          selection is preserved for retry.
        </Notice>
        <Link href={reportHref({ account: query.account })}>
          Choose an available snapshot
        </Link>
      </div>
    );
  }
}

async function renderReportPage(
  clients: Awaited<ReturnType<typeof reportClients>>,
  access: Awaited<ReturnType<typeof requireWebAccess>>,
  query: ReportQuery,
) {
  const accounts = await clients.portfolio.listAccounts();
  const accountSelection = resolveAccountSelection(
    accounts,
    query.account,
    process.env.T212PI_ACCOUNT_ID,
  );
  const account = accountSelection.account;
  if (!account) return <AccountRequired selection={accountSelection} />;
  const snapshots = await clients.portfolio.listSnapshots(account.id, {
    limit: 25,
    cursor: query.snapshots_cursor,
  });
  const snapshot = query.snapshot
    ? (snapshots.items.find((item) => item.id === query.snapshot) ??
      (await clients.portfolio.getSnapshot(account.id, query.snapshot)))
    : snapshots.items[0];
  const options = await choicesFor(clients, account.id);
  const canRead = access.principal.scopes.includes("reports:read");
  const canCreate =
    access.principal.scopes.includes("reports:write") &&
    access.principal.scopes.includes("analytics:read");
  let history:
    | Awaited<ReturnType<typeof clients.reports.list_reports>>["data"]
    | Awaited<
        ReturnType<typeof clients.reports.list_portfolio_exports>
      >["data"] = null;
  let selected: ReportJobStatus | ExportJobStatus | null = null;
  let manifest: Awaited<
    ReturnType<typeof clients.reports.get_report_manifest>
  >["data"] = null;
  let failure: string | null = null;
  if (canRead) {
    try {
      history =
        query.kind === "report"
          ? reportData(
              await clients.reports.list_reports({
                account_id: account.id,
                state: query.state,
                report_type: query.history_type,
                sort: "created_desc",
                limit: 25,
                cursor: query.cursor,
              }),
            )
          : reportData(
              await clients.reports.list_portfolio_exports({
                account_id: account.id,
                state: query.state,
                dataset: query.history_dataset,
                sort: "created_desc",
                limit: 25,
                cursor: query.cursor,
              }),
            );
    } catch (error) {
      failure =
        error instanceof ReportApiError
          ? `${error.code}: ${error.message}`
          : "Private report history is temporarily unavailable.";
    }
    try {
      if (query.report && query.kind === "report")
        selected = reportData(
          await clients.reports.get_report_status(query.report, {
            account_id: account.id,
          }),
        );
      if (query.export && query.kind === "export")
        selected = reportData(
          await clients.reports.get_export_status(query.export, {
            account_id: account.id,
          }),
        );
      if (
        selected &&
        "report_id" in selected &&
        selected.state === "succeeded" &&
        selected.report_id
      )
        manifest = reportData(
          await clients.reports.get_report_manifest(selected.report_id, {
            account_id: account.id,
          }),
        );
    } catch (error) {
      failure =
        error instanceof ReportApiError
          ? `${error.code}: ${error.message}`
          : "Private report history is temporarily unavailable.";
    }
  }
  const knownSnapshots = [
    ...new Map(
      [...snapshots.items, ...(snapshot ? [snapshot] : [])].map((item) => [
        item.id,
        item,
      ]),
    ).values(),
  ];
  return (
    <AccountView accountId={account.id}>
      <div className="page-stack">
        <PageHeader
          title="Reports"
          description="Generate private reports and dataset exports from immutable portfolio sources."
        />
        <nav className="historical-tabs" aria-label="Report collections">
          <Link
            prefetch={false}
            aria-current="page"
            href={reportHref({ account: account.id })}
          >
            Portfolio reports and exports
          </Link>
          <Link
            prefetch={false}
            href={`/reports/premium?account=${encodeURIComponent(account.id)}`}
          >
            Risk reports
          </Link>
        </nav>
        <Surface>
          <h2>Account and valuation snapshot</h2>
          <form method="get" action="/reports" className="target-form">
            <label>
              <span>Account</span>
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
          <form method="get" action="/reports" className="target-form">
            <input type="hidden" name="account" value={account.id} />
            <input type="hidden" name="kind" value={query.kind} />
            <label>
              <span>Valuation snapshot</span>
              <select name="snapshot" defaultValue={snapshot?.id} required>
                {knownSnapshots.map((item) => (
                  <option key={item.id} value={item.id}>
                    {formatDateTime(item.valuation_at)} ·{" "}
                    {item.reporting_currency} · {item.data_quality.state}
                  </option>
                ))}
              </select>
            </label>
            <Button
              type="submit"
              variant="secondary"
              disabled={!knownSnapshots.length}
            >
              Choose snapshot
            </Button>
          </form>
          {snapshots.next_cursor ? (
            <Link
              prefetch={false}
              href={reportHref({
                account: account.id,
                snapshots_cursor: snapshots.next_cursor,
              })}
            >
              Browse more snapshots
            </Link>
          ) : null}
        </Surface>
        {snapshot ? (
          <ReportSelectionForm
            key={`${account.id}:${snapshot.id}`}
            accountId={account.id}
            snapshot={snapshot}
            initial={query}
            choices={options}
            canCreate={canCreate}
            defaultCutoff={new Date().toISOString()}
          />
        ) : (
          <Notice title="No valuation snapshot">
            Create a portfolio snapshot before requesting a report.
          </Notice>
        )}
        {failure ? (
          <Notice title="Report access unavailable" tone="danger">
            <p>{failure}</p>
            {query.cursor ? (
              <Link href={reportHref({ ...query, cursor: undefined })}>
                Return to first page
              </Link>
            ) : null}
          </Notice>
        ) : null}
        {selected ? (
          <>
            <ReportJobStatusCard
              key={"job_id" in selected ? selected.job_id : selected.export_id}
              job={selected}
            />
            <ReportArtifacts job={selected} />
          </>
        ) : null}
        {manifest ? <ReportManifestCard manifest={manifest} /> : null}
        {canRead ? (
          <>
            <Surface>
              <h2>Browse saved jobs</h2>
              <form method="get" action="/reports" className="target-form">
                <input type="hidden" name="account" value={account.id} />
                {snapshot ? (
                  <input type="hidden" name="snapshot" value={snapshot.id} />
                ) : null}
                <label>
                  <span>History</span>
                  <select name="kind" defaultValue={query.kind}>
                    <option value="report">Reports</option>
                    <option value="export">Exports</option>
                  </select>
                </label>
                <label>
                  <span>Job state</span>
                  <select name="state" defaultValue={query.state}>
                    {REPORT_STATES.map((state) => (
                      <option key={state} value={state}>
                        {titleCase(state)}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  <span>Report type filter</span>
                  <select name="history_type" defaultValue={query.history_type}>
                    {["all", ...REPORT_TYPES].map((type) => (
                      <option key={type} value={type}>
                        {titleCase(type)}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  <span>Dataset filter</span>
                  <select
                    name="history_dataset"
                    defaultValue={query.history_dataset}
                  >
                    {["all", ...EXPORT_DATASETS].map((dataset) => (
                      <option key={dataset} value={dataset}>
                        {titleCase(dataset)}
                      </option>
                    ))}
                  </select>
                </label>
                <Button type="submit" variant="secondary">
                  Apply history filters
                </Button>
              </form>
            </Surface>
            {history ? (
              <ReportHistory
                history={history}
                query={query}
                accountId={account.id}
              />
            ) : null}
          </>
        ) : (
          <Notice title="History requires report read access">
            Creation permission does not grant report retrieval or download
            permission.
          </Notice>
        )}
      </div>
    </AccountView>
  );
}
