import {
  AccountRequired,
  AccountView,
} from "../../../../../components/account-context";
import type { ReactNode } from "react";
import { loadSelectedAccount } from "../../../../../lib/api-adapter";
import Link from "../../../../../components/navigation-intent";
import { notFound } from "next/navigation";
import { Notice, Surface } from "@trading212/ui";
import { PageHeader } from "../../../../../components/page-header";
import { BenchmarkForm } from "../../../../../components/benchmark-form";
import { CollectionPagination } from "../../../../../components/collection-pagination";
import {
  sourceClients,
  sourceData,
  sourceResult,
} from "../../../../../lib/source-adapter";
import {
  planningHref,
  planningUuid,
  type PlanningSearch,
} from "../../../../../lib/planning-selection";
import { readOpaqueCursor } from "../../../../../lib/collection-query";
import { formatDateTime, titleCase } from "../../../../../lib/format";

export default async function BenchmarkPage({
  params,
  searchParams,
}: Readonly<{
  params: Promise<{ definitionId: string }>;
  searchParams: Promise<PlanningSearch>;
}>) {
  const definitionId = planningUuid((await params).definitionId);
  if (!definitionId) notFound();
  const query = await searchParams;
  // Definitions belong to the owner. Only an explicit account requests catalog scope.
  const accountSelection =
    query.account === undefined
      ? null
      : await loadSelectedAccount(query.account);
  if (accountSelection && !accountSelection.account)
    return <AccountRequired selection={accountSelection} />;
  const account = accountSelection?.account;
  const withScope = (content: ReactNode) =>
    account ? (
      <AccountView accountId={account.id}>{content}</AccountView>
    ) : (
      <>
        <Notice title="Owner-wide benchmark">
          This benchmark is shown for its owner without a portfolio account
          selection.
        </Notice>
        {content}
      </>
    );
  const clients = await sourceClients();
  const result = await sourceResult(async () => {
    const detail = sourceData(
      await clients.sources.get_benchmark_definition(definitionId, {
        limit: 25,
        cursor: readOpaqueCursor(query.cursor),
        selected_version_id: planningUuid(query.version),
      }),
    );
    const [market, benchmark] = account
      ? await Promise.all([
          clients.sources
            .get_market_source_status(account.id, { limit: 100 })
            .then(sourceData),
          clients.sources
            .get_benchmark_source_status(account.id, { limit: 100 })
            .then(sourceData),
        ])
      : [null, null];
    const available = [
      ...(market?.series.items ?? []),
      ...(benchmark?.series.items ?? []),
    ]
      .filter(
        (item) => item.latest_snapshot && item.availability !== "unavailable",
      )
      .map((item) => item.series);
    const selected = detail.selected_version;
    const preserved = {
      account: account?.id,
      version: planningUuid(query.version),
    };
    return { detail, available, selected, preserved };
  });
  if (!result.ok) {
    if (result.code === "NOT_FOUND") notFound();
    return withScope(
      <Notice title="Benchmark unavailable">{result.message}</Notice>,
    );
  }
  const { detail, available, selected, preserved } = result.data;
  return withScope(
    <div className="page-stack source-page">
      <PageHeader
        title={detail.definition.name}
        description={`${detail.definition.reporting_currency} · ${titleCase(detail.definition.state)} · ${detail.definition.version_count} immutable versions`}
      />
      <Link
        prefetch={false}
        href={planningHref("/sources", {
          account: account?.id,
          kind: "definitions",
        })}
      >
        Back to benchmarks
      </Link>
      <Surface>
        <h2>Published versions</h2>
        <ul className="source-definition-list">
          {detail.versions.items.map((version) => (
            <li key={version.id}>
              <Link
                prefetch={false}
                aria-current={selected?.id === version.id ? "page" : undefined}
                href={planningHref(`/sources/benchmarks/${definitionId}`, {
                  account: account?.id,
                  version: version.id,
                })}
              >
                Version {version.version_number}
              </Link>
              <span>
                {formatDateTime(version.published_at)} ·{" "}
                {titleCase(version.content.rebalance_rule)}
              </span>
            </li>
          ))}
        </ul>
        <CollectionPagination
          pathname={`/sources/benchmarks/${definitionId}`}
          preservedQuery={preserved}
          returnedCount={detail.versions.items.length}
          total={detail.versions.total}
          nextCursor={detail.versions.next_cursor}
        />
      </Surface>
      {selected ? (
        <Surface>
          <h2>Version {selected.version_number} composition</h2>
          <dl className="detail-grid">
            <div>
              <dt>Effective time</dt>
              <dd>{formatDateTime(selected.content.effective_at)}</dd>
            </div>
            <div>
              <dt>Return basis</dt>
              <dd>{titleCase(selected.content.return_basis)}</dd>
            </div>
            <div>
              <dt>Calendar</dt>
              <dd>
                {selected.content.calendar_id} ·{" "}
                {selected.content.calendar_version}
              </dd>
            </div>
            <div>
              <dt>Convention</dt>
              <dd>{titleCase(selected.content.rebalance_rule)}</dd>
            </div>
          </dl>
          <div className="table-scroll">
            <table className="data-table" aria-label="Benchmark composition">
              <thead>
                <tr>
                  <th>Source series</th>
                  <th>Exact weight fraction</th>
                </tr>
              </thead>
              <tbody>
                {selected.content.components.map((component) => (
                  <tr key={component.source_id}>
                    <td className="source-identifier">
                      {available.find(
                        (source) => source.id === component.source_id,
                      )?.provider_key ?? component.source_id}
                    </td>
                    <td className="numeric">{component.weight}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {selected.normalization_adjustments.length ? (
            <details className="source-disclosure">
              <summary>Explicit normalization adjustments</summary>
              <ul>
                {selected.normalization_adjustments.map((item) => (
                  <li key={item.source_id}>
                    <span className="source-identifier">{item.source_id}</span>:{" "}
                    {item.original_weight} → {item.normalized_weight}
                  </li>
                ))}
              </ul>
            </details>
          ) : null}
          <details className="source-disclosure">
            <summary>Content identity</summary>
            <p className="source-identifier">{selected.content_digest}</p>
          </details>
        </Surface>
      ) : (
        <Notice title="No version selected">
          Choose a published version to inspect its composition.
        </Notice>
      )}
      <BenchmarkForm
        key={`${detail.definition.id}:${detail.definition.revision}:${selected?.id ?? "none"}`}
        sources={available}
        accountId={account?.id}
        initial={detail}
        effectiveAt={new Date().toISOString()}
        currency={detail.definition.reporting_currency}
      />
    </div>,
  );
}
