import "server-only";

import {
  HistoricalApiClient,
  HistoricalApiError,
  SourceApiClient,
  SourceApiError,
  TargetApiError,
  type HistoricalApiResponse,
} from "@trading212/api-contracts";
import { targetClients } from "./target-adapter";
import type { HistoricalQuery } from "./historical-query";

export async function historicalClients() {
  const clients = await targetClients();
  return {
    ...clients,
    historical: new HistoricalApiClient(clients.options),
    sources: new SourceApiClient(clients.options),
  };
}

export function historicalData<T>(response: HistoricalApiResponse<T>): T {
  if (response.notModified) {
    throw new HistoricalApiError(
      "INVALID_RESPONSE",
      502,
      "The historical response had no content.",
    );
  }
  return response.data;
}

export async function historicalResult<T>(
  operation: () => Promise<T>,
): Promise<
  { ok: true; data: T } | { ok: false; code: string; message: string }
> {
  try {
    return { ok: true, data: await operation() };
  } catch (error) {
    if (
      error instanceof HistoricalApiError ||
      error instanceof SourceApiError ||
      error instanceof TargetApiError
    ) {
      return { ok: false, code: error.code, message: error.message };
    }
    throw error;
  }
}

export function historicalWindow(query: HistoricalQuery) {
  return {
    start_date: query.start,
    end_date: query.end,
    source_cutoff_at: query.cutoff,
    reporting_currency: query.currency,
    coverage_policy: query.coverage,
    knowledge_policy: query.knowledge,
    input_snapshot_id: query.capture,
  };
}

export function performanceOptions(query: HistoricalQuery) {
  return {
    ...historicalWindow(query),
    method: query.method,
    frequency: query.frequency,
    rolling_window: query.rolling,
    calendar_period: query.calendar,
  };
}
