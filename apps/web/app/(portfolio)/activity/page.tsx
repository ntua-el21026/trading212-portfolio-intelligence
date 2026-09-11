import {
  AccountRequired,
  AccountView,
} from "../../../components/account-context";
import { loadSelectedAccount } from "../../../lib/api-adapter";
import { ListTree } from "lucide-react";

import { EmptyState, Surface } from "@trading212/ui";

import { CollectionPagination } from "../../../components/collection-pagination";
import { PageHeader } from "../../../components/page-header";
import { ActivityTable } from "../../../components/portfolio-tables";
import { QualityBanner } from "../../../components/quality";
import { loadActivityPage, readDemoViewState } from "../../../lib/api-adapter";
import {
  firstSearchParam,
  readDateParam,
  readEnumParam,
  readOpaqueCursor,
  validateDateRange,
} from "../../../lib/collection-query";

const ACTIVITY_TYPES = new Set([
  "all",
  "buy",
  "sell",
  "deposit",
  "withdrawal",
  "dividend",
  "interest",
  "fee",
  "tax",
  "fx_conversion",
  "unknown",
] as const);

export default async function ActivityPage({
  searchParams,
}: Readonly<{
  searchParams: Promise<{
    account?: string | string[];
    activity_type?: string | string[];
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
  const activityType = readEnumParam(
    params.activity_type,
    ACTIVITY_TYPES,
    "all",
  );
  const bundle = await loadActivityPage(
    {
      activityType,
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
          description="Canonical transactions and cash flows. Buys and sells remain internal portfolio flows."
          title="Activity"
        />
        <QualityBanner quality={bundle.quality} />
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
            <label>
              <span>Activity type</span>
              <select defaultValue={activityType} name="activity_type">
                {Array.from(ACTIVITY_TYPES).map((value) => (
                  <option key={value} value={value}>
                    {value.replaceAll("_", " ")}
                  </option>
                ))}
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
          {bundle.activity.items.length === 0 ? (
            <EmptyState
              description="Transactions and cash flows will appear after covered history is synchronized."
              icon={<ListTree aria-hidden="true" size={22} />}
              title="No activity available"
            />
          ) : (
            <ActivityTable activity={bundle.activity.items} />
          )}
          <CollectionPagination
            nextCursor={bundle.activity.next_cursor}
            pathname="/activity"
            preservedQuery={{
              account: selectedAccountId,
              activity_type: activityType,
              end_date: endDate,
              start_date: startDate,
              state: firstSearchParam(params.state),
            }}
            returnedCount={bundle.activity.items.length}
            total={bundle.activity.total}
          />
        </Surface>
      </div>
    </AccountView>
  );
}
