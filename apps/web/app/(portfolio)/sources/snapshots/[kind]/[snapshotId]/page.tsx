import Link from "../../../../../../components/navigation-intent";
import type { ReactNode } from "react";
import {
  AccountRequired,
  AccountView,
} from "../../../../../../components/account-context";
import { loadSelectedAccount } from "../../../../../../lib/api-adapter";
import { notFound } from "next/navigation";
import {
  SourceApiError,
  type PriceSnapshotHeader,
  type FxSnapshotHeader,
  type BenchmarkSnapshotHeader,
  type SourceSeries,
} from "@trading212/api-contracts";
import { Notice, Surface } from "@trading212/ui";
import { PageHeader } from "../../../../../../components/page-header";
import { CompositeSourceDetails } from "../../../../../../components/composite-source-details";
import { CollectionPagination } from "../../../../../../components/collection-pagination";
import {
  SourceLicenseDetails,
  SourceProvenanceDetails,
} from "../../../../../../components/source-details";
import {
  sourceClients,
  sourceData,
  sourceResult,
} from "../../../../../../lib/source-adapter";
import {
  planningUuid,
  type PlanningSearch,
} from "../../../../../../lib/planning-selection";
import { readOpaqueCursor } from "../../../../../../lib/collection-query";
import { formatDateTime, titleCase } from "../../../../../../lib/format";

export default async function SourceSnapshotPage({
  params,
  searchParams,
}: Readonly<{
  params: Promise<{ kind: string; snapshotId: string }>;
  searchParams: Promise<PlanningSearch>;
}>) {
  const { kind, snapshotId: rawId } = await params;
  if (kind !== "price" && kind !== "fx" && kind !== "benchmark") notFound();
  const snapshotId = planningUuid(rawId);
  if (!snapshotId) notFound();
  const query = await searchParams;
  // An absent account is an owner-wide source read, not a preferred account.
  const accountSelection =
    query.account === undefined
      ? null
      : await loadSelectedAccount(query.account);
  if (accountSelection && !accountSelection.account)
    return <AccountRequired selection={accountSelection} />;
  const accountId = accountSelection?.account?.id;
  const withScope = (content: ReactNode) =>
    accountId ? (
      <AccountView accountId={accountId}>{content}</AccountView>
    ) : (
      <>
        <Notice title="Owner-wide source">
          This retained source is shown for its owner without a portfolio
          account selection.
        </Notice>
        {content}
      </>
    );
  const { sources } = await sourceClients();
  const result = await sourceResult(async () => {
    const details = accountId ? { account_id: accountId } : {};
    const pageQuery = {
      ...details,
      limit: 25,
      cursor: readOpaqueCursor(query.cursor),
    };
    let header:
      PriceSnapshotHeader | FxSnapshotHeader | BenchmarkSnapshotHeader;
    let series: SourceSeries | null = null;
    if (kind === "price") {
      const result = sourceData(
        await sources.get_price_snapshot(snapshotId, details),
      );
      header = result;
      series = result.series;
    } else if (kind === "benchmark") {
      const result = sourceData(
        await sources.get_benchmark_snapshot(snapshotId, details),
      );
      if ("inputs" in result) {
        const observations = sourceData(
          await sources.list_benchmark_observations(snapshotId, pageQuery),
        );
        if (!("kind" in observations) || observations.kind !== "composite") {
          throw new SourceApiError(
            "INVALID_RESPONSE",
            502,
            "The composite observations do not match their header.",
          );
        }
        return { type: "composite" as const, header: result, observations };
      }
      header = result;
      series = result.series;
    } else {
      header = sourceData(await sources.get_fx_snapshot(snapshotId, details));
    }
    const observations =
      kind === "price"
        ? sourceData(
            await sources.list_price_observations(snapshotId, pageQuery),
          )
        : kind === "fx"
          ? sourceData(
              await sources.list_fx_observations(snapshotId, pageQuery),
            )
          : sourceData(
              await sources.list_benchmark_observations(snapshotId, pageQuery),
            );
    if ("kind" in observations) {
      throw new SourceApiError(
        "INVALID_RESPONSE",
        502,
        "The source observations do not match their header.",
      );
    }
    return { type: "provider" as const, header, series, observations };
  });
  if (!result.ok) {
    if (result.code === "NOT_FOUND") notFound();
    return withScope(
      <Notice title="Source data is unavailable">{result.message}</Notice>,
    );
  }
  if (result.data.type === "composite") {
    return withScope(
      <CompositeSourceDetails
        header={result.data.header}
        observations={result.data.observations}
        accountId={accountId}
      />,
    );
  }
  const { header, series, observations } = result.data;
  return withScope(
    <div className="page-stack source-page">
      <PageHeader
        title={`${titleCase(kind)} source snapshot`}
        description={`${header.period.start} through ${header.period.end}`}
      />
      <Link
        prefetch={false}
        href={`/sources?kind=${kind === "price" ? "market" : kind}${accountId ? `&account=${accountId}` : ""}`}
      >
        Back to sources
      </Link>
      <SourceProvenanceDetails
        provenance={header.provenance}
        coverage={header.coverage}
        digest={header.content_digest}
        freshness={header.freshness}
        calendar={"series" in header ? header.series : header}
      />
      <Surface>
        <h2>License and permitted uses</h2>
        <SourceLicenseDetails license={header.license} />
        <p>
          Latest retrieval:{" "}
          {header.latest_retrieval
            ? formatDateTime(header.latest_retrieval.retrieved_at)
            : "Unavailable"}
        </p>
        {series ? (
          <p>
            {series.provider_key} · {titleCase(series.basis)} ·{" "}
            {series.currency}
          </p>
        ) : null}
      </Surface>
      <Surface>
        <h2>Immutable observations</h2>
        <div className="table-scroll">
          <table
            className="data-table"
            aria-label="Immutable source observations"
          >
            <thead>
              <tr>
                <th>Session</th>
                <th>Effective time</th>
                <th>Value</th>
                <th>Currency or pair</th>
                <th>Availability</th>
              </tr>
            </thead>
            <tbody>
              {observations.items.map((row, index) => {
                if ("wealth" in row)
                  throw new SourceApiError(
                    "INVALID_RESPONSE",
                    502,
                    "The source observation kind differs from its header.",
                  );
                return (
                  <tr key={index}>
                    <td>{row.session_date}</td>
                    <td>{formatDateTime(row.effective_at)}</td>
                    <td className="numeric">
                      {"rate" in row
                        ? (row.rate ?? "Unavailable")
                        : "value" in row
                          ? (row.value ?? "Unavailable")
                          : (row.level ?? "Unavailable")}
                    </td>
                    <td>
                      {"base" in row
                        ? `${row.base}/${row.quote}`
                        : series
                          ? series.currency
                          : "Unavailable"}
                    </td>
                    <td>{titleCase(row.state ?? "unavailable")}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <CollectionPagination
          pathname={`/sources/snapshots/${kind}/${snapshotId}`}
          preservedQuery={{ account: accountId }}
          returnedCount={observations.items.length}
          total={observations.total}
          nextCursor={observations.next_cursor}
        />
      </Surface>
    </div>,
  );
}
