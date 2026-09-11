import {
  AccountRequired,
  AccountView,
} from "../../../components/account-context";
import { loadSelectedAccount } from "../../../lib/api-adapter";
import { BriefcaseBusiness } from "lucide-react";

import { EmptyState, Surface } from "@trading212/ui";

import { CollectionPagination } from "../../../components/collection-pagination";
import { PageHeader } from "../../../components/page-header";
import { PositionsTable } from "../../../components/portfolio-tables";
import { QualityBanner } from "../../../components/quality";
import { loadHoldingsPage, readDemoViewState } from "../../../lib/api-adapter";
import {
  firstSearchParam,
  readBoundedSearch,
  readEnumParam,
  readOpaqueCursor,
} from "../../../lib/collection-query";

const POSITION_SORTS = new Set([
  "market_value_desc",
  "weight_desc",
  "ticker_asc",
] as const);

export default async function HoldingsPage({
  searchParams,
}: Readonly<{
  searchParams: Promise<{
    account?: string | string[];
    cursor?: string | string[];
    search?: string | string[];
    sort?: string | string[];
    state?: string | string[];
  }>;
}>) {
  const params = await searchParams;
  const accountSelection = await loadSelectedAccount(params.account);
  if (!accountSelection.account)
    return <AccountRequired selection={accountSelection} />;
  const selectedAccountId = accountSelection.account.id;
  const state = readDemoViewState(params.state);
  const search = readBoundedSearch(params.search);
  const sort = readEnumParam(params.sort, POSITION_SORTS, "market_value_desc");
  const bundle = await loadHoldingsPage(
    { cursor: readOpaqueCursor(params.cursor), search, sort },
    state,
    selectedAccountId,
  );
  return (
    <AccountView accountId={selectedAccountId}>
      <div className="page-stack">
        <PageHeader
          description="Provider-observed direct positions with canonical values and availability."
          title="Holdings"
        />
        <QualityBanner quality={bundle.summary.data_quality} />
        <Surface>
          <form className="collection-filters" method="get">
            <input type="hidden" name="account" value={selectedAccountId} />
            <label>
              <span>Search ticker or name</span>
              <input defaultValue={search} maxLength={120} name="search" />
            </label>
            <label>
              <span>Sort</span>
              <select defaultValue={sort} name="sort">
                <option value="market_value_desc">Market value</option>
                <option value="weight_desc">Direct weight</option>
                <option value="ticker_asc">Ticker A–Z</option>
              </select>
            </label>
            {firstSearchParam(params.state) ? (
              <input
                name="state"
                type="hidden"
                value={firstSearchParam(params.state)}
              />
            ) : null}
            <button type="submit">Apply</button>
          </form>
          {bundle.positions.items.length === 0 ? (
            <EmptyState
              description="Positions will appear after the first successful read-only synchronization."
              icon={<BriefcaseBusiness aria-hidden="true" size={22} />}
              title="No holdings available"
            />
          ) : (
            <PositionsTable
              accountId={selectedAccountId}
              positions={bundle.positions.items}
            />
          )}
          <CollectionPagination
            nextCursor={bundle.positions.next_cursor}
            pathname="/holdings"
            preservedQuery={{
              account: selectedAccountId,
              search,
              sort,
              state: firstSearchParam(params.state),
            }}
            returnedCount={bundle.positions.items.length}
            total={bundle.positions.total}
          />
        </Surface>
      </div>
    </AccountView>
  );
}
