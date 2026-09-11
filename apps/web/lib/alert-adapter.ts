import "server-only";

import {
  AlertApiClient,
  AlertApiError,
  type AlertApiResponse,
} from "@trading212/api-contracts";

import { targetClients } from "./target-adapter";

export async function alertClients(mutating = false) {
  const clients = await targetClients(mutating);
  return { ...clients, alerts: new AlertApiClient(clients.options) };
}

export function alertData<T>(response: AlertApiResponse<T>): T {
  if (response.notModified)
    throw new AlertApiError(
      "INVALID_RESPONSE",
      502,
      "The alert response had no content.",
    );
  return response.data;
}
