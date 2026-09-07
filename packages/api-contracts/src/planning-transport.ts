import {
  BoundedTransport,
  type BoundedClientOptions,
  type BoundedReadOptions,
  type BoundedCommandOptions,
  type BoundedApiResponse,
} from "./bounded-transport";

export type PlanningClientOptions = BoundedClientOptions;
export type PlanningReadOptions = BoundedReadOptions;
export type PlanningCommandOptions = BoundedCommandOptions;
export type PlanningApiResponse<T> = BoundedApiResponse<T>;

export class PlanningApiError extends Error {
  constructor(
    readonly code: string,
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "PlanningApiError";
  }
}

const planningErrors: Readonly<Record<string, string>> = {
  AUTHENTICATION_REQUIRED: "Sign in to continue.",
  ACCESS_DENIED: "You do not have access to this planning operation.",
  NOT_FOUND: "The requested planning resource was not found.",
  IDEMPOTENCY_KEY_REUSED:
    "This request identity belongs to a different command.",
  REVISION_MISMATCH:
    "The plan changed. Preserve your inputs and reload before recalculating.",
  REVISION_REQUIRED: "The current plan revision is required. Reload this page.",
  VALIDATION_FAILED: "The planning request is invalid. Review its fields.",
  INVALID_STATE_TRANSITION:
    "This planning lifecycle transition is unavailable.",
  CURRENCY_MISMATCH:
    "The contribution currency does not match the reporting currency.",
  REQUEST_TOO_LARGE: "The planning request exceeds 64 KiB.",
  RESULT_TOO_LARGE: "The planning response exceeds its permitted size.",
  CURSOR_INVALID:
    "The pagination cursor is invalid or expired. Return to the first page.",
  COLLECTION_SNAPSHOT_CAPACITY_EXCEEDED:
    "Active pagination capacity is temporarily exhausted. Retry after earlier views expire.",
  PLANNING_UNAVAILABLE:
    "Planning is temporarily unavailable. Your inputs are preserved.",
  INTERNAL_ERROR:
    "The planning request could not be completed. Your inputs are preserved.",
  PLANNING_REQUEST_FAILED:
    "The planning request could not be completed. Your inputs are preserved.",
};

/** Internal transport; consumers receive only six fixed PlanningApiClient operations. */
export class PlanningTransport extends BoundedTransport {
  constructor(options: PlanningClientOptions) {
    super(options, {
      label: "planning",
      errors: planningErrors,
      fallbackCode: "PLANNING_REQUEST_FAILED",
      error: (code, status, message) =>
        new PlanningApiError(code, status, message),
    });
  }
}
