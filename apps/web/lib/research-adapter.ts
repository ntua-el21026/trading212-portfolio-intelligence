import "server-only";
import {
  ResearchApiClient,
  ResearchApiError,
  TargetApiError,
  PortfolioApiError,
  type ResearchApiResponse,
  type ResearchItemView,
} from "@trading212/api-contracts";
import { targetClients } from "./target-adapter";

export async function researchClients(mutating = false) {
  const clients = await targetClients(mutating);
  const required = [
    "portfolio:read",
    "analytics:read",
    "research:read",
    ...(mutating ? ["research:write"] : []),
  ];
  if (
    !required.every((scope) => clients.access.principal.scopes.includes(scope))
  )
    throw new ResearchApiError(
      "ACCESS_DENIED",
      403,
      "Current research access is required.",
    );
  return { ...clients, research: new ResearchApiClient(clients.options) };
}
export function researchData<T>(response: ResearchApiResponse<T>): T {
  if (response.notModified)
    throw new ResearchApiError(
      "INVALID_RESPONSE",
      502,
      "The research response had no content.",
    );
  return response.data;
}
export function assertResearchAccount(actual: string, expected: string): void {
  if (actual !== expected)
    throw new ResearchApiError(
      "NOT_FOUND",
      404,
      "The research resource is unavailable for this account.",
    );
}
export function assertResearchItem(
  item: ResearchItemView,
  accountId: string,
): void {
  assertResearchAccount(item.portfolio.pin.account_id, accountId);
  for (const note of item.owner_revisions)
    assertResearchAccount(note.account_id, accountId);
  if (item.review) assertResearchAccount(item.review.account_id, accountId);
}
export async function researchResult<T>(
  operation: () => Promise<T>,
): Promise<
  { ok: true; data: T } | { ok: false; code: string; message: string }
> {
  try {
    return { ok: true, data: await operation() };
  } catch (error) {
    if (error instanceof ResearchApiError || error instanceof TargetApiError)
      return { ok: false, code: error.code, message: error.message };
    if (error instanceof PortfolioApiError)
      return {
        ok: false,
        code: error.code,
        message: "The selected account is unavailable.",
      };
    return {
      ok: false,
      code: "RESEARCH_UNAVAILABLE",
      message: "Research could not be loaded. Retry the current selection.",
    };
  }
}
