import {
  BoundedTransport,
  type BoundedClientOptions,
  type BoundedReadOptions,
  type BoundedCommandOptions,
  type BoundedApiResponse,
} from "./bounded-transport";
import type { ZodType } from "zod";

export type HistoricalClientOptions = BoundedClientOptions;
export type HistoricalReadOptions = BoundedReadOptions;
export type HistoricalCommandOptions = BoundedCommandOptions;
export type HistoricalApiResponse<T> = BoundedApiResponse<T>;

export class HistoricalApiError extends Error {
  constructor(
    readonly code: string,
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "HistoricalApiError";
  }
}

const historicalErrors: Readonly<Record<string, string>> = {
  AUTHENTICATION_REQUIRED: "Sign in to continue.",
  ACCESS_DENIED: "You do not have access to this historical calculation.",
  NOT_FOUND: "The requested historical resource was not found.",
  VALIDATION_FAILED: "The historical request is invalid. Review its fields.",
  INPUT_SNAPSHOT_MISMATCH:
    "The selected historical input does not match this request. Preserve the original scope and period.",
  REQUEST_TOO_LARGE: "The historical request exceeds 64 KiB.",
  RESULT_TOO_LARGE: "The historical response exceeds its permitted size.",
  CURSOR_INVALID:
    "The pagination cursor is invalid or expired. Return to the first page.",
  COLLECTION_SNAPSHOT_CAPACITY_EXCEEDED:
    "Active pagination capacity is temporarily exhausted. Retry after earlier views expire.",
  HISTORICAL_UNAVAILABLE:
    "The historical calculation service is temporarily unavailable.",
  INTERNAL_ERROR: "The historical request could not be completed.",
  HISTORICAL_REQUEST_FAILED: "The historical request could not be completed.",
};

/** Internal transport for the six fixed historical read operations. */
export class HistoricalTransport extends BoundedTransport {
  constructor(options: HistoricalClientOptions) {
    super(options, {
      label: "historical",
      errors: historicalErrors,
      fallbackCode: "HISTORICAL_REQUEST_FAILED",
      error: (code, status, message) =>
        new HistoricalApiError(code, status, message),
      // Cold immutable full-year captures include exact source verification.
      // This fixed policy is internal; callers cannot widen it further.
      readTimeoutMs: 30_000,
    });
  }

  override async request<T>(
    method: string,
    path: string,
    schema: ZodType<T>,
    query: Record<string, unknown> | undefined,
    body: unknown,
    options: HistoricalReadOptions | HistoricalCommandOptions,
  ): Promise<HistoricalApiResponse<T>> {
    try {
      return await super.request(method, path, schema, query, body, options);
    } catch (error) {
      if (error instanceof HistoricalApiError) throw error;
      // Fetch, abort and stream errors may contain private URLs or headers.
      throw new HistoricalApiError(
        "HISTORICAL_UNAVAILABLE",
        503,
        historicalErrors.HISTORICAL_UNAVAILABLE,
      );
    }
  }
}
