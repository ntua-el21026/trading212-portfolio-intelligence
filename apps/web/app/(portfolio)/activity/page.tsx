import { ListTree } from "lucide-react";

import { EmptyState, Surface } from "@trading212/ui";

import { PageHeader } from "../../../components/page-header";
import { ActivityTable } from "../../../components/portfolio-tables";
import { QualityBanner } from "../../../components/quality";
import {
  loadPortfolioBundle,
  readDemoViewState,
} from "../../../lib/api-adapter";

export default async function ActivityPage({
  searchParams,
}: Readonly<{ searchParams: Promise<{ state?: string | string[] }> }>) {
  const bundle = await loadPortfolioBundle(
    readDemoViewState((await searchParams).state),
  );
  return (
    <div className="page-stack">
      <PageHeader
        description="Canonical transactions and cash flows. Buys and sells remain internal portfolio flows."
        title="Activity"
      />
      <QualityBanner quality={bundle.quality} />
      <Surface>
        {bundle.activity.items.length === 0 ? (
          <EmptyState
            description="Transactions and cash flows will appear after covered history is synchronized."
            icon={<ListTree aria-hidden="true" size={22} />}
            title="No activity available"
          />
        ) : (
          <ActivityTable activity={bundle.activity.items} />
        )}
      </Surface>
    </div>
  );
}
