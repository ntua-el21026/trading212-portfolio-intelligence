import {
  BoundedTransport,
  type BoundedClientOptions,
  type BoundedReadOptions,
  type BoundedCommandOptions,
  type BoundedApiResponse,
} from "./bounded-transport";
import { z, type ZodType } from "zod";

export type ProjectionClientOptions = BoundedClientOptions;
export type ProjectionReadOptions = BoundedReadOptions;
export type ProjectionCommandOptions = BoundedCommandOptions;
export type ProjectionApiResponse<T> = BoundedApiResponse<T>;

export class ProjectionApiError extends Error {
  constructor(
    readonly code: string,
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ProjectionApiError";
  }
}

const projectionErrors: Readonly<Record<string, string>> = {
  AUTHENTICATION_REQUIRED: "Sign in to continue.",
  ACCESS_DENIED: "You do not have access to this projection operation.",
  NOT_FOUND: "The requested projection resource was not found.",
  VALIDATION_FAILED: "The projection request is invalid. Review its fields.",
  INPUT_BOUND_EXCEEDED: "The projection inputs exceed their supported bounds.",
  CONFLICT:
    "The request identity or pinned input conflicts. Review the saved request.",
  INVALID_STATE_TRANSITION:
    "This projection job cannot make the requested transition.",
  REVISION_MISMATCH:
    "This definition changed. Reload its current version before saving.",
  REVISION_REQUIRED: "A current definition revision is required.",
  REQUEST_TOO_LARGE: "The projection request exceeds 64 KiB.",
  RESULT_TOO_LARGE: "The projection response exceeds its permitted size.",
  CURSOR_INVALID:
    "The pagination cursor is invalid or expired. Return to the first page.",
  RATE_LIMITED:
    "Projection capacity is currently full. Wait for an active job to finish.",
  SOURCE_UNAVAILABLE:
    "The pinned projection source is unavailable or restricted.",
  RUN_EXPIRED: "The retained projection inputs have expired.",
  PROJECTION_UNAVAILABLE:
    "The projection result or service is temporarily unavailable.",
  CALENDAR_OVERFLOW: "The projection calendar exceeds supported dates.",
  DATE_OUTSIDE_HORIZON: "A scheduled date is outside the projection horizon.",
  DATE_NOT_MONTH_BOUNDARY:
    "A scheduled date is not a projection month boundary.",
  GOAL_DATE_MISMATCH: "The goal date differs from the projection horizon.",
  INTERNAL_ERROR: "The projection request could not be completed.",
  PROJECTION_REQUEST_FAILED: "The projection request could not be completed.",
};

/** Internal transport for the seventeen fixed projection operations. */
export class ProjectionTransport extends BoundedTransport {
  constructor(options: ProjectionClientOptions) {
    super(options, {
      label: "projection",
      errors: projectionErrors,
      fallbackCode: "PROJECTION_REQUEST_FAILED",
      error: (code, status, message) =>
        new ProjectionApiError(code, status, message),
    });
  }

  override async request<T>(
    method: string,
    path: string,
    schema: ZodType<T>,
    query: Record<string, unknown> | undefined,
    body: unknown,
    options: ProjectionReadOptions | ProjectionCommandOptions,
  ): Promise<ProjectionApiResponse<T>> {
    try {
      return await super.request(method, path, schema, query, body, options);
    } catch (error) {
      if (error instanceof ProjectionApiError) throw error;
      if (error instanceof z.ZodError) {
        throw new ProjectionApiError(
          "VALIDATION_FAILED",
          422,
          "The bounded projection request is invalid.",
        );
      }
      // Fetch, abort and stream errors may contain private URLs or headers.
      throw new ProjectionApiError(
        "PROJECTION_UNAVAILABLE",
        503,
        projectionErrors.PROJECTION_UNAVAILABLE,
      );
    }
  }
}
