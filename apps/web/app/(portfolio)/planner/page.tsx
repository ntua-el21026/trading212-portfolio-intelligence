import { formatPlanningMoney } from "../../../lib/planning-format";
import Link from "next/link";
import { Notice, StatusPill, Surface } from "@trading212/ui";

import { PageHeader } from "../../../components/page-header";
import { CollectionPagination } from "../../../components/collection-pagination";
import { PlanningSelectionForms } from "../../../components/planning-selection";
import { PlanningForm } from "../../../components/planning-form";
import { PlanningContext } from "../../../components/planning-results";
import { requireWebAccess } from "../../../lib/auth";
import { readEnumParam, readOpaqueCursor } from "../../../lib/collection-query";
import { planningData } from "../../../lib/planning-adapter";
import {
  loadPlanningSelection,
  type PlanningSearch,
} from "../../../lib/planning-selection";
import { formatDateTime, titleCase } from "../../../lib/format";

export default async function PlannerPage({
  searchParams,
}: Readonly<{ searchParams: Promise<PlanningSearch> }>) {
  const access = await requireWebAccess();
  if (access.isDemo)
    return (
      <div className="page-stack">
        <PageHeader
          title="Contribution planner"
          description="Use new contributions to move toward your portfolio targets."
        />
        <Notice title="Planning requires the connected runtime">
          Sign in to the local API to store and calculate contribution
          proposals.
        </Notice>
      </div>
    );
  const query = await searchParams;
  const data = await loadPlanningSelection(query);
  const { account, selection, clients } = data;
  const state = readEnumParam(
    query.state,
    new Set([
      "all",
      "queued",
      "running",
      "succeeded",
      "failed",
      "expired",
      "cancelled",
    ] as const),
    "all",
  );
  const outcome = readEnumParam(
    query.outcome,
    new Set([
      "all",
      "optimal",
      "feasible_nonoptimal",
      "infeasible",
      "unavailable",
      "failed",
    ] as const),
    "all",
  );
  const pins =
    account &&
    selection?.pie &&
    selection.version?.published_at &&
    selection.snapshot
      ? {
          account_id: account.id,
          virtual_portfolio_id: selection.pie.id,
          target_version_id: selection.version.id,
          snapshot_id: selection.snapshot.id,
        }
      : null;
  const [actual, plans] = await Promise.all([
    pins && selection?.version
      ? clients.planning
          .get_actual_vs_target(pins.account_id, {
            snapshot_id: pins.snapshot_id,
            virtual_portfolio_id: pins.virtual_portfolio_id,
            target_version_id: pins.target_version_id,
            reporting_currency: selection.version.reporting_currency,
            limit: 25,
          })
          .then(planningData)
      : null,
    account
      ? clients.planning
          .list_contribution_plans({
            account_id: account.id,
            state: state === "all" ? null : state,
            outcome: outcome === "all" ? null : outcome,
            limit: 25,
            cursor: readOpaqueCursor(query.cursor),
          })
          .then(planningData)
      : null,
  ]);
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
  const preserved = {
    account: account?.id,
    pie: selection?.pie?.id,
    version: selection?.version?.id,
    snapshot: selection?.snapshot?.id,
    state,
    outcome,
  };
  return (
    <div className="page-stack planning-page">
      <PageHeader
        title="Contribution planner"
        description="Build an immutable manual proposal from a fixed snapshot, published targets and your contribution constraints."
      />
      <PlanningSelectionForms data={data} pathname="/planner" />
      {actual && pins && selection?.version ? (
        <>
          <PlanningForm
            key={`${pins.snapshot_id}:${pins.target_version_id}`}
            targets={targets}
            initial={{
              ...pins,
              contribution: {
                amount: "0",
                currency: selection.version.reporting_currency,
              },
              mode: "global",
              coverage_policy: "require_complete",
              eligible_holding_ids: null,
              excluded_holding_ids: [],
              restricted_group_ids: [],
              listing_preferences: [],
              allocation_constraints: [],
              holding_constraints: [],
              cash_reserve: null,
              monetary_quantum: null,
            }}
          />
          <PlanningContext context={actual.context} />
        </>
      ) : (
        <Notice title="A target and snapshot are required">
          Choose a published target version and a stored snapshot to create a
          plan.
        </Notice>
      )}
      <Surface>
        <h2>Saved contribution plans</h2>
        <form method="get" className="target-form">
          {Object.entries(preserved)
            .filter(([key]) => key !== "state" && key !== "outcome")
            .map(([key, value]) =>
              value ? (
                <input key={key} type="hidden" name={key} value={value} />
              ) : null,
            )}
          <label>
            <span>Calculation state</span>
            <select name="state" defaultValue={state}>
              {[
                "all",
                "queued",
                "running",
                "succeeded",
                "failed",
                "expired",
                "cancelled",
              ].map((value) => (
                <option value={value} key={value}>
                  {titleCase(value)}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>Plan outcome</span>
            <select name="outcome" defaultValue={outcome}>
              {[
                "all",
                "optimal",
                "feasible_nonoptimal",
                "infeasible",
                "unavailable",
                "failed",
              ].map((value) => (
                <option value={value} key={value}>
                  {titleCase(value)}
                </option>
              ))}
            </select>
          </label>
          <button type="submit">Filter plans</button>
        </form>
        {plans?.items.length ? (
          <div className="target-pie-list">
            {plans.items.map((plan) => (
              <article className="target-pie-summary" key={plan.job.request_id}>
                <div>
                  <Link
                    prefetch={false}
                    className="target-title-link"
                    href={`/planner/${plan.job.plan_id}`}
                  >
                    {plan.options.contribution.currency}{" "}
                    {formatPlanningMoney(plan.options.contribution.amount)} ·{" "}
                    {titleCase(plan.options.mode)}
                  </Link>
                  <p className="muted">
                    Revision {plan.job.request_revision} ·{" "}
                    {formatDateTime(plan.job.requested_at)}
                  </p>
                </div>
                <StatusPill
                  tone={
                    plan.job.state === "failed"
                      ? "danger"
                      : plan.job.state === "succeeded"
                        ? "positive"
                        : "info"
                  }
                >
                  {titleCase(plan.job.outcome ?? plan.job.state)}
                </StatusPill>
              </article>
            ))}
          </div>
        ) : (
          <p className="muted">No saved plans match this view.</p>
        )}
        {plans ? (
          <CollectionPagination
            pathname="/planner"
            nextCursor={plans.next_cursor}
            total={plans.total}
            returnedCount={plans.items.length}
            preservedQuery={preserved}
          />
        ) : null}
      </Surface>
    </div>
  );
}
