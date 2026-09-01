import { Overview } from "../../components/overview";
import { PageHeader } from "../../components/page-header";
import { loadOverview, readDemoViewState } from "../../lib/api-adapter";

export default async function OverviewPage({
  searchParams,
}: Readonly<{ searchParams: Promise<{ state?: string | string[] }> }>) {
  const state = readDemoViewState((await searchParams).state);
  const bundle = await loadOverview(state);
  return (
    <div className="page-stack">
      <PageHeader
        description={`All values in ${bundle.summary.account.reporting_currency} unless stated otherwise.`}
        title="Overview"
      />
      <Overview bundle={bundle} />
    </div>
  );
}
