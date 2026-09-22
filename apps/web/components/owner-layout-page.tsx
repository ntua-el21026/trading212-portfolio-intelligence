import { randomUUID } from "node:crypto";
import { redirect } from "next/navigation";
import { Notice, Surface } from "@trading212/ui";
import type {
  OwnerLayoutContent,
  OwnerLayoutView,
} from "@trading212/api-contracts";
import { requireWebAccess } from "../lib/auth";
import { loadAvailableAccounts, loadOverview } from "../lib/api-adapter";
import {
  ownerLayoutClients,
  ownerLayoutData,
  ownerLayoutResult,
} from "../lib/owner-layout-adapter";
import {
  ownerLayoutHref,
  readOwnerLayoutQuery,
  type OwnerLayoutQuery,
} from "../lib/owner-layout-query";
import type { HistoricalSearch } from "../lib/historical-query";
import type { OverviewBundle } from "../lib/contracts";
import { formatDateTime } from "../lib/format";
import { AccountView } from "./account-context";
import {
  OwnerLayoutForm,
  ArchiveOwnerLayoutButton,
} from "./owner-layout-forms";
import { OwnerLayoutDisplay } from "./owner-layout-views";
import { PageHeader } from "./page-header";
import Link from "./navigation-intent";
import styles from "./owner-layouts.module.css";

