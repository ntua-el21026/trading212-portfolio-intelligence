import Link from "next/link";
import { ChartPie } from "lucide-react";
import { EmptyState, Notice, StatusPill, Surface } from "@trading212/ui";
import { z } from "zod";

import { PageHeader } from "../../../components/page-header";
import { CollectionPagination } from "../../../components/collection-pagination";
import { CreatePieForm } from "../../../components/target-forms";
import {
  firstSearchParam,
  readBoundedSearch,
  readEnumParam,
  readOpaqueCursor,
} from "../../../lib/collection-query";
import { targetClients, targetData } from "../../../lib/target-adapter";
import { requireWebAccess } from "../../../lib/auth";

export default async function PiesPage({
  searchParams,
}: Readonly<{
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}>) {
  const access = await requireWebAccess();
  const params = await searchParams;
  const state = readEnumParam(
    params.state,
    new Set(["draft", "active", "archived", "all"] as const),
    "all",
  );
  const sort = readEnumParam(
    params.sort,
    new Set(["name_asc", "updated_desc"] as const),
    "name_asc",
  );
  const search = readBoundedSearch(params.search);
  const cursor = readOpaqueCursor(params.cursor);
  const template = z
    .string()
    .uuid()
    .optional()
    .parse(firstSearchParam(params.template));
  if (access.isDemo)
    return (
      <div className="page-stack">
        <PageHeader
          title="Pies"
          description="Private portfolio targets and reusable templates."
        />
        <Notice title="Target editing requires the connected runtime">
          Start the local API and PostgreSQL runtime and sign in with local API
          authentication to create durable Pies.
        </Notice>
      </div>
    );
  const { targets, portfolio } = await targetClients();
  const [accounts, source] = await Promise.all([
    portfolio.listAccounts(),
    template ? targets.get_target_version(template).then(targetData) : null,
  ]);
  const accountScope = z
    .union([z.literal("template"), z.string().uuid()])
    .parse(
      firstSearchParam(params.account) ??
        (template
          ? "template"
          : (process.env.T212PI_ACCOUNT_ID ?? accounts[0]?.id ?? "template")),
    );
  const response = await targets.list_virtual_portfolios({
    state,
    sort,
    search,
    cursor,
    limit: 25,
    account_id: accountScope === "template" ? null : accountScope,
  });
  const page = targetData(response);
  return (
    <div className="page-stack">
      <PageHeader
        title="Pies"
        description="Set portfolio targets, preserve published versions, and reuse private templates."
      />
      {source ? (
        <Notice title={`Create from template version ${source.version_number}`}>
          The selected version will be available to clone after creating your
          Pie.
        </Notice>
      ) : null}
      <Surface>
        <form className="collection-filters" method="get">
          <label>
            <span>Portfolio scope</span>
            <select name="account" defaultValue={accountScope}>
              {accounts.map((account) => (
                <option key={account.id} value={account.id}>
                  {account.display_name}
                </option>
              ))}
              <option value="template">Private templates</option>
            </select>
          </label>
          <label>
            <span>Search Pies</span>
            <input name="search" defaultValue={search} maxLength={80} />
          </label>
          <label>
            <span>State</span>
            <select name="state" defaultValue={state}>
              <option value="all">All states</option>
              <option value="active">Active</option>
              <option value="draft">Draft</option>
              <option value="archived">Archived</option>
            </select>
          </label>
          <label>
            <span>Sort</span>
            <select name="sort" defaultValue={sort}>
              <option value="name_asc">Name A–Z</option>
              <option value="updated_desc">Recently updated</option>
            </select>
          </label>
          <button type="submit">Apply</button>
        </form>
        {page.items.length ? (
          <div className="target-pie-list">
            {page.items.map((pie) => (
              <article className="target-pie-summary" key={pie.id}>
                <div>
                  <Link
                    prefetch={false}
                    className="target-title-link"
                    href={`/pies/${pie.id}`}
                  >
                    {pie.name}
                  </Link>
                  <p className="muted">
                    {pie.account_id ? "Account target" : "Private template"} ·{" "}
                    {pie.reporting_currency} · revision {pie.revision}
                  </p>
                  {pie.description ? <p>{pie.description}</p> : null}
                </div>
                <div className="target-actions">
                  <StatusPill
                    tone={pie.state === "active" ? "positive" : "neutral"}
                  >
                    {pie.state}
                  </StatusPill>
                  {!pie.account_id && pie.active_version_id ? (
                    <Link
                      prefetch={false}
                      className="text-link"
                      href={`/pies?template=${pie.active_version_id}`}
                    >
                      Use template
                    </Link>
                  ) : null}
                </div>
              </article>
            ))}
          </div>
        ) : (
          <EmptyState
            icon={<ChartPie aria-hidden="true" size={24} />}
            title="No Pies match this view"
            description="Create your first Pie or adjust the state and search filters."
          />
        )}
        <CollectionPagination
          pathname="/pies"
          nextCursor={page.next_cursor}
          total={page.total}
          returnedCount={page.items.length}
          preservedQuery={{ state, sort, search, account: accountScope }}
        />
      </Surface>
      <CreatePieForm accounts={accounts} sourceVersionId={source?.id} />
    </div>
  );
}
