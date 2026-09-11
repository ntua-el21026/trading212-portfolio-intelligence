import { redirect } from "next/navigation";
import {
  PlanningApiError,
  XrayApiError,
  type ActualVsTargetResult,
  type DriftAnalysisResult,
} from "@trading212/api-contracts";
import { PlanningCompanyContext } from "../../../components/planning-company";
import { readPlanningCompanyQuery } from "../../../lib/planning-company-query";
import { xrayClients, xrayData } from "../../../lib/xray-adapter";
import {
  AccountRequired,
  AccountView,
} from "../../../components/account-context";
import Link from "../../../components/navigation-intent";
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
  if (!account) return <AccountRequired selection={data.accountSelection} />;
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
  let companyQuery: ReturnType<typeof readPlanningCompanyQuery>;
  try {
    companyQuery = readPlanningCompanyQuery(query);
  } catch {
    return (
      <AccountView accountId={account.id}>
        <section className="page-stack">
          <PageHeader
            title="Drift"
            description="Compare retained portfolio sources."
          />
          <Notice title="Invalid company selection">
            Use one company selection and one retained run identity.
            <Link href={planningHref("/drift", { account: account.id })}>
              Reset comparison selection
            </Link>
          </Notice>
        </section>
      </AccountView>
    );
  }
  const preserved = {
    account: account.id,
    pie: selection?.pie?.id,
    version: selection?.version?.id,
    snapshot: selection?.snapshot?.id,
    basis,
    node: nodeId,
    company: companyQuery.included ? "include" : undefined,
    xray_run: companyQuery.runId,
  };
  let actual: ActualVsTargetResult | null = null;
  let drift: DriftAnalysisResult | null = null;
  let comparisonError: string | null = null;
  let selectedRun = companyQuery.runId;
  let pinRedirect: string | null = null;
  if (pins && selection?.snapshot) {
    try {
      if (companyQuery.included && !selectedRun) {
        const xray = await xrayClients();
        const retained = xrayData(
          await xray.xray.get_effective_exposure(account.id, {
            snapshot_id: pins.snapshot_id,
            source_cutoff_at: selection.snapshot.source_cutoff_at,
            reporting_currency: pins.reporting_currency,
            dimension: "company",
            view: "exposures",
            normalized_known_only: false,
            limit: 1,
          }),
        );
        // Pin the full retained calculation. Never derive a company total from this page.
        selectedRun = retained.context.run_id;
        pinRedirect = planningHref("/drift", {
          ...preserved,
          xray_run: selectedRun,
        });
      } else {
        [actual, drift] = await Promise.all([
          clients.planning
            .get_actual_vs_target(account.id, {
              ...pins,
              xray_run_id: selectedRun,
              node_id: nodeId,
              cursor: readOpaqueCursor(query.cursor),
              limit: 25,
            })
            .then(planningData),
          clients.planning
            .get_drift_analysis(account.id, {
              ...pins,
              xray_run_id: selectedRun,
              basis,
              top_n: 25,
            })
            .then(planningData),
        ]);
      }
    } catch (error) {
      comparisonError =
        error instanceof PlanningApiError || error instanceof XrayApiError
          ? error.code.replaceAll("_", " ")
          : "The comparison could not be loaded.";
    }
  }
  // Next redirects throw a control signal; keep it outside the service error handler.
  if (pinRedirect) redirect(pinRedirect);
  return (
    <AccountView accountId={account.id}>
      <div className="page-stack planning-page">
        <PageHeader
          title="Drift"
          description="Trace target gaps through groups, holdings, cash and unclassified exposure."
          actions={
            pins ? (
              <Link
                prefetch={false}
                className="text-link"
                href={planningHref("/planner", {
                  ...preserved,
                  company: undefined,
                  xray_run: undefined,
                })}
              >
                Plan a contribution
              </Link>
            ) : null
          }
        />
        <PlanningSelectionForms data={data} pathname="/drift" />
        {pins ? (
          <p>
            <Link
              prefetch={false}
              href={planningHref("/drift", {
                ...preserved,
                company: companyQuery.included ? undefined : "include",
                xray_run: undefined,
              })}
            >
              {companyQuery.included
                ? "Remove company comparison"
                : "Include company actual weights"}
            </Link>
          </p>
        ) : null}
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
                  Company actual weights require a pinned, usable X-ray
                  calculation. Company drift requires company targets and
                  remains unavailable when only listing targets exist. Direct
                  drift keeps its separate listing basis.
                </Notice>
              ) : null}
              <DriftTable
                rows={actual.rows.items}
                caption="Direct actual versus target for the selected hierarchy scope"
                showCompany={Boolean(actual.company_basis)}
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
                Server-ranked {drift.top_n}-row view using {drift.basis}{" "}
                weights. {drift.omitted_rows} of {drift.eligible_rows} rows
                omitted from this bounded sample.
              </p>
              <DriftTable
                rows={drift.groups}
                caption="Group and subgroup drift"
                basis={basis}
                showCompany={basis === "direct" && Boolean(drift.company_basis)}
              />
              <DriftTable
                rows={drift.leaves}
                caption="Holding drift"
                basis={basis}
                showCompany={basis === "direct" && Boolean(drift.company_basis)}
              />
              <DriftTable
                rows={drift.cash_and_unclassified}
                caption="Cash and unclassified drift"
                basis={basis}
                showCompany={basis === "direct" && Boolean(drift.company_basis)}
              />
            </Surface>
            {actual.company_basis ? (
              <p>
                <Link
                  prefetch={false}
                  href={planningHref("/reports", {
                    account: account.id,
                    snapshot: actual.company_basis.snapshot_id,
                    report_type: "target_drift",
                    target_version_id: pins?.target_version_id,
                    reporting_currency: actual.company_basis.reporting_currency,
                    xray_run_id: actual.company_basis.xray_run_id,
                  })}
                >
                  Create a report with this company basis
                </Link>
              </p>
            ) : null}
            <PlanningContext context={actual.context} />
            {actual.company_basis &&
            actual.company_context &&
            actual.projection_digest ? (
              <PlanningCompanyContext
                basis={actual.company_basis}
                context={actual.company_context}
                projectionDigest={actual.projection_digest}
              />
            ) : null}
          </>
        ) : comparisonError ? (
          <Notice title="Comparison unavailable">
            {comparisonError} The selected sources remain in the URL for retry.
          </Notice>
        ) : (
          <Notice title="Choose a published target and snapshot">
            A stored portfolio snapshot and a published, account-scoped target
            version are required.{" "}
            <Link
              prefetch={false}
              href={planningHref("/pies", { account: account.id })}
            >
              Manage Pies
            </Link>
          </Notice>
        )}
      </div>
    </AccountView>
  );
}
