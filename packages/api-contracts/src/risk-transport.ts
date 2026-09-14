import {
  BoundedTransport,
  type BoundedClientOptions,
  type BoundedReadOptions,
  type BoundedCommandOptions,
  type BoundedApiResponse,
} from "./bounded-transport";
import { z, type ZodType } from "zod";

export type RiskClientOptions = BoundedClientOptions;
export type RiskReadOptions = BoundedReadOptions;
export type RiskCommandOptions = BoundedCommandOptions;
export type RiskApiResponse<T> = BoundedApiResponse<T>;

export class RiskApiError extends Error {
  constructor(
    readonly code: string,
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "RiskApiError";
  }
}

const riskErrors: Readonly<Record<string, string>> = {
  AUTHENTICATION_REQUIRED: "Sign in to continue.",
  ACCESS_DENIED: "You do not have access to this risk operation.",
  NOT_FOUND: "The requested risk resource was not found.",
  VALIDATION_FAILED: "The risk request is invalid. Review its fields.",
  INPUT_BOUND_EXCEEDED: "The risk inputs exceed their supported bounds.",
  CONFLICT:
    "The request identity or pinned input conflicts. Review the saved request.",
  INVALID_STATE_TRANSITION:
    "This risk job cannot make the requested transition.",
  REVISION_MISMATCH:
    "This definition changed. Reload its current version before saving.",
  REVISION_REQUIRED: "A current definition revision is required.",
  REQUEST_TOO_LARGE: "The risk request exceeds 64 KiB.",
  RESULT_TOO_LARGE: "The risk response exceeds its permitted size.",
  CURSOR_INVALID:
    "The pagination cursor is invalid or expired. Return to the first page.",
  RATE_LIMITED:
    "Risk capacity is currently full. Wait for an active job to finish.",
  SOURCE_UNAVAILABLE: "The pinned risk source is unavailable or restricted.",
  RUN_EXPIRED: "The retained risk inputs have expired.",
  RISK_UNAVAILABLE: "The risk result or service is temporarily unavailable.",
  INTERNAL_ERROR: "The risk request could not be completed.",
  RISK_REQUEST_FAILED: "The risk request could not be completed.",
};

/** Internal transport for the eleven fixed risk operations. */
export class RiskTransport extends BoundedTransport {
  constructor(options: RiskClientOptions) {
    super(options, {
      label: "risk",
      errors: riskErrors,
      fallbackCode: "RISK_REQUEST_FAILED",
      error: (code, status, message) => new RiskApiError(code, status, message),
    });
  }

  override async request<T>(
    method: string,
    path: string,
    schema: ZodType<T>,
    query: Record<string, unknown> | undefined,
    body: unknown,
    options: RiskReadOptions | RiskCommandOptions,
  ): Promise<RiskApiResponse<T>> {
    try {
      return await super.request(method, path, schema, query, body, options);
    } catch (error) {
      if (error instanceof RiskApiError) throw error;
      if (error instanceof z.ZodError) {
        throw new RiskApiError(
          "VALIDATION_FAILED",
          422,
          "The bounded risk request is invalid.",
        );
      }
      // Fetch, abort and stream errors may contain private URLs or headers.
      throw new RiskApiError(
        "RISK_UNAVAILABLE",
        503,
        riskErrors.RISK_UNAVAILABLE,
      );
    }
  }
}
