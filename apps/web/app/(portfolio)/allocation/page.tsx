import { ChartPie } from "lucide-react";

import { EmptyState, Surface } from "@trading212/ui";

import { AllocationChart } from "../../../components/charts";
import { PageHeader } from "../../../components/page-header";
import { QualityBanner } from "../../../components/quality";
import {
  loadPortfolioBundle,
  readDemoViewState,
} from "../../../lib/api-adapter";
import { formatMoney, formatPercent, titleCase } from "../../../lib/format";

export default async function AllocationPage({
  searchParams,
}: Readonly<{ searchParams: Promise<{ state?: string | string[] }> }>) {
  const bundle = await loadPortfolioBundle(
    readDemoViewState((await searchParams).state),
  );
  return (
    <div className="page-stack">
      <PageHeader
        description="Direct position weights supplied by the canonical Phase 1 allocation response."
        title="Allocation"
      />
      <QualityBanner quality={bundle.summary.data_quality} />
      <Surface className="allocation-page-panel">
        {bundle.allocation.length === 0 ? (
          <EmptyState
            description="Allocation requires at least one available position or cash balance."
            icon={<ChartPie aria-hidden="true" size={22} />}
            title="Allocation unavailable"
          />
        ) : (
          <div className="allocation-page-grid">
            <AllocationChart data={bundle.allocation} />
            <div className="table-scroll">
              <table className="data-table data-table--roomy">
                <caption className="ui-visually-hidden">
                  Direct allocation details
                </caption>
                <thead>
                  <tr>
                    <th scope="col">Holding</th>
                    <th scope="col">Type</th>
                    <th scope="col">Market value</th>
                    <th scope="col">Weight</th>
                    <th scope="col">Availability</th>
                  </tr>
                </thead>
                <tbody>
                  {bundle.allocation.map((item, index) => (
                    <tr key={item.id}>
                      <th scope="row">
                        <span
                          aria-hidden="true"
                          className={`allocation-key allocation-key--${(index % 6) + 1}`}
                        />
                        {item.label}
                      </th>
                      <td>{titleCase(item.asset_type)}</td>
                      <td>
                        {formatMoney(item.market_value.value)}{" "}
                        {item.market_value.reporting_currency}
                      </td>
                      <td>{formatPercent(item.weight)}</td>
                      <td>{titleCase(item.weight_availability)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </Surface>
    </div>
  );
}
