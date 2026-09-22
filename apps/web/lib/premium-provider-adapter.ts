import "server-only";
import {
  PremiumProviderApiClient,
  PremiumProviderApiError,
  TargetApiError,
  type PremiumProviderStatusResponse,
} from "@trading212/api-contracts";
import { targetClients } from "./target-adapter";

export type PremiumProviderStatusResult =
  | { ok: true; data: PremiumProviderStatusResponse }
  | { ok: false; code: string; message: string };

export async function loadPremiumProviderStatus(
  accountId: string,
): Promise<PremiumProviderStatusResult> {
  try {
    const clients = await targetClients();
    const response = await new PremiumProviderApiClient(
      clients.options,
    ).get_premium_provider_status(accountId);
    if (response.notModified || response.data.account_id !== accountId) {
      return {
        ok: false,
        code: "INVALID_RESPONSE",
        message: "Provider status could not be verified for this account.",
      };
    }
    return { ok: true, data: response.data };
  } catch (error) {
    if (
      error instanceof PremiumProviderApiError ||
      error instanceof TargetApiError
    ) {
      return {
        ok: false,
        code: error.code,
        message:
          error.code === "ACCESS_DENIED"
            ? "Provider status requires current access to this account and analytics."
            : "Provider status is currently unavailable.",
      };
    }
    throw error;
  }
}
