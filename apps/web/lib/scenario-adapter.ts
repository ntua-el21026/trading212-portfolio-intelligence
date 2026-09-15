import "server-only";
import {
  ScenarioApiClient,
  ScenarioApiError,
  XrayApiClient,
  XrayApiError,
  PortfolioApiError,
  TargetApiError,
  type ScenarioApiResponse,
  type CreateScenarioRunRequest,
} from "@trading212/api-contracts";
import { targetClients } from "./target-adapter";
import { xrayData } from "./xray-adapter";

export async function scenarioClients(mutating = false) {
  const clients = await targetClients(mutating);
  return {
    ...clients,
    scenarios: new ScenarioApiClient(clients.options),
    xray: new XrayApiClient(clients.options),
  };
}
export function scenarioData<T>(response: ScenarioApiResponse<T>): T {
  if (response.notModified)
    throw new ScenarioApiError(
      "INVALID_RESPONSE",
      502,
      "The scenario response had no content.",
    );
  return response.data;
}
export function assertScenarioAccount(actual: string, expected: string) {
  if (actual !== expected)
    throw new ScenarioApiError(
      "NOT_FOUND",
      404,
      "This scenario resource is unavailable for the selected account.",
    );
}
export async function savedScenarioXray(
  clients: Awaited<ReturnType<typeof scenarioClients>>,
  account: string,
  body: CreateScenarioRunRequest,
) {
  const result = xrayData(
    await clients.xray.get_effective_exposure(account, {
      run_id: body.xray_run_id,
      snapshot_id: body.portfolio_snapshot_id,
      source_cutoff_at: body.source_cutoff_at,
      reporting_currency: body.reporting_currency,
      dimension: "company",
      limit: 1,
    }),
  );
  assertScenarioAccount(result.context.account_id, account);
  if (
    result.context.run_id !== body.xray_run_id ||
    result.context.snapshot_id !== body.portfolio_snapshot_id ||
    result.context.reporting_currency !== body.reporting_currency
  )
    throw new ScenarioApiError(
      "CONFLICT",
      409,
      "The saved X-ray does not match the selected pins.",
    );
  // The saved-run endpoint validates the exact cutoff before loading its result.
  return result.context;
}
export async function scenarioResult<T>(
  operation: () => Promise<T>,
): Promise<
  { ok: true; data: T } | { ok: false; code: string; message: string }
> {
  try {
    return { ok: true, data: await operation() };
  } catch (error) {
    if (
      error instanceof ScenarioApiError ||
      error instanceof XrayApiError ||
      error instanceof TargetApiError
    )
      return { ok: false, code: error.code, message: error.message };
    if (error instanceof PortfolioApiError)
      return {
        ok: false,
        code: error.code,
        message: "The selected portfolio snapshot is unavailable.",
      };
    throw error;
  }
}
