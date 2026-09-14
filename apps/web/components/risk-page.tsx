import type { ReactNode } from "react";
import type { RiskVersionResponse } from "@trading212/api-contracts";
import { Notice, Surface } from "@trading212/ui";
import { requireWebAccess } from "../lib/auth";
import { resolveAccountSelection } from "../lib/account-selection";
import {
  assertRiskAccount,
  riskClients,
  riskData,
  riskResult,
} from "../lib/risk-adapter";
import { historicalData } from "../lib/historical-adapter";
import { sourceData } from "../lib/source-adapter";
import { xrayData } from "../lib/xray-adapter";
import {
  readRiskQuery,
  riskHref,
  riskWindow,
  RiskQueryError,
  type RiskQuery,
} from "../lib/risk-query";
import type { HistoricalSearch } from "../lib/historical-query";
import { AccountRequired, AccountView } from "./account-context";
import Link from "./navigation-intent";
import { PageHeader } from "./page-header";
import { RiskDefinitionForm, RiskRunForm, RiskJobControls } from "./risk-forms";
import { RiskSelectionForm } from "./risk-selection";
import { HistoricalContextDetails } from "./historical-results";
import { RiskResults } from "./risk-results";

type Clients = Awaited<ReturnType<typeof riskClients>>;
type Cursor =
  | "definitions_cursor"
  | "versions_cursor"
  | "runs_cursor"
  | "sources_cursor"
  | "snapshots_cursor"
  | "benchmarks_cursor";
