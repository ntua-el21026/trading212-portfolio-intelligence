import Link from "next/link";
import { Button, Notice, Surface } from "@trading212/ui";
import { PageHeader } from "../../../components/page-header";
import { CollectionPagination } from "../../../components/collection-pagination";
import {
  SourceProviderDetails,
  SourceSeriesTable,
} from "../../../components/source-details";
import { BenchmarkForm } from "../../../components/benchmark-form";
import {
  sourceClients,
  sourceData,
  sourceResult,
} from "../../../lib/source-adapter";
import { requireWebAccess } from "../../../lib/auth";
import {
  planningHref,
  planningUuid,
  type PlanningSearch,
} from "../../../lib/planning-selection";
import {
  readBoundedSearch,
  readEnumParam,
  readOpaqueCursor,
} from "../../../lib/collection-query";
import { titleCase } from "../../../lib/format";

export default async function SourcesPage({
  searchParams,
}: Readonly<{ searchParams: Promise<PlanningSearch> }>) {
  const access = await requireWebAccess();
  if (access.isDemo)
    return (
      <div className="page-stack">
        <PageHeader
          title="Sources and benchmarks"
          description="Inspect the provenance, coverage and permitted uses behind your analysis."
        />
        <Notice title="Sources require the connected runtime">
          Sign in to the local API to inspect persisted reference data and
          manage benchmark definitions.
        </Notice>
      </div>
    );
  const query = await searchParams;
  const clients = await sourceClients();
  const accounts = await clients.portfolio.listAccounts();
  const accountId = planningUuid(query.account) ?? accounts[0]?.id;
  const account = accounts.find((item) => item.id === accountId);
  const kind = readEnumParam(
    query.kind,
    new Set(["market", "fx", "benchmark", "definitions"] as const),
    "market",
  );
  const search = readBoundedSearch(query.search);
  const cursor = readOpaqueCursor(query.cursor);
  const basis = readEnumParam(
    query.basis,
    new Set(["all", "raw_close", "split_adjusted", "total_return"] as const),
    "all",
  );
  const state = readEnumParam(
    query.state,
    new Set(["active", "archived", "all"] as const),
    "active",
  );
  const preserved = { account: account?.id, kind, search, basis, state };
  const result = await sourceResult(async () => {
    if (kind === "definitions") {
      const [definitions, catalogs] = await Promise.all([
        clients.sources
          .list_benchmark_definitions({ limit: 25, cursor, state, search })
          .then(sourceData),
        sourceResult(async () =>
          account
            ? Promise.all([
                clients.sources
                  .get_market_source_status(account.id, { limit: 100 })
                  .then(sourceData),
                clients.sources
                  .get_benchmark_source_status(account.id, { limit: 100 })
                  .then(sourceData),
              ])
            : [],
        ),
      ]);
      const available = (
        catalogs.ok
          ? catalogs.data.flatMap((catalog) => catalog.series.items)
          : []
      )
        .filter(
          (item) => item.latest_snapshot && item.availability !== "unavailable",
        )
        .map((item) => item.series);
      return () => (
        <>
          <Surface>
            <h2>Saved benchmark definitions</h2>
            {definitions.items.length ? (
              <ul className="source-definition-list">
                {definitions.items.map((item) => (
                  <li key={item.id}>
                    <Link
                      prefetch={false}
                      href={planningHref(`/sources/benchmarks/${item.id}`, {
                        account: account?.id,
                      })}
                    >
                      {item.name}
                    </Link>
                    <span>
                      {item.reporting_currency} · {item.version_count} versions
                      · {titleCase(item.state)}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p>No benchmark definitions match these filters.</p>
            )}
            <CollectionPagination
              pathname="/sources"
              preservedQuery={preserved}
              returnedCount={definitions.items.length}
              total={definitions.total}
              nextCursor={definitions.next_cursor}
            />
          </Surface>
          {!catalogs.ok ? (
            <Notice title="Source choices are unavailable">
              {catalogs.message}
            </Notice>
          ) : null}
          <BenchmarkForm
            sources={available}
            accountId={account?.id}
            currency={account?.reporting_currency}
            effectiveAt={new Date().toISOString()}
          />
        </>
      );
    }
    if (!account)
      return () => (
        <Notice title="No account is available">
          Select an authorized account to inspect its sources.
        </Notice>
      );
    if (kind === "fx") {
      const data = sourceData(
        await clients.sources.get_fx_source_status(account.id, {
          limit: 25,
          cursor,
        }),
      );
      return () => (
        <>
          <SourceProviderDetails providers={data.providers} />
          <Surface>
            <h2>FX reference pairs</h2>
            <p>
              Rates mean quote-currency units for one base-currency unit.
              Derived conversions pin their source legs.
            </p>
            <div className="table-scroll">
              <table className="data-table" aria-label="FX reference pairs">
                <thead>
                  <tr>
                    <th>Pair</th>
                    <th>Coverage</th>
                    <th>State</th>
                    <th>Source</th>
                  </tr>
                </thead>
                <tbody>
                  {data.pairs.items.map((item) => (
                    <tr key={`${item.provider_id}:${item.base}:${item.quote}`}>
                      <td>
                        {item.base}/{item.quote}
                      </td>
                      <td>
                        {item.latest_snapshot
                          ? `${item.latest_snapshot.available_count} / ${item.latest_snapshot.expected_count}`
                          : "Unavailable"}
                      </td>
                      <td>
                        {titleCase(
                          item.latest_snapshot?.freshness.state ??
                            item.availability,
                        )}
                      </td>
                      <td>
                        {item.latest_snapshot ? (
                          <Link
                            prefetch={false}
                            href={`/sources/snapshots/fx/${item.latest_snapshot.id}?account=${account.id}`}
                          >
                            Inspect observations
                          </Link>
                        ) : (
                          titleCase(item.reason ?? "unavailable")
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <CollectionPagination
              pathname="/sources"
              preservedQuery={preserved}
              returnedCount={data.pairs.items.length}
              total={data.pairs.total}
              nextCursor={data.pairs.next_cursor}
            />
          </Surface>
        </>
      );
    } else {
      const filters = {
        limit: 25,
        cursor,
        search,
        basis: basis === "all" ? null : basis,
      };
      const data = sourceData(
        kind === "market"
          ? await clients.sources.get_market_source_status(account.id, filters)
          : await clients.sources.get_benchmark_source_status(
              account.id,
              filters,
            ),
      );
      return () => (
        <>
          <SourceProviderDetails providers={data.providers} />
          <Surface>
            <h2>
              {kind === "market"
                ? "Market price series"
                : "Provider benchmark series"}
            </h2>
            <p>
              {kind === "market"
                ? "Raw close, split-adjusted and total-return data retain separate series identities."
                : "These are provider levels. Saved benchmark definitions are separate from calculated composite results."}
            </p>
            <SourceSeriesTable
              items={data.series.items}
              accountId={account.id}
              kind={kind === "market" ? "price" : "benchmark"}
            />
            <CollectionPagination
              pathname="/sources"
              preservedQuery={preserved}
              returnedCount={data.series.items.length}
              total={data.series.total}
              nextCursor={data.series.next_cursor}
            />
          </Surface>
        </>
      );
    }
  });
  const content = result.ok ? (
    result.data()
  ) : (
    <Notice title="Source data is unavailable">
      <p>{result.message}</p>
      <Link prefetch={false} href={planningHref("/sources", preserved)}>
        Reload first page with these filters
      </Link>
    </Notice>
  );
  return (
    <div className="page-stack source-page">
      <PageHeader
        title="Sources and benchmarks"
        description="Inspect source coverage, revisions and licenses, and choose a versioned benchmark."
      />
      <nav className="source-tabs" aria-label="Source categories">
        {(["market", "fx", "benchmark", "definitions"] as const).map(
          (value) => (
            <Link
              key={value}
              prefetch={false}
              aria-current={kind === value ? "page" : undefined}
              href={planningHref("/sources", {
                account: account?.id,
                kind: value,
              })}
            >
              {value === "definitions"
                ? "My benchmarks"
                : value === "fx"
                  ? "FX"
                  : titleCase(value)}
            </Link>
          ),
        )}
      </nav>
      <Surface>
        <form className="target-form" method="get">
          <input type="hidden" name="kind" value={kind} />
          <label>
            <span>Account</span>
            <select
              name="account"
              defaultValue={account?.id}
              disabled={!accounts.length}
            >
              {!accounts.length ? (
                <option value="">No accounts available</option>
              ) : null}
              {accounts.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.display_name}
                </option>
              ))}
            </select>
          </label>
          {kind !== "fx" ? (
            <label>
              <span>Search sources or benchmarks</span>
              <input name="search" defaultValue={search} maxLength={80} />
            </label>
          ) : null}
          {kind === "market" || kind === "benchmark" ? (
            <label>
              <span>Price basis</span>
              <select name="basis" defaultValue={basis}>
                <option value="all">All bases</option>
                <option value="raw_close">Raw close</option>
                <option value="split_adjusted">Split adjusted</option>
                <option value="total_return">Total return</option>
              </select>
            </label>
          ) : null}
          {kind === "definitions" ? (
            <label>
              <span>Definition state</span>
              <select name="state" defaultValue={state}>
                <option value="active">Active</option>
                <option value="archived">Archived</option>
                <option value="all">All</option>
              </select>
            </label>
          ) : null}
          <Button type="submit">Apply filters</Button>
        </form>
      </Surface>
      {content}
    </div>
  );
}
