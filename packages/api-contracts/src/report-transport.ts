import { z } from "zod";

import {
  BoundedTransport,
  type BoundedApiResponse,
  type BoundedClientOptions,
  type BoundedCommandOptions,
  type BoundedReadOptions,
} from "./bounded-transport";
import type { ReportArtifactMetadata } from "./reports.generated";

export type ReportClientOptions = BoundedClientOptions;
export type ReportReadOptions = BoundedReadOptions;
export type ReportCommandOptions = BoundedCommandOptions;
export type ReportApiResponse<T> = BoundedApiResponse<T>;
export type ReportGrantOptions = Record<string, never>;
export interface ReportDownloadOptions {
  grantToken: string;
  metadata: ReportArtifactMetadata;
}
export interface ReportArtifactResponse {
  content: Uint8Array<ArrayBuffer>;
  metadata: ReportArtifactMetadata;
  filename: string;
}

export class ReportApiError extends Error {
  constructor(
    readonly code: string,
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ReportApiError";
  }
}

const messages: Readonly<Record<string, string>> = {
  AUTHENTICATION_REQUIRED: "Sign in to access private reports.",
  ACCESS_DENIED:
    "You do not have access to this report or its current sources.",
  NOT_FOUND: "The private report resource was not found.",
  VALIDATION_FAILED:
    "Review the report selections, period and required sources.",
  IDEMPOTENCY_KEY_REUSED:
    "This request identity belongs to a different selection.",
  INVALID_STATE_TRANSITION:
    "The report is not ready for this operation. Check its job status.",
  RATE_LIMITED:
    "The private report request rate limit was reached. Retry in five minutes.",
  REQUEST_TOO_LARGE: "The report request exceeds 64 KiB.",
  RESULT_TOO_LARGE: "The report exceeds its permitted size.",
  ARTIFACT_EXPIRED:
    "This artifact has expired. Create a new report from available sources.",
  CURSOR_INVALID: "This history cursor expired. Return to the first page.",
  COLLECTION_SNAPSHOT_CAPACITY_EXCEEDED:
    "History capacity is temporarily exhausted. Retry later.",
  REPORT_UNAVAILABLE:
    "Private reports are temporarily unavailable. Your selections are preserved.",
  JOB_DISPATCH_UNAVAILABLE:
    "Report dispatch is temporarily unavailable. Retry the same request.",
  INTERNAL_ERROR: "The private report operation could not complete.",
  REPORT_REQUEST_FAILED: "The private report request could not complete.",
};
const uuid = z.string().uuid();
const grant = z.string().regex(/^[A-Za-z0-9_-]{32,512}$/);
const accountQuery = z.strictObject({ account_id: uuid });
const mimeByFormat = {
  pdf: "application/pdf",
  csv: "text/csv; charset=utf-8",
  json: "application/json",
  xlsx: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
} as const;
const maximumArtifactBytes = 10 * 1024 * 1024;
const errorCodeSchema = z.object({
  error: z.object({ code: z.string().max(80) }),
});

function invalid(): ReportApiError {
  return new ReportApiError(
    "INVALID_RESPONSE",
    502,
    "The private artifact could not be verified.",
  );
}

async function invalidResponse(response: Response): Promise<ReportApiError> {
  try {
    await response.body?.cancel();
  } catch {
    /* Never retain a rejected body or its failure text. */
  }
  return invalid();
}

async function privateHeaders(response: Response): Promise<void> {
  const directives = response.headers
    .get("cache-control")
    ?.toLowerCase()
    .split(",")
    .map((item) => item.trim());
  if (
    response.redirected ||
    response.headers.has("location") ||
    !directives?.includes("no-store") ||
    response.headers.get("x-content-type-options")?.toLowerCase() !== "nosniff"
  ) {
    throw await invalidResponse(response);
  }
}

async function readBounded(
  response: Response,
  maximum: number,
): Promise<Uint8Array<ArrayBuffer>> {
  const reader = response.body?.getReader();
  if (!reader) throw invalid();
  const chunks: Uint8Array[] = [];
  let length = 0;
  try {
    while (true) {
      const next = await reader.read();
      if (next.done) break;
      length += next.value.byteLength;
      if (length > maximum) {
        await reader.cancel();
        throw new ReportApiError(
          "RESULT_TOO_LARGE",
          502,
          "The private artifact exceeds its byte bound.",
        );
      }
      chunks.push(next.value);
    }
  } catch (error) {
    if (error instanceof ReportApiError) throw error;
    throw invalid();
  } finally {
    reader.releaseLock();
  }
  const bytes = new Uint8Array(length);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return bytes;
}

async function safeResponseError(response: Response): Promise<ReportApiError> {
  let code = "REPORT_REQUEST_FAILED";
  try {
    const bytes = await readBounded(response, 2 * 1024 * 1024);
    const payload: unknown = JSON.parse(
      new TextDecoder("utf-8", { fatal: true }).decode(bytes),
    );
    const parsed = errorCodeSchema.safeParse(payload);
    if (parsed.success && Object.hasOwn(messages, parsed.data.error.code))
      code = parsed.data.error.code;
  } catch {
    /* An untrusted body never becomes an error message. */
  }
  return new ReportApiError(code, response.status, messages[code]);
}

