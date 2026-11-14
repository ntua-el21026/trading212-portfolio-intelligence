import { Button, Notice, Surface } from "@trading212/ui";
import {
  ResearchApiClient,
  ResearchApiError,
  ReportApiError,
} from "@trading212/api-contracts";
import type { WebAccess } from "../lib/auth";
import { resolveAccountSelection } from "../lib/account-selection";
import { reportClients, reportData } from "../lib/report-adapter";
import { researchData } from "../lib/research-adapter";
import {
  researchReportPinsSchema,
  researchReportSource,
} from "../lib/research-report-query";
import { AccountRequired, AccountView } from "./account-context";
import { PageHeader } from "./page-header";
import { ResearchReportSelection } from "./research-report-selection";
import { ReportArtifacts, ReportManifestCard } from "./report-manifest";
import { ReportJobStatusCard } from "./report-job-status";
import Link from "./navigation-intent";
import { formatDateTime, titleCase } from "../lib/format";

type Query = {
  account?: string;
  item?: string;
  report?: string;
  note_revisions?: string;
  review?: string;
  cursor?: string;
};

function href(query: Query): string {
  const search = new URLSearchParams({
    profile: "report_sections_v3",
    family: "research",
  });
  for (const [key, value] of Object.entries(query))
    if (value) search.set(key, value);
  return `/reports/premium?${search}`;
}

async function read<T>(
  operation: () => Promise<T>,
): Promise<{ data: T; error: null } | { data: null; error: string }> {
  try {
    return { data: await operation(), error: null };
  } catch (error) {
    return {
      data: null,
      error:
        error instanceof ResearchApiError || error instanceof ReportApiError
          ? `${error.code}: ${error.message}`
          : "The selected research report is unavailable.",
    };
  }
}

