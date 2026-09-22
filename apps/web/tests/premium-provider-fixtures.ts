import type { PremiumProviderStatusResponse } from "@trading212/api-contracts";
export const account = "00000000-0000-4000-8000-000000000002";
export const other = "00000000-0000-4000-8000-000000000003";
export const status: PremiumProviderStatusResponse = {
  account_id: account,
  observed_at: "2026-09-15T12:00:00Z",
  credential_verification: "unavailable",
  live_verification: "unavailable",
  providers: [
    {
      provider: "alpha_vantage",
      capabilities: (
        [
          "daily_adjusted",
          "etf_profile",
          "company_overview",
          "news_sentiment",
        ] as const
      ).map((capability) => ({
        capability,
        state: "not_configured",
        reason: "credential_configuration_required",
        canonical_publication_supported: capability !== "etf_profile",
        daily_allowance: null,
        attempts_charged: null,
        retry_at: null,
      })),
    },
    {
      provider: "ecb",
      capabilities: [
        {
          capability: "reference_fx",
          state: "ready_unverified",
          reason: "metadata_eligible_unverified",
          canonical_publication_supported: true,
          daily_allowance: 24,
          attempts_charged: 3,
          retry_at: null,
        },
      ],
    },
  ],
};
