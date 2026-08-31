import { CircleDollarSign } from "lucide-react";

import { EmptyState, Surface } from "@trading212/ui";

import { MetricCard } from "../../../components/financial";
import { PageHeader } from "../../../components/page-header";
import { DividendsTable } from "../../../components/portfolio-tables";
import { MethodologyDetails, QualityBanner } from "../../../components/quality";
import {
  loadPortfolioBundle,
  readDemoViewState,
} from "../../../lib/api-adapter";

export default async function DividendsPage({
  searchParams,
}: Readonly<{ searchParams: Promise<{ state?: string | string[] }> }>) {
  const bundle = await loadPortfolioBundle(
    readDemoViewState((await searchParams).state),
  );
  return (
    <div className="page-stack">
      <PageHeader
        description="Covered normalized dividend records with gross, withholding, and net values kept distinct."
        title="Dividends"
      />
      <QualityBanner quality={bundle.quality} />
      <Surface className="summary-strip">
        <MetricCard
          label="Dividends received"
          metric={bundle.summary.dividends_received}
          note="Covered history only"
          primary
        />
        <MethodologyDetails metric={bundle.summary.dividends_received} />
      </Surface>
      <Surface>
        {bundle.dividends.items.length === 0 ? (
          <EmptyState
            description="No dividend records are available for the covered history. Missing history is not presented as zero."
            icon={<CircleDollarSign aria-hidden="true" size={22} />}
            title="No dividend history"
          />
        ) : (
          <DividendsTable dividends={bundle.dividends.items} />
        )}
      </Surface>
    </div>
  );
}
