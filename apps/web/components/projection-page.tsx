import type { ReactNode } from "react";
import {
  ProjectionApiError,
  type AssumptionSetResponse,
  type GoalResponse,
} from "@trading212/api-contracts";
import { Button, Notice, Surface } from "@trading212/ui";
import { requireWebAccess } from "../lib/auth";
import { resolveAccountSelection } from "../lib/account-selection";
import {
  assertProjectionAccount,
  projectionClients,
  projectionData,
  projectionResult,
} from "../lib/projection-adapter";
import {
  selectedProjectionAssumption,
  selectedProjectionGoal,
} from "../lib/projection-selection";
import {
  readProjectionQuery,
  projectionHref,
  projectionSelectionHref,
  ProjectionQueryError,
  type ProjectionQuery,
} from "../lib/projection-query";
import type { HistoricalSearch } from "../lib/historical-query";
import { AccountRequired, AccountView } from "./account-context";
import Link from "./navigation-intent";
import { PageHeader } from "./page-header";
import { ProjectionAssumptionEditor } from "./projection-assumption-editor";
import { ProjectionGoalEditor } from "./projection-goal-editor";
import { ProjectionRunForm } from "./projection-run-form";
import { ProjectionJobControls } from "./projection-job-controls";
import {
  ProjectionResults,
  ProjectionGoalAnalysis,
} from "./projection-results";
import styles from "./projection-workspace.module.css";
type Clients = Awaited<ReturnType<typeof projectionClients>>;
type Cursor =
  | "sets_cursor"
  | "versions_cursor"
  | "goals_cursor"
  | "goal_versions_cursor"
  | "runs_cursor"
  | "snapshots_cursor";
