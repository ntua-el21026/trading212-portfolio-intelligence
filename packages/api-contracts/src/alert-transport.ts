import {
  BoundedTransport,
  type BoundedClientOptions,
  type BoundedReadOptions,
  type BoundedCommandOptions,
  type BoundedApiResponse,
} from "./bounded-transport";

export type AlertClientOptions = BoundedClientOptions;
export type AlertReadOptions = BoundedReadOptions;
export type AlertCommandOptions = BoundedCommandOptions;
export type AlertApiResponse<T> = BoundedApiResponse<T>;

export class AlertApiError extends Error {
  constructor(
    readonly code: string,
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "AlertApiError";
  }
}

const errors: Readonly<Record<string, string>> = {
  AUTHENTICATION_REQUIRED: "Sign in to continue.",
  ACCESS_DENIED: "You do not have access to this alert operation.",
  NOT_FOUND: "The requested alert was not found.",
  IDEMPOTENCY_KEY_REUSED:
    "This request identity belongs to a different command.",
  IMMUTABLE_VERSION:
    "Saved rule definitions are immutable. Create a new version to edit one.",
  INVALID_STATE_TRANSITION: "This alert lifecycle transition is unavailable.",
  REVISION_MISMATCH:
    "This alert changed. Your edits are preserved; reload its current revision before retrying.",
  REVISION_REQUIRED:
    "The current alert revision is required. Reload this view.",
  SOURCE_REVISION_CONFLICT:
    "A selected source revision changed. Review the source selection.",
  VALIDATION_FAILED:
    "Review the alert fields and their metric-specific requirements.",
  CURRENCY_MISMATCH:
    "The selected currency does not match the required sourced inputs.",
  REQUEST_TOO_LARGE: "The alert request exceeds 64 KiB.",
  RESULT_TOO_LARGE: "The alert response exceeds its permitted size.",
  CURSOR_INVALID:
    "This history cursor is invalid or expired. Return to the first page.",
  COLLECTION_SNAPSHOT_CAPACITY_EXCEEDED:
    "Pagination capacity is temporarily exhausted. Retry after earlier views expire.",
  RATE_LIMITED:
    "This operation is temporarily limited. Retry after the indicated interval.",
  ALERTS_UNAVAILABLE:
    "The alert service is temporarily unavailable. Your edits are preserved.",
  INTERNAL_ERROR:
    "The alert operation could not complete. Your edits are preserved.",
  ALERT_REQUEST_FAILED:
    "The alert operation could not complete. Your edits are preserved.",
};

/** Internal transport; package consumers receive only fixed alert operations. */
export class AlertTransport extends BoundedTransport {
  constructor(options: AlertClientOptions) {
    super(options, {
      label: "alert",
      errors,
      fallbackCode: "ALERT_REQUEST_FAILED",
      error: (code, status, message) =>
        new AlertApiError(code, status, message),
    });
  }
}
