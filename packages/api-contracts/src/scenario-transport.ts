import {
  BoundedTransport,
  type BoundedClientOptions,
  type BoundedReadOptions,
  type BoundedCommandOptions,
  type BoundedApiResponse,
} from "./bounded-transport";
import { z, type ZodType } from "zod";

export type ScenarioClientOptions = BoundedClientOptions;
export type ScenarioReadOptions = BoundedReadOptions;
export type ScenarioCommandOptions = BoundedCommandOptions;
export type ScenarioApiResponse<T> = BoundedApiResponse<T>;

export class ScenarioApiError extends Error {
  constructor(
    readonly code: string,
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ScenarioApiError";
  }
}

const scenarioErrors: Readonly<Record<string, string>> = {
  AUTHENTICATION_REQUIRED: "Sign in to continue.",
  ACCESS_DENIED: "You do not have access to this scenario operation.",
  NOT_FOUND: "The requested scenario resource was not found.",
  VALIDATION_FAILED: "The scenario request is invalid. Review its fields.",
  INPUT_BOUND_EXCEEDED: "The scenario inputs exceed their supported bounds.",
  CONFLICT:
    "The request identity or pinned input conflicts. Review the saved request.",
  INVALID_STATE_TRANSITION:
    "This scenario job cannot make the requested transition.",
  REVISION_MISMATCH:
    "This definition changed. Reload its current version before saving.",
  REVISION_REQUIRED: "A current definition revision is required.",
  REQUEST_TOO_LARGE: "The scenario request exceeds 64 KiB.",
  RESULT_TOO_LARGE: "The scenario response exceeds its permitted size.",
  CURSOR_INVALID:
    "The pagination cursor is invalid or expired. Return to the first page.",
  RATE_LIMITED:
    "Scenario capacity is currently full. Wait for an active job to finish.",
  SOURCE_UNAVAILABLE:
    "The pinned scenario source is unavailable or restricted.",
  RUN_EXPIRED: "The retained scenario inputs have expired.",
  SCENARIO_UNAVAILABLE:
    "The scenario result or service is temporarily unavailable.",
  INTERNAL_ERROR: "The scenario request could not be completed.",
  SCENARIO_REQUEST_FAILED: "The scenario request could not be completed.",
};

/** Internal transport for the eleven fixed scenario operations. */
export class ScenarioTransport extends BoundedTransport {
  constructor(options: ScenarioClientOptions) {
    super(options, {
      label: "scenario",
      repeatedQueryKeys: ["run_ids"],
      errors: scenarioErrors,
      fallbackCode: "SCENARIO_REQUEST_FAILED",
      error: (code, status, message) =>
        new ScenarioApiError(code, status, message),
    });
  }

  override async request<T>(
    method: string,
    path: string,
    schema: ZodType<T>,
    query: Record<string, unknown> | undefined,
    body: unknown,
    options: ScenarioReadOptions | ScenarioCommandOptions,
  ): Promise<ScenarioApiResponse<T>> {
    try {
      return await super.request(method, path, schema, query, body, options);
    } catch (error) {
      if (error instanceof ScenarioApiError) throw error;
      if (error instanceof z.ZodError) {
        throw new ScenarioApiError(
          "VALIDATION_FAILED",
          422,
          "The bounded scenario request is invalid.",
        );
      }
      // Fetch, abort and stream errors may contain private URLs or headers.
      throw new ScenarioApiError(
        "SCENARIO_UNAVAILABLE",
        503,
        scenarioErrors.SCENARIO_UNAVAILABLE,
      );
    }
  }
}
