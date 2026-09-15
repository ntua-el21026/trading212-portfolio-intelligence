import { z } from "zod";
import type {
  RiskRunResponse,
  ScenarioRunResponse,
} from "@trading212/api-contracts";
import type { ReportSearch } from "./report-query";

const uuid = z.string().uuid();
const cursor = z.string().regex(/^[A-Za-z0-9_-]{1,2048}$/);
const querySchema = z
  .strictObject({
    account: uuid.optional(),
    run: uuid.optional(),
    report: uuid.optional(),
    cursor: cursor.optional(),
    runs_cursor: cursor.optional(),
    profile: z.enum(["report_sections_v2", "report_sections_v3"]).optional(),
    family: z.enum(["risk", "scenario"]).optional(),
    snapshot: uuid.optional(),
    currency: z
      .string()
      .regex(/^[A-Z]{3}$/)
      .optional(),
    cutoff: z
      .string()
      .regex(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$/)
      .refine((value) => !Number.isNaN(Date.parse(value)))
      .optional(),
    result_digest: z
      .string()
      .regex(/^[a-f0-9]{64}$/)
      .optional(),
  })
  .superRefine((value, context) => {
    const hints = [
      value.snapshot,
      value.currency,
      value.cutoff,
      value.result_digest,
    ];
    const supplied = hints.filter((item) => item !== undefined).length;
    if (
      (value.profile !== "report_sections_v3" &&
        (value.family !== undefined || supplied > 0)) ||
      (value.profile === "report_sections_v3" &&
        value.run !== undefined &&
        value.family === undefined) ||
      (supplied > 0 &&
        (supplied !== hints.length || !value.run || !value.account))
    )
      context.addIssue({
        code: "custom",
        message: "The premium report selection is incomplete.",
      });
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
    if (
      value !== undefined &&
      !(key === "profile" && value === "report_sections_v2")
    )
      search.set(key, value);
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

export type PremiumReportSourceV3 = PremiumReportSource & {
  profile: "report_sections_v3";
  family: "risk" | "scenario";
};

export function premiumRiskReportSourceV3(
  run: RiskRunResponse,
  accountId: string,
): PremiumReportSourceV3 | null {
  const source = premiumReportSource(run, accountId);
  return source
    ? { ...source, profile: "report_sections_v3", family: "risk" }
    : null;
}

export function premiumScenarioReportSource(
  run: ScenarioRunResponse,
  accountId: string,
): PremiumReportSourceV3 | null {
  if (
    run.account_id !== accountId ||
    run.state !== "succeeded" ||
    run.result_availability !== "available" ||
    !run.result
  )
    return null;
  const context = run.result.context;
  const pins = context.pins;
  if (
    context.run_id !== run.id ||
    pins.account_id !== accountId ||
    pins.portfolio_snapshot_id !== run.portfolio_snapshot_id ||
    pins.xray_run_id !== run.xray_run_id ||
    pins.scenario_version_id !== run.scenario_version_id ||
    context.input_digest !== run.input_digest
  )
    return null;
  // Use the retained monetary basis and full saved-result digest. The paged
  // presentation digest and market knowledge cutoff identify different things.
  return {
    profile: "report_sections_v3",
    family: "scenario",
    accountId,
    runId: run.id,
    snapshotId: pins.portfolio_snapshot_id,
    startDate:
      context.replay?.selection.start_date ?? context.valuation_at.slice(0, 10),
    endDate:
      context.replay?.selection.end_date ?? context.valuation_at.slice(0, 10),
    sourceCutoff: pins.source_cutoff_at,
    currency: pins.reporting_currency,
    resultDigest: context.saved_result_digest,
    name: context.definition.name,
  };
}

export function premiumSourceMatchesQuery(
  source: PremiumReportSource | PremiumReportSourceV3,
  query: PremiumReportQuery,
): boolean {
  return (
    source.accountId === query.account &&
    source.runId === query.run &&
    (query.profile !== "report_sections_v3" ||
      ("profile" in source && source.family === query.family)) &&
    (query.snapshot === undefined ||
      (query.snapshot === source.snapshotId &&
        query.currency === source.currency &&
        query.cutoff === source.sourceCutoff &&
        query.result_digest === source.resultDigest))
  );
}

export function premiumReportSourceHref(
  source: PremiumReportSource | PremiumReportSourceV3,
  report?: string,
): string {
  return premiumReportHref({
    account: source.accountId,
    run: source.runId,
    report,
    ...("profile" in source
      ? {
          profile: source.profile,
          family: source.family,
          snapshot: source.snapshotId,
          currency: source.currency,
          cutoff: source.sourceCutoff,
          result_digest: source.resultDigest,
        }
      : {}),
  });
}
