import Link from "next/link";
import type {
  CompositeBenchmarkSnapshotHeader,
  CompositeBenchmarkObservationPage,
} from "@trading212/api-contracts";
import { Surface } from "@trading212/ui";
import { PageHeader } from "./page-header";
import { CollectionPagination } from "./collection-pagination";
import { HistoricalValue } from "./historical-results";
import { formatDateTime, formatPercent, titleCase } from "../lib/format";

export function CompositeSourceDetails({
  header,
  observations,
  accountId,
}: Readonly<{
  header: CompositeBenchmarkSnapshotHeader;
  observations: CompositeBenchmarkObservationPage;
  accountId?: string;
}>) {
  return (
    <div className="page-stack source-page">
      <PageHeader
        title="Composite benchmark snapshot"
        description={`${header.window.start_date} through ${header.window.end_date} · ${header.reporting_currency}`}
      />
      <Link
        prefetch={false}
        href={`/sources?kind=benchmark${accountId ? `&account=${accountId}` : ""}`}
      >
        Back to sources
      </Link>
      <Surface>
        <h2>Derived benchmark wealth</h2>
        <p>
          Base wealth 1 · {titleCase(header.return_basis)} ·{" "}
          {titleCase(header.rebalance_rule)}
        </p>
        <p>
          {header.method.name} {header.method.version} · calculated{" "}
          {formatDateTime(header.calculated_at)} ·{" "}
          {titleCase(header.access.reproducibility)}
        </p>
        <p>
          Source permissions are checked across the contributing inputs. The
          composite retains its calculation and component identities.
        </p>
        <dl className="historical-identities">
          <dt>Input digest</dt>
          <dd>
            <code>{header.input_digest}</code>
          </dd>
          <dt>Content digest</dt>
          <dd>
            <code>{header.content_digest}</code>
          </dd>
          <dt>Calendar</dt>
          <dd>
            {header.calendar_id} · {header.calendar_version}
          </dd>
        </dl>
      </Surface>
      <Surface>
        <h2>Pinned components</h2>
        <div
          className="table-scroll"
          tabIndex={0}
          role="region"
          aria-label="Composite component table"
        >
          <table className="data-table" aria-label="Composite components">
            <thead>
              <tr>
                <th>Source series</th>
                <th>Weight</th>
                <th>Retained snapshots</th>
                <th>License versions</th>
              </tr>
            </thead>
            <tbody>
              {header.inputs.map((row) => (
                <tr key={row.source_id}>
                  <th scope="row">
                    <code>{row.source_id}</code>
                  </th>
                  <td>{formatPercent(row.weight)}</td>
                  <td>{row.snapshot_ids.length}</td>
                  <td>{row.license_version_ids.length}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <details>
          <summary>Coverage</summary>
          <ul>
            {header.coverage.measures.map((row) => (
              <li key={row.key}>
                {titleCase(row.key)}: {row.available_count} /{" "}
                {row.expected_count} ·{" "}
                {row.complete ? "Complete" : "Incomplete"}
              </li>
            ))}
          </ul>
        </details>
      </Surface>
      <Surface>
        <h2>Immutable composite observations</h2>
        <div
          className="table-scroll"
          tabIndex={0}
          role="region"
          aria-label="Composite observation table"
        >
          <table className="data-table" aria-label="Composite observations">
            <thead>
              <tr>
                <th>Session</th>
                <th>Effective time</th>
                <th>Wealth, base 1</th>
                <th>Period return</th>
              </tr>
            </thead>
            <tbody>
              {observations.items.map((row) => (
                <tr key={row.ordinal}>
                  <th scope="row">{row.session_date}</th>
                  <td>{formatDateTime(row.effective_at)}</td>
                  <td>
                    <HistoricalValue metric={row.wealth} unit="multiple" />
                  </td>
                  <td>
                    <HistoricalValue metric={row.interval_return} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <CollectionPagination
          pathname={`/sources/snapshots/benchmark/${header.id}`}
          preservedQuery={{ account: accountId }}
          returnedCount={observations.items.length}
          total={observations.total}
          nextCursor={observations.next_cursor}
        />
      </Surface>
    </div>
  );
}
