import { BriefcaseBusiness } from "lucide-react";

import { EmptyState, Surface } from "@trading212/ui";

import { PageHeader } from "../../../components/page-header";
import { PositionsTable } from "../../../components/portfolio-tables";
import { QualityBanner } from "../../../components/quality";
import {
  loadPortfolioBundle,
  readDemoViewState,
} from "../../../lib/api-adapter";

export default async function HoldingsPage({
  searchParams,
}: Readonly<{ searchParams: Promise<{ state?: string | string[] }> }>) {
  const bundle = await loadPortfolioBundle(
    readDemoViewState((await searchParams).state),
  );
  return (
    <div className="page-stack">
      <PageHeader
        description="Provider-observed direct positions with canonical values and availability."
        title="Holdings"
      />
      <QualityBanner quality={bundle.summary.data_quality} />
      <Surface>
        {bundle.positions.items.length === 0 ? (
          <EmptyState
            description="Positions will appear after the first successful read-only synchronization."
            icon={<BriefcaseBusiness aria-hidden="true" size={22} />}
            title="No holdings available"
          />
        ) : (
          <PositionsTable positions={bundle.positions.items} />
        )}
      </Surface>
    </div>
  );
}
