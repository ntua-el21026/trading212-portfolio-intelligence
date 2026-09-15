import type {
  ProjectionRunResponse,
  SnapshotDetail,
} from "@trading212/api-contracts";
import {
  premiumReportHref,
  type PremiumReportQuery,
} from "./premium-report-query";

export type ProjectionReportSource = {
  profile: "report_sections_v4";
  family: "projection";
  accountId: string;
  runId: string;
  resultDigest: string;
  captureDigest: string;
  numericalInputDigest: string;
  currency: string;
  goalVersionId: string | null;
  initialKind: "observed_snapshot" | "modeled_value";
  anchorDate: string;
  terminalDate: string;
  originalValuation: string | null;
  originalCutoff: string | null;
  snapshotId: string;
  snapshotCurrency: string;
  snapshotValuation: string;
  sourceCutoff: string;
  startDate: string;
  endDate: string;
};

/** Snapshot is read through the chosen account's authenticated snapshot endpoint. */
export function projectionReportSource(
  run: ProjectionRunResponse,
  accountId: string,
  snapshot: SnapshotDetail,
): ProjectionReportSource | null {
  if (
    run.account_id !== accountId ||
    run.state !== "succeeded" ||
    run.result_availability !== "available" ||
    !run.result
  )
    return null;
  const context = run.result.context;
  if (
    context.run_id !== run.id ||
    context.account_id !== accountId ||
    context.selection.account_id !== accountId ||
    context.capture_digest !== run.capture_digest ||
    context.numerical_input_digest !== run.numerical_input_digest ||
    context.selection.assumption_version_id !== run.assumption_version_id ||
    context.selection.goal_version_id !== run.goal_version_id
  )
    return null;
  return {
    profile: "report_sections_v4",
    family: "projection",
    accountId,
    runId: run.id,
    resultDigest: context.saved_result_digest,
    captureDigest: context.capture_digest,
    numericalInputDigest: context.numerical_input_digest,
    currency: context.reporting_currency,
    goalVersionId: run.goal_version_id,
    initialKind: context.selection.initial.kind,
    anchorDate: context.anchor_date,
    terminalDate: context.terminal_date,
    originalValuation: context.snapshot_valuation_at,
    originalCutoff: context.source_cutoff_at,
    snapshotId: snapshot.id,
    snapshotCurrency: snapshot.reporting_currency,
    snapshotValuation: snapshot.valuation_at,
    sourceCutoff: snapshot.source_cutoff_at,
    startDate: snapshot.valuation_at.slice(0, 10),
    endDate: snapshot.valuation_at.slice(0, 10),
  };
}

export function projectionReportSourceMatches(
  source: ProjectionReportSource,
  query: PremiumReportQuery,
): boolean {
  return (
    query.profile === source.profile &&
    (query.family === undefined || query.family === source.family) &&
    query.account === source.accountId &&
    query.run === source.runId &&
    query.snapshot === source.snapshotId &&
    (query.result_digest === undefined ||
      query.result_digest === source.resultDigest) &&
    (query.currency === undefined || query.currency === source.currency) &&
    (query.cutoff === undefined || query.cutoff === source.sourceCutoff)
  );
}

export function projectionReportSourceHref(
  source: ProjectionReportSource,
  report?: string,
): string {
  return premiumReportHref({
    profile: source.profile,
    family: source.family,
    account: source.accountId,
    run: source.runId,
    snapshot: source.snapshotId,
    currency: source.currency,
    cutoff: source.sourceCutoff,
    result_digest: source.resultDigest,
    report,
  });
}
