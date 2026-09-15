import "server-only";
import {
  ProjectionApiClient,
  ProjectionApiError,
  PortfolioApiError,
  TargetApiError,
  type ProjectionApiResponse,
} from "@trading212/api-contracts";
import { targetClients } from "./target-adapter";
export async function projectionClients(mutating = false) {
  const clients = await targetClients(mutating);
  return { ...clients, projections: new ProjectionApiClient(clients.options) };
}
export function projectionData<T>(response: ProjectionApiResponse<T>): T {
  if (response.notModified)
    throw new ProjectionApiError(
      "INVALID_RESPONSE",
      502,
      "The projection response had no content.",
    );
  return response.data;
}
export function assertProjectionAccount(actual: string, expected: string) {
  if (actual !== expected)
    throw new ProjectionApiError(
      "NOT_FOUND",
      404,
      "This saved resource is unavailable for the selected account.",
    );
}
export async function projectionResult<T>(
  operation: () => Promise<T>,
): Promise<
  { ok: true; data: T } | { ok: false; code: string; message: string }
> {
  try {
    return { ok: true, data: await operation() };
  } catch (error) {
    if (error instanceof ProjectionApiError || error instanceof TargetApiError)
      return { ok: false, code: error.code, message: error.message };
    if (error instanceof PortfolioApiError)
      return {
        ok: false,
        code: error.code,
        message: "The selected saved portfolio source is unavailable.",
      };
    throw error;
  }
}