function Pagination({
  query,
  field,
  page,
  label,
}: Readonly<{
  query: RiskQuery;
  field: Cursor;
  page: {
    total: number;
    next_cursor: string | null;
    items: readonly unknown[];
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
          href={riskHref(query, { [field]: page.next_cursor })}
        >
          Next {label}
        </Link>
      ) : null}
      {query[field] ? (
        <Link prefetch={false} href={riskHref(query, { [field]: null })}>
          First {label}
        </Link>
      ) : null}
    </nav>
  );
}
function Tabs({ query }: Readonly<{ query: RiskQuery }>) {
  return (
    <nav className="historical-tabs" aria-label="Risk views">
      {(
        [
          ["runs", "Runs"],
          ["definitions", "Definitions"],
          ["new", "New analysis"],
        ] as const
      ).map(([view, label]) => (
        <Link
          key={view}
          prefetch={false}
          aria-current={query.view === view ? "page" : undefined}
          href={riskHref(query, { view, run: null })}
        >
          {label}
        </Link>
      ))}
    </nav>
  );
}
async function selectedDefinition(
  clients: Clients,
  query: RiskQuery,
  accountId: string,
) {
  const version = query.version
    ? riskData(await clients.risk.get_risk_version(query.version))
    : undefined;
  if (version) assertRiskAccount(version.account_id, accountId);
  const definitionId = query.definition ?? version?.definition_id;
  if (!definitionId) return null;
  const definition = riskData(
    await clients.risk.get_risk_definition(definitionId),
  );
  assertRiskAccount(definition.account_id, accountId);
  if (version && version.definition_id !== definition.id)
    throw new RiskQueryError();
  const [versions, current] = await Promise.all([
    clients.risk
      .list_risk_versions(definition.id, {
        limit: 25,
        cursor: query.versions_cursor,
      })
      .then(riskData),
    version
      ? Promise.resolve(version)
      : clients.risk
          .get_risk_version(definition.current_version_id)
          .then(riskData),
  ]);
  for (const row of [...versions.items, current]) {
    assertRiskAccount(row.account_id, accountId);
    if (row.definition_id !== definition.id) throw new RiskQueryError();
  }
  return { definition, version: current, versions };
}
async function loadRiskView(
  clients: Clients,
  query: RiskQuery,
  accountId: string,
  canWrite: boolean,
): Promise<ReactNode> {
  if (query.view === "result" && query.run) {
    const run = riskData(await clients.risk.get_risk_run(query.run));
    assertRiskAccount(run.account_id, accountId);
    return (
      <>
        <Surface>
          <h2>Risk run</h2>
          <p className="risk-digest">{run.id}</p>
          <p>
            State: {run.state} · Result: {run.result_availability}
          </p>
          <RiskJobControls key={run.id} run={run} canWrite={canWrite} />
        </Surface>
        <RiskResults run={run} />
      </>
    );
  }
  if (query.view === "runs") {
    const page = riskData(
      await clients.risk.list_risk_runs(accountId, {
        limit: 25,
        cursor: query.runs_cursor,
      }),
    );
    for (const row of page.items) assertRiskAccount(row.account_id, accountId);
    return (
      <Surface>
        <h2>Retained risk analyses</h2>
        {page.items.length ? (
          <div
            className="table-scroll"
            role="region"
            tabIndex={0}
            aria-label="Retained risk analyses"
          >
            <table className="data-table">
              <caption>Retained risk runs</caption>
              <thead>
                <tr>
                  <th>Created</th>
                  <th>State</th>
                  <th>Result</th>
                  <th>Analysis</th>
                </tr>
              </thead>
              <tbody>
                {page.items.map((row) => (
                  <tr key={row.id}>
                    <td>{row.created_at}</td>
                    <td>{row.state}</td>
                    <td>{row.result_availability}</td>
                    <td>
                      <Link
                        prefetch={false}
                        href={riskHref(query, { view: "result", run: row.id })}
                      >
                        Open analysis{" "}
                        <span className="ui-visually-hidden">{row.id}</span>
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Notice title="No risk runs yet">
            Create a risk definition and prepare a historical analysis to begin.
          </Notice>
        )}
        <Pagination
          query={query}
          field="runs_cursor"
          page={page}
          label="runs"
        />
      </Surface>
    );
  }
  const [definitions, selected, sources] = await Promise.all([
    clients.risk
      .list_risk_definitions(accountId, {
        limit: 25,
        cursor: query.definitions_cursor,
      })
      .then(riskData),
    selectedDefinition(clients, query, accountId),
    clients.sources
      .get_market_source_status(accountId, {
        start: query.start,
        end: query.end,
        source_cutoff_at: query.cutoff,
        limit: 25,
        cursor: query.sources_cursor,
      })
      .then(sourceData),
  ]);
  for (const row of definitions.items)
    assertRiskAccount(row.account_id, accountId);
  assertRiskAccount(sources.account_id, accountId);
  const selectedQuery = {
    ...query,
    ...(selected
      ? { definition: selected.definition.id, version: selected.version.id }
      : {}),
  };
  const definitionList = (
    <Surface>
      <h2>Risk definitions</h2>
      <ul>
        {definitions.items.map((row) => (
          <li key={row.id}>
            <Link
              prefetch={false}
              href={riskHref(query, {
                definition: row.id,
                version: row.current_version_id,
                versions_cursor: null,
              })}
            >
              {row.name} · version {row.revision}
            </Link>
          </li>
        ))}
      </ul>
      {!definitions.items.length ? (
        <p>No saved definitions for this account.</p>
      ) : null}
      <Pagination
        query={query}
        field="definitions_cursor"
        page={definitions}
        label="definitions"
      />
    </Surface>
  );
  const versionList = selected ? (
    <Surface>
      <h2>Version history</h2>
      <ul>
        {selected.versions.items.map((row) => (
          <li key={row.id}>
            <Link
              prefetch={false}
              aria-current={row.id === selected.version.id ? "true" : undefined}
              href={riskHref(selectedQuery, { version: row.id })}
            >
              Version {row.version_number} · {row.content.name} ·{" "}
              {row.created_at}
            </Link>
          </li>
        ))}
      </ul>
      <Pagination
        query={selectedQuery}
        field="versions_cursor"
        page={selected.versions}
        label="versions"
      />
    </Surface>
  ) : null;
  if (query.view === "definitions") {
    const calendars = [
      ...new Map(
        sources.series.items.map((row) => [
          `${row.series.calendar_id}:${row.series.calendar_version}`,
          { id: row.series.calendar_id, version: row.series.calendar_version },
        ]),
      ).values(),
    ];
    return (
      <>
        {definitionList}
        {versionList}
        <Surface>
          <h2>{selected ? "Revise assumptions" : "Create a definition"}</h2>
          {selected ? (
            <Link
              prefetch={false}
              href={riskHref(query, {
                definition: null,
                version: null,
                versions_cursor: null,
              })}
            >
              Create a separate definition
            </Link>
          ) : null}
          <RiskDefinitionForm
            key={`${accountId}:${selected?.version.id ?? "new"}`}
            accountId={accountId}
            query={selectedQuery}
            calendars={calendars}
            definition={selected?.definition}
            version={selected?.version}
            canWrite={canWrite}
          />
          <Pagination
            query={selectedQuery}
            field="sources_cursor"
            page={sources.series}
            label="sources"
          />
        </Surface>
      </>
    );
  }
  if (!selected)
    return (
      <>
        {definitionList}
        <Notice title="Choose a risk definition">
          Select a saved definition above, or create one in Definitions.
        </Notice>
      </>
    );
  const [snapshots, snapshot, benchmarks] = await Promise.all([
    clients.portfolio.listSnapshots(accountId, {
      limit: 25,
      cursor: query.snapshots_cursor ?? undefined,
    }),
    query.snapshot
      ? clients.portfolio.getSnapshot(accountId, query.snapshot)
      : clients.portfolio.getLatestSnapshot(accountId),
    clients.sources
      .list_benchmark_definitions({
        limit: 25,
        cursor: query.benchmarks_cursor,
        state: "active",
      })
      .then(sourceData),
  ]);
  const preparedQuery = { ...selectedQuery, snapshot: snapshot.id };
  const versionChoices: RiskVersionResponse[] = selected.versions.items.some(
    (row) => row.id === selected.version.id,
  )
    ? selected.versions.items
    : [selected.version, ...selected.versions.items];
  const snapshotChoices = snapshots.items.some((row) => row.id === snapshot.id)
    ? snapshots.items
    : [snapshot, ...snapshots.items];
  const preparation = await riskResult(async () => {
    const options = {
      ...riskWindow(query),
      input_snapshot_id: query.capture,
      frequency: selected.version.content.frequency ?? "daily",
    };
    const history = query.benchmark
      ? historicalData(
          await clients.historical.get_benchmark_comparison(accountId, {
            ...options,
            benchmark_version_id: query.benchmark,
          }),
        ).context
      : historicalData(
          await clients.historical.get_performance_summary(accountId, {
            ...options,
            method: "twr",
          }),
        ).context;
    assertRiskAccount(history.account_id, accountId);
    const xray =
      query.xray_mode === "capture" || query.xray
        ? xrayData(
            await clients.xray.get_effective_exposure(accountId, {
              snapshot_id: snapshot.id,
              source_cutoff_at: query.cutoff,
              reporting_currency: query.currency,
              dimension: "company",
              limit: 1,
              run_id: query.xray,
            }),
          ).context
        : null;
    if (xray) assertRiskAccount(xray.account_id, accountId);
    return {
      history,
      xray,
      body: {
        definition_version_id: selected.version.id,
        portfolio_snapshot_id: snapshot.id,
        historical_input_snapshot_id: history.input_snapshot_id,
        window: riskWindow(query),
        benchmark_version_id: query.benchmark ?? null,
        xray_run_id: xray?.run_id ?? null,
      },
    };
  });
  const pinnedQuery = preparation.ok
    ? {
        ...preparedQuery,
        capture: preparation.data.history.input_snapshot_id,
        xray: preparation.data.xray?.run_id,
      }
    : preparedQuery;
  return (
    <>
      {definitionList}
      {versionList}
      <Surface>
        <h2>Period and sources</h2>
        <RiskSelectionForm
          key={JSON.stringify(preparedQuery)}
          query={preparedQuery}
          versions={versionChoices}
          snapshots={snapshotChoices}
          benchmarks={benchmarks.items.flatMap((row) =>
            row.latest_version_id
              ? [
                  {
                    id: row.latest_version_id,
                    label: `${row.name} · ${row.reporting_currency}`,
                  },
                ]
              : [],
          )}
        />
        <Pagination
          query={pinnedQuery}
          field="snapshots_cursor"
          page={snapshots}
          label="snapshots"
        />
        <Pagination
          query={pinnedQuery}
          field="benchmarks_cursor"
          page={benchmarks}
          label="benchmarks"
        />
      </Surface>
      {preparation.ok ? (
        <Surface>
          <h2>Prepared immutable inputs</h2>
          <dl className="risk-provenance">
            <dt>Definition</dt>
            <dd>
              {selected.version.content.name} · version{" "}
              {selected.version.version_number}
            </dd>
            <dt>Snapshot valuation</dt>
            <dd>{snapshot.valuation_at}</dd>
            <dt>Historical capture</dt>
            <dd className="risk-digest">
              {preparation.data.history.input_snapshot_id}
            </dd>
            <dt>Source cutoff</dt>
            <dd>{query.cutoff}</dd>
            <dt>X-ray capture</dt>
            <dd className="risk-digest">
              {preparation.data.xray?.run_id ??
                "Omitted; look-through concentration unavailable"}
            </dd>
          </dl>
          <HistoricalContextDetails context={preparation.data.history} />
          <RiskRunForm
            key={JSON.stringify(preparation.data.body)}
            accountId={accountId}
            query={pinnedQuery}
            prepared={preparation.data.body}
            sources={sources.series.items}
            canWrite={canWrite}
          />
          <Pagination
            query={pinnedQuery}
            field="sources_cursor"
            page={sources.series}
            label="sources"
          />
        </Surface>
      ) : (
        <Notice title="Risk inputs unavailable">
          {preparation.message} ({preparation.code})
        </Notice>
      )}
    </>
  );
}
export async function RiskPage({
  search,
}: Readonly<{ search: HistoricalSearch }>) {
  const access = await requireWebAccess();
  const header = (
    <PageHeader
      title="Risk"
      description="Inspect observed historical risk, model current-weight exposure and keep every analysis tied to its assumptions and sources."
    />
  );
  if (access.isDemo)
    return (
      <div className="page-stack">
        {header}
        <Notice title="Risk analysis requires the connected runtime">
          Sign in to the local API to use retained historical inputs and
          persisted risk analyses.
        </Notice>
      </div>
    );
  const clients = await riskClients();
  const accounts = await clients.portfolio.listAccounts();
  const selection = resolveAccountSelection(
    accounts,
    search.account,
    process.env.T212PI_ACCOUNT_ID,
  );
  if (!selection.account) return <AccountRequired selection={selection} />;
  const account = selection.account;
  let query: RiskQuery;
  try {
    query = {
      ...readRiskQuery(search, {
        now: new Date(),
        currency: account.reporting_currency,
      }),
      account: account.id,
    };
  } catch (error) {
    if (!(error instanceof RiskQueryError)) throw error;
    return (
      <AccountView accountId={account.id}>
        <div className="page-stack">
          {header}
          <Notice title="Invalid risk filters">
            {error.message}{" "}
            <Link prefetch={false} href={`/risk?account=${account.id}`}>
              Reset filters
            </Link>
          </Notice>
        </div>
      </AccountView>
    );
  }
  const result = await riskResult(async () => {
    try {
      return await loadRiskView(
        clients,
        query,
        account.id,
        access.principal.scopes.includes("risk:write"),
      );
    } catch (error) {
      if (error instanceof RiskQueryError)
        return <Notice title="Invalid risk selections">{error.message}</Notice>;
      throw error;
    }
  });
  return (
    <AccountView accountId={account.id}>
      <div className="page-stack historical-page risk-page">
        {header}
        <Tabs query={query} />
        {result.ok ? (
          result.data
        ) : (
          <Notice title="Risk analysis unavailable">
            {result.message} ({result.code})
          </Notice>
        )}
      </div>
    </AccountView>
  );
}
