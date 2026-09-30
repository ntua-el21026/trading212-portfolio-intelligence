import {
  BoundedTransport,
  type BoundedClientOptions,
  type BoundedReadOptions,
  type BoundedCommandOptions,
  type BoundedApiResponse,
} from "./bounded-transport";
import { z, type ZodType } from "zod";

export type AggregateClientOptions = BoundedClientOptions;
export type AggregateReadOptions = BoundedReadOptions;
export type AggregateCommandOptions = BoundedCommandOptions;
export type AggregateApiResponse<T> = BoundedApiResponse<T>;

export class AggregateApiError extends Error {
  constructor(
    readonly code: string,
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "AggregateApiError";
  }
}

const aggregateErrors: Readonly<Record<string, string>> = {
  AUTHENTICATION_REQUIRED: "Sign in to continue.",
  ACCESS_DENIED: "You do not have access to this aggregate operation.",
  NOT_FOUND: "The requested aggregate resource was not found.",
  VALIDATION_FAILED: "The aggregate request is invalid. Review its fields.",
  INPUT_BOUND_EXCEEDED: "The aggregate input exceeds its supported bounds.",
  CONFLICT: "The request identity or retained revision conflicts.",
  REVISION_MISMATCH:
    "This selection changed. Reload its current revision before running.",
  REVISION_REQUIRED: "A current selection revision is required.",
  REQUEST_TOO_LARGE: "The aggregate request exceeds 64 KiB.",
  RESULT_TOO_LARGE: "The aggregate response exceeds its permitted size.",
  CURSOR_INVALID:
    "The pagination cursor is invalid or expired. Return to the first page.",
  RATE_LIMITED: "Aggregate storage or collection capacity is currently full.",
  SOURCE_UNAVAILABLE:
    "The retained aggregate source or service is unavailable or restricted.",
  RUN_EXPIRED: "The saved aggregate run has expired.",
  DEADLINE_EXCEEDED: "The aggregate operation exceeded its execution deadline.",
  INTERNAL_ERROR: "The aggregate request could not be completed.",
  AGGREGATE_REQUEST_FAILED: "The aggregate request could not be completed.",
};

/** Internal transport for the six fixed aggregate operations. */
export class AggregateTransport extends BoundedTransport {
  constructor(options: AggregateClientOptions) {
    super(options, {
      label: "aggregate",
      commandTimeoutMs: 30_000,
      errors: aggregateErrors,
      fallbackCode: "AGGREGATE_REQUEST_FAILED",
      error: (code, status, message) =>
        new AggregateApiError(code, status, message),
    });
  }

  override async request<T>(
    method: string,
    path: string,
    schema: ZodType<T>,
    query: Record<string, unknown> | undefined,
    body: unknown,
    options: AggregateReadOptions | AggregateCommandOptions,
  ): Promise<AggregateApiResponse<T>> {
    try {
      const uuid =
        "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}";
      const selections = path === "/api/v1/aggregate-selections";
      const selection = new RegExp(
        `^/api/v1/aggregate-selections/${uuid}$`,
      ).test(path);
      const runs = new RegExp(
        `^/api/v1/aggregate-selections/${uuid}/runs$`,
      ).test(path);
      const run = new RegExp(`^/api/v1/aggregate-runs/${uuid}$`).test(path);
      if (!(
        (method === "GET" && (selections || selection || runs || run)) ||
        (method === "POST" && (selections || runs))
      )) {
        throw new AggregateApiError(
          "VALIDATION_FAILED",
          422,
          "Unknown aggregate operation.",
        );
      }
      return await super.request(method, path, schema, query, body, options);
    } catch (error) {
      if (error instanceof AggregateApiError) throw error;
      if (error instanceof z.ZodError) {
        throw new AggregateApiError(
          "VALIDATION_FAILED",
          422,
          "The bounded aggregate request is invalid.",
        );
      }
      // Fetch, abort and stream errors may contain private URLs or headers.
      throw new AggregateApiError(
        "SOURCE_UNAVAILABLE",
        503,
        aggregateErrors.SOURCE_UNAVAILABLE,
      );
    }
  }
}
