import { AccountView } from "../../../../components/account-context";
import { loadSelectedAccount } from "../../../../lib/api-adapter";
import { resourceAccountHref } from "../../../../lib/account-selection";
import { formatPlanningMoney } from "../../../../lib/planning-format";
import Link from "../../../../components/navigation-intent";
import { notFound, redirect } from "next/navigation";
import { PlanningApiError } from "@trading212/api-contracts";
import { Notice, StatusPill, Surface } from "@trading212/ui";

import { PageHeader } from "../../../../components/page-header";
import { CollectionPagination } from "../../../../components/collection-pagination";
import { PlanningForm } from "../../../../components/planning-form";
import { PlanningSelectionForms } from "../../../../components/planning-selection";
import { PlanningJobStatus } from "../../../../components/planning-job-status";
import {
  DriftTotals,
  Objective,
  PlanningContext,
} from "../../../../components/planning-results";
import {
  firstSearchParam,
  readOpaqueCursor,
} from "../../../../lib/collection-query";
import {
  planningClients,
  planningData,
} from "../../../../lib/planning-adapter";
import { buildPlanningRevision } from "../../../../lib/planning-revision";
import {
  loadPlanningSelection,
  planningHref,
  planningUuid,
  type PlanningSearch,
} from "../../../../lib/planning-selection";
import {
  formatDateTime,
  formatPercent,
  titleCase,
} from "../../../../lib/format";

