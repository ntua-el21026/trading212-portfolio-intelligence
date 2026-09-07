import Link from "next/link";
import type { ReactNode } from "react";
import type { HistoricalRunContext } from "@trading212/api-contracts";
import { Notice, Surface } from "@trading212/ui";
import { requireWebAccess } from "../lib/auth";
import {
  historicalClients,
  historicalData,
  historicalResult,
  historicalWindow,
  performanceOptions,
} from "../lib/historical-adapter";
import {
  historicalHref,
  HistoricalQueryError,
  readHistoricalQuery,
  type HistoricalQuery,
  type HistoricalSearch,
} from "../lib/historical-query";
import { sourceData } from "../lib/source-adapter";
import { targetData } from "../lib/target-adapter";
import { PageHeader } from "./page-header";
import {
  HistoricalSelectionForm,
  HistoricalTabs,
} from "./historical-selection";
import {
  AttributionResult,
  BenchmarkResult,
  CashFlowResult,
  HistoricalContextDetails,
  IncomeResult,
  PerformanceMetricCards,
  PerformanceSeriesResult,
  PeriodReturnsResult,
} from "./historical-results";

type Path = "/performance" | "/income";

function HistoricalPagination({
  pathname,
  query,
  context,
  page,
}: Readonly<{
  pathname: Path;
  query: HistoricalQuery;
  context: HistoricalRunContext;
  page: {
    items: readonly unknown[];
    total: number;
    next_cursor: string | null;
  };
}>) {
  return (
    <nav className="collection-pagination" aria-label="Historical pagination">
      <p>
        Showing {page.items.length} rows on this page of {page.total} matching
        rows.
      </p>
      {page.next_cursor ? (
        <Link
          prefetch={false}
          href={historicalHref(pathname, query, {
            capture: context.input_snapshot_id,
            cursor: page.next_cursor,
          })}
        >
          Next page
        </Link>
      ) : null}
      {query.cursor ? (
        <Link
          prefetch={false}
          href={historicalHref(pathname, query, {
            capture: context.input_snapshot_id,
            cursor: null,
          })}
        >
          First page
        </Link>
      ) : null}
    </nav>
  );
}

async function loadHistoricalView(
  clients: Awaited<ReturnType<typeof historicalClients>>,
  pathname: Path,
  query: HistoricalQuery,
  accountId: string,
): Promise<{ content: ReactNode; context?: HistoricalRunContext }> {
  const client = clients.historical;
  if (query.view === "benchmark") {
    if (!query.benchmark)
      return {
        content: (
          <Notice title="Choose a benchmark version">
            Select a published benchmark above to compare returns on an explicit
            common currency and return basis.
          </Notice>
        ),
      };
    const data = historicalData(
      await client.get_benchmark_comparison(accountId, {
        ...historicalWindow(query),
        benchmark_version_id: query.benchmark,
        frequency: query.frequency,
        rolling_window: query.rolling,
        calendar_period: query.calendar,
      }),
    );
    return { context: data.context, content: <BenchmarkResult data={data} /> };
  }
  if (query.view === "attribution") {
    if (query.method === "mwr") throw new HistoricalQueryError();
    const data = historicalData(
      await client.get_attribution_summary(accountId, {
        ...historicalWindow(query),
        method: query.method,
        grouping: query.grouping,
        grouping_policy: query.grouping_policy,
        benchmark_version_id: query.benchmark,
        target_version_id: query.target,
        top_n: query.top,
      }),
    );
    return {
      context: data.context,
      content: <AttributionResult data={data} />,
    };
  }
  if (query.view === "income") {
    if (query.grouping !== "holding" && query.grouping !== "group")
      throw new HistoricalQueryError();
    const data = historicalData(
      await client.get_dividend_intelligence(accountId, {
        ...historicalWindow(query),
        grouping: query.grouping,
        grouping_policy: query.grouping_policy,
        target_version_id: query.target,
        top_n: query.top,
      }),
    );
    return { context: data.context, content: <IncomeResult data={data} /> };
  }
  if (query.view === "cash_flows") {
    const data = historicalData(
      await client.get_cash_flow_intelligence(accountId, {
        ...historicalWindow(query),
        frequency: query.frequency,
        kind: query.kind === "all" ? null : query.kind,
        cursor: query.cursor,
        limit: query.limit,
      }),
    );
    return {
      context: data.context,
      content: (
        <>
          <CashFlowResult data={data} />
          <HistoricalPagination
            pathname={pathname}
            query={query}
            context={data.context}
            page={data.events}
          />
        </>
      ),
    };
  }
  if (query.view === "series") {
    const data = historicalData(
      await client.get_performance_series(accountId, {
        ...performanceOptions(query),
        cursor: query.cursor,
        limit: query.limit,
      }),
    );
    return {
      context: data.context,
      content: (
        <>
          <PerformanceMetricCards summary={data.summary} />
          <PerformanceSeriesResult
            points={data.points.items}
            currency={query.currency}
            showFlows={query.flows === "show"}
            detailed
          />
          <HistoricalPagination
            pathname={pathname}
            query={query}
            context={data.context}
            page={data.points}
          />
        </>
      ),
    };
  }
  const data = historicalData(
    await client.get_performance_summary(accountId, performanceOptions(query)),
  );
  return {
    context: data.context,
    content: (
      <>
        <PerformanceMetricCards summary={data.summary} />
        {query.view === "rolling" ? (
          <PeriodReturnsResult
            title="Rolling returns"
            rows={data.rolling_returns}
          />
        ) : query.view === "calendar" ? (
          <PeriodReturnsResult
            title="Calendar returns"
            rows={data.calendar_returns}
          />
        ) : (
          <PerformanceSeriesResult
            points={data.series}
            currency={query.currency}
            showFlows={query.flows === "show"}
          />
        )}
      </>
    ),
  };
}

