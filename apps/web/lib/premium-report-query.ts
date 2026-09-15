import { z } from "zod";
import type { RiskRunResponse } from "@trading212/api-contracts";
import type { ReportSearch } from "./report-query";

const uuid = z.string().uuid();
const cursor = z.string().regex(/^[A-Za-z0-9_-]{1,2048}$/);
const querySchema = z.strictObject({
  account: uuid.optional(),
  run: uuid.optional(),
  report: uuid.optional(),
  cursor: cursor.optional(),
  runs_cursor: cursor.optional(),
});
export type PremiumReportQuery = z.infer<typeof querySchema>;
export function parsePremiumReportQuery(
  search: ReportSearch,
): PremiumReportQuery {
  return querySchema.parse(search);
}
export function premiumReportHref(query: PremiumReportQuery): string {
  const parsed = querySchema.parse(query);
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(parsed))
    if (value !== undefined) search.set(key, value);
  return `/reports/premium${search.size ? `?${search}` : ""}`;
}
export type PremiumReportSource = {
  accountId: string;
  runId: string;
  snapshotId: string;
  startDate: string;
  endDate: string;
  sourceCutoff: string;
  currency: string;
  resultDigest: string;
  name: string;
};
export function premiumReportSource(
  run: RiskRunResponse,
  accountId: string,
): PremiumReportSource | null {
  if (
    run.account_id !== accountId ||
    run.state !== "succeeded" ||
    run.result_availability !== "available" ||
    !run.result
  )
    return null;
  const window = run.result.historical_context.window;
  return {
    accountId,
    runId: run.id,
    snapshotId: run.portfolio_snapshot_id,
    startDate: window.start_date,
    endDate: window.end_date,
    sourceCutoff: window.source_cutoff_at,
    currency: window.reporting_currency,
    resultDigest: run.result.content_digest,
    name: run.result.definition.name,
  };
}
