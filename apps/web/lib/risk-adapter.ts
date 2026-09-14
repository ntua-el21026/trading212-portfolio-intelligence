import "server-only";

import {
  RiskApiClient,
  XrayApiClient,
  XrayApiError,
  PortfolioApiError,
  RiskApiError,
  HistoricalApiClient,
  SourceApiClient,
  HistoricalApiError,
  SourceApiError,
  TargetApiError,
  type RiskApiResponse,
} from "@trading212/api-contracts";
import { targetClients } from "./target-adapter";

export async function riskClients(mutating = false) {
  const clients = await targetClients(mutating);
  return {
    ...clients,
    risk: new RiskApiClient(clients.options),
    xray: new XrayApiClient(clients.options),
    historical: new HistoricalApiClient(clients.options),
    sources: new SourceApiClient(clients.options),
  };
}

export function riskData<T>(response: RiskApiResponse<T>): T {
  if (response.notModified)
    throw new RiskApiError(
      "INVALID_RESPONSE",
      502,
      "The risk response had no content.",
    );
  return response.data;
}

export function assertRiskAccount(accountId: string, expected: string) {
  if (accountId !== expected)
    throw new RiskApiError(
      "NOT_FOUND",
      404,
      "This risk resource is unavailable for the selected account.",
    );
}

export async function riskResult<T>(
  operation: () => Promise<T>,
): Promise<
  { ok: true; data: T } | { ok: false; code: string; message: string }
> {
  try {
    return { ok: true, data: await operation() };
  } catch (error) {
    if (
      error instanceof RiskApiError ||
      error instanceof XrayApiError ||
      error instanceof HistoricalApiError ||
      error instanceof SourceApiError ||
      error instanceof TargetApiError
    )
      return { ok: false, code: error.code, message: error.message };
    if (error instanceof PortfolioApiError)
      return {
        ok: false,
        code: error.code,
        message: "The portfolio snapshot is unavailable for this session.",
      };
    throw error;
  }
}
