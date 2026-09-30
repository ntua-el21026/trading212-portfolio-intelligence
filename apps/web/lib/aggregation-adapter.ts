import "server-only";
import {
  AggregateApiClient,
  AggregateApiError,
  PortfolioApiError,
  TargetApiError,
  SourceApiClient,
  SourceApiError,
  type AggregateApiResponse,
} from "@trading212/api-contracts";
import { targetClients } from "./target-adapter";
export async function aggregationClients(mutating = false) {
  const clients = await targetClients(mutating);
  return {
    ...clients,
    aggregates: new AggregateApiClient(clients.options),
    sources: new SourceApiClient(clients.options),
  };
}
export function aggregationData<T>(response: AggregateApiResponse<T>): T {
  if (response.notModified)
    throw new AggregateApiError(
      "INVALID_RESPONSE",
      502,
      "The aggregate response had no content.",
    );
  return response.data;
}
export async function aggregationResult<T>(
  operation: () => Promise<T>,
): Promise<
  { ok: true; data: T } | { ok: false; code: string; message: string }
> {
  try {
    return { ok: true, data: await operation() };
  } catch (error) {
    if (
      error instanceof AggregateApiError ||
      error instanceof TargetApiError ||
      error instanceof SourceApiError
    )
      return {
        ok: false,
        code: error.code,
        message:
          error.code === "REVISION_MISMATCH"
            ? "The selection changed. Reload its current revision before retrying."
            : error.code === "ACCESS_DENIED"
              ? "Current access is required for every included account and source."
              : "The aggregate request is unavailable. Review its saved sources and retry.",
      };
    if (error instanceof PortfolioApiError)
      return {
        ok: false,
        code: error.code,
        message: "An included account or saved snapshot is unavailable.",
      };
    throw error;
  }
}