/** Internal transport; only the eleven fixed generated client methods are exported. */
export class ReportTransport extends BoundedTransport {
  constructor(private readonly reportOptions: ReportClientOptions) {
    super(
      {
        ...reportOptions,
        fetchImpl: async (input, init) => {
          let response: Response;
          try {
            const headers = new Headers(init?.headers);
            headers.delete("X-Artifact-Grant");
            response = await (reportOptions.fetchImpl ?? fetch)(input, {
              ...init,
              headers,
              redirect: "error",
              cache: "no-store",
            });
          } catch {
            throw new ReportApiError(
              "REPORT_REQUEST_FAILED",
              503,
              messages.REPORT_REQUEST_FAILED,
            );
          }
          if (
            response.redirected ||
            (response.status >= 300 &&
              response.status !== 304 &&
              response.status < 400) ||
            response.headers.has("location")
          )
            throw await invalidResponse(response);
          if (
            response.status === 304 &&
            (init?.method !== "GET" ||
              !new Headers(init.headers).has("if-none-match"))
          )
            throw await invalidResponse(response);
          if (response.ok || response.status === 304)
            await privateHeaders(response);
          if (
            response.ok &&
            response.headers
              .get("content-type")
              ?.split(";")[0]
              .trim()
              .toLowerCase() !== "application/json"
          )
            throw await invalidResponse(response);
          return response;
        },
      },
      {
        label: "report",
        errors: messages,
        fallbackCode: "REPORT_REQUEST_FAILED",
        error: (code, status, message) =>
          new ReportApiError(code, status, message),
      },
    );
  }

  override async request<T>(
    method: string,
    path: string,
    schema: z.ZodType<T>,
    query: Record<string, unknown> | undefined,
    body: unknown,
    options: ReportReadOptions | ReportCommandOptions,
  ): Promise<ReportApiResponse<T>> {
    try {
      return await super.request(method, path, schema, query, body, options);
    } catch (error) {
      if (error instanceof ReportApiError) throw error;
      if (error instanceof z.ZodError)
        throw new ReportApiError(
          "VALIDATION_FAILED",
          422,
          messages.VALIDATION_FAILED,
        );
      throw new ReportApiError(
        "REPORT_REQUEST_FAILED",
        503,
        messages.REPORT_REQUEST_FAILED,
      );
    }
  }

  async download(
    family: "reports" | "exports",
    parentId: string,
    artifactId: string,
    query: { account_id: string },
    options: ReportDownloadOptions,
    metadataSchema: z.ZodType<ReportArtifactMetadata>,
  ): Promise<ReportArtifactResponse> {
    let metadata: ReportArtifactMetadata;
    let token: string;
    let parent: string;
    let artifact: string;
    let account: string;
    try {
      metadata = metadataSchema.parse(options.metadata);
      token = grant.parse(options.grantToken);
      parent = uuid.parse(parentId);
      artifact = uuid.parse(artifactId);
      account = accountQuery.parse(query).account_id;
      if (
        metadata.mime_type !== mimeByFormat[metadata.format] ||
        metadata.artifact_id !== artifact ||
        !Number.isSafeInteger(metadata.byte_length) ||
        metadata.byte_length < 1 ||
        metadata.byte_length > maximumArtifactBytes
      )
        throw invalid();
    } catch {
      throw new ReportApiError(
        "VALIDATION_FAILED",
        422,
        messages.VALIDATION_FAILED,
      );
    }
    const path = `/api/v1/${family}/${encodeURIComponent(parent)}/artifacts/${encodeURIComponent(artifact)}/content`;
    const url = new URL(this.reportOptions.baseUrl.replace(/\/$/, "") + path);
    url.searchParams.set("account_id", account);
    let headers: Headers;
    try {
      headers = new Headers(await this.reportOptions.headers?.());
    } catch {
      throw new ReportApiError(
        "REPORT_REQUEST_FAILED",
        503,
        messages.REPORT_REQUEST_FAILED,
      );
    }
    for (const key of ["if-none-match", "if-match", "x-idempotency-key"])
      headers.delete(key);
    headers.set("Accept", metadata.mime_type);
    headers.set("X-Artifact-Grant", token);
    let response: Response;
    try {
      response = await (this.reportOptions.fetchImpl ?? fetch)(url, {
        method: "GET",
        headers,
        redirect: "error",
        cache: "no-store",
        signal: AbortSignal.timeout(30_000),
      });
    } catch {
      throw new ReportApiError(
        "REPORT_REQUEST_FAILED",
        503,
        messages.REPORT_REQUEST_FAILED,
      );
    }
    if (
      response.redirected ||
      (response.status >= 300 && response.status < 400) ||
      response.headers.has("location")
    )
      throw await invalidResponse(response);
    if (!response.ok) throw await safeResponseError(response);
    await privateHeaders(response);
    const declared = response.headers.get("content-length");
    const filename = `portfolio-artifact-${artifact}.${metadata.format}`;
    if (
      response.status !== 200 ||
      !declared ||
      !/^[1-9][0-9]{0,7}$/.test(declared) ||
      Number(declared) !== metadata.byte_length ||
      response.headers.get("content-type")?.toLowerCase() !==
        metadata.mime_type ||
      response.headers.get("x-artifact-sha256") !== metadata.content_digest ||
      response.headers.get("content-disposition") !==
        `attachment; filename="${filename}"`
    )
      throw await invalidResponse(response);
    const content = await readBounded(response, maximumArtifactBytes);
    const digest = Array.from(
      new Uint8Array(await crypto.subtle.digest("SHA-256", content)),
      (value) => value.toString(16).padStart(2, "0"),
    ).join("");
    if (
      content.byteLength !== metadata.byte_length ||
      digest !== metadata.content_digest
    )
      throw invalid();
    return { content, metadata, filename };
  }
}
