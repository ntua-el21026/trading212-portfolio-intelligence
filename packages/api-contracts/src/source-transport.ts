import {
  BoundedTransport,
  type BoundedClientOptions,
  type BoundedReadOptions,
  type BoundedCommandOptions,
  type BoundedApiResponse,
} from "./bounded-transport";

export type SourceClientOptions = BoundedClientOptions;
export type SourceReadOptions = BoundedReadOptions;
export type SourceCommandOptions = BoundedCommandOptions;
export type SourceApiResponse<T> = BoundedApiResponse<T>;

export class SourceApiError extends Error {
  constructor(
    readonly code: string,
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "SourceApiError";
  }
}

const sourceErrors: Readonly<Record<string, string>> = {
  AUTHENTICATION_REQUIRED: "Sign in to continue.",
  ACCESS_DENIED: "You do not have access to this reference source.",
  NOT_FOUND: "The requested reference resource was not found.",
  IDEMPOTENCY_KEY_REUSED:
    "This request identity belongs to a different command.",
  REVISION_MISMATCH:
    "The benchmark changed. Preserve your inputs and reload before submitting.",
  REVISION_REQUIRED:
    "The current benchmark revision is required. Reload this page.",
  VALIDATION_FAILED:
    "The reference source request is invalid. Review its fields.",
  INVALID_STATE_TRANSITION:
    "This benchmark lifecycle transition is unavailable.",
  IMMUTABLE_VERSION:
    "Published benchmarks are immutable. Create a new version.",
  SOURCE_REVISION_CONFLICT:
    "The source revision conflicts with retained evidence.",
  CURRENCY_MISMATCH: "The benchmark reporting currency does not match.",
  REQUEST_TOO_LARGE: "The reference source request exceeds 64 KiB.",
  RESULT_TOO_LARGE: "The reference source response exceeds its permitted size.",
  CURSOR_INVALID:
    "The pagination cursor is invalid or expired. Return to the first page.",
  COLLECTION_SNAPSHOT_CAPACITY_EXCEEDED:
    "Active pagination capacity is temporarily exhausted. Retry after earlier views expire.",
  PROVIDER_UNAVAILABLE:
    "The reference source service is temporarily unavailable.",
  INTERNAL_ERROR:
    "The reference source request could not be completed. Your inputs are preserved.",
  SOURCE_REQUEST_FAILED:
    "The reference source request could not be completed. Your inputs are preserved.",
};

/** Internal transport; consumers receive only sixteen fixed source and quality operations. */
export class SourceTransport extends BoundedTransport {
  constructor(options: SourceClientOptions) {
    super(options, {
      label: "source",
      errors: sourceErrors,
      fallbackCode: "SOURCE_REQUEST_FAILED",
      error: (code, status, message) =>
        new SourceApiError(code, status, message),
    });
  }
}
