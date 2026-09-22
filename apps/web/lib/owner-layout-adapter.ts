import "server-only";
import {
  OwnerLayoutApiClient,
  OwnerLayoutApiError,
  TargetApiError,
  type OwnerLayoutApiResponse,
} from "@trading212/api-contracts";
import { targetClients } from "./target-adapter";

export async function ownerLayoutClients(mutating = false) {
  const clients = await targetClients(mutating);
  if (
    !["preferences:read", ...(mutating ? ["preferences:write"] : [])].every(
      (scope) => clients.access.principal.scopes.includes(scope),
    )
  )
    throw new OwnerLayoutApiError(
      "ACCESS_DENIED",
      403,
      "Current preferences access is required.",
    );
  return { ...clients, layouts: new OwnerLayoutApiClient(clients.options) };
}
export function ownerLayoutData<T>(response: OwnerLayoutApiResponse<T>): T {
  if (response.notModified)
    throw new OwnerLayoutApiError(
      "INVALID_RESPONSE",
      502,
      "The layout response had no content.",
    );
  return response.data;
}
export async function ownerLayoutResult<T>(
  operation: () => Promise<T>,
): Promise<
  { ok: true; data: T } | { ok: false; code: string; message: string }
> {
  try {
    return { ok: true, data: await operation() };
  } catch (error) {
    if (error instanceof OwnerLayoutApiError || error instanceof TargetApiError)
      return { ok: false, code: error.code, message: error.message };
    return {
      ok: false,
      code: "SOURCE_UNAVAILABLE",
      message: "The saved layout is unavailable. Reload the current selection.",
    };
  }
}