export async function OwnerLayoutsPage({
  search,
}: Readonly<{ search: HistoricalSearch }>) {
  const access = await requireWebAccess();
  const header = (
    <PageHeader
      title="Saved layouts"
      description="Arrange current portfolio previews and owned saved views. Versions retain presentation choices and exact selections."
    />
  );
  if (access.isDemo || !access.principal.scopes.includes("preferences:read"))
    return (
      <div className={`page-stack ${styles.root}`}>
        {header}
        <Notice title="Preferences access required">
          Sign in with current preferences access to use durable owner layouts.
        </Notice>
      </div>
    );
  let query: OwnerLayoutQuery;
  try {
    query = readOwnerLayoutQuery(search);
  } catch {
    return (
      <div className={`page-stack ${styles.root}`}>
        {header}
        <Notice title="Invalid layout selection">
          <Link prefetch={false} href="/settings/layouts">
            Return to saved layouts
          </Link>
        </Notice>
      </div>
    );
  }
  const canWrite = access.principal.scopes.includes("preferences:write");
  const outcome = await ownerLayoutResult(async () => {
    const clients = await ownerLayoutClients();
    if (query.mode === "list")
      return {
        kind: "list" as const,
        page: ownerLayoutData(
          await clients.layouts.list_owner_layouts({
            limit: 25,
            include_archived: query.archived === "true",
            ...(query.cursor ? { cursor: query.cursor } : {}),
          }),
        ),
      };
    if (!query.layout) return { kind: "new" as const };
    return {
      kind: "detail" as const,
      value: ownerLayoutData(
        await clients.layouts.get_owner_layout(
          query.layout,
          query.version ? { version_id: query.version } : {},
        ),
      ),
    };
  });
  if (!outcome.ok)
    return (
      <div className={`page-stack ${styles.root}`}>
        {header}
        <Notice title="Saved layout unavailable">{outcome.message}</Notice>
        <Link prefetch={false} href="/settings/layouts">
          Return to saved layouts
        </Link>
      </div>
    );
  const result = outcome.data;
  const toolbar = (
    <nav className={styles.toolbar} aria-label="Saved layouts navigation">
      <Link
        prefetch={false}
        href={ownerLayoutHref({
          mode: "list",
          ...(query.account ? { account: query.account } : {}),
        })}
      >
        Owner layouts
      </Link>
      {canWrite ? (
        <Link
          prefetch={false}
          href={ownerLayoutHref({
            mode: "edit",
            ...(query.account ? { account: query.account } : {}),
          })}
        >
          New layout
        </Link>
      ) : null}
    </nav>
  );
  if (result.kind === "list")
    return (
      <div className={`page-stack ${styles.root}`}>
        {header}
        {toolbar}
        <p>
          Up to 32 retained layouts, including archived layouts. Each has up to
          24 widgets and 128 content versions.
        </p>
        <form
          method="get"
          action="/settings/layouts"
          className={styles.toolbar}
        >
          <input type="hidden" name="mode" value="list" />
          {query.account ? (
            <input type="hidden" name="account" value={query.account} />
          ) : null}
          <label>
            <input
              type="checkbox"
              name="archived"
              value="true"
              defaultChecked={query.archived === "true"}
            />{" "}
            Include archived layouts
          </label>
          <button type="submit">Apply</button>
        </form>
        {result.page.items.length === 0 ? (
          <Notice title="No saved layouts">
            Create an owner template or bind one explicit account.
          </Notice>
        ) : (
          result.page.items.map((item) => (
            <Surface key={item.id}>
              <h2>{item.name}</h2>
              <p>
                Revision {item.revision} · {item.state} ·{" "}
                {formatDateTime(item.updated_at)}
              </p>
              {item.availability === "restricted" ? (
                <Notice title="Saved selection restricted">
                  The account or an owned source is unavailable. Private
                  selections are not shown.
                </Notice>
              ) : (
                <Link
                  prefetch={false}
                  href={ownerLayoutHref({ layout: item.id, mode: "view" })}
                >
                  Open layout
                </Link>
              )}
              {canWrite && item.state === "active" ? (
                <ArchiveOwnerLayoutButton
                  layoutId={item.id}
                  revision={item.revision}
                />
              ) : null}
            </Surface>
          ))
        )}
        <nav
          className="collection-pagination"
          aria-label="Saved layouts pagination"
        >
          <p>
            {result.page.items.length} of {result.page.total} layouts on this
            page.
          </p>
          {result.page.next_cursor ? (
            <Link
              prefetch={false}
              href={ownerLayoutHref({
                ...query,
                cursor: result.page.next_cursor,
              })}
            >
              Next layouts
            </Link>
          ) : null}
          {query.cursor ? (
            <Link
              prefetch={false}
              href={ownerLayoutHref({ ...query, cursor: undefined })}
            >
              First layouts
            </Link>
          ) : null}
        </nav>
      </div>
    );
  const value: OwnerLayoutView | null =
    result.kind === "detail" ? result.value : null;
  if (value && query.account && value.content.account_id !== query.account)
    return (
      <div className={`page-stack ${styles.root}`}>
        {header}
        {toolbar}
        <Notice title="Layout account differs">
          Return to owner layouts and open this saved selection in its original
          account.
        </Notice>
      </div>
    );
  if (value?.content.account_id && !query.account)
    redirect(ownerLayoutHref({ ...query, account: value.content.account_id }));
  const portfolioRead = access.principal.scopes.includes("portfolio:read");
  if (query.mode === "edit") {
    if (
      !canWrite ||
      (value && (value.state === "archived" || value.revision >= 128))
    )
      return (
        <div className={`page-stack ${styles.root}`}>
          {header}
          {toolbar}
          <Notice title="Layout editing unavailable">
            Current write access, an active layout and an unused version slot
            are required.
          </Notice>
        </div>
      );
    const accounts = portfolioRead ? await loadAvailableAccounts() : [];
    if (
      query.account &&
      !accounts.some((account) => account.id === query.account)
    )
      return (
        <div className={`page-stack ${styles.root}`}>
          {header}
          <Notice title="Account unavailable">
            Choose a currently authorized account or an owner template.
          </Notice>
        </div>
      );
    const initial: OwnerLayoutContent = value?.content ?? {
      schema_version: 1,
      name: "",
      description: "",
      account_id: query.account ?? null,
      columns: 2,
      density: "comfortable",
      widgets: [
        {
          id: randomUUID(),
          kind: "portfolio_summary",
          label: "",
          selection: null,
        },
      ],
    };
    return (
      <div className={`page-stack ${styles.root}`}>
        {header}
        {toolbar}
        <Surface>
          <OwnerLayoutForm
            key={`${value?.id ?? "new"}:${value?.version.id ?? "new"}:${query.account ?? "template"}`}
            initial={initial}
            accounts={accounts}
            layoutId={value?.id}
            revision={value?.revision}
          />
        </Surface>
      </div>
    );
  }
  if (!value)
    return (
      <div className={`page-stack ${styles.root}`}>
        {header}
        {toolbar}
        <Notice title="Choose a layout">
          Select an owner layout to open its saved version.
        </Notice>
      </div>
    );
  let bundle: OverviewBundle | null = null;
  let unavailable: string | undefined;
  if (
    value.content.account_id &&
    value.content.widgets.some((widget) => widget.kind !== "saved_view")
  ) {
    const preview = await ownerLayoutResult(() =>
      loadOverview("default", value.content.account_id!),
    );
    if (
      preview.ok &&
      preview.data.summary.account.id === value.content.account_id
    )
      bundle = preview.data;
    else
      unavailable =
        "Current portfolio previews are unavailable for the saved account.";
  }
  const display = (
    <div className={`page-stack ${styles.root}`}>
      {header}
      {toolbar}
      <Surface>
        <h2>{value.content.name}</h2>
        <p>{value.content.description}</p>
        <p>
          Content version {value.version.number} saved{" "}
          {formatDateTime(value.version.created_at)} · Current revision{" "}
          {value.revision} · {value.state}
        </p>
        {canWrite && value.state === "active" && value.revision < 128 ? (
          <Link
            prefetch={false}
            href={ownerLayoutHref({ ...query, mode: "edit" })}
          >
            Edit as new version
          </Link>
        ) : null}
        <details>
          <summary>Immutable version history</summary>
          <ol>
            {value.versions.map((version) => (
              <li key={version.id}>
                <Link
                  prefetch={false}
                  href={ownerLayoutHref({
                    ...query,
                    mode: "view",
                    version: version.id,
                  })}
                >
                  Version {version.number}
                </Link>{" "}
                · {formatDateTime(version.created_at)}
              </li>
            ))}
          </ol>
        </details>
        {canWrite && value.state === "active" ? (
          <ArchiveOwnerLayoutButton
            layoutId={value.id}
            revision={value.revision}
          />
        ) : null}
      </Surface>
      <OwnerLayoutDisplay
        value={value}
        bundle={bundle}
        unavailable={unavailable}
      />
    </div>
  );
  return value.content.account_id ? (
    <AccountView accountId={value.content.account_id}>{display}</AccountView>
  ) : (
    display
  );
}
