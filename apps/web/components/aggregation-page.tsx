import { AggregateApiError } from "@trading212/api-contracts";
import { Notice, Surface } from "@trading212/ui";
import { requireWebAccess } from "../lib/auth";
import { loadAvailableAccounts } from "../lib/api-adapter";
import {
  aggregationClients,
  aggregationData,
  aggregationResult,
} from "../lib/aggregation-adapter";
import {
  aggregationHref,
  readAggregationQuery,
  type AggregationQuery,
} from "../lib/aggregation-query";
import type { HistoricalSearch } from "../lib/historical-query";
import { formatDateTime } from "../lib/format";
import { PageHeader } from "./page-header";
import { AggregateSelectionForm, AggregateRunForm } from "./aggregation-forms";
import { AggregateResult } from "./aggregation-result";
import Link from "./navigation-intent";
import styles from "./aggregation.module.css";
export async function AggregationPage({
  search,
}: Readonly<{ search: HistoricalSearch }>) {
  const access = await requireWebAccess();
  const header = (
    <PageHeader
      title="Account aggregation"
      description="Combine exact saved accounts with original valuation dates, source provenance and visible conversion coverage."
    />
  );
  if (
    access.isDemo ||
    !["portfolio:read", "analytics:read", "aggregate:read"].every((scope) =>
      access.principal.scopes.includes(scope),
    )
  )
    return (
      <div className={styles.stack}>
        {header}
        <Notice title="Aggregation access required">
          Connect the local API and use current portfolio, analytics and
          aggregate access.
        </Notice>
      </div>
    );
  let query: AggregationQuery;
  try {
    query = readAggregationQuery(search);
  } catch {
    return (
      <div className={styles.stack}>
        {header}
        <Notice title="Invalid aggregate selection">
          <Link prefetch={false} href="/aggregation">
            Return to aggregate selections
          </Link>
        </Notice>
      </div>
    );
  }
  const canWrite = access.principal.scopes.includes("aggregate:write");
  const canReadActivity = access.principal.scopes.includes("activity:read");
  if (
    query.view === "result" &&
    query.table === "transfers" &&
    !canReadActivity
  )
    return (
      <div className={styles.stack}>
        {header}
        <Notice title="Activity access required">
          Transfer evidence requires current activity access for every included
          account.
        </Notice>
      </div>
    );
  const outcome = await aggregationResult(async () => {
    const clients = await aggregationClients();
    const pageQuery = {
      limit: 25,
      ...(query.cursor ? { cursor: query.cursor } : {}),
    };
    if (query.view === "selections")
      return {
        kind: "selections" as const,
        page: aggregationData(
          await clients.aggregates.list_aggregate_selections(pageQuery),
        ),
      };
    const accounts = await loadAvailableAccounts();
    if (query.view === "new") return { kind: "new" as const, accounts };
    const selection = aggregationData(
      await clients.aggregates.get_aggregate_selection(query.selection!),
    );
    if (selection.selection_id !== query.selection)
      throw new AggregateApiError(
        "INVALID_RESPONSE",
        502,
        "The saved selection could not be verified.",
      );
    if (query.view === "runs")
      return {
        kind: "runs" as const,
        accounts,
        selection,
        page: aggregationData(
          await clients.aggregates.list_aggregate_runs(
            selection.selection_id,
            pageQuery,
          ),
        ),
      };
    const value = aggregationData(
      await clients.aggregates.get_aggregate_run(query.run!, {
        ...pageQuery,
        view: query.table,
      }),
    );
    if (
      value.run.run_id !== query.run ||
      value.run.selection_id !== selection.selection_id ||
      (value.page && value.page.view !== query.table)
    )
      throw new AggregateApiError(
        "INVALID_RESPONSE",
        502,
        "The aggregate response does not match the selected immutable context.",
      );
    return { kind: "result" as const, accounts, selection, value };
  });
  const toolbar = (
    <nav className={styles.toolbar} aria-label="Aggregation navigation">
      <Link href="/aggregation" prefetch={false}>
        Aggregate selections
      </Link>
      {canWrite ? (
        <Link
          href={aggregationHref({ view: "new", account: query.account })}
          prefetch={false}
        >
          New aggregate
        </Link>
      ) : null}
      {query.selection ? (
        <Link
          href={aggregationHref({
            view: "runs",
            selection: query.selection,
            account: query.account,
          })}
          prefetch={false}
        >
          Selection and calculations
        </Link>
      ) : null}
    </nav>
  );
  if (!outcome.ok)
    return (
      <div className={styles.stack}>
        {header}
        {toolbar}
        <Notice title="Aggregate unavailable">{outcome.message}</Notice>
      </div>
    );
  const result = outcome.data;
  if (result.kind === "new")
    return (
      <div className={styles.stack}>
        {header}
        {toolbar}
        {canWrite ? (
          <Surface>
            <AggregateSelectionForm
              key={query.account ?? "owner"}
              accounts={result.accounts}
              cutoff={new Date().toISOString()}
            />
          </Surface>
        ) : (
          <Notice title="Aggregate write access required">
            Current aggregate write access is required to save a selection.
          </Notice>
        )}
      </div>
    );
  if (result.kind === "selections")
    return (
      <div className={styles.stack}>
        {header}
        {toolbar}
        <Surface>
          <h2>Saved aggregate selections</h2>
          {!result.page.items.length ? (
            <p>
              No saved selections. Choose accounts and immutable snapshots to
              create one.
            </p>
          ) : (
            <ul>
              {result.page.items.map((selection) => (
                <li key={selection.selection_id}>
                  <Link
                    prefetch={false}
                    href={aggregationHref({
                      view: "runs",
                      selection: selection.selection_id,
                      account: query.account,
                    })}
                  >
                    {selection.content.name}
                  </Link>
                  <p>
                    {selection.content.members.length} accounts ·{" "}
                    {selection.content.reporting_currency} · cutoff{" "}
                    {formatDateTime(selection.content.source_cutoff_at)}
                  </p>
                </li>
              ))}
            </ul>
          )}
          <p>{result.page.total} retained selections.</p>
          {result.page.next_cursor ? (
            <Link
              prefetch={false}
              href={aggregationHref({
                ...query,
                cursor: result.page.next_cursor,
              })}
            >
              Next selections page
            </Link>
          ) : null}
        </Surface>
      </div>
    );
  const selection = result.selection;
  return (
    <div className={styles.stack}>
      {header}
      {toolbar}
      <Surface>
        <h2>{selection.content.name}</h2>
        <p>
          {selection.content.reporting_currency} · cutoff{" "}
          {formatDateTime(selection.content.source_cutoff_at)} · operational
          revision {selection.revision}
        </p>
        <ul>
          {selection.content.members.map((member) => (
            <li key={member.account_id} className={styles.proof}>
              {result.accounts.find(
                (account) => account.id === member.account_id,
              )?.display_name ?? member.account_id}
              : saved snapshot {member.portfolio_snapshot_id}
            </li>
          ))}
        </ul>
        <p className={styles.proof}>
          Immutable selection digest: {selection.content_digest}
        </p>
      </Surface>
      {result.kind === "result" ? (
        <AggregateResult
          value={result.value}
          query={query}
          accounts={result.accounts}
          canReadActivity={canReadActivity}
        />
      ) : (
        <>
          {canWrite ? (
            <Surface>
              <AggregateRunForm
                key={selection.selection_id}
                selection={selection}
                accounts={result.accounts}
                canReadActivity={canReadActivity}
              />
            </Surface>
          ) : null}
          <Surface>
            <h2>Saved calculations</h2>
            {result.page.items.length ? (
              <ul>
                {result.page.items.map((run) => (
                  <li key={run.run_id}>
                    <Link
                      href={aggregationHref({
                        view: "result",
                        selection: selection.selection_id,
                        run: run.run_id,
                        account: query.account,
                      })}
                      prefetch={false}
                    >
                      {formatDateTime(run.created_at)} · {run.state}
                    </Link>
                    <p>
                      Retention deadline: {formatDateTime(run.expires_at)} ·
                      activity{" "}
                      {run.activity_requested ? "included" : "not requested"}
                    </p>
                  </li>
                ))}
              </ul>
            ) : (
              <p>No calculations have been saved for this selection.</p>
            )}
            {result.page.next_cursor ? (
              <Link
                href={aggregationHref({
                  ...query,
                  cursor: result.page.next_cursor,
                })}
                prefetch={false}
              >
                Next calculations page
              </Link>
            ) : null}
          </Surface>
        </>
      )}
    </div>
  );
}
