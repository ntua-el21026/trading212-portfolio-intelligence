import {
  BoundedTransport,
  type BoundedClientOptions,
  type BoundedReadOptions,
  type BoundedCommandOptions,
  type BoundedApiResponse,
} from "./bounded-transport";
import { z, type ZodType } from "zod";

export type ResearchClientOptions = BoundedClientOptions;
export type ResearchReadOptions = BoundedReadOptions;
export type ResearchCommandOptions = BoundedCommandOptions;
export type ResearchApiResponse<T> = BoundedApiResponse<T>;

export class ResearchApiError extends Error {
  constructor(
    readonly code: string,
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ResearchApiError";
  }
}

const researchErrors: Readonly<Record<string, string>> = {
  AUTHENTICATION_REQUIRED: "Sign in to continue.",
  ACCESS_DENIED: "You do not have access to this research operation.",
  NOT_FOUND: "The requested research resource was not found.",
  VALIDATION_FAILED: "The research request is invalid. Review its fields.",
  INPUT_BOUND_EXCEEDED: "The research input exceeds its supported bounds.",
  CONFLICT: "The request identity or retained revision conflicts.",
  REVISION_MISMATCH:
    "This note changed. Reload its current revision before saving.",
  REVISION_REQUIRED: "A current note revision is required.",
  REQUEST_TOO_LARGE: "The research request exceeds 64 KiB.",
  RESULT_TOO_LARGE: "The research response exceeds its permitted size.",
  CURSOR_INVALID:
    "The pagination cursor is invalid or expired. Return to the first page.",
  RATE_LIMITED: "Research storage or collection capacity is currently full.",
  SOURCE_UNAVAILABLE:
    "The retained research source or service is unavailable or restricted.",
  INTERNAL_ERROR: "The research request could not be completed.",
  RESEARCH_REQUEST_FAILED: "The research request could not be completed.",
};

/** Internal transport for the eight fixed research operations. */
export class ResearchTransport extends BoundedTransport {
  constructor(options: ResearchClientOptions) {
    super(options, {
      label: "research",
      errors: researchErrors,
      fallbackCode: "RESEARCH_REQUEST_FAILED",
      error: (code, status, message) =>
        new ResearchApiError(code, status, message),
    });
  }

  override async request<T>(
    method: string,
    path: string,
    schema: ZodType<T>,
    query: Record<string, unknown> | undefined,
    body: unknown,
    options: ResearchReadOptions | ResearchCommandOptions,
  ): Promise<ResearchApiResponse<T>> {
    try {
      return await super.request(method, path, schema, query, body, options);
    } catch (error) {
      if (error instanceof ResearchApiError) throw error;
      if (error instanceof z.ZodError) {
        throw new ResearchApiError(
          "VALIDATION_FAILED",
          422,
          "The bounded research request is invalid.",
        );
      }
      // Fetch, abort and stream errors may contain private URLs or headers.
      throw new ResearchApiError(
        "SOURCE_UNAVAILABLE",
        503,
        researchErrors.SOURCE_UNAVAILABLE,
      );
    }
  }
}