type Page = {
  items: readonly unknown[];
  total: number;
  next_cursor: string | null;
};
function Pages({
  query,
  field,
  page,
  label,
}: Readonly<{
  query: ProjectionQuery;
  field: Cursor;
  page: Page;
  label: string;
}>) {
  return (
    <nav aria-label={`${label} pages`} className={styles.actions}>
      <p>
        {page.items.length} of {page.total} {label} on this page.
      </p>
      {query[field] ? (
        <Link prefetch={false} href={projectionHref(query, { [field]: null })}>
          First {label}
        </Link>
      ) : null}
      {page.next_cursor ? (
        <Link
          prefetch={false}
          href={projectionHref(query, { [field]: page.next_cursor })}
        >
          Next {label}
        </Link>
      ) : null}
    </nav>
  );
}
function Tabs({ query }: Readonly<{ query: ProjectionQuery }>) {
  return (
    <nav aria-label="Projection workspace" className={styles.actions}>
      {(
        [
          ["runs", "Saved runs"],
          ["assumptions", "Assumptions"],
          ["goals", "Goals"],
          ["new", "New run"],
        ] as const
      ).map(([view, label]) => (
        <Link
          key={view}
          prefetch={false}
          aria-current={query.view === view ? "page" : undefined}
          href={projectionHref(
            readProjectionQuery({ account: query.account, view }),
          )}
        >
          {label}
        </Link>
      ))}
    </nav>
  );
}
function SelectionForm({
  query,
  sets,
  goals = [],
  includeSnapshot = false,
}: Readonly<{
  query: ProjectionQuery;
  sets: readonly AssumptionSetResponse[];
  goals?: readonly GoalResponse[];
  includeSnapshot?: boolean;
}>) {
  return (
    <form
      action="/projections"
      method="get"
      className={styles.form}
      aria-label="Select saved projection inputs"
    >
      <input type="hidden" name="account" value={query.account ?? ""} />
      <input type="hidden" name="view" value={query.view} />
      {query.goal && query.view === "goals" ? (
        <input type="hidden" name="goal" value={query.goal} />
      ) : null}
      {query.goal_version && query.view === "goals" ? (
        <input type="hidden" name="goal_version" value={query.goal_version} />
      ) : null}
      <div className={styles.fields}>
        <label>
          Saved assumption version ID
          <input
            name="version"
            defaultValue={query.version ?? ""}
            list="projection-assumption-versions"
            placeholder="Select or paste an immutable version ID"
          />
        </label>
        <datalist id="projection-assumption-versions">
          {sets.map((set) => (
            <option key={set.id} value={set.current_version_id}>
              {set.name} · revision {set.revision}
            </option>
          ))}
        </datalist>
        {query.view === "new" ? (
          <>
            <label>
              Optional saved goal version ID
              <input
                name="goal_version"
                defaultValue={query.goal_version ?? ""}
                list="projection-goal-versions"
              />
            </label>
            <datalist id="projection-goal-versions">
              {goals.map((goal) => (
                <option key={goal.id} value={goal.current_version_id}>
                  {goal.name} · revision {goal.revision}
                </option>
              ))}
            </datalist>
          </>
        ) : null}
        {includeSnapshot ? (
          <label>
            Optional observed snapshot ID
            <input
              name="snapshot"
              defaultValue={query.snapshot ?? ""}
              placeholder="Paste a saved snapshot ID"
            />
          </label>
        ) : null}
      </div>
      <Button type="submit">Load saved selection</Button>
      <p>
        Only saved IDs are placed in the URL. Exact amounts and schedules remain
        in the form until submitted. Browser back and forward preserve the exact
        saved selections in each URL.
      </p>
    </form>
  );
}
async function assumptionsView(
  clients: Clients,
  query: ProjectionQuery,
  account: string,
  currency: string,
  write: boolean,
) {
  const [sets, selected] = await Promise.all([
    clients.projections
      .list_assumption_sets(account, { limit: 25, cursor: query.sets_cursor })
      .then(projectionData),
    selectedProjectionAssumption(clients, query, account),
  ]);
  for (const set of sets.items)
    assertProjectionAccount(set.account_id, account);
  const versions = selected
    ? projectionData(
        await clients.projections.list_assumption_versions(
          selected.definition.id,
          { limit: 25, cursor: query.versions_cursor },
        ),
      )
    : null;
  for (const version of versions?.items ?? []) {
    assertProjectionAccount(version.account_id, account);
    if (version.set_id !== selected?.definition.id)
      throw new ProjectionApiError(
        "CONFLICT",
        409,
        "The version collection has a different assumption set.",
      );
  }
  const pinned = selected
    ? { ...query, set: selected.definition.id, version: selected.version.id }
    : query;
  return (
    <>
      <Surface>
        <h2>Saved assumption sets</h2>
        {sets.items.length ? (
          <ul>
            {sets.items.map((set) => (
              <li key={set.id}>
                <Link
                  prefetch={false}
                  href={projectionSelectionHref(query, {
                    set: set.id,
                    version: set.current_version_id,
                    goal: null,
                    goal_version: null,
                  })}
                >
                  {set.name} · revision {set.revision}
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          <p>No assumptions saved for this account.</p>
        )}
        <Pages
          query={query}
          page={sets}
          field="sets_cursor"
          label="assumption sets"
        />
        <SelectionForm query={query} sets={sets.items} />
      </Surface>
      {selected && versions ? (
        <Surface>
          <h2>Immutable assumption versions</h2>
          <ul>
            {versions.items.map((version) => (
              <li key={version.id}>
                <Link
                  prefetch={false}
                  aria-current={
                    version.id === selected.version.id ? "true" : undefined
                  }
                  href={projectionHref(pinned, { version: version.id })}
                >
                  Version {version.version_number} · {version.metadata.name} ·{" "}
                  {version.created_at}
                </Link>
              </li>
            ))}
          </ul>
          <Pages
            query={pinned}
            page={versions}
            field="versions_cursor"
            label="assumption versions"
          />
          <p>
            Selected digest: <code>{selected.version.content_digest}</code>.
            Editing creates a new version from the current revision; existing
            versions and saved runs remain intact.
          </p>
          <div className={styles.actions}>
            <Link
              prefetch={false}
              href={projectionSelectionHref(pinned, {
                view: "new",
                goal: null,
                goal_version: null,
              })}
            >
              Run selected assumption version
            </Link>
            <Link
              prefetch={false}
              href={projectionSelectionHref(pinned, {
                view: "goals",
                goal: null,
                goal_version: null,
              })}
            >
              Create a goal for this version
            </Link>
            <Link
              prefetch={false}
              href={projectionSelectionHref(query, {
                set: null,
                version: null,
              })}
            >
              Create a separate assumption set
            </Link>
          </div>
        </Surface>
      ) : null}
      <Surface>
        <ProjectionAssumptionEditor
          key={`${account}:${selected?.version.id ?? "new"}`}
          accountId={account}
          currency={currency}
          query={pinned}
          definition={selected?.definition}
          version={selected?.version}
          canWrite={write}
        />
      </Surface>
    </>
  );
}
async function goalsView(
  clients: Clients,
  query: ProjectionQuery,
  account: string,
  write: boolean,
) {
  const [goals, sets, selected] = await Promise.all([
    clients.projections
      .list_goals(account, { limit: 25, cursor: query.goals_cursor })
      .then(projectionData),
    clients.projections
      .list_assumption_sets(account, { limit: 25, cursor: query.sets_cursor })
      .then(projectionData),
    selectedProjectionGoal(clients, query, account),
  ]);
  for (const row of [...goals.items, ...sets.items])
    assertProjectionAccount(row.account_id, account);
  const assumption = await selectedProjectionAssumption(
    clients,
    query,
    account,
    !query.version
      ? selected?.version.content.assumption_version_id
      : undefined,
  );
  const versions = selected
    ? projectionData(
        await clients.projections.list_goal_versions(selected.goal.id, {
          limit: 25,
          cursor: query.goal_versions_cursor,
        }),
      )
    : null;
  for (const version of versions?.items ?? []) {
    assertProjectionAccount(version.account_id, account);
    if (version.goal_id !== selected?.goal.id)
      throw new ProjectionApiError(
        "CONFLICT",
        409,
        "The version collection has a different goal.",
      );
  }
  const pinned = {
    ...query,
    ...(selected
      ? { goal: selected.goal.id, goal_version: selected.version.id }
      : {}),
    ...(assumption
      ? { set: assumption.definition.id, version: assumption.version.id }
      : {}),
  };
  return (
    <>
      <Surface>
        <h2>Saved goals</h2>
        {goals.items.length ? (
          <ul>
            {goals.items.map((goal) => (
              <li key={goal.id}>
                <Link
                  prefetch={false}
                  href={projectionSelectionHref(query, {
                    goal: goal.id,
                    goal_version: goal.current_version_id,
                    set: null,
                    version: null,
                  })}
                >
                  {goal.name} · revision {goal.revision}
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          <p>No goals saved for this account.</p>
        )}
        <Pages query={query} page={goals} field="goals_cursor" label="goals" />
        <SelectionForm query={pinned} sets={sets.items} />
        <Pages
          query={query}
          page={sets}
          field="sets_cursor"
          label="assumption suggestions"
        />
      </Surface>
      {selected && versions ? (
        <Surface>
          <h2>Immutable goal versions</h2>
          <ul>
            {versions.items.map((version) => (
              <li key={version.id}>
                <Link
                  prefetch={false}
                  aria-current={
                    selected.version.id === version.id ? "true" : undefined
                  }
                  href={projectionHref(pinned, {
                    goal_version: version.id,
                    set: null,
                    version: null,
                  })}
                >
                  Version {version.version_number} · {version.metadata.name} ·{" "}
                  {version.created_at}
                </Link>
              </li>
            ))}
          </ul>
          <Pages
            query={pinned}
            page={versions}
            field="goal_versions_cursor"
            label="goal versions"
          />
          <p>
            Selected digest <code>{selected.version.content_digest}</code>. A
            new goal version never changes an earlier projection’s goal.
          </p>
          <div className={styles.actions}>
            <Link
              prefetch={false}
              href={projectionSelectionHref(pinned, {
                view: "new",
                set: null,
                version: selected.version.content.assumption_version_id,
              })}
            >
              Run selected goal version
            </Link>
            <Link
              prefetch={false}
              href={projectionSelectionHref(pinned, {
                goal: null,
                goal_version: null,
              })}
            >
              Create a separate goal
            </Link>
          </div>
        </Surface>
      ) : null}
      {assumption ? (
        selected &&
        assumption.version.content.reporting_currency !==
          selected.version.content.target.currency ? (
          <Notice title="Goal currency differs">
            Choose an assumption version in the goal’s saved currency, or create
            a separate goal with a new explicit target.
          </Notice>
        ) : (
          <Surface>
            <ProjectionGoalEditor
              key={`${account}:${selected?.version.id ?? "new"}:${assumption.version.id}`}
              accountId={account}
              query={pinned}
              assumption={assumption.version}
              goal={selected?.goal}
              version={selected?.version}
              canWrite={write}
            />
          </Surface>
        )
      ) : (
        <Notice title="Choose a saved assumption version">
          Save assumptions first, then load an immutable version above to define
          the goal’s target and schedule.
        </Notice>
      )}
    </>
  );
}
async function newRunView(
  clients: Clients,
  query: ProjectionQuery,
  account: string,
  write: boolean,
) {
  const [sets, goals, selectedGoal, snapshots, snapshot] = await Promise.all([
    clients.projections
      .list_assumption_sets(account, { limit: 25, cursor: query.sets_cursor })
      .then(projectionData),
    clients.projections
      .list_goals(account, { limit: 25, cursor: query.goals_cursor })
      .then(projectionData),
    selectedProjectionGoal(clients, query, account),
    clients.portfolio.listSnapshots(account, {
      limit: 25,
      cursor: query.snapshots_cursor ?? undefined,
    }),
    query.snapshot
      ? clients.portfolio.getSnapshot(account, query.snapshot)
      : Promise.resolve(undefined),
  ]);
  for (const row of [...sets.items, ...goals.items])
    assertProjectionAccount(row.account_id, account);
  if (snapshot && snapshot.id !== query.snapshot)
    throw new ProjectionApiError(
      "CONFLICT",
      409,
      "The saved snapshot differs from the selected ID.",
    );
  const assumption = await selectedProjectionAssumption(
    clients,
    query,
    account,
    selectedGoal?.version.content.assumption_version_id,
  );
  const pinned = {
    ...query,
    ...(assumption
      ? { set: assumption.definition.id, version: assumption.version.id }
      : {}),
    ...(selectedGoal
      ? { goal: selectedGoal.goal.id, goal_version: selectedGoal.version.id }
      : {}),
  };
  return (
    <>
      <Surface>
        <h2>Select immutable run inputs</h2>
        <SelectionForm
          key={`${account}:${query.version}:${query.goal_version}:${query.snapshot}`}
          query={pinned}
          sets={sets.items}
          goals={goals.items}
          includeSnapshot
        />
        <Pages
          query={query}
          page={sets}
          field="sets_cursor"
          label="assumption suggestions"
        />
        <Pages
          query={query}
          page={goals}
          field="goals_cursor"
          label="goal suggestions"
        />
        <h3>Saved observed snapshots</h3>
        {snapshots.items.length ? (
          <ul>
            {snapshots.items.map((item) => (
              <li key={item.id}>
                <Link
                  prefetch={false}
                  href={projectionSelectionHref(pinned, { snapshot: item.id })}
                >
                  {item.valuation_at} · {item.reporting_currency} ·{" "}
                  <code>{item.id}</code>
                </Link>
                <p>Source cutoff: {item.source_cutoff_at}</p>
              </li>
            ))}
          </ul>
        ) : (
          <p>
            No observed snapshots saved. Explicit modeled initial values remain
            available.
          </p>
        )}
        <Pages
          query={pinned}
          page={snapshots}
          field="snapshots_cursor"
          label="snapshots"
        />
        {snapshot ? (
          <p>
            <Link
              prefetch={false}
              href={projectionSelectionHref(pinned, { snapshot: null })}
            >
              Clear observed snapshot selection
            </Link>
          </p>
        ) : null}
      </Surface>
      {assumption ? (
        <Surface>
          <ProjectionRunForm
            key={`${account}:${assumption.version.id}:${selectedGoal?.version.id ?? "none"}:${snapshot?.id ?? "modeled"}`}
            accountId={account}
            query={pinned}
            assumption={assumption.version}
            goal={selectedGoal?.version}
            snapshot={snapshot}
            defaultAnchor={new Date().toISOString().slice(0, 10)}
            canWrite={write}
          />
        </Surface>
      ) : (
        <Notice title="Select saved assumptions">
          Choose an immutable assumption version or goal version before
          preparing the run.
        </Notice>
      )}
    </>
  );
}
async function loadView(
  clients: Clients,
  query: ProjectionQuery,
  account: string,
  currency: string,
  canWrite: boolean,
  canWriteGoal: boolean,
): Promise<ReactNode> {
  if (query.view === "assumptions")
    return assumptionsView(clients, query, account, currency, canWrite);
  if (query.view === "goals")
    return goalsView(clients, query, account, canWriteGoal);
  if (query.view === "new")
    return newRunView(clients, query, account, canWrite);
  if (query.view === "result" || query.view === "goal") {
    if (!query.run) throw new ProjectionQueryError();
    const run = projectionData(
      await clients.projections.get_projection_run(query.run, {
        point_limit: query.view === "goal" ? 1 : 25,
        point_cursor: query.view === "goal" ? null : query.point_cursor,
      }),
    );
    assertProjectionAccount(run.account_id, account);
    if (run.id !== query.run)
      throw new ProjectionApiError(
        "CONFLICT",
        409,
        "The saved result differs from the selected run.",
      );
    const analysis =
      query.view === "goal"
        ? projectionData(await clients.projections.get_goal_analysis(run.id))
        : null;
    if (analysis) {
      assertProjectionAccount(analysis.account_id, account);
      if (analysis.run_id !== run.id)
        throw new ProjectionApiError(
          "CONFLICT",
          409,
          "The saved goal analysis belongs to a different run.",
        );
    }
    return (
      <>
        <Surface>
          <h2>Saved projection run</h2>
          <dl className={styles.context}>
            <dt>Run ID</dt>
            <dd>
              <code>{run.id}</code>
            </dd>
            <dt>State</dt>
            <dd>{run.state}</dd>
            <dt>Result</dt>
            <dd>{run.result_availability}</dd>
            <dt>Created</dt>
            <dd>{run.created_at}</dd>
            <dt>Expires</dt>
            <dd>{run.expires_at}</dd>
            <dt>Completed</dt>
            <dd>{run.completed_at ?? "Pending"}</dd>
            <dt>Last attempt</dt>
            <dd>{run.failure_code ?? "No failure reported"}</dd>
          </dl>
          <ProjectionJobControls
            key={`${account}:${run.id}`}
            run={{ id: run.id, account_id: run.account_id, state: run.state }}
            canWrite={canWrite}
          />
          <div className={styles.actions}>
            <Link
              prefetch={false}
              href={projectionHref(query, {
                view: "result",
                point_cursor: null,
              })}
            >
              Saved result points
            </Link>
            <Link
              prefetch={false}
              href={projectionHref(query, { view: "goal", point_cursor: null })}
            >
              Saved goal analysis
            </Link>
            <Link
              prefetch={false}
              href={projectionSelectionHref(query, {
                view: "new",
                version: run.assumption_version_id,
                goal_version: run.goal_version_id,
                set: null,
                goal: null,
                snapshot: null,
              })}
            >
              Prepare a separate run with these versions
            </Link>
          </div>
        </Surface>
        {analysis ? (
          <ProjectionGoalAnalysis value={analysis} />
        ) : run.result ? (
          <ProjectionResults value={run.result} query={query} />
        ) : (
          <Notice title="No published financial result">
            {run.result_availability === "pending"
              ? "The background job is pending. Status refresh does not create another run."
              : "The retained result is unavailable. No forecast or zero balance is substituted."}
          </Notice>
        )}
      </>
    );
  }
  const runs = projectionData(
    await clients.projections.list_projection_runs(account, {
      limit: 25,
      cursor: query.runs_cursor,
    }),
  );
  for (const run of runs.items)
    assertProjectionAccount(run.account_id, account);
  return (
    <Surface>
      <h2>Saved projection runs</h2>
      {runs.items.length ? (
        <div
          className="table-scroll"
          role="region"
          tabIndex={0}
          aria-label="Saved projection runs"
        >
          <table className="data-table">
            <caption>
              Persisted projection jobs; financial results open separately
            </caption>
            <thead>
              <tr>
                <th scope="col">Created</th>
                <th scope="col">State</th>
                <th scope="col">Availability</th>
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
                      href={projectionHref(query, {
                        view: "result",
                        run: run.id,
                        point_cursor: null,
                      })}
                    >
                      Open projection{" "}
                      <span className="ui-visually-hidden">{run.id}</span>
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <Notice title="No saved projection runs">
          Save an assumption set, optionally create a goal, then prepare a run
          with explicit modeled money or an observed snapshot.
        </Notice>
      )}
      <Pages query={query} page={runs} field="runs_cursor" label="runs" />
    </Surface>
  );
}
export async function ProjectionPage({
  search,
}: Readonly<{ search: HistoricalSearch }>) {
  const access = await requireWebAccess();
  const header = (
    <PageHeader
      title="Projections"
      description="Explore explicit model assumptions, immutable goals and saved projection paths with visible uncertainty."
    />
  );
  if (access.isDemo)
    return (
      <div className="page-stack">
        {header}
        <Notice title="Projections require the connected runtime">
          Sign in to create persisted assumption versions, goals and background
          projection runs.
        </Notice>
      </div>
    );
  const scopes = access.principal.scopes;
  if (!scopes.includes("portfolio:read") || !scopes.includes("analytics:read"))
    return (
      <div className="page-stack">
        {header}
        <Notice title="Projection read access required">
          This workspace requires portfolio:read and analytics:read.
        </Notice>
      </div>
    );
  const clients = await projectionClients();
  const accounts = await clients.portfolio.listAccounts();
  const selection = resolveAccountSelection(
    accounts,
    search.account,
    process.env.T212PI_ACCOUNT_ID,
  );
  if (!selection.account) return <AccountRequired selection={selection} />;
  const account = selection.account;
  let query: ProjectionQuery;
  try {
    query = { ...readProjectionQuery(search), account: account.id };
  } catch (error) {
    if (!(error instanceof ProjectionQueryError)) throw error;
    return (
      <AccountView accountId={account.id}>
        <div className="page-stack">
          {header}
          <Notice title="Invalid projection selection">
            {error.message}{" "}
            <Link prefetch={false} href={`/projections?account=${account.id}`}>
              Reset selections
            </Link>
          </Notice>
        </div>
      </AccountView>
    );
  }
  const result = await projectionResult(() =>
    loadView(
      clients,
      query,
      account.id,
      account.reporting_currency,
      scopes.includes("projections:write"),
      scopes.includes("goals:write"),
    ),
  );
  return (
    <AccountView accountId={account.id}>
      <div className={`page-stack ${styles.page}`}>
        {header}
        <Tabs query={query} />
        {result.ok ? (
          result.data
        ) : (
          <Notice title="Projection workspace unavailable">
            {result.message} ({result.code})
          </Notice>
        )}
      </div>
    </AccountView>
  );
}
