import type { ReactNode } from "react";
import {
  CreateScenarioRunRequestSchema,
  ScenarioApiError,
  type ScenarioRunResponse,
} from "@trading212/api-contracts";
import { Button, Notice, Surface } from "@trading212/ui";
import { requireWebAccess } from "../lib/auth";
import { resolveAccountSelection } from "../lib/account-selection";
import {
  assertScenarioAccount,
  scenarioClients,
  scenarioData,
  scenarioResult,
  savedScenarioXray,
} from "../lib/scenario-adapter";
import {
  readScenarioQuery,
  scenarioHref,
  ScenarioQueryError,
  type ScenarioQuery,
} from "../lib/scenario-query";
import type { HistoricalSearch } from "../lib/historical-query";
import { AccountRequired, AccountView } from "./account-context";
import Link from "./navigation-intent";
import { PageHeader } from "./page-header";
import { ScenarioDefinitionForm } from "./scenario-editor";
import { ScenarioRunForm, ScenarioJobControls } from "./scenario-forms";
import { ScenarioResults, ScenarioComparison } from "./scenario-results";
import styles from "./scenario-workspace.module.css";

type Clients = Awaited<ReturnType<typeof scenarioClients>>;
type Cursor =
  "definitions_cursor" | "versions_cursor" | "runs_cursor" | "snapshots_cursor";
