import {
  BoundedTransport,
  type BoundedClientOptions,
  type BoundedReadOptions,
  type BoundedCommandOptions,
  type BoundedApiResponse,
} from "./bounded-transport";

export type TargetClientOptions = BoundedClientOptions;
export type TargetReadOptions = BoundedReadOptions;
export type TargetCommandOptions = BoundedCommandOptions;
export type TargetApiResponse<T> = BoundedApiResponse<T>;

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

/** Internal transport; package consumers receive only fixed TargetApiClient methods. */
export class TargetTransport extends BoundedTransport {
  constructor(options: TargetClientOptions) {
    super(options, {
      label: "target",
      errors: targetErrors,
      fallbackCode: "TARGET_REQUEST_FAILED",
      error: (code, status, message) =>
        new TargetApiError(code, status, message),
    });
  }
}
