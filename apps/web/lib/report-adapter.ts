import "server-only";

import {
  PlanningApiClient,
  ReportApiClient,
  ReportApiError,
  SourceApiClient,
  type ReportApiResponse,
} from "@trading212/api-contracts";
import { targetClients } from "./target-adapter";

export async function reportClients(mutating = false) {
  const clients = await targetClients(mutating);
  return {
    ...clients,
    reports: new ReportApiClient(clients.options),
    planning: new PlanningApiClient(clients.options),
    sources: new SourceApiClient(clients.options),
  };
}

export function reportData<T>(response: ReportApiResponse<T>): T {
  if (response.notModified)
    throw new ReportApiError(
      "INVALID_RESPONSE",
      502,
      "The report response had no content.",
    );
  return response.data;
}
