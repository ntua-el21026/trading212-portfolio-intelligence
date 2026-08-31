import { Clock3 } from "lucide-react";

import { EmptyState, Surface } from "@trading212/ui";

import { SnapshotChart } from "../../../components/charts";
import { PageHeader } from "../../../components/page-header";
import { SnapshotsTable } from "../../../components/portfolio-tables";
import { QualityBanner } from "../../../components/quality";
import {
  loadPortfolioBundle,
  readDemoViewState,
} from "../../../lib/api-adapter";

export default async function SnapshotsPage({
  searchParams,
}: Readonly<{ searchParams: Promise<{ state?: string | string[] }> }>) {
  const bundle = await loadPortfolioBundle(
    readDemoViewState((await searchParams).state),
  );
  return (
    <div className="page-stack">
      <PageHeader
        description="Immutable historical portfolio observations with explicit valuation and source cutoffs."
        title="Snapshots"
      />
      <QualityBanner quality={bundle.quality} />
      {bundle.snapshots.items.length === 0 ? (
        <Surface>
          <EmptyState
            description="Snapshot history will appear after a successful snapshot-enabled synchronization."
            icon={<Clock3 aria-hidden="true" size={22} />}
            title="No snapshots available"
          />
        </Surface>
      ) : (
        <>
          <Surface className="chart-panel">
            <div className="section-heading-row">
              <div>
                <h2>Portfolio value history</h2>
                <p>Exact values remain available in the table below.</p>
              </div>
            </div>
            <SnapshotChart snapshots={bundle.snapshots.items} />
          </Surface>
          <Surface>
            <SnapshotsTable snapshots={bundle.snapshots.items} />
          </Surface>
        </>
      )}
    </div>
  );
}