export async function HistoricalPage({
  pathname,
  search,
}: Readonly<{ pathname: Path; search: HistoricalSearch }>) {
  const access = await requireWebAccess();
  const header = (
    <PageHeader
      title={
        pathname === "/performance" ? "Performance" : "Income and cash flows"
      }
      description={
        pathname === "/performance"
          ? "Reconstruct portfolio returns, compare benchmarks and inspect the sources of change."
          : "Inspect dividend income and separate external contributions from internal portfolio activity."
      }
    />
  );
  if (access.isDemo)
    return (
      <div className="page-stack">
        {header}
        <Notice title="Historical analysis requires the connected runtime">
          Sign in to the local API to use persisted historical evidence and
          replayable calculations.
        </Notice>
      </div>
    );
  const clients = await historicalClients();
  const accounts = await clients.portfolio.listAccounts();
  const requested =
    typeof search.account === "string" ? search.account : undefined;
  const account = accounts.find(
    (row) =>
      row.id ===
      (requested ?? process.env.T212PI_ACCOUNT_ID ?? accounts[0]?.id),
  );
  let query: HistoricalQuery;
  try {
    query = readHistoricalQuery(search, {
      now: new Date(),
      currency: account?.reporting_currency ?? "EUR",
      pathname,
    });
  } catch (error) {
    if (!(error instanceof HistoricalQueryError)) throw error;
    return (
      <div className="page-stack">
        {header}
        <Notice title="Invalid historical filters">
          {error.message}{" "}
          <Link prefetch={false} href={pathname}>
            Reset filters
          </Link>
          .
        </Notice>
      </div>
    );
  }
  if (!account)
    return (
      <div className="page-stack">
        {header}
        <Notice title="Account unavailable">
          The selected account is unavailable for this session.{" "}
          <Link prefetch={false} href={pathname}>
            Reset selection
          </Link>
          .
        </Notice>
      </div>
    );
  query = { ...query, account: account.id };
  const [benchmarks, targets] = await Promise.all([
    historicalResult(async () =>
      query.view === "benchmark" || query.view === "attribution"
        ? sourceData(
            await clients.sources.list_benchmark_definitions({
              state: "active",
              limit: 25,
              cursor: query.benchmarks_cursor,
            }),
          )
        : null,
    ),
    historicalResult(async () =>
      query.view === "attribution" || query.view === "income"
        ? targetData(
            await clients.targets.list_virtual_portfolios({
              account_id: account.id,
              state: "active",
              sort: "name_asc",
              limit: 25,
            }),
          )
        : null,
    ),
  ]);
  const result = await historicalResult(() =>
    loadHistoricalView(clients, pathname, query, account.id),
  );
  return (
    <div className="page-stack historical-page">
      {header}
      <HistoricalTabs query={query} pathname={pathname} />
      <HistoricalSelectionForm
        pathname={pathname}
        query={query}
        accounts={accounts.map((row) => ({
          id: row.id,
          label: row.display_name,
        }))}
        benchmarks={
          benchmarks.ok
            ? (benchmarks.data?.items ?? []).flatMap((row) =>
                row.latest_version_id
                  ? [
                      {
                        id: row.latest_version_id,
                        label: `${row.name} · ${row.reporting_currency} · latest published version`,
                      },
                    ]
                  : [],
              )
            : []
        }
        benchmarkTotal={benchmarks.ok ? (benchmarks.data?.total ?? 0) : 0}
        nextBenchmarkCursor={
          benchmarks.ok ? (benchmarks.data?.next_cursor ?? null) : null
        }
        targets={
          targets.ok
            ? (targets.data?.items ?? []).flatMap((row) =>
                row.active_version_id
                  ? [
                      {
                        id: row.active_version_id,
                        label: `${row.name} · ${row.reporting_currency}`,
                      },
                    ]
                  : [],
              )
            : []
        }
        targetTotal={targets.ok ? (targets.data?.total ?? 0) : 0}
      />
      {!benchmarks.ok ? (
        <Notice title="Benchmark choices unavailable">
          {benchmarks.message}
        </Notice>
      ) : null}
      {!targets.ok ? (
        <Notice title="Target choices unavailable">{targets.message}</Notice>
      ) : null}
      {result.ok ? (
        <>
          {result.data.content}
          {result.data.context ? (
            <HistoricalContextDetails
              context={result.data.context}
              replayHref={historicalHref(pathname, query, {
                capture: result.data.context.input_snapshot_id,
              })}
            />
          ) : null}
        </>
      ) : (
        <Notice title="Historical analysis unavailable">
          {result.message} <span className="muted">{result.code}</span>
        </Notice>
      )}
      <Surface>
        <p>
          Source coverage, valuation times and the selected knowledge policy
          determine which results are available. Every financial amount is
          calculated by the server. Inspect{" "}
          <Link prefetch={false} href={`/sources?account=${account.id}`}>
            sources and licenses
          </Link>{" "}
          or{" "}
          <Link prefetch={false} href="/quality">
            data quality
          </Link>{" "}
          for missing evidence.
        </p>
      </Surface>
    </div>
  );
}
