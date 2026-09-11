import Link from "../../../../../components/navigation-intent";
import type { ReactNode } from "react";
import {
  AccountRequired,
  AccountView,
} from "../../../../../components/account-context";
import { loadSelectedAccount } from "../../../../../lib/api-adapter";
import { z } from "zod";
import { Notice, Surface } from "@trading212/ui";
import {
  XrayApiError,
  type XrayConstituentSnapshotHeader,
  type XrayConstituentHoldingPage,
} from "@trading212/api-contracts";
import { requireWebAccess } from "../../../../../lib/auth";
import { xrayClients, xrayData } from "../../../../../lib/xray-adapter";
import { formatDateTime, titleCase } from "../../../../../lib/format";
import { formatHistoricalPercent } from "../../../../../lib/historical-format";
import { PageHeader } from "../../../../../components/page-header";

const querySchema = z.strictObject({
  account: z.string().uuid().optional(),
  run: z.string().uuid().optional(),
  cursor: z
    .string()
    .max(2048)
    .regex(/^[A-Za-z0-9_-]+$/u)
    .optional(),
});

export default async function Page({
  params,
  searchParams,
}: Readonly<{
  params: Promise<{ snapshotId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}>) {
  const access = await requireWebAccess();
  const header = (
    <PageHeader
      title="Constituent source"
      description="Inspect the retained fund source, its license and complete paged holdings."
    />
  );
  if (access.isDemo)
    return (
      <div className="page-stack xray-page">
        {header}
        <Notice title="Connected runtime required">
          Sign in to inspect authorized retained sources.
        </Notice>
      </div>
    );
  const search = await searchParams;
  // Owner-wide diagnostics need neither an account lookup nor a synthetic run.
  const accountSelection =
    search.account === undefined
      ? null
      : await loadSelectedAccount(search.account);
  if (accountSelection && !accountSelection.account)
    return <AccountRequired selection={accountSelection} />;
  const accountId = accountSelection?.account?.id;
  const parsed = querySchema.safeParse(search);
  const snapshot = z
    .string()
    .uuid()
    .safeParse((await params).snapshotId);
  if (
    !parsed.success ||
    !snapshot.success ||
    Boolean(parsed.data?.account) !== Boolean(parsed.data?.run)
  )
    return (
      <div className="page-stack xray-page">
        {header}
        <Notice title="Invalid source selection">
          Use the source link from a retained X-ray calculation.
        </Notice>
      </div>
    );
  const query = parsed.data;
  const withScope = (content: ReactNode) =>
    accountId ? (
      <AccountView accountId={accountId}>{content}</AccountView>
    ) : (
      <>
        <Notice title="Owner-wide source">
          This retained source is shown for its owner without a portfolio
          account or X-ray run selection.
        </Notice>
        {content}
      </>
    );
  const clients = await xrayClients();
  let source: XrayConstituentSnapshotHeader;
  let holdings: XrayConstituentHoldingPage;
  try {
    const scope = accountId ? { account_id: accountId, run_id: query.run } : {};
    source = xrayData(
      await clients.xray.get_constituent_snapshot(snapshot.data, scope),
    );
    holdings = xrayData(
      await clients.xray.list_constituent_holdings(snapshot.data, {
        ...scope,
        cursor: query.cursor,
        limit: 25,
      }),
    );
  } catch (error) {
    if (!(error instanceof XrayApiError)) throw error;
    return withScope(
      <div className="page-stack xray-page">
        {header}
        <Notice title="Source unavailable">{error.message}</Notice>
      </div>,
    );
  }
  const href = (cursor?: string) => {
    const values = new URLSearchParams();
    if (accountId) values.set("account", accountId);
    if (query.run) values.set("run", query.run);
    if (cursor) values.set("cursor", cursor);
    return `/xray/sources/${encodeURIComponent(source.id)}?${values}`;
  };
  return withScope(
    <div className="page-stack xray-page">
      {header}
      <Surface>
        <h2>{source.fund_name}</h2>
        <p>
          {source.provider_name} · Source {formatDateTime(source.source_at)} ·
          First observed {formatDateTime(source.first_observed_at)}
        </p>
        <p>
          {titleCase(source.quality)} · Confidence{" "}
          {source.confidence === null
            ? "Unknown"
            : formatHistoricalPercent(source.confidence)}{" "}
          · Known {formatHistoricalPercent(source.known_weight)} · Cash{" "}
          {formatHistoricalPercent(source.cash_weight)} · Unresolved{" "}
          {formatHistoricalPercent(source.unresolved_weight)}
        </p>
        <p>
          Freshness: {titleCase(source.freshness.state)} · Evaluated{" "}
          {formatDateTime(source.freshness_evaluated_at)}
          {source.freshness.policy_version !== null &&
            ` · Policy ${source.freshness.policy_version}`}
        </p>
        <h3>License and attribution</h3>
        <p>{source.license.attribution}</p>
        <p>
          Storage: {source.license.store} · Display: {source.license.display} ·
          Report: {source.license.report} · Export: {source.license.export} ·
          Retention: {source.license.retention_days ?? "Unspecified"} days.
        </p>
        <p>
          License {source.license.version} · <code>{source.license.id}</code>
          <br />
          Source digest <code>{source.content_digest}</code>
        </p>
      </Surface>
      <Surface>
        <h2>Constituent holdings</h2>
        <div
          className="table-wrap"
          tabIndex={0}
          role="region"
          aria-label="Constituent holdings"
        >
          <table className="data-table" aria-label="Constituent holdings">
            <thead>
              <tr>
                <th scope="col">Constituent</th>
                <th scope="col">State</th>
                <th scope="col">Weight</th>
                <th scope="col">Currency</th>
                <th scope="col">Confidence</th>
              </tr>
            </thead>
            <tbody>
              {holdings.items.map((row) => (
                <tr key={row.id}>
                  <td>{row.name ?? row.source_key}</td>
                  <td>{titleCase(row.state)}</td>
                  <td>{formatHistoricalPercent(row.weight)}</td>
                  <td>{row.currency}</td>
                  <td>
                    {row.confidence === null
                      ? "Unknown"
                      : formatHistoricalPercent(row.confidence)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <nav
          className="collection-pagination"
          aria-label="Constituent pagination"
        >
          <p>
            {holdings.items.length} rows on this page of {holdings.total}{" "}
            holdings.
          </p>
          {holdings.next_cursor ? (
            <Link prefetch={false} href={href(holdings.next_cursor)}>
              Next holdings
            </Link>
          ) : null}
          {query.cursor ? (
            <Link prefetch={false} href={href()}>
              First holdings
            </Link>
          ) : null}
        </nav>
      </Surface>
    </div>,
  );
}
