"use server";

import {
  CreateExportRequestSchema,
  GenerateReportRequestSchema,
  ReportApiError,
  type ExportJobStatus,
  type ReportJobStatus,
} from "@trading212/api-contracts";
import { revalidatePath } from "next/cache";
import { z } from "zod";

import { reportClients, reportData } from "./report-adapter";

const identity = {
  idempotency_key: z.string().regex(/^[A-Za-z0-9._:-]{1,180}$/),
};
const commandSchema = z.discriminatedUnion("kind", [
  z.strictObject({
    kind: z.literal("report"),
    ...identity,
    body: GenerateReportRequestSchema,
  }),
  z.strictObject({
    kind: z.literal("export"),
    ...identity,
    body: CreateExportRequestSchema,
  }),
]);
export type ReportActionResult =
  | { ok: true; kind: "report"; job: ReportJobStatus }
  | { ok: true; kind: "export"; job: ExportJobStatus }
  | { ok: false; code: string; message: string };

export async function submitReportCommand(
  input: unknown,
): Promise<ReportActionResult> {
  const { reports } = await reportClients(true);
  try {
    const serialized = JSON.stringify(input);
    if (
      serialized === undefined ||
      new TextEncoder().encode(serialized).byteLength > 65_536
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
          "Review the report selections, dates, formats and required sources.",
      };
    const command = parsed.data;
    const result =
      command.kind === "report"
        ? {
            ok: true as const,
            kind: "report" as const,
            job: reportData(
              await reports.generate_portfolio_report(command.body, {
                idempotencyKey: command.idempotency_key,
              }),
            ),
          }
        : {
            ok: true as const,
            kind: "export" as const,
            job: reportData(
              await reports.create_portfolio_export(command.body, {
                idempotencyKey: command.idempotency_key,
              }),
            ),
          };
    revalidatePath("/reports");
    return result;
  } catch (error) {
    return error instanceof ReportApiError
      ? { ok: false, code: error.code, message: error.message }
      : {
          ok: false,
          code: "REPORT_UNAVAILABLE",
          message:
            "Your selections are preserved. Retry when reports are available.",
        };
  }
}
