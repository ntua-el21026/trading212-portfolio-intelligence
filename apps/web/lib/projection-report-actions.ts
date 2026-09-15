"use server";

import { revalidatePath } from "next/cache";
import { z } from "zod";
import {
  ReportApiError,
  ProjectionApiError,
  PortfolioApiError,
  type PremiumReportJobStatusV4,
} from "@trading212/api-contracts";
import { reportClients, reportData } from "./report-adapter";
import { projectionData } from "./projection-adapter";
import { projectionReportSource } from "./projection-report-query";

const commandSchema = z.strictObject({
  profile_version: z.literal("report_sections_v4"),
  account_id: z.string().uuid(),
  premium_run: z.strictObject({
    family: z.literal("projection"),
    run_id: z.string().uuid(),
  }),
  snapshot_id: z.string().uuid(),
  expected_result_digest: z.string().regex(/^[a-f0-9]{64}$/),
  expected_capture_digest: z.string().regex(/^[a-f0-9]{64}$/),
  expected_snapshot_valuation: z.string().min(1).max(64),
  expected_snapshot_cutoff: z.string().min(1).max(64),
  include_goal: z.boolean(),
  idempotency_key: z.string().regex(/^[A-Za-z0-9._:-]{1,180}$/),
  formats: z
    .array(z.enum(["pdf", "csv", "json", "xlsx"]))
    .min(1)
    .max(4)
    .refine((values) => new Set(values).size === values.length),
  ttl_days: z.number().int().min(1).max(30),
});
export type ProjectionReportActionResult =
  | { ok: true; job: PremiumReportJobStatusV4 }
  | { ok: false; code: string; message: string };

export async function submitProjectionReportCommand(
  input: unknown,
): Promise<ProjectionReportActionResult> {
  // Authentication and same-origin CSRF precede caller input and private reads.
  const clients = await reportClients(true);
  try {
    const encoded = JSON.stringify(input);
    if (
      encoded === undefined ||
      new TextEncoder().encode(encoded).byteLength > 65_536
    )
      return {
        ok: false,
        code: "REQUEST_TOO_LARGE",
        message: "The report request exceeds 64 KiB.",
      };
    const parsed = commandSchema.safeParse(input);
    if (!parsed.success)
      return {
        ok: false,
        code: "VALIDATION_FAILED",
        message:
          "Choose an owned report-context snapshot, saved projection and report formats.",
      };
    const command = parsed.data;
    const [run, snapshot] = await Promise.all([
      clients.projections
        .get_projection_run(command.premium_run.run_id, { point_limit: 1 })
        .then(projectionData),
      clients.portfolio.getSnapshot(command.account_id, command.snapshot_id),
    ]);
    const source = projectionReportSource(run, command.account_id, snapshot);
    if (
      !source ||
      source.runId !== command.premium_run.run_id ||
      source.snapshotId !== command.snapshot_id
    )
      return {
        ok: false,
        code: "SOURCE_UNAVAILABLE",
        message:
          "The selected projection or report-context snapshot is no longer available for this account.",
      };
    if (
      source.resultDigest !== command.expected_result_digest ||
      source.captureDigest !== command.expected_capture_digest ||
      source.snapshotValuation !== command.expected_snapshot_valuation ||
      source.sourceCutoff !== command.expected_snapshot_cutoff
    )
      return {
        ok: false,
        code: "SOURCE_CHANGED",
        message:
          "The selected saved basis changed. Reload it before creating a report.",
      };
    if (command.include_goal && source.goalVersionId === null)
      return {
        ok: false,
        code: "SOURCE_UNAVAILABLE",
        message: "This saved projection has no pinned goal.",
      };
    const job = reportData(
      await clients.premiumReportsV4.generate_premium_portfolio_report(
        {
          profile_version: "report_sections_v4",
          premium_run: { family: "projection", run_id: source.runId },
          account_id: source.accountId,
          snapshot_id: source.snapshotId,
          reporting_currency: source.currency,
          start_date: source.startDate,
          end_date: source.endDate,
          source_cutoff_at: source.sourceCutoff,
          report_type: "portfolio_summary",
          sections: [
            "overview",
            "allocation",
            "quality",
            "projection",
            ...(command.include_goal ? ["goal" as const] : []),
          ],
          formats: command.formats,
          ttl_days: command.ttl_days,
        },
        { idempotencyKey: command.idempotency_key },
      ),
    );
    if (
      job.account_id !== source.accountId ||
      job.profile_version !== "report_sections_v4" ||
      !job.context ||
      job.context.snapshot_id !== source.snapshotId ||
      job.context.reporting_currency !== source.currency
    )
      throw new ReportApiError(
        "INVALID_RESPONSE",
        502,
        "The report response could not be verified.",
      );
    revalidatePath("/reports/premium");
    return { ok: true, job };
  } catch (error) {
    if (error instanceof ReportApiError || error instanceof ProjectionApiError)
      return { ok: false, code: error.code, message: error.message };
    if (error instanceof PortfolioApiError)
      return {
        ok: false,
        code: error.code,
        message: "The owned report-context snapshot is unavailable.",
      };
    return {
      ok: false,
      code: "REPORT_UNAVAILABLE",
      message:
        "Your selection and retry identity are preserved. Retry when reports are available.",
    };
  }
}
