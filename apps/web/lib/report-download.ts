import "server-only";

import { ReportApiError, TargetApiError } from "@trading212/api-contracts";
import { z } from "zod";
import { reportClients, reportData } from "./report-adapter";

const uuid = z.string().uuid();

async function accountFromForm(request: Request): Promise<string> {
  if (
    request.headers.get("content-type")?.split(";")[0].trim() !==
    "application/x-www-form-urlencoded"
  )
    throw new ReportApiError(
      "VALIDATION_FAILED",
      422,
      "The download request is invalid.",
    );
  const reader = request.body?.getReader();
  if (!reader)
    throw new ReportApiError(
      "VALIDATION_FAILED",
      422,
      "The download request is invalid.",
    );
  const chunks: Uint8Array[] = [];
  let length = 0;
  try {
    while (true) {
      const next = await reader.read();
      if (next.done) break;
      length += next.value.byteLength;
      if (length > 1024) {
        await reader.cancel();
        throw new ReportApiError(
          "REQUEST_TOO_LARGE",
          413,
          "The download request exceeds its bound.",
        );
      }
      chunks.push(next.value);
    }
  } finally {
    reader.releaseLock();
  }
  const bytes = new Uint8Array(length);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  const form = new URLSearchParams(
    new TextDecoder("utf-8", { fatal: true }).decode(bytes),
  );
  if ([...form.keys()].length !== 1 || form.getAll("account_id").length !== 1)
    throw new ReportApiError(
      "VALIDATION_FAILED",
      422,
      "The download request is invalid.",
    );
  return uuid.parse(form.get("account_id"));
}

export async function serveReportArtifact(
  request: Request,
  family: "reports" | "exports",
  parentId: string,
  artifactId: string,
): Promise<Response> {
  // Authenticate and verify same-origin command access before parsing caller input.
  const { reports } = await reportClients(true);
  try {
    const parent = uuid.parse(parentId),
      artifact = uuid.parse(artifactId);
    const account = await accountFromForm(request);
    const query = { account_id: account };
    const job =
      family === "reports"
        ? reportData(await reports.get_report_status(parent, query))
        : reportData(await reports.get_export_status(parent, query));
    if (job.state === "expired")
      throw new ReportApiError(
        "ARTIFACT_EXPIRED",
        410,
        "This artifact has expired.",
      );
    const metadata = job.artifacts.find(
      (item) => item.artifact_id === artifact,
    );
    if (job.state !== "succeeded" || !metadata)
      throw new ReportApiError(
        "NOT_FOUND",
        404,
        "This artifact is unavailable.",
      );
    const grant = reportData(
      family === "reports"
        ? await reports.create_report_download_grant(
            parent,
            artifact,
            query,
            {},
          )
        : await reports.create_export_download_grant(
            parent,
            artifact,
            query,
            {},
          ),
    );
    if (grant.artifact_id !== artifact)
      throw new ReportApiError(
        "INVALID_RESPONSE",
        502,
        "The private artifact could not be verified.",
      );
    const result =
      family === "reports"
        ? await reports.download_report_artifact(parent, artifact, query, {
            grantToken: grant.token,
            metadata,
          })
        : await reports.download_export_artifact(parent, artifact, query, {
            grantToken: grant.token,
            metadata,
          });
    return new Response(result.content, {
      status: 200,
      headers: {
        "Content-Type": result.metadata.mime_type,
        "Content-Length": String(result.metadata.byte_length),
        "Content-Disposition": `attachment; filename="${result.filename}"`,
        "X-Artifact-SHA256": result.metadata.content_digest,
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
      },
    });
  } catch (error) {
    const known =
      error instanceof ReportApiError || error instanceof TargetApiError;
    return Response.json(
      {
        error: {
          code: known ? error.code : "VALIDATION_FAILED",
          message: known ? error.message : "The download request is invalid.",
          retryable: known && error.code === "RATE_LIMITED",
        },
      },
      {
        status: known ? error.status : 422,
        headers: {
          "Cache-Control": "private, no-store",
          "X-Content-Type-Options": "nosniff",
          ...(known && error.code === "RATE_LIMITED"
            ? { "Retry-After": "300" }
            : {}),
        },
      },
    );
  }
}
