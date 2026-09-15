"use server";

import { revalidatePath } from "next/cache";
import { z } from "zod";
import {
  ReportApiError,
  RiskApiError,
  ScenarioApiError,
  type PremiumReportJobStatusV3,
  type PremiumReportJobStatus,
} from "@trading212/api-contracts";
import { reportClients, reportData } from "./report-adapter";
import {
  premiumReportSource,
  premiumRiskReportSourceV3,
  premiumScenarioReportSource,
} from "./premium-report-query";
import { scenarioData } from "./scenario-adapter";
import { riskData } from "./risk-adapter";

const commandSchema = z.strictObject({
  account_id: z.string().uuid(),
  risk_run_id: z.string().uuid(),
  expected_result_digest: z.string().regex(/^[a-f0-9]{64}$/),
  idempotency_key: z.string().regex(/^[A-Za-z0-9._:-]{1,180}$/),
  formats: z
    .array(z.enum(["pdf", "csv", "json", "xlsx"]))
    .min(1)
    .max(4)
    .refine((values) => new Set(values).size === values.length),
  ttl_days: z.number().int().min(1).max(30),
});
export type PremiumReportActionResult =
  | { ok: true; job: PremiumReportJobStatus }
  | { ok: false; code: string; message: string };

export async function submitPremiumReportCommand(
  input: unknown,
): Promise<PremiumReportActionResult> {
  // Authenticate and enforce same-origin CSRF before inspecting caller input.
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
          "Choose a retained risk run, formats and retention between 1 and 30 days.",
      };
    const command = parsed.data;
    const run = riskData(await clients.risk.get_risk_run(command.risk_run_id));
    const source = premiumReportSource(run, command.account_id);
    if (!source || source.runId !== command.risk_run_id)
      return {
        ok: false,
        code: "SOURCE_UNAVAILABLE",
        message:
          "The selected risk result is no longer available for this account.",
      };
    if (source.resultDigest !== command.expected_result_digest)
      return {
        ok: false,
        code: "SOURCE_CHANGED",
        message:
          "The selected risk result changed. Reload it before generating a report.",
      };
    const job = reportData(
      await clients.premiumReports.generate_premium_portfolio_report(
        {
          account_id: source.accountId,
          risk_run_id: source.runId,
          snapshot_id: source.snapshotId,
          start_date: source.startDate,
          end_date: source.endDate,
          source_cutoff_at: source.sourceCutoff,
          reporting_currency: source.currency,
          report_type: "portfolio_summary",
          sections: ["overview", "allocation", "quality", "risk"],
          formats: command.formats,
          ttl_days: command.ttl_days,
        },
        { idempotencyKey: command.idempotency_key },
      ),
    );
    if (job.account_id !== source.accountId)
      throw new ReportApiError(
        "INVALID_RESPONSE",
        502,
        "The report response could not be verified.",
      );
    revalidatePath("/reports/premium");
    return { ok: true, job };
  } catch (error) {
    return error instanceof ReportApiError || error instanceof RiskApiError
      ? { ok: false, code: error.code, message: error.message }
      : {
          ok: false,
          code: "REPORT_UNAVAILABLE",
          message:
            "Your selection is preserved. Retry when risk reports are available.",
        };
  }
}

const commandV3Schema = commandSchema.omit({ risk_run_id: true }).extend({
  profile_version: z.literal("report_sections_v3"),
  premium_run: z.strictObject({
    family: z.enum(["risk", "scenario"]),
    run_id: z.string().uuid(),
  }),
});
export type PremiumReportV3ActionResult =
  | { ok: true; job: PremiumReportJobStatusV3 }
  | { ok: false; code: string; message: string };

export async function submitPremiumReportV3Command(
  input: unknown,
): Promise<PremiumReportV3ActionResult> {
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
    const parsed = commandV3Schema.safeParse(input);
    if (!parsed.success)
      return {
        ok: false,
        code: "VALIDATION_FAILED",
        message:
          "Choose a saved analysis, formats and retention between 1 and 30 days.",
      };
    const command = parsed.data;
    const source =
      command.premium_run.family === "risk"
        ? premiumRiskReportSourceV3(
            riskData(
              await clients.risk.get_risk_run(command.premium_run.run_id),
            ),
            command.account_id,
          )
        : premiumScenarioReportSource(
            scenarioData(
              await clients.scenarios.get_scenario_run(
                command.premium_run.run_id,
                { component_limit: 1 },
              ),
            ),
            command.account_id,
          );
    if (
      !source ||
      source.runId !== command.premium_run.run_id ||
      source.family !== command.premium_run.family
    )
      return {
        ok: false,
        code: "SOURCE_UNAVAILABLE",
        message: "The selected result is no longer available for this account.",
      };
    if (source.resultDigest !== command.expected_result_digest)
      return {
        ok: false,
        code: "SOURCE_CHANGED",
        message:
          "The selected result changed. Reload it before generating a report.",
      };
    const job = reportData(
      await clients.premiumReportsV3.generate_premium_portfolio_report(
        {
          profile_version: "report_sections_v3",
          premium_run: { family: source.family, run_id: source.runId },
          account_id: source.accountId,
          snapshot_id: source.snapshotId,
          start_date: source.startDate,
          end_date: source.endDate,
          source_cutoff_at: source.sourceCutoff,
          reporting_currency: source.currency,
          report_type: "portfolio_summary",
          sections: ["overview", "allocation", "quality", source.family],
          formats: command.formats,
          ttl_days: command.ttl_days,
        },
        { idempotencyKey: command.idempotency_key },
      ),
    );
    if (
      job.account_id !== source.accountId ||
      job.profile_version !== "report_sections_v3"
    )
      throw new ReportApiError(
        "INVALID_RESPONSE",
        502,
        "The report response could not be verified.",
      );
    revalidatePath("/reports/premium");
    return { ok: true, job };
  } catch (error) {
    return error instanceof ReportApiError ||
      error instanceof RiskApiError ||
      error instanceof ScenarioApiError
      ? { ok: false, code: error.code, message: error.message }
      : {
          ok: false,
          code: "REPORT_UNAVAILABLE",
          message:
            "Your selection is preserved. Retry when reports are available.",
        };
  }
}
