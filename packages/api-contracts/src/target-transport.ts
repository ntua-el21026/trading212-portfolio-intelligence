import { z } from "zod";

export interface TargetClientOptions {
  baseUrl: string;
  fetchImpl?: typeof fetch;
  headers?: () => HeadersInit | Promise<HeadersInit>;
}

export interface TargetReadOptions {
  ifNoneMatch?: string;
}

export interface TargetCommandOptions {
  idempotencyKey: string;
  ifMatch?: string;
}

export type TargetApiResponse<T> =
  | { data: T; etag: string | null; notModified: false }
  | { data: null; etag: string | null; notModified: true };

export class TargetApiError extends Error {
  constructor(
    readonly code: string,
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "TargetApiError";
  }
}

const errorSchema = z.object({
  error: z.object({
    code: z.string().max(80),
  }),
});

const targetErrors: Readonly<Record<string, string>> = {
  AUTHENTICATION_REQUIRED: "Sign in to continue.",
  ACCESS_DENIED: "You do not have access to this target operation.",
  NOT_FOUND: "The requested target was not found.",
  IDEMPOTENCY_KEY_REUSED:
    "This request identity belongs to a different command.",
  IMMUTABLE_VERSION:
    "Published target content is immutable; create a draft version to edit it.",
  INVALID_STATE_TRANSITION: "This target lifecycle transition is unavailable.",
  REVISION_MISMATCH:
    "The revision changed. Preserve your edits and reload before submitting again.",
  REVISION_REQUIRED:
    "The current target revision is required. Reload this page.",
  VALIDATION_FAILED: "The target request is invalid. Review its fields.",
  TARGET_VALIDATION_FAILED:
    "Validate the current target content before publishing.",
  CURRENCY_MISMATCH:
    "The reporting currency does not match the referenced target inputs.",
  REQUEST_TOO_LARGE: "The target request exceeds 64 KiB.",
  RESULT_TOO_LARGE: "The target response exceeds its permitted size.",
  CURSOR_INVALID:
    "The pagination cursor is invalid or expired. Return to the first page.",
  COLLECTION_SNAPSHOT_CAPACITY_EXCEEDED:
    "Active pagination capacity is temporarily exhausted. Retry after earlier views expire.",
  TARGETS_UNAVAILABLE:
    "The target service is temporarily unavailable. Your edits are preserved.",
  INTERNAL_ERROR:
    "The target request could not be completed. Your edits are preserved.",
  TARGET_REQUEST_FAILED:
    "The target request could not be completed. Your edits are preserved.",
};

async function readBoundedJson(response: Response): Promise<unknown> {
  const reader = response.body?.getReader();
  if (!reader)
    throw new TargetApiError("INVALID_RESPONSE", 502, "Empty target response.");
  const chunks: Uint8Array[] = [];
  let length = 0;
  try {
    while (true) {
      const next = await reader.read();
      if (next.done) break;
      length += next.value.byteLength;
      if (length > 2 * 1024 * 1024) {
        await reader.cancel();
        throw new TargetApiError(
          "RESULT_TOO_LARGE",
          502,
          "The target response exceeds its limit.",
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
  try {
    return JSON.parse(
      new TextDecoder("utf-8", { fatal: true }).decode(bytes),
    ) as unknown;
  } catch {
    throw new TargetApiError(
      "INVALID_RESPONSE",
      502,
      "The target response is malformed.",
    );
  }
}

/** Internal transport; package consumers receive only fixed TargetApiClient methods. */
export class TargetTransport {
  constructor(private readonly options: TargetClientOptions) {}

  async request<T>(
    method: string,
    path: string,
    schema: z.ZodType<T>,
    query: Record<string, unknown> | undefined,
    body: unknown,
    options: TargetReadOptions | TargetCommandOptions,
  ): Promise<TargetApiResponse<T>> {
    const url = new URL(this.options.baseUrl.replace(/\/$/, "") + path);
    for (const [key, value] of Object.entries(query ?? {})) {
      if (value !== undefined && value !== null)
        url.searchParams.set(key, String(value));
    }
    const headers = new Headers(await this.options.headers?.());
    headers.set("Accept", "application/json");
    if ("idempotencyKey" in options) {
      headers.set(
        "X-Idempotency-Key",
        z
          .string()
          .regex(/^[A-Za-z0-9._:-]{1,180}$/)
          .parse(options.idempotencyKey),
      );
      if (options.ifMatch !== undefined)
        headers.set("If-Match", options.ifMatch);
    } else if (options.ifNoneMatch !== undefined) {
      headers.set("If-None-Match", options.ifNoneMatch);
    }
    const serialized = body === undefined ? undefined : JSON.stringify(body);
    if (serialized !== undefined) {
      if (new TextEncoder().encode(serialized).byteLength > 65_536) {
        throw new TargetApiError(
          "REQUEST_TOO_LARGE",
          413,
          "The target request exceeds 64 KiB.",
        );
      }
      headers.set("Content-Type", "application/json");
    }
    const response = await (this.options.fetchImpl ?? fetch)(url, {
      method,
      headers,
      body: serialized,
      cache: "no-store",
      redirect: "error",
      signal: AbortSignal.timeout(8_000),
    });
    const etag = response.headers.get("etag");
    if (response.status === 304) return { data: null, etag, notModified: true };
    const payload = await readBoundedJson(response);
    if (!response.ok) {
      const error = errorSchema.safeParse(payload);
      const suppliedCode = error.success
        ? error.data.error.code
        : "TARGET_REQUEST_FAILED";
      const code = Object.hasOwn(targetErrors, suppliedCode)
        ? suppliedCode
        : "TARGET_REQUEST_FAILED";
      throw new TargetApiError(code, response.status, targetErrors[code]);
    }
    const parsed = schema.safeParse(payload);
    if (!parsed.success) {
      throw new TargetApiError(
        "INVALID_RESPONSE",
        502,
        "The target response does not match its contract.",
      );
    }
    return { data: parsed.data, etag, notModified: false };
  }
}