function Pagination({
  query,
  field,
  page,
  label,
}: Readonly<{
  query: ScenarioQuery;
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
          href={scenarioHref(query, { [field]: page.next_cursor })}
        >
          Next {label}
        </Link>
      ) : null}
      {query[field] ? (
        <Link prefetch={false} href={scenarioHref(query, { [field]: null })}>
          First {label}
        </Link>
      ) : null}
    </nav>
  );
}
function Tabs({ query }: Readonly<{ query: ScenarioQuery }>) {
  return (
    <nav className="historical-tabs" aria-label="Scenario views">
      {(
        [
          ["runs", "Runs"],
          ["definitions", "Definitions"],
          ["new", "New run"],
          ["compare", "Compare"],
        ] as const
      ).map(([view, label]) => (
        <Link
          key={view}
          prefetch={false}
          aria-current={query.view === view ? "page" : undefined}
          href={scenarioHref(query, {
            view,
            run: null,
            component_cursor: null,
          })}
        >
          {label}
        </Link>
      ))}
    </nav>
  );
}
async function selectedDefinition(
  clients: Clients,
  query: ScenarioQuery,
  accountId: string,
) {
  const chosen = query.version
    ? scenarioData(await clients.scenarios.get_scenario_version(query.version))
    : undefined;
  if (chosen) assertScenarioAccount(chosen.account_id, accountId);
  const definitionId = query.definition ?? chosen?.definition_id;
  if (!definitionId) return null;
  const definition = scenarioData(
    await clients.scenarios.get_scenario(definitionId),
  );
  assertScenarioAccount(definition.account_id, accountId);
  if (chosen && chosen.definition_id !== definition.id)
    throw new ScenarioQueryError();
  const [versions, version] = await Promise.all([
    clients.scenarios
      .list_scenario_versions(definition.id, {
        limit: 25,
        cursor: query.versions_cursor,
      })
      .then(scenarioData),
    chosen
      ? Promise.resolve(chosen)
      : clients.scenarios
          .get_scenario_version(definition.current_version_id)
          .then(scenarioData),
  ]);
  for (const row of [...versions.items, version]) {
    assertScenarioAccount(row.account_id, accountId);
    if (row.definition_id !== definition.id) throw new ScenarioQueryError();
  }
  return { definition, version, versions };
}
function ComparisonSelection({
  query,
  runs,
}: Readonly<{ query: ScenarioQuery; runs: readonly ScenarioRunResponse[] }>) {
  return (
    <Surface>
      <h2>Choose two saved results</h2>
      <p>
        Select two succeeded runs for this account. Compatibility is checked
        against their saved bases, including snapshot and currency.
      </p>
      <form action="/scenarios" method="get" className={styles.form}>
        <input type="hidden" name="account" value={query.account} />
        <input type="hidden" name="view" value="compare" />
        <div className={styles.fields}>
          {(
            [
              ["before", "First saved run"],
              ["after", "Second saved run"],
            ] as const
          ).map(([name, label]) => (
            <label key={name}>
              <span>{label}</span>
              <input
                name={name}
                defaultValue={query[name] ?? ""}
                required
                maxLength={36}
                list="scenario-saved-runs"
                autoComplete="off"
              />
            </label>
          ))}
        </div>
        <datalist id="scenario-saved-runs">
          {runs
            .filter(
              (run) =>
                run.state === "succeeded" &&
                run.result_availability !== "expired" &&
                run.result_availability !== "unavailable",
            )
            .map((run) => (
              <option key={run.id} value={run.id}>
                {run.created_at}
              </option>
            ))}
        </datalist>
        <Button type="submit">Compare saved results</Button>
      </form>
      <p>
        Suggestions contain this page of runs. An exact saved run ID can also be
        entered.
      </p>
    </Surface>
  );
}
async function loadView(
  clients: Clients,
  query: ScenarioQuery,
  accountId: string,
  canWrite: boolean,
  canReplay: boolean,
): Promise<ReactNode> {
  const api = clients.scenarios;
  if (query.view === "result" && query.run) {
    const run = scenarioData(
      await api.get_scenario_run(query.run, {
        component_limit: 25,
        component_cursor: query.component_cursor,
      }),
    );
    assertScenarioAccount(run.account_id, accountId);
    if (run.id !== query.run) throw new ScenarioQueryError();
    return (
      <>
        <Surface>
          <h2>Saved scenario run</h2>
          <dl className={styles.context}>
            <dt>Run</dt>
            <dd>{run.id}</dd>
            <dt>State / result</dt>
            <dd>
              {run.state} / {run.result_availability}
            </dd>
            <dt>Created / expires</dt>
            <dd>
              {run.created_at} / {run.expires_at}
            </dd>
            <dt>Assumption version</dt>
            <dd>{run.scenario_version_id}</dd>
          </dl>
          <ScenarioJobControls
            key={`${accountId}:${run.id}`}
            run={run}
            canWrite={canWrite}
          />
          {run.result ? (
            <Link
              prefetch={false}
              href={scenarioHref(query, {
                view: "compare",
                before: run.id,
                after: null,
                component_cursor: null,
              })}
            >
              Compare this saved result
            </Link>
          ) : null}
        </Surface>
        <ScenarioResults run={run} query={query} />
      </>
    );
  }
  if (query.view === "runs" || query.view === "compare") {
    const runs = scenarioData(
      await api.list_scenario_runs(accountId, {
        limit: 25,
        cursor: query.runs_cursor,
      }),
    );
    for (const run of runs.items)
      assertScenarioAccount(run.account_id, accountId);
    if (query.view === "compare") {
      const comparison =
        query.before && query.after
          ? scenarioData(
              await api.compare_scenarios(accountId, {
                run_ids: [query.before, query.after],
                component_limit: 25,
                component_cursor: query.component_cursor,
              }),
            )
          : null;
      if (comparison) {
        assertScenarioAccount(comparison.before.pins.account_id, accountId);
        assertScenarioAccount(comparison.after.pins.account_id, accountId);
        if (
          comparison.before.run_id !== query.before ||
          comparison.after.run_id !== query.after
        )
          throw new ScenarioQueryError();
      }
      return (
        <>
          <ComparisonSelection
            key={`${accountId}:${query.before}:${query.after}`}
            query={query}
            runs={runs.items}
          />
          <Pagination
            query={query}
            field="runs_cursor"
            page={runs}
            label="run suggestions"
          />
          {comparison ? (
            <ScenarioComparison value={comparison} query={query} />
          ) : null}
        </>
      );
    }
    return (
      <Surface>
        <h2>Retained scenario runs</h2>
        {runs.items.length ? (
          <div
            className="table-scroll"
            role="region"
            tabIndex={0}
            aria-label="Retained scenario runs"
          >
            <table className="data-table">
              <caption>Saved scenario jobs and results</caption>
              <thead>
                <tr>
                  <th scope="col">Created</th>
                  <th scope="col">State</th>
                  <th scope="col">Result</th>
                  <th scope="col">Run</th>
                </tr>
              </thead>
              <tbody>
                {runs.items.map((run) => (
                  <tr key={run.id}>
                    <td>{run.created_at}</td>
                    <td>{run.state}</td>
                    <td>{run.result_availability}</td>
                    <td>
                      <Link
                        prefetch={false}
                        href={scenarioHref(query, {
                          view: "result",
                          run: run.id,
                          component_cursor: null,
                        })}
                      >
                        Open scenario{" "}
                        <span className="ui-visually-hidden">{run.id}</span>
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Notice title="No scenario runs yet">
            Create an assumption definition, then choose an existing saved X-ray
            and snapshot in New run.
          </Notice>
        )}
        <Pagination
          query={query}
          field="runs_cursor"
          page={runs}
          label="runs"
        />
      </Surface>
    );
  }
  const [definitions, selected] = await Promise.all([
    api
      .list_scenarios(accountId, {
        limit: 25,
        cursor: query.definitions_cursor,
      })
      .then(scenarioData),
    selectedDefinition(clients, query, accountId),
  ]);
  for (const definition of definitions.items)
    assertScenarioAccount(definition.account_id, accountId);
  const selectedQuery = {
    ...query,
    ...(selected
      ? { definition: selected.definition.id, version: selected.version.id }
      : {}),
  };
  const definitionsView = (
    <Surface>
      <h2>Scenario definitions</h2>
      {definitions.items.length ? (
        <ul>
          {definitions.items.map((definition) => (
            <li key={definition.id}>
              <Link
                prefetch={false}
                href={scenarioHref(query, {
                  definition: definition.id,
                  version: definition.current_version_id,
                  versions_cursor: null,
                })}
              >
                {definition.name} · revision {definition.revision}
                {definition.archived ? " · Archived" : ""}
              </Link>
            </li>
          ))}
        </ul>
      ) : (
        <p>No definitions saved for this account.</p>
      )}
      <Pagination
        query={query}
        field="definitions_cursor"
        page={definitions}
        label="definitions"
      />
    </Surface>
  );
  const history = selected ? (
    <Surface>
      <h2>Version history</h2>
      <p>
        Versions are immutable. Saving edited assumptions creates a new version.
      </p>
      <ul>
        {selected.versions.items.map((version) => (
          <li key={version.id}>
            <Link
              prefetch={false}
              aria-current={
                version.id === selected.version.id ? "true" : undefined
              }
              href={scenarioHref(selectedQuery, { version: version.id })}
            >
              Version {version.version_number} · {version.content.name} ·{" "}
              {version.created_at}
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
  if (query.view === "definitions")
    return (
      <>
        {definitionsView}
        {history}
        <Surface>
          <h2>{selected ? "Revise assumptions" : "Create a definition"}</h2>
          {selected ? (
            <p>
              <Link
                prefetch={false}
                href={scenarioHref(query, {
                  definition: null,
                  version: null,
                  versions_cursor: null,
                })}
              >
                Create a separate definition
              </Link>
              {" · "}
              <Link
                prefetch={false}
                href={scenarioHref(selectedQuery, { view: "new" })}
              >
                Use selected version in a new run
              </Link>
            </p>
          ) : null}
          <ScenarioDefinitionForm
            key={`${accountId}:${selected?.version.id ?? "new"}:${selected?.definition.revision ?? 0}`}
            accountId={accountId}
            query={selectedQuery}
            definition={selected?.definition}
            version={selected?.version}
            canWrite={canWrite && !selected?.definition.archived}
          />
        </Surface>
      </>
    );
  if (!selected)
    return (
      <>
        {definitionsView}
        <Notice title="Choose an assumption version">
          Select a saved scenario definition, or create one in Definitions.
        </Notice>
      </>
    );
  const [snapshots, snapshot] = await Promise.all([
    clients.portfolio.listSnapshots(accountId, {
      limit: 25,
      cursor: query.snapshots_cursor ?? undefined,
    }),
    query.snapshot
      ? clients.portfolio.getSnapshot(accountId, query.snapshot)
      : Promise.resolve(null),
  ]);
  const choices =
    snapshot && !snapshots.items.some((item) => item.id === snapshot.id)
      ? [snapshot, ...snapshots.items]
      : snapshots.items;
  const hasPins = Boolean(query.snapshot && query.xray);
  const preparation = hasPins
    ? await scenarioResult(async () => {
        const parsed = CreateScenarioRunRequestSchema.safeParse({
          scenario_version_id: selected.version.id,
          portfolio_snapshot_id: query.snapshot,
          xray_run_id: query.xray,
          reporting_currency: query.currency,
          source_cutoff_at: query.cutoff,
          replay:
            query.replay === "historical"
              ? {
                  historical_input_snapshot_id: query.capture,
                  start_date: query.start_date,
                  end_date: query.end_date,
                  market_knowledge_cutoff_at: query.market_cutoff,
                  holdings_basis: query.holdings,
                  knowledge_basis: query.knowledge,
                }
              : null,
        });
        if (!parsed.success)
          throw new ScenarioApiError(
            "VALIDATION_FAILED",
            422,
            "Complete the saved IDs and replay window before admission.",
          );
        const context = await savedScenarioXray(
          clients,
          accountId,
          parsed.data,
        );
        return { body: parsed.data, context };
      })
    : null;
  return (
    <>
      {definitionsView}
      {history}
      <Surface>
        <h2>Select saved inputs</h2>
        <p>
          Use an existing X-ray run with its exact snapshot, reporting currency
          and knowledge cutoff.{" "}
          <Link
            prefetch={false}
            href={`/xray?account=${encodeURIComponent(accountId)}`}
          >
            Open portfolio X-ray
          </Link>{" "}
          to inspect a saved result.
        </p>
        <form
          key={JSON.stringify(selectedQuery)}
          action="/scenarios"
          method="get"
          className={styles.form}
        >
          <input type="hidden" name="account" value={accountId} />
          <input type="hidden" name="view" value="new" />
          <input
            type="hidden"
            name="definition"
            value={selected.definition.id}
          />
          <input type="hidden" name="version" value={selected.version.id} />
          <div className={styles.fields}>
            <label>
              <span>Portfolio snapshot</span>
              <select
                name="snapshot"
                defaultValue={query.snapshot ?? ""}
                required
              >
                <option value="">Choose a saved snapshot</option>
                {choices.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.valuation_at} · {item.reporting_currency} · {item.id}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span>Saved X-ray run ID</span>
              <input
                name="xray"
                defaultValue={query.xray ?? ""}
                required
                maxLength={36}
                autoComplete="off"
              />
            </label>
            <label>
              <span>Reporting currency</span>
              <input
                name="currency"
                defaultValue={query.currency}
                required
                pattern="[A-Z]{3}"
                maxLength={3}
              />
            </label>
            <label>
              <span>X-ray knowledge cutoff (ISO timestamp)</span>
              <input
                name="cutoff"
                defaultValue={query.cutoff}
                required
                maxLength={40}
                aria-describedby="scenario-cutoff-help"
              />
            </label>
          </div>
          <p id="scenario-cutoff-help">
            Keep the saved timestamp, including its timezone and fractional
            seconds.
          </p>
          <label>
            <span>Run basis</span>
            <select name="replay" defaultValue={query.replay}>
              <option value="none">Hypothetical shocks</option>
              <option value="historical">Historical replay</option>
            </select>
          </label>
          <details open={query.replay === "historical"}>
            <summary>Historical replay inputs</summary>
            <p>
              Replay requires an existing historical input capture and a version
              containing no hypothetical shocks. Exclusions still apply.
              Holdings and market knowledge are independently pinned.
            </p>
            <div className={styles.fields}>
              <label>
                <span>Historical input capture ID</span>
                <input
                  name="capture"
                  defaultValue={query.capture ?? ""}
                  maxLength={36}
                  autoComplete="off"
                />
              </label>
              <label>
                <span>Replay start date</span>
                <input
                  name="start_date"
                  type="date"
                  defaultValue={query.start_date}
                  required
                />
              </label>
              <label>
                <span>Replay end date</span>
                <input
                  name="end_date"
                  type="date"
                  defaultValue={query.end_date}
                  required
                />
              </label>
              <label>
                <span>Market knowledge cutoff (ISO timestamp)</span>
                <input
                  name="market_cutoff"
                  defaultValue={query.market_cutoff}
                  required
                  maxLength={40}
                />
              </label>
              <label>
                <span>Holdings basis</span>
                <select name="holdings" defaultValue={query.holdings}>
                  <option value="current_holdings">
                    Current holdings counterfactual
                  </option>
                  <option value="historical_holdings">
                    Historical holdings with retained evidence
                  </option>
                </select>
              </label>
              <label>
                <span>Knowledge basis</span>
                <select name="knowledge" defaultValue={query.knowledge}>
                  <option value="point_in_time">Point in time</option>
                  <option value="retrospective">Retrospective</option>
                </select>
              </label>
            </div>
          </details>
          <Button type="submit" variant="secondary">
            Verify saved input pins
          </Button>
        </form>
        <Pagination
          query={selectedQuery}
          field="snapshots_cursor"
          page={snapshots}
          label="snapshots"
        />
      </Surface>
      {preparation?.ok ? (
        <Surface>
          <h2>Verified saved X-ray selection</h2>
          <dl className={styles.context}>
            <dt>Assumptions</dt>
            <dd>
              {selected.version.content.name} · version{" "}
              {selected.version.version_number}
            </dd>
            <dt>Snapshot / valuation</dt>
            <dd>
              {preparation.data.context.snapshot_id} / {snapshot?.valuation_at}
            </dd>
            <dt>X-ray run</dt>
            <dd>{preparation.data.context.run_id}</dd>
            <dt>Reporting currency</dt>
            <dd>{preparation.data.context.reporting_currency}</dd>
            <dt>Source cutoff</dt>
            <dd>{preparation.data.context.source_cutoff_at}</dd>
            <dt>Run basis</dt>
            <dd>
              {query.replay === "historical"
                ? "Historical replay; saved history is validated at admission"
                : "Hypothetical"}
            </dd>
          </dl>
          {query.replay === "historical" &&
          (selected.version.content.shocks?.length ?? 0) > 0 ? (
            <Notice title="Replay assumptions need a separate version">
              Create a version without hypothetical shocks before requesting
              historical replay.
            </Notice>
          ) : (
            <ScenarioRunForm
              key={`${accountId}:${JSON.stringify(preparation.data.body)}`}
              accountId={accountId}
              query={selectedQuery}
              prepared={preparation.data.body}
              canWrite={
                canWrite &&
                !selected.definition.archived &&
                (query.replay !== "historical" || canReplay)
              }
            />
          )}
        </Surface>
      ) : preparation ? (
        <Notice title="Saved inputs unavailable">
          {preparation.message} ({preparation.code})
        </Notice>
      ) : (
        <Notice title="Select saved inputs to continue">
          Choose a snapshot and enter its saved X-ray run ID. No new financial
          analysis is created while preparing this form.
        </Notice>
      )}
    </>
  );
}
export async function ScenarioPage({
  search,
}: Readonly<{ search: HistoricalSearch }>) {
  const access = await requireWebAccess();
  const header = (
    <PageHeader
      title="Scenarios"
      description="Test explicit assumptions against saved portfolio exposures, inspect coverage and compare immutable results."
    />
  );
  if (access.isDemo)
    return (
      <div className="page-stack">
        {header}
        <Notice title="Scenarios require the connected runtime">
          Sign in to use saved X-ray and historical inputs with persisted
          scenario runs.
        </Notice>
      </div>
    );
  const scopes = access.principal.scopes;
  if (!scopes.includes("portfolio:read") || !scopes.includes("analytics:read"))
    return (
      <div className="page-stack">
        {header}
        <Notice title="Scenario read access required">
          This workspace requires portfolio:read and analytics:read.
        </Notice>
      </div>
    );
  const clients = await scenarioClients();
  const accounts = await clients.portfolio.listAccounts();
  const selection = resolveAccountSelection(
    accounts,
    search.account,
    process.env.T212PI_ACCOUNT_ID,
  );
  if (!selection.account) return <AccountRequired selection={selection} />;
  const account = selection.account;
  let query: ScenarioQuery;
  try {
    query = {
      ...readScenarioQuery(search, {
        now: new Date(),
        currency: account.reporting_currency,
      }),
      account: account.id,
    };
  } catch (error) {
    if (!(error instanceof ScenarioQueryError)) throw error;
    return (
      <AccountView accountId={account.id}>
        <div className="page-stack">
          {header}
          <Notice title="Invalid scenario filters">
            {error.message}{" "}
            <Link prefetch={false} href={`/scenarios?account=${account.id}`}>
              Reset filters
            </Link>
          </Notice>
        </div>
      </AccountView>
    );
  }
  const result = await scenarioResult(async () => {
    try {
      return await loadView(
        clients,
        query,
        account.id,
        scopes.includes("scenarios:write"),
        scopes.includes("activity:read"),
      );
    } catch (error) {
      if (error instanceof ScenarioQueryError)
        return (
          <Notice title="Invalid saved selections">
            Review the saved IDs and replay window. A complete selection is
            required before admission.
          </Notice>
        );
      throw error;
    }
  });
  return (
    <AccountView accountId={account.id}>
      <div className={`page-stack ${styles.page}`}>
        {header}
        <Tabs query={query} />
        {result.ok ? (
          result.data
        ) : (
          <Notice title="Scenario workspace unavailable">
            {result.message} ({result.code})
          </Notice>
        )}
      </div>
    </AccountView>
  );
}
