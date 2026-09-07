import "server-only";

import {
  PlanningApiClient,
  PlanningApiError,
  type PlanningApiResponse,
} from "@trading212/api-contracts";

import { targetClients } from "./target-adapter";

export async function planningClients(mutating = false) {
  const clients = await targetClients(mutating);
  return { ...clients, planning: new PlanningApiClient(clients.options) };
}

export function planningData<T>(response: PlanningApiResponse<T>): T {
  if (response.notModified) {
    throw new PlanningApiError(
      "INVALID_RESPONSE",
      502,
      "The planning response had no content.",
    );
  }
  return response.data;
}
