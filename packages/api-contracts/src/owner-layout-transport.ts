import {
  BoundedTransport,
  type BoundedClientOptions,
  type BoundedReadOptions,
  type BoundedCommandOptions,
  type BoundedApiResponse,
} from "./bounded-transport";
import { z, type ZodType } from "zod";

export type OwnerLayoutClientOptions = BoundedClientOptions;
export type OwnerLayoutReadOptions = BoundedReadOptions;
export type OwnerLayoutCommandOptions = BoundedCommandOptions;
export type OwnerLayoutApiResponse<T> = BoundedApiResponse<T>;

export class OwnerLayoutApiError extends Error {
  constructor(
    readonly code: string,
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "OwnerLayoutApiError";
  }
}

const layoutErrors: Readonly<Record<string, string>> = {
  AUTHENTICATION_REQUIRED: "Sign in to continue.",
  ACCESS_DENIED: "You do not have access to this saved layout operation.",
  NOT_FOUND: "The requested saved layout resource was not found.",
  VALIDATION_FAILED: "The saved layout request is invalid. Review its fields.",
  INPUT_BOUND_EXCEEDED: "The saved layout input exceeds its supported bounds.",
  CONFLICT: "The request identity or retained revision conflicts.",
  REVISION_MISMATCH:
    "This layout changed. Reload its current revision before saving.",
  REVISION_REQUIRED: "A current layout revision is required.",
  REQUEST_TOO_LARGE: "The saved layout request exceeds 64 KiB.",
  RESULT_TOO_LARGE: "The saved layout response exceeds its permitted size.",
  CURSOR_INVALID:
    "The pagination cursor is invalid or expired. Return to the first page.",
  RATE_LIMITED: "OwnerLayout storage or collection capacity is currently full.",
  SOURCE_UNAVAILABLE:
    "The retained saved layout source or service is unavailable or restricted.",
  INTERNAL_ERROR: "The saved layout request could not be completed.",
  OWNER_LAYOUT_REQUEST_FAILED:
    "The saved layout request could not be completed.",
};

/** Internal transport for the five fixed saved layout operations. */
export class OwnerLayoutTransport extends BoundedTransport {
  constructor(options: OwnerLayoutClientOptions) {
    super(options, {
      label: "saved layout",
      errors: layoutErrors,
      fallbackCode: "OWNER_LAYOUT_REQUEST_FAILED",
      error: (code, status, message) =>
        new OwnerLayoutApiError(code, status, message),
    });
  }

  override async request<T>(
    method: string,
    path: string,
    schema: ZodType<T>,
    query: Record<string, unknown> | undefined,
    body: unknown,
    options: OwnerLayoutReadOptions | OwnerLayoutCommandOptions,
  ): Promise<OwnerLayoutApiResponse<T>> {
    try {
      return await super.request(method, path, schema, query, body, options);
    } catch (error) {
      if (error instanceof OwnerLayoutApiError) throw error;
      if (error instanceof z.ZodError) {
        throw new OwnerLayoutApiError(
          "VALIDATION_FAILED",
          422,
          "The bounded saved layout request is invalid.",
        );
      }
      // Fetch, abort and stream errors may contain private URLs or headers.
      throw new OwnerLayoutApiError(
        "SOURCE_UNAVAILABLE",
        503,
        layoutErrors.SOURCE_UNAVAILABLE,
      );
    }
  }
}