export default async function PlanDetailPage({
  params,
  searchParams,
}: Readonly<{
  params: Promise<{ planId: string }>;
  searchParams: Promise<PlanningSearch>;
}>) {
  const planId = planningUuid((await params).planId);
  if (!planId) notFound();
  const query = await searchParams;
  const accountSelection = await loadSelectedAccount(query.account);
  if (query.account !== undefined && !accountSelection.account) notFound();
  const revisionId = planningUuid(query.revision);
  const editing = firstSearchParam(query.edit) === "1";
  const clients = await planningClients();
  const detail = await clients.planning
    .get_contribution_plan(planId, {
      plan_revision_id: revisionId,
      cursor: readOpaqueCursor(query.cursor),
      limit: 25,
    })
    .then(planningData)
    .catch((error: unknown) => {
      if (error instanceof PlanningApiError && error.status === 404) notFound();
      throw error;
    });
  const pathname = `/planner/${planId}` as const;
  if (query.account === undefined)
    redirect(resourceAccountHref(pathname, detail.request.account_id, query));
  if (detail.request.account_id !== accountSelection.account?.id) notFound();
  const showHistory =
    firstSearchParam(query.history) === "1" || Boolean(query.history_cursor);
  const history = showHistory
    ? planningData(
        await clients.planning.list_contribution_plans({
          account_id: detail.job.account_id,
          plan_id: planId,
          include_revisions: true,
          limit: 25,
          cursor: readOpaqueCursor(query.history_cursor),
        }),
      )
    : null;
  const editSelection = editing
    ? await loadPlanningSelection({
        ...query,
        account: detail.request.account_id,
        pie: detail.request.virtual_portfolio_id,
        version:
          firstSearchParam(query.version) ?? detail.request.target_version_id,
        snapshot:
          firstSearchParam(query.snapshot) ?? detail.request.snapshot_id,
      })
    : null;
  const selection = editSelection?.selection;
  const actual =
    editSelection?.account &&
    selection?.pie &&
    selection.version?.published_at &&
    selection.snapshot
      ? planningData(
          await clients.planning.get_actual_vs_target(
            editSelection.account.id,
            {
              snapshot_id: selection.snapshot.id,
              virtual_portfolio_id: selection.pie.id,
              target_version_id: selection.version.id,
              reporting_currency: selection.version.reporting_currency,
              limit: 25,
            },
          ),
        )
      : null;
  const targets =
    actual && selection?.version
      ? actual.target_identities.map((identity) => {
          const node = selection.version!.content.nodes.find(
            (item) => item.key === identity.key,
          );
          if (!node)
            throw new Error(
              "The target identity does not match the pinned target.",
            );
          return { ...identity, holding_id: identity.holding_id ?? null, node };
        })
      : [];
  const revision =
    selection?.pie && selection.version && selection.snapshot
      ? buildPlanningRevision(
          detail.request,
          {
            account_id: detail.request.account_id,
            virtual_portfolio_id: selection.pie.id,
            target_version_id: selection.version.id,
            snapshot_id: selection.snapshot.id,
            reporting_currency: selection.version.reporting_currency,
          },
          firstSearchParam(query.reset) === "1",
        )
      : null;
  const request = revision?.status === "ready" ? revision.request : null;
  const result = detail.result;
  return (
    <AccountView accountId={detail.request.account_id}>
      <div className="page-stack planning-page">
        <PageHeader
          title="Contribution plan"
          description={`Revision ${detail.job.request_revision} · requested ${formatDateTime(detail.job.requested_at)}`}
          actions={
            <Link
              prefetch={false}
              className="text-link"
              href={`/planner?account=${detail.job.account_id}`}
            >
              All plans
            </Link>
          }
        />
        <PlanningJobStatus
          key={detail.job.job_id}
          job={detail.job}
          paused={editing}
        />
        <Surface>
          <div className="target-actions">
            <h2>
              {detail.request.options.contribution.currency}{" "}
              {formatPlanningMoney(detail.request.options.contribution.amount)}
            </h2>
            <StatusPill
              tone={
                result?.outcome === "optimal"
                  ? "positive"
                  : result?.outcome === "infeasible" ||
                      detail.job.state === "failed"
                    ? "danger"
                    : "info"
              }
            >
              {titleCase(result?.outcome ?? detail.job.state)}
            </StatusPill>
          </div>
          <p>
            {titleCase(detail.request.options.mode)} · manual contribution
            proposal · execution disabled
          </p>
          <details className="target-details">
            <summary>Sources and revision details</summary>
            <dl className="planning-identities">
              <dt>Input snapshot</dt>
              <dd>{detail.request.snapshot_id}</dd>
              <dt>Target version</dt>
              <dd>{detail.request.target_version_id}</dd>
              <dt>Input digest</dt>
              <dd>{detail.job.input_digest}</dd>
              {detail.content_digest ? (
                <>
                  <dt>Finalized content digest</dt>
                  <dd>{detail.content_digest}</dd>
                  <dt>Immutable revision</dt>
                  <dd>{detail.job.plan_revision_id}</dd>
                </>
              ) : null}
            </dl>
          </details>
          <div className="target-actions">
            <Link
              prefetch={false}
              className="text-link"
              href={planningHref(pathname, {
                account: detail.request.account_id,
                edit: "1",
              })}
            >
              Calculate a new revision
            </Link>
            <Link
              prefetch={false}
              className="text-link"
              href={planningHref(pathname, {
                account: detail.request.account_id,
                revision: revisionId,
                history: "1",
              })}
            >
              Revision history
            </Link>
            <Link
              prefetch={false}
              className="text-link"
              href={planningHref("/drift", {
                account: detail.request.account_id,
                pie: detail.request.virtual_portfolio_id,
                version: detail.request.target_version_id,
                snapshot: detail.request.snapshot_id,
              })}
            >
              View source drift
            </Link>
          </div>
        </Surface>
        {history ? (
          <Surface>
            <h2>Revision history</h2>
            <div className="target-version-list">
              {history.items.map((item) => (
                <article
                  className="target-version-link"
                  key={item.job.request_id}
                >
                  {item.job.plan_revision_id ? (
                    <Link
                      prefetch={false}
                      href={planningHref(pathname, {
                        account: detail.request.account_id,
                        revision: item.job.plan_revision_id,
                        history: "1",
                      })}
                    >
                      Revision {item.job.request_revision} ·{" "}
                      {titleCase(item.job.outcome ?? item.job.state)}
                    </Link>
                  ) : (
                    <strong>
                      Revision {item.job.request_revision} ·{" "}
                      {titleCase(item.job.state)}
                    </strong>
                  )}
                  <span>
                    {formatDateTime(item.job.requested_at)} ·{" "}
                    {item.options.contribution.currency}{" "}
                    {formatPlanningMoney(item.options.contribution.amount)}
                  </span>
                </article>
              ))}
            </div>
            <CollectionPagination
              pathname={pathname}
              nextCursor={history.next_cursor}
              total={history.total}
              returnedCount={history.items.length}
              cursorParameter="history_cursor"
              preservedQuery={{
                account: detail.request.account_id,
                history: "1",
                revision: revisionId,
              }}
            />
          </Surface>
        ) : null}
        {result ? (
          <>
            <Surface>
              <h2>Allocation result</h2>
              <dl className="planning-facts">
                <div>
                  <dt>Residual contribution cash</dt>
                  <dd>
                    {result.residual_cash
                      ? `${result.residual_cash.currency} ${formatPlanningMoney(result.residual_cash.amount)}`
                      : "Unavailable"}
                  </dd>
                </div>
                <div>
                  <dt>Total cash after contribution</dt>
                  <dd>
                    {result.post_cash
                      ? `${result.post_cash.currency} ${formatPlanningMoney(result.post_cash.amount)}`
                      : "Unavailable"}
                  </dd>
                </div>
                <div>
                  <dt>Portfolio after contribution</dt>
                  <dd>
                    {result.post_total
                      ? `${result.post_total.currency} ${formatPlanningMoney(result.post_total.amount)}`
                      : "Unavailable"}
                  </dd>
                </div>
              </dl>
              {detail.lines.items.length ? (
                <div
                  className="table-scroll"
                  tabIndex={0}
                  role="region"
                  aria-label="Contribution allocation lines"
                >
                  <table className="data-table planning-table">
                    <caption>
                      New funds only; existing holdings are retained
                    </caption>
                    <thead>
                      <tr>
                        <th scope="col">Holding</th>
                        <th scope="col">Current value</th>
                        <th scope="col">Target</th>
                        <th scope="col">New funds</th>
                        <th scope="col">Post value</th>
                        <th scope="col">Post weight</th>
                        <th scope="col">Minimum / increment</th>
                        <th scope="col">Constraints</th>
                      </tr>
                    </thead>
                    <tbody>
                      {detail.lines.items.map((line) => (
                        <tr key={line.node_id}>
                          <th scope="row">
                            {line.node_key}
                            <span>
                              {line.excluded
                                ? "Excluded from funding"
                                : (line.listing_id ?? "Unresolved listing")}
                            </span>
                          </th>
                          <td>
                            {line.current_value.currency}{" "}
                            {formatPlanningMoney(line.current_value.amount)}
                          </td>
                          <td>{formatPercent(line.target_weight)}</td>
                          <td>
                            {line.recommended_amount.currency}{" "}
                            {formatPlanningMoney(
                              line.recommended_amount.amount,
                            )}
                          </td>
                          <td>
                            {line.post_value.currency}{" "}
                            {formatPlanningMoney(line.post_value.amount)}
                          </td>
                          <td>{formatPercent(line.post_weight)}</td>
                          <td>
                            {line.minimum_funded_amount.currency}{" "}
                            {line.minimum_funded_amount.amount} /{" "}
                            {line.value_increment.amount}
                          </td>
                          <td>
                            {line.binding_constraint_keys.join(", ") ||
                              "None binding"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <Notice title="No allocation recommendations">
                  {result.outcome === "infeasible"
                    ? "The server proved that these constraints admit no feasible proposal."
                    : result.outcome === "unavailable" ||
                        result.outcome === "failed"
                      ? "A usable allocation was not established for this request."
                      : "This proposal retains the contribution as cash."}
                </Notice>
              )}
              <CollectionPagination
                pathname={pathname}
                nextCursor={detail.lines.next_cursor}
                total={detail.lines.total}
                returnedCount={detail.lines.items.length}
                preservedQuery={{
                  account: detail.request.account_id,
                  revision: detail.job.plan_revision_id ?? undefined,
                }}
              />
            </Surface>
            <Surface>
              <h2>Objective, bounds and explanations</h2>
              <dl className="planning-facts">
                <div>
                  <dt>Objective if contribution stays in cash</dt>
                  <dd>
                    <Objective value={result.objective_before} />
                  </dd>
                </div>
                <div>
                  <dt>Objective after</dt>
                  <dd>
                    <Objective value={result.objective_after} />
                  </dd>
                </div>
                <div>
                  <dt>Lower bound</dt>
                  <dd>
                    <Objective value={result.lower_bound} />
                  </dd>
                </div>
                <div>
                  <dt>Objective gap</dt>
                  <dd>
                    <Objective value={result.objective_gap} />
                  </dd>
                </div>
                <div>
                  <dt>Bound method</dt>
                  <dd>{result.bound_kind ?? "Unavailable"}</dd>
                </div>
                <div>
                  <dt>Search evidence</dt>
                  <dd>
                    {result.attempted_assignments} assignments ·{" "}
                    {result.examined_moves} moves ·{" "}
                    {result.exhaustive ? "exhaustive" : "bounded"}
                  </dd>
                </div>
              </dl>
              <p className="muted">
                Amount quantum {result.monetary_quantum ?? "unavailable"} ·
                currency policy {result.currency_policy_version}
              </p>
              {result.explanations.map((item, index) => (
                <Notice
                  key={`${item.code}:${index}`}
                  title={titleCase(item.code)}
                  tone={item.severity === "error" ? "danger" : "info"}
                >
                  {item.message}
                  {item.constraint_keys?.length
                    ? ` Constraints: ${item.constraint_keys.join(", ")}.`
                    : null}
                </Notice>
              ))}
              <details className="target-details">
                <summary>Effective constraints and unresolved targets</summary>
                <ul>
                  {result.constraints.map((constraint) => (
                    <li key={constraint.key}>
                      {constraint.key} · {titleCase(constraint.kind)} ·{" "}
                      {constraint.node_key ?? "whole portfolio"}
                      {constraint.amount != null
                        ? ` · ${constraint.currency} ${constraint.amount}`
                        : ""}
                      {constraint.weight != null
                        ? ` · weight ${constraint.weight}`
                        : ""}
                      {constraint.count != null
                        ? ` · ${constraint.count} lines`
                        : ""}
                      {constraint.coefficient != null
                        ? ` · coefficient ${constraint.coefficient}`
                        : ""}
                      {constraint.enabled != null
                        ? ` · ${constraint.enabled ? "eligible" : "excluded"}`
                        : ""}
                    </li>
                  ))}
                </ul>
                <p>
                  Excluded: {result.excluded_node_keys.join(", ") || "None"}
                </p>
                <p>
                  Unresolved: {result.unresolved_node_keys.join(", ") || "None"}
                </p>
              </details>
            </Surface>
            <Surface>
              <h2>Drift before contribution</h2>
              <DriftTotals totals={result.before_drift} />
              {result.after_drift ? (
                <>
                  <h2>Drift after contribution</h2>
                  <DriftTotals totals={result.after_drift} />
                </>
              ) : null}
            </Surface>
            <PlanningContext context={result.context} />
          </>
        ) : null}
        {editing && editSelection ? (
          <>
            <PlanningSelectionForms data={editSelection} pathname={pathname} />
            {revision?.status === "reset_required" ? (
              <Notice title="Review options for the selected target">
                <p>
                  This selection changes the target version or reporting
                  currency. Start with default options to clear holdings,
                  groups, constraints, cash reserves and precision from the
                  previous selection. A changed currency also requires a new
                  contribution amount.
                </p>
                <Link
                  prefetch={false}
                  className="text-link"
                  href={planningHref(pathname, {
                    account: detail.request.account_id,
                    edit: "1",
                    reset: "1",
                    version: selection?.version?.id,
                    snapshot: selection?.snapshot?.id,
                  })}
                >
                  Reset options for this selection
                </Link>
              </Notice>
            ) : request && actual ? (
              <PlanningForm
                key={`${detail.job.request_id}:${request.snapshot_id}:${request.target_version_id}`}
                initial={request}
                targets={targets}
                revision={{ planId, etag: detail.revision_etag }}
              />
            ) : (
              <Notice title="Choose a published target and snapshot">
                A new revision requires complete source selections.
              </Notice>
            )}
          </>
        ) : null}
      </div>
    </AccountView>
  );
}
