import { Clock3 } from "lucide-react";

import { EmptyState, Surface } from "@trading212/ui";

import { CollectionPagination } from "../../../components/collection-pagination";
import { SnapshotChart } from "../../../components/charts";
import { PageHeader } from "../../../components/page-header";
import { SnapshotsTable } from "../../../components/portfolio-tables";
import { QualityBanner } from "../../../components/quality";
import { loadSnapshotsPage, readDemoViewState } from "../../../lib/api-adapter";
import {
  firstSearchParam,
  readOpaqueCursor,
} from "../../../lib/collection-query";

export default async function SnapshotsPage({
  searchParams,
}: Readonly<{
  searchParams: Promise<{
    cursor?: string | string[];
    state?: string | string[];
  }>;
}>) {
  const params = await searchParams;
  const bundle = await loadSnapshotsPage(
    readOpaqueCursor(params.cursor),
    readDemoViewState(params.state),
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
                <p>
                  This chart covers the {bundle.snapshots.items.length} records
                  returned on this page; exact values remain in the table.
                </p>
              </div>
            </div>
            <SnapshotChart snapshots={bundle.snapshots.items} />
          </Surface>
          <Surface>
            <SnapshotsTable snapshots={bundle.snapshots.items} />
            <CollectionPagination
              nextCursor={bundle.snapshots.next_cursor}
              pathname="/snapshots"
              preservedQuery={{ state: firstSearchParam(params.state) }}
              returnedCount={bundle.snapshots.items.length}
              total={bundle.snapshots.total}
            />
          </Surface>
        </>
      )}
    </div>
  );
}
