import Link from "next/link";
import { Notice, Surface } from "@trading212/ui";

import { PageHeader } from "../../../components/page-header";
import { CollectionPagination } from "../../../components/collection-pagination";
import { PlanningSelectionForms } from "../../../components/planning-selection";
import {
  DriftTable,
  DriftTotals,
  PlanningContext,
} from "../../../components/planning-results";
import { requireWebAccess } from "../../../lib/auth";
import { readEnumParam, readOpaqueCursor } from "../../../lib/collection-query";
import { planningData } from "../../../lib/planning-adapter";
import {
  loadPlanningSelection,
  planningHref,
  planningUuid,
  type PlanningSearch,
} from "../../../lib/planning-selection";

export default async function DriftPage({
  searchParams,
}: Readonly<{ searchParams: Promise<PlanningSearch> }>) {
  const access = await requireWebAccess();
  if (access.isDemo)
    return (
      <div className="page-stack">
        <PageHeader
          title="Drift"
          description="Compare actual exposures with a published portfolio target."
        />
        <Notice title="Drift requires the connected runtime">
          Sign in to the local API to compare durable snapshots and target
          versions.
        </Notice>
      </div>
    );
  const query = await searchParams;
  const data = await loadPlanningSelection(query);
  const { account, selection, clients } = data;
  const basis = readEnumParam(
    query.basis,
    new Set(["direct", "effective"] as const),
    "direct",
  );
  const nodeId = planningUuid(query.node);
  const pins =
    account &&
    selection?.pie &&
    selection.version?.published_at &&
    selection.snapshot
      ? {
          virtual_portfolio_id: selection.pie.id,
          target_version_id: selection.version.id,
          snapshot_id: selection.snapshot.id,
          reporting_currency: selection.version.reporting_currency,
        }
      : null;
  const [actual, drift] =
    account && pins
      ? await Promise.all([
          clients.planning
            .get_actual_vs_target(account.id, {
              ...pins,
              node_id: nodeId,
              cursor: readOpaqueCursor(query.cursor),
              limit: 25,
            })
            .then(planningData),
          clients.planning
            .get_drift_analysis(account.id, { ...pins, basis, top_n: 25 })
            .then(planningData),
        ])
      : [null, null];
  const preserved = {
    account: account?.id,
    pie: selection?.pie?.id,
    version: selection?.version?.id,
    snapshot: selection?.snapshot?.id,
    basis,
    node: nodeId,
  };
  return (
    <div className="page-stack planning-page">
      <PageHeader
        title="Drift"
        description="Trace target gaps through groups, holdings, cash and unclassified exposure."
        actions={
          pins ? (
            <Link
              prefetch={false}
              className="text-link"
              href={planningHref("/planner", preserved)}
            >
              Plan a contribution
            </Link>
          ) : null
        }
      />
      <PlanningSelectionForms data={data} pathname="/drift" />
      {actual && drift ? (
        <>
          <Surface>
            <h2>Actual versus target</h2>
            <DriftTotals totals={actual.totals} />
            <form method="get" className="target-form">
              {Object.entries(preserved)
                .filter(([key]) => key !== "basis" && key !== "node")
                .map(([key, value]) =>
                  value ? (
                    <input key={key} type="hidden" name={key} value={value} />
                  ) : null,
                )}
              <label>
                <span>Hierarchy scope</span>
                <select name="node" defaultValue={nodeId ?? ""}>
                  <option value="">Whole Pie</option>
                  {actual.target_identities.map((item) => (
                    <option key={item.id} value={item.id}>
                      {selection?.version?.content.nodes.find(
                        (node) => node.key === item.key,
                      )?.name ?? item.key}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                <span>Ranked drift basis</span>
                <select name="basis" defaultValue={basis}>
                  <option value="direct">Direct exposure</option>
                  <option value="effective">Effective exposure</option>
                </select>
              </label>
              <button type="submit">Apply drift view</button>
            </form>
            {basis === "effective" ? (
              <Notice title="Effective exposure coverage">
                Effective weights remain unavailable until sourced look-through
                coverage supports them. Direct weights and their provenance
                remain available in the direct view.
              </Notice>
            ) : null}
            <DriftTable
              rows={actual.rows.items}
              caption="Direct actual versus target for the selected hierarchy scope"
            />
            <CollectionPagination
              pathname="/drift"
              nextCursor={actual.rows.next_cursor}
              total={actual.rows.total}
              returnedCount={actual.rows.items.length}
              preservedQuery={preserved}
            />
          </Surface>
          <Surface>
            <h2>Largest drift across the Pie</h2>
            <p className="muted">
              Server-ranked {drift.top_n}-row view using {drift.basis} weights.{" "}
              {drift.omitted_rows} of {drift.eligible_rows} rows omitted from
              this bounded sample.
            </p>
            <DriftTable
              rows={drift.groups}
              caption="Group and subgroup drift"
              basis={basis}
            />
            <DriftTable
              rows={drift.leaves}
              caption="Holding drift"
              basis={basis}
            />
            <DriftTable
              rows={drift.cash_and_unclassified}
              caption="Cash and unclassified drift"
              basis={basis}
            />
          </Surface>
          <PlanningContext context={actual.context} />
        </>
      ) : (
        <Notice title="Choose a published target and snapshot">
          A stored portfolio snapshot and a published, account-scoped target
          version are required.{" "}
          <Link prefetch={false} href="/pies">
            Manage Pies
          </Link>
        </Notice>
      )}
    </div>
  );
}