export async function ResearchReportsPage({
  query,
  access,
}: Readonly<{ query: Query; access: WebAccess }>) {
  const clients = await reportClients();
  const accounts = await clients.portfolio.listAccounts();
  const selected = resolveAccountSelection(
    accounts,
    query.account,
    process.env.T212PI_ACCOUNT_ID,
  );
  const account = selected.account;
  if (!account) return <AccountRequired selection={selected} />;
  const required = [
    "portfolio:read",
    "analytics:read",
    "reports:read",
    "research:read",
  ];
  if (!required.every((scope) => access.principal.scopes.includes(scope)))
    return (
      <AccountView accountId={account.id}>
        <Notice title="Research reports unavailable">
          Current research, portfolio, analytics and report read access are
          required.
        </Notice>
      </AccountView>
    );
  const canCreate = access.principal.scopes.includes("reports:write");
  const research = new ResearchApiClient(clients.options);
  const [item, history, status] = await Promise.all([
    read(async () => {
      if (!query.item) return null;
      const value = researchData(await research.get_research_item(query.item));
      if (
        value.item_id !== query.item ||
        !researchReportSource(value, account.id)
      )
        throw new Error("item mismatch");
      return value;
    }),
    read(async () => {
      const value = reportData(
        await clients.premiumReportsV3.list_premium_reports({
          account_id: account.id,
          limit: 25,
          cursor: query.cursor,
          sort: "created_desc",
        }),
      );
      if (value.items.some((job) => job.account_id !== account.id))
        throw new Error("account mismatch");
      return value;
    }),
    read(async () => {
      if (!query.report) return null;
      const value = reportData(
        await clients.premiumReportsV3.get_premium_report_status(query.report, {
          account_id: account.id,
        }),
      );
      if (value.account_id !== account.id) throw new Error("account mismatch");
      return value;
    }),
  ]);
  const source = item.data ? researchReportSource(item.data, account.id) : null;
  const pins = source
    ? researchReportPinsSchema.parse({
        family: "research",
        item_id: source.itemId,
        note_revision_ids:
          query.note_revisions?.split(",").filter(Boolean) ?? [],
        ...(query.review ? { review_acknowledgment_id: query.review } : {}),
      })
    : null;
  const job = status.data;
  const manifest = await read(async () => {
    if (!job?.report_id || job.state !== "succeeded") return null;
    const value = reportData(
      await clients.premiumReportsV3.get_premium_report_manifest(
        job.report_id,
        { account_id: account.id },
      ),
    );
    if (value.document.selection.account_id !== account.id)
      throw new Error("account mismatch");
    return value;
  });
  return (
    <AccountView accountId={account.id}>
      <div className="page-stack">
        <PageHeader
          title="Research reports"
          description="Private reports from exact source revisions, saved portfolio evidence and explicitly selected owner revisions."
        />
        <nav className="historical-tabs" aria-label="Report collections">
          <Link prefetch={false} href={`/reports?account=${account.id}`}>
            Portfolio reports and exports
          </Link>
          <Link
            prefetch={false}
            href={`/reports/premium?account=${account.id}`}
          >
            Risk reports
          </Link>
          <Link
            prefetch={false}
            href={`/reports/premium?account=${account.id}&profile=report_sections_v3&family=scenario`}
          >
            Scenario and risk reports
          </Link>
          <Link
            prefetch={false}
            href={href({ account: account.id })}
            aria-current="page"
          >
            Research reports
          </Link>
          <Link
            prefetch={false}
            href={`/reports/premium?account=${account.id}&profile=report_sections_v4&family=projection`}
          >
            Projection and goal reports
          </Link>
        </nav>
        <Surface>
          <h2>Choose an account and retained research item</h2>
          <form action="/reports/premium" method="get" className="target-form">
            <input type="hidden" name="profile" value="report_sections_v3" />
            <input type="hidden" name="family" value="research" />
            <label>
              Account
              <select name="account" defaultValue={account.id}>
                {accounts.map((value) => (
                  <option key={value.id} value={value.id}>
                    {value.display_name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Research item ID
              <input
                name="item"
                defaultValue={query.item ?? ""}
                required
                maxLength={36}
                autoComplete="off"
              />
            </label>
            <Button type="submit" variant="secondary">
              Use retained research item
            </Button>
          </form>
          <p>
            <Link prefetch={false} href={`/research?account=${account.id}`}>
              Open Research
            </Link>{" "}
            to inspect retained items and owner note histories.
          </p>
        </Surface>
        {item.error ? (
          <Notice title="Selected research item unavailable">
            {item.error}
          </Notice>
        ) : null}
        {source && item.data && pins ? (
          <ResearchReportSelection
            key={`${account.id}:${source.itemId}:${source.eventDigest}:${pins.note_revision_ids.join(",")}:${pins.review_acknowledgment_id ?? ""}`}
            item={item.data}
            source={source}
            initialPins={pins}
            canCreate={canCreate}
          />
        ) : null}
        <Surface aria-label="Research report history">
          <h2>Saved profile-three reports</h2>
          {history.error ? (
            <Notice title="Report history unavailable">{history.error}</Notice>
          ) : null}
          {history.data?.items.length ? (
            <div
              className="table-scroll"
              role="region"
              tabIndex={0}
              aria-label="Saved profile-three reports"
            >
              <table className="data-table">
                <caption>
                  Saved profile-three reports for {account.display_name}
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
                  {history.data.items.map((value) => (
                    <tr key={value.job_id}>
                      <th scope="row">
                        <Link
                          prefetch={false}
                          href={href({
                            ...query,
                            account: account.id,
                            report: value.job_id,
                          })}
                        >
                          {formatDateTime(value.requested_at)}
                        </Link>
                      </th>
                      <td>{titleCase(value.state)}</td>
                      <td>
                        {value.formats
                          .map((format) => format.toUpperCase())
                          .join(", ")}
                      </td>
                      <td>{formatDateTime(value.expires_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : history.data ? (
            <p>No saved profile-three reports on this page.</p>
          ) : null}
          {history.data ? (
            <nav
              className="collection-pagination"
              aria-label="Research reports pagination"
            >
              <p>
                {history.data.items.length} of {history.data.total} reports.
              </p>
              {history.data.next_cursor ? (
                <Link
                  prefetch={false}
                  href={href({
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
                  href={href({
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
        {status.error ? (
          <Notice title="Selected report unavailable">{status.error}</Notice>
        ) : null}
        {job ? (
          <>
            <ReportJobStatusCard
              key={`${account.id}:${job.job_id}`}
              job={job}
            />
            <ReportArtifacts job={job} premium profile="report_sections_v3" />
          </>
        ) : null}
        {manifest.error ? (
          <Notice title="Report evidence unavailable">{manifest.error}</Notice>
        ) : null}
        {manifest.data ? <ReportManifestCard manifest={manifest.data} /> : null}
      </div>
    </AccountView>
  );
}
