"use server";

import { revalidatePath } from "next/cache";
import { z } from "zod";
import {
  ReportApiError,
  ResearchApiClient,
  ResearchApiError,
  type PremiumReportJobStatusV3,
} from "@trading212/api-contracts";
import { reportClients, reportData } from "./report-adapter";
import { researchData } from "./research-adapter";
import {
  researchReportPinsSchema,
  researchReportSource,
} from "./research-report-query";

const commandSchema = z.strictObject({
  account_id: z.string().uuid(),
  premium_run: researchReportPinsSchema,
  expected_event_digest: z.string().regex(/^[a-f0-9]{64}$/),
  expected_xray_result_digest: z.string().regex(/^[a-f0-9]{64}$/),
  idempotency_key: z.string().regex(/^[A-Za-z0-9._:-]{1,180}$/),
  formats: z
    .array(z.enum(["pdf", "csv", "json", "xlsx"]))
    .min(1)
    .max(4)
    .refine((values) => new Set(values).size === values.length),
  ttl_days: z.number().int().min(1).max(30),
});

export type ResearchReportActionResult =
  | { ok: true; job: PremiumReportJobStatusV3 }
  | { ok: false; code: string; message: string };

export async function submitResearchReportCommand(
  input: unknown,
): Promise<ResearchReportActionResult> {
  // Authentication and same-origin/CSRF checks precede caller serialization.
  const clients = await reportClients(true);
  if (
    ![
      "portfolio:read",
      "analytics:read",
      "reports:write",
      "research:read",
    ].every((scope) => clients.access.principal.scopes.includes(scope))
  )
    return {
      ok: false,
      code: "ACCESS_DENIED",
      message: "Current research and report creation access are required.",
    };
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
    const checked = commandSchema.safeParse(input);
    if (!checked.success)
      return {
        ok: false,
        code: "VALIDATION_FAILED",
        message:
          "Choose an exact research item, note revisions, formats and retention.",
      };
    const command = checked.data;
    const research = new ResearchApiClient(clients.options);
    const item = researchData(
      await research.get_research_item(command.premium_run.item_id),
    );
    const source = researchReportSource(item, command.account_id);
    if (!source || source.itemId !== command.premium_run.item_id)
      return {
        ok: false,
        code: "SOURCE_UNAVAILABLE",
        message: "The selected research item is unavailable for this account.",
      };
    if (
      source.eventDigest !== command.expected_event_digest ||
      source.xrayResultDigest !== command.expected_xray_result_digest
    )
      return {
        ok: false,
        code: "SOURCE_CHANGED",
        message: "The selected source evidence differs. Reload this item.",
      };
    const job = reportData(
      await clients.premiumReportsV3.generate_premium_portfolio_report(
        {
          profile_version: "report_sections_v3",
          premium_run: command.premium_run,
          account_id: source.accountId,
          snapshot_id: source.snapshotId,
          start_date: source.valuationAt.slice(0, 10),
          end_date: source.valuationAt.slice(0, 10),
          source_cutoff_at: source.sourceCutoff,
          reporting_currency: source.currency,
          report_type: "portfolio_summary",
          sections: ["overview", "allocation", "quality", "research"],
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
    return error instanceof ReportApiError || error instanceof ResearchApiError
      ? { ok: false, code: error.code, message: error.message }
      : {
          ok: false,
          code: "REPORT_UNAVAILABLE",
          message:
            "Your exact selection is preserved. Retry when research reports are available.",
        };
  }
}
