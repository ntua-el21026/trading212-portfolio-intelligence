import styles from "./report-view.module.css";
import Link from "./navigation-intent";
import type { ExportPage, ReportPage } from "@trading212/api-contracts";
import { Surface } from "@trading212/ui";

import { CollectionPagination } from "./collection-pagination";
import { formatDateTime, titleCase } from "../lib/format";
import { reportHref, type ReportQuery } from "../lib/report-query";

export function ReportHistory({
  history,
  query,
  accountId,
}: Readonly<{
  history: ReportPage | ExportPage;
  query: ReportQuery;
  accountId: string;
}>) {
  const preserved = {
    ...query,
    report: undefined,
    export: undefined,
    cursor: undefined,
    account: accountId,
    snapshot: query.snapshot,
    kind: query.kind,
    state: query.state,
    report_type: query.report_type,
    dataset: query.dataset,
  };
  return (
    <Surface className={styles.surface} aria-label="Report history">
      <h2>{query.kind === "report" ? "Report history" : "Export history"}</h2>
      {history.items.length ? (
        <div
          className="table-scroll"
          role="region"
          aria-label="Private report history table"
          tabIndex={0}
        >
          <table className="data-table" aria-label="Private report history">
            <thead>
              <tr>
                <th scope="col">Report</th>
                <th scope="col">State</th>
                <th scope="col">Requested</th>
                <th scope="col">Expires</th>
              </tr>
            </thead>
            <tbody>
              {history.items.map((job) => {
                const id = "job_id" in job ? job.job_id : job.export_id;
                return (
                  <tr key={id}>
                    <th scope="row">
                      <Link
                        prefetch={false}
                        href={reportHref({
                          ...preserved,
                          report: "job_id" in job ? id : undefined,
                          export: "export_id" in job ? id : undefined,
                        })}
                      >
                        {"report_type" in job
                          ? titleCase(job.report_type)
                          : `${titleCase(job.dataset)} export`}
                      </Link>
                    </th>
                    <td>{job.state}</td>
                    <td>{formatDateTime(job.requested_at)}</td>
                    <td>{formatDateTime(job.expires_at)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <p>No stored jobs match this selection.</p>
      )}
      <CollectionPagination
        pathname="/reports"
        preservedQuery={preserved}
        returnedCount={history.items.length}
        total={history.total}
        nextCursor={history.next_cursor}
      />
      {query.cursor ? (
        <Link prefetch={false} href={reportHref(preserved)}>
          Return to first page
        </Link>
      ) : null}
    </Surface>
  );
}
