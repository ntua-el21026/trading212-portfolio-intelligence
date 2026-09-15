import type { ReactNode } from "react";
import { ResearchApiError } from "@trading212/api-contracts";
import { Button, Notice, Surface } from "@trading212/ui";
import { requireWebAccess } from "../lib/auth";
import { resolveAccountSelection } from "../lib/account-selection";
import {
  researchClients,
  researchData,
  researchResult,
  assertResearchAccount,
  assertResearchItem,
} from "../lib/research-adapter";
import {
  readResearchQuery,
  researchHref,
  ResearchQueryError,
  type ResearchQuery,
} from "../lib/research-query";
import type { HistoricalSearch } from "../lib/historical-query";
import { AccountRequired, AccountView } from "./account-context";
import Link from "./navigation-intent";
import { PageHeader } from "./page-header";
import { ResearchItem, ResearchNote, ResearchPin } from "./research-views";
import { ResearchNoteForm } from "./research-forms";
import styles from "./research-workspace.module.css";

type Clients = Awaited<ReturnType<typeof researchClients>>;
function Pagination({
  query,
  field,
  page,
  label,
}: Readonly<{
  query: ResearchQuery;
  field: "cursor" | "notes_cursor" | "versions_cursor";
  page: {
    items: readonly unknown[];
    total: number;
    next_cursor: string | null;
  };
  label: string;
}>) {
  return (
    <nav className="collection-pagination" aria-label={`${label} pagination`}>
      <p>
        {page.items.length} of {page.total} {label} on this page.
      </p>
      {page.next_cursor ? (
        <Link
          prefetch={false}
          href={researchHref(query, { [field]: page.next_cursor })}
        >
          Next {label}
        </Link>
      ) : null}
      {query[field] ? (
        <Link prefetch={false} href={researchHref(query, { [field]: null })}>
          First {label}
        </Link>
      ) : null}
    </nav>
  );
}
function Selection({ query }: Readonly<{ query: ResearchQuery }>) {
  return (
    <Surface>
      <h2>Research selection</h2>
      <p>
        Choose an existing portfolio X-ray and a research source cutoff. Results
        retain their original portfolio and source dates.
      </p>
      <form
        method="get"
        action="/research"
        className={styles.form}
        key={researchHref(query)}
        aria-label="Research selection"
      >
        <input type="hidden" name="account" value={query.account} />
        <input type="hidden" name="view" value="summary" />
        <div className={styles.fields}>
          <label>
            <span>Saved X-ray run ID</span>
            <input
              name="xray"
              required
              maxLength={36}
              defaultValue={query.xray ?? ""}
              autoComplete="off"
            />
          </label>
          <label>
            <span>Research source cutoff (ISO timestamp)</span>
            <input
              name="cutoff"
              required
              maxLength={40}
              defaultValue={query.cutoff}
            />
          </label>
          <label>
            <span>Entity ID (optional)</span>
            <input
              name="entity"
              maxLength={36}
              defaultValue={query.entity ?? ""}
              autoComplete="off"
            />
          </label>
          <label>
            <span>Source kind</span>
            <select name="event_kind" defaultValue={query.event_kind}>
              <option value="all">All source kinds</option>
              <option value="news">News</option>
              <option value="company_overview">Company overview</option>
            </select>
          </label>
          <label>
            <span>Review state</span>
            <select name="review_state" defaultValue={query.review_state}>
              <option value="all">All revisions</option>
              <option value="reviewed">Reviewed</option>
              <option value="unreviewed">Unreviewed</option>
            </select>
          </label>
        </div>
        <Button type="submit">Load research</Button>
      </form>
      <p>
        <Link prefetch={false} href={`/xray?account=${query.account}`}>
          Open portfolio X-ray
        </Link>{" "}
        to inspect and select a saved result.
      </p>
    </Surface>
  );
}
async function loadView(
  clients: Clients,
  query: ResearchQuery,
  accountId: string,
  canWrite: boolean,
): Promise<ReactNode> {
  const api = clients.research;
  if (query.view === "item" && query.item) {
    const item = researchData(await api.get_research_item(query.item));
    assertResearchItem(item, accountId);
    if (
      item.item_id !== query.item ||
      (query.xray && item.portfolio.pin.run_id !== query.xray)
    )
      throw new ResearchApiError(
        "NOT_FOUND",
        404,
        "The selected item does not match this saved X-ray.",
      );
    const pinned = {
      ...query,
      xray: item.portfolio.pin.run_id,
      cutoff: item.source_cutoff_at,
    };
    return (
      <ResearchItem
        key={item.item_id}
        item={item}
        query={pinned}
        canWrite={canWrite}
        detailed
      />
    );
  }
  if (query.view === "notes") {
    const notes = researchData(
      await api.list_research_notes(accountId, {
        limit: 25,
        cursor: query.notes_cursor,
      }),
    );
    for (const note of notes.items)
      assertResearchAccount(note.account_id, accountId);
    const selected = query.note
      ? researchData(await api.get_research_note(query.note))
      : undefined;
    if (selected) assertResearchAccount(selected.account_id, accountId);
    const versions = selected
      ? researchData(
          await api.list_research_note_versions(selected.note_id, {
            limit: 25,
            cursor: query.versions_cursor,
          }),
        )
      : undefined;
    for (const version of versions?.items ?? []) {
      assertResearchAccount(version.account_id, accountId);
      if (version.note_id !== selected?.note_id) throw new ResearchQueryError();
    }
    return (
      <>
        <Surface>
          <h2>Owner notes</h2>
          <p>
            Owner-authored notes and revision history remain separate from
            licensed source availability.
          </p>
          {notes.items.length ? (
            <ul className={styles.noteList}>
              {notes.items.map((note) => (
                <li key={note.note_id}>
                  <Link
                    prefetch={false}
                    href={researchHref(query, { note: note.note_id })}
                  >
                    {note.content.title}
                  </Link>
                  <p>
                    Entity {note.entity_id} · revision {note.revision}
                  </p>
                </li>
              ))}
            </ul>
          ) : (
            <p>No owner notes for this account.</p>
          )}
          <Pagination
            query={query}
            field="notes_cursor"
            page={notes}
            label="notes"
          />
          {query.note ? (
            <Link prefetch={false} href={researchHref(query, { note: null })}>
              Write another owner note
            </Link>
          ) : null}
        </Surface>
        <Surface>
          <h2>{selected ? "Selected owner note" : "New owner note"}</h2>
          {selected ? <ResearchNote value={selected} /> : null}
          <ResearchNoteForm
            key={`${accountId}:${selected?.revision_id ?? "new"}`}
            accountId={accountId}
            query={query}
            existing={selected}
            canWrite={canWrite}
          />
        </Surface>
        {versions ? (
          <Surface>
            <h2>Immutable revision history</h2>
            {versions.items.map((note) => (
              <details key={note.revision_id}>
                <summary>
                  Revision {note.revision} · {note.created_at}
                </summary>
                <ResearchNote value={note} />
              </details>
            ))}
            <Pagination
              query={query}
              field="versions_cursor"
              page={versions}
              label="revisions"
            />
          </Surface>
        ) : null}
      </>
    );
  }
  if (!query.xray)
    return (
      <Notice title="Select a saved X-ray">
        Research ranking copies retained company exposure from the chosen
        result. Select a saved run to load licensed source facts.
      </Notice>
    );
  const summary = researchData(
    await api.get_research_summary(accountId, {
      xray_run_id: query.xray,
      source_cutoff_at: query.cutoff,
      entity_id: query.entity,
      event_kind: query.event_kind === "all" ? undefined : query.event_kind,
      review_state: query.review_state,
      limit: 25,
      cursor: query.cursor,
    }),
  );
  assertResearchAccount(summary.pin.account_id, accountId);
  if (summary.pin.run_id !== query.xray) throw new ResearchQueryError();
  for (const item of summary.items) assertResearchItem(item, accountId);
  const pinned = { ...query, cutoff: summary.source_cutoff_at };
  return (
    <>
      <Surface>
        <h2>Exposure-ranked research</h2>
        <p>
          {summary.total} matching source revisions;{" "}
          {summary.unknown_exposure_total} have unavailable copied exposure.
        </p>
        <p>Research source cutoff: {summary.source_cutoff_at}</p>
        <p>
          Method: {summary.method} · {summary.method_version}
        </p>
        <ResearchPin pin={summary.pin} />
        {!summary.items.length ? (
          <Notice title="No eligible research items">
            No retained source revisions match these filters with current source
            access. Owner notes remain available in their own view.
          </Notice>
        ) : null}
      </Surface>
      {summary.items.map((item) => (
        <ResearchItem
          key={item.item_id}
          item={item}
          query={pinned}
          canWrite={canWrite}
        />
      ))}
      <Pagination
        query={pinned}
        field="cursor"
        page={summary}
        label="research items"
      />
    </>
  );
}
export async function ResearchPage({
  search,
}: Readonly<{ search: HistoricalSearch }>) {
  const access = await requireWebAccess();
  const header = (
    <PageHeader
      title="Research"
      description="Read source facts alongside saved portfolio exposure, maintain owner notes and review exact source revisions."
    />
  );
  if (access.isDemo)
    return (
      <div className="page-stack">
        {header}
        <Notice title="Research requires the connected runtime">
          Sign in to use retained source facts and account-owned notes.
        </Notice>
      </div>
    );
  const scopes = access.principal.scopes;
  if (
    !["portfolio:read", "analytics:read", "research:read"].every((scope) =>
      scopes.includes(scope),
    )
  )
    return (
      <div className="page-stack">
        {header}
        <Notice title="Research read access required">
          This workspace requires portfolio:read, analytics:read and
          research:read.
        </Notice>
      </div>
    );
  const clients = await researchClients();
  const accounts = await clients.portfolio.listAccounts();
  const selection = resolveAccountSelection(
    accounts,
    search.account,
    process.env.T212PI_ACCOUNT_ID,
  );
  if (!selection.account) return <AccountRequired selection={selection} />;
  const account = selection.account;
  let query: ResearchQuery;
  try {
    query = { ...readResearchQuery(search, new Date()), account: account.id };
  } catch (error) {
    if (!(error instanceof ResearchQueryError)) throw error;
    return (
      <AccountView accountId={account.id}>
        <div className="page-stack">
          {header}
          <Notice title="Invalid research selection">
            {error.message}{" "}
            <Link prefetch={false} href={`/research?account=${account.id}`}>
              Reset selection
            </Link>
          </Notice>
        </div>
      </AccountView>
    );
  }
  const result = await researchResult(() =>
    loadView(clients, query, account.id, scopes.includes("research:write")),
  );
  return (
    <AccountView accountId={account.id}>
      <div className={`page-stack ${styles.page}`}>
        {header}
        <nav className="historical-tabs" aria-label="Research views">
          <Link
            prefetch={false}
            aria-current={query.view === "summary" ? "page" : undefined}
            href={researchHref(query, {
              view: "summary",
              item: null,
              note: null,
            })}
          >
            Summary
          </Link>
          <Link
            prefetch={false}
            aria-current={query.view === "notes" ? "page" : undefined}
            href={researchHref(query, { view: "notes", item: null })}
          >
            Owner notes
          </Link>
        </nav>
        {query.view === "summary" ? <Selection query={query} /> : null}
        {result.ok ? (
          result.data
        ) : (
          <Notice title="Research unavailable">
            {result.message} ({result.code})
            <p>
              <Link
                prefetch={false}
                href={researchHref(query, {
                  cursor: null,
                  notes_cursor: null,
                  versions_cursor: null,
                })}
              >
                Reload current selection from the first page
              </Link>
            </p>
          </Notice>
        )}
      </div>
    </AccountView>
  );
}
