import { AccountRequired, AccountView } from "../../components/account-context";
import { loadSelectedAccount } from "../../lib/api-adapter";
import { Overview } from "../../components/overview";
import { PageHeader } from "../../components/page-header";
import { loadOverview, readDemoViewState } from "../../lib/api-adapter";

export default async function OverviewPage({
  searchParams,
}: Readonly<{
  searchParams: Promise<{
    account?: string | string[];
    state?: string | string[];
  }>;
}>) {
  const params = await searchParams;
  const accountSelection = await loadSelectedAccount(params.account);
  if (!accountSelection.account)
    return <AccountRequired selection={accountSelection} />;
  const selectedAccountId = accountSelection.account.id;
  const state = readDemoViewState(params.state);
  const bundle = await loadOverview(state, selectedAccountId);
  return (
    <AccountView accountId={selectedAccountId}>
      <div className="page-stack">
        <PageHeader
          description={`All values in ${bundle.summary.account.reporting_currency} unless stated otherwise.`}
          title="Overview"
        />
        <Overview bundle={bundle} />
      </div>
    </AccountView>
  );
}
