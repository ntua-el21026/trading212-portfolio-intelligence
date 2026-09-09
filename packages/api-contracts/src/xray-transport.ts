import {
  BoundedTransport,
  type BoundedClientOptions,
  type BoundedReadOptions,
  type BoundedCommandOptions,
  type BoundedApiResponse,
} from "./bounded-transport";
import type { ZodType } from "zod";

export type XrayClientOptions = BoundedClientOptions;
export type XrayReadOptions = BoundedReadOptions;
export type XrayCommandOptions = BoundedCommandOptions;
export type XrayApiResponse<T> = BoundedApiResponse<T>;

export class XrayApiError extends Error {
  constructor(
    readonly code: string,
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "XrayApiError";
  }
}

const xrayErrors: Readonly<Record<string, string>> = {
  AUTHENTICATION_REQUIRED: "Sign in to continue.",
  ACCESS_DENIED: "You do not have access to this X-ray calculation.",
  NOT_FOUND: "The requested X-ray resource was not found.",
  VALIDATION_FAILED: "The X-ray request is invalid. Review its fields.",
  INPUT_SNAPSHOT_MISMATCH:
    "The selected X-ray input does not match this request. Preserve the original scope and period.",
  REQUEST_TOO_LARGE: "The X-ray request exceeds 64 KiB.",
  RESULT_TOO_LARGE: "The X-ray response exceeds its permitted size.",
  CURSOR_INVALID:
    "The pagination cursor is invalid or expired. Return to the first page.",
  COLLECTION_SNAPSHOT_CAPACITY_EXCEEDED:
    "Active pagination capacity is temporarily exhausted. Retry after earlier views expire.",
  XRAY_UNAVAILABLE: "The X-ray calculation service is temporarily unavailable.",
  INTERNAL_ERROR: "The X-ray request could not be completed.",
  XRAY_REQUEST_FAILED: "The X-ray request could not be completed.",
};

/** Internal transport for the four fixed X-ray read operations. */
export class XrayTransport extends BoundedTransport {
  constructor(options: XrayClientOptions) {
    super(options, {
      label: "X-ray",
      errors: xrayErrors,
      fallbackCode: "XRAY_REQUEST_FAILED",
      error: (code, status, message) => new XrayApiError(code, status, message),
      // Complete bounded immutable source captures use a fixed internal timeout.
      repeatedQueryKeys: ["fund_ids"],
      readTimeoutMs: 30_000,
    });
  }

  override async request<T>(
    method: string,
    path: string,
    schema: ZodType<T>,
    query: Record<string, unknown> | undefined,
    body: unknown,
    options: XrayReadOptions | XrayCommandOptions,
  ): Promise<XrayApiResponse<T>> {
    try {
      return await super.request(method, path, schema, query, body, options);
    } catch (error) {
      if (error instanceof XrayApiError) throw error;
      // Fetch, abort and stream errors may contain private URLs or headers.
      throw new XrayApiError(
        "XRAY_UNAVAILABLE",
        503,
        xrayErrors.XRAY_UNAVAILABLE,
      );
    }
  }
}
