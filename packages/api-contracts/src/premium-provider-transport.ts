import {
  BoundedTransport,
  type BoundedClientOptions,
  type BoundedReadOptions,
  type BoundedCommandOptions,
  type BoundedApiResponse,
} from "./bounded-transport";
import { z, type ZodType } from "zod";

export type PremiumProviderClientOptions = BoundedClientOptions;
export type PremiumProviderReadOptions = BoundedReadOptions;
export type PremiumProviderCommandOptions = BoundedCommandOptions;
export type PremiumProviderApiResponse<T> = BoundedApiResponse<T>;

export class PremiumProviderApiError extends Error {
  constructor(
    readonly code: string,
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "PremiumProviderApiError";
  }
}
const errors: Readonly<Record<string, string>> = {
  AUTHENTICATION_REQUIRED: "Sign in to inspect provider status.",
  ACCESS_DENIED: "Provider status is not available for this account.",
  VALIDATION_FAILED: "The provider status request is invalid.",
  SOURCE_UNAVAILABLE: "Provider status is currently unavailable.",
  INVALID_RESPONSE: "Provider status could not be verified.",
  INTERNAL_ERROR: "Provider status is currently unavailable.",
  PREMIUM_PROVIDER_REQUEST_FAILED: "Provider status is currently unavailable.",
};

/** Internal transport for the one fixed account metadata read. */
export class PremiumProviderTransport extends BoundedTransport {
  constructor(options: PremiumProviderClientOptions) {
    super(options, {
      label: "premium-providers",
      errors,
      fallbackCode: "PREMIUM_PROVIDER_REQUEST_FAILED",
      error: (code, status, message) =>
        new PremiumProviderApiError(code, status, message),
    });
  }
  override async request<T>(
    method: string,
    path: string,
    schema: ZodType<T>,
    query: Record<string, unknown> | undefined,
    body: unknown,
    options: PremiumProviderReadOptions | PremiumProviderCommandOptions,
  ): Promise<PremiumProviderApiResponse<T>> {
    if (
      method !== "GET" ||
      !/^\/api\/v1\/accounts\/[0-9a-f-]{36}\/premium-providers$/.test(path) ||
      body !== undefined ||
      (query !== undefined && Object.keys(query).length > 0)
    )
      throw new PremiumProviderApiError(
        "VALIDATION_FAILED",
        422,
        errors.VALIDATION_FAILED,
      );
    try {
      return await super.request(method, path, schema, query, body, options);
    } catch (error) {
      if (error instanceof PremiumProviderApiError) throw error;
      if (error instanceof z.ZodError)
        throw new PremiumProviderApiError(
          "VALIDATION_FAILED",
          422,
          errors.VALIDATION_FAILED,
        );
      throw new PremiumProviderApiError(
        "SOURCE_UNAVAILABLE",
        503,
        errors.SOURCE_UNAVAILABLE,
      );
    }
  }
}
