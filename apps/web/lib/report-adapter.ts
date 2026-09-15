import "server-only";

import {
  PlanningApiClient,
  ReportApiClient,
  PremiumReportApiClient,
  RiskApiClient,
  ScenarioApiClient,
  ProjectionApiClient,
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
    premiumReports: new PremiumReportApiClient(clients.options),
    premiumReportsV3: new PremiumReportApiClient({
      ...clients.options,
      profile: "report_sections_v3",
    }),
    premiumReportsV4: new PremiumReportApiClient({
      ...clients.options,
      profile: "report_sections_v4",
    }),
    projections: new ProjectionApiClient(clients.options),
    scenarios: new ScenarioApiClient(clients.options),
    risk: new RiskApiClient(clients.options),
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
