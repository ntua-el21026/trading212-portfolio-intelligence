import {
  AccountRequired,
  AccountView,
} from "../../../components/account-context";
import { loadSelectedAccount } from "../../../lib/api-adapter";
import { CircleDollarSign } from "lucide-react";

import { EmptyState, Surface } from "@trading212/ui";

import { CollectionPagination } from "../../../components/collection-pagination";
import { MetricCard } from "../../../components/financial";
import { PageHeader } from "../../../components/page-header";
import { DividendsTable } from "../../../components/portfolio-tables";
import { MethodologyDetails, QualityBanner } from "../../../components/quality";
import { loadDividendsPage, readDemoViewState } from "../../../lib/api-adapter";
import {
  firstSearchParam,
  readDateParam,
  readOpaqueCursor,
  validateDateRange,
} from "../../../lib/collection-query";

export default async function DividendsPage({
  searchParams,
}: Readonly<{
  searchParams: Promise<{
    account?: string | string[];
    cursor?: string | string[];
    end_date?: string | string[];
    start_date?: string | string[];
    state?: string | string[];
  }>;
}>) {
  const params = await searchParams;
  const accountSelection = await loadSelectedAccount(params.account);
  if (!accountSelection.account)
    return <AccountRequired selection={accountSelection} />;
  const selectedAccountId = accountSelection.account.id;
  const state = readDemoViewState(params.state);
  const startDate = readDateParam(params.start_date);
  const endDate = readDateParam(params.end_date);
  validateDateRange(startDate, endDate);
  const bundle = await loadDividendsPage(
    {
      cursor: readOpaqueCursor(params.cursor),
      endDate,
      startDate,
    },
    state,
    selectedAccountId,
  );
  return (
    <AccountView accountId={selectedAccountId}>
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
          <form className="collection-filters" method="get">
            <input type="hidden" name="account" value={selectedAccountId} />
            <label>
              <span>From</span>
              <input defaultValue={startDate} name="start_date" type="date" />
            </label>
            <label>
              <span>To</span>
              <input defaultValue={endDate} name="end_date" type="date" />
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
          {bundle.dividends.items.length === 0 ? (
            <EmptyState
              description="No dividend records are available for the covered history. Missing history is not presented as zero."
              icon={<CircleDollarSign aria-hidden="true" size={22} />}
              title="No dividend history"
            />
          ) : (
            <DividendsTable dividends={bundle.dividends.items} />
          )}
          <CollectionPagination
            nextCursor={bundle.dividends.next_cursor}
            pathname="/dividends"
            preservedQuery={{
              account: selectedAccountId,
              end_date: endDate,
              start_date: startDate,
              state: firstSearchParam(params.state),
            }}
            returnedCount={bundle.dividends.items.length}
            total={bundle.dividends.total}
          />
        </Surface>
      </div>
    </AccountView>
  );
}
