import "server-only";

import {
  SourceApiClient,
  SourceApiError,
  type SourceApiResponse,
} from "@trading212/api-contracts";
import { targetClients } from "./target-adapter";

export async function sourceClients(mutating = false) {
  const clients = await targetClients(mutating);
  return { ...clients, sources: new SourceApiClient(clients.options) };
}

export function sourceData<T>(response: SourceApiResponse<T>): T {
  if (response.notModified)
    throw new SourceApiError(
      "INVALID_RESPONSE",
      502,
      "The source response had no content.",
    );
  return response.data;
}

export async function sourceResult<T>(
  operation: () => Promise<T>,
): Promise<
  { ok: true; data: T } | { ok: false; code: string; message: string }
> {
  try {
    return { ok: true, data: await operation() };
  } catch (error) {
    if (error instanceof SourceApiError)
      return { ok: false, code: error.code, message: error.message };
    throw error;
  }
}
