import { Surface, StatusPill } from "@trading212/ui";
import type { PremiumProviderStatusResponse } from "@trading212/api-contracts";
type Capability =
  PremiumProviderStatusResponse["providers"][number]["capabilities"][number];
import type { PremiumProviderStatusResult } from "../lib/premium-provider-adapter";
import { formatDateTime } from "../lib/format";

const capabilities: Record<Capability["capability"], string> = {
  daily_adjusted: "Daily prices",
  etf_profile: "ETF profile",
  company_overview: "Company overview",
  news_sentiment: "News",
  reference_fx: "Reference FX",
};
const states: Record<Capability["state"], string> = {
  not_configured: "Not configured",
  blocked_external: "External requirements missing",
  ready_unverified: "Eligible, unverified",
  degraded: "Temporarily limited",
  unavailable: "Unavailable",
};
const reasons: Record<Capability["reason"], string> = {
  outbound_disabled: "Provider acquisition is disabled.",
  provider_configuration_required: "Provider configuration is required.",
  credential_configuration_required:
    "A credential port must be configured. No credential has been checked.",
  capability_rights_required:
    "Explicit current storage and display rights are required.",
  research_scope_required: "Current research read permission is required.",
  acquisition_policy_required:
    "A current enabled acquisition policy is required.",
  canonical_metadata_unavailable:
    "Compatible canonical source metadata is unavailable.",
  metadata_eligible_unverified:
    "Current metadata permits configuration readiness. Credentials and live access have not been verified.",
  daily_allowance_exhausted:
    "The owner/provider daily allowance has been used.",
  provider_attempt_in_flight: "A provider attempt is already in flight.",
};

export function PremiumProviderStatusCard({
  accountId,
  result,
}: Readonly<{ accountId: string; result: PremiumProviderStatusResult }>) {
  const value =
    result.ok && result.data.account_id === accountId ? result.data : null;
  return (
    <Surface className="settings-card" compact>
      <h2>Premium provider status</h2>
      {!value ? (
        <p className="settings-copy" role="status">
          {result.ok
            ? "Provider status could not be verified for this account."
            : result.message}
        </p>
      ) : (
        <>
          <p className="settings-copy">
            Configuration presence does not verify a credential. Live access and
            credentials remain unverified; this view makes no provider request.
          </p>
          {value.providers.map((provider) => (
            <section
              key={provider.provider}
              aria-label={
                provider.provider === "ecb"
                  ? "ECB capabilities"
                  : "Alpha Vantage capabilities"
              }
            >
              <h3>{provider.provider === "ecb" ? "ECB" : "Alpha Vantage"}</h3>
              <dl className="settings-list">
                {provider.capabilities.map((capability) => (
                  <div key={capability.capability}>
                    <dt>{capabilities[capability.capability]}</dt>
                    <dd>
                      <StatusPill
                        tone={
                          capability.state === "unavailable"
                            ? "neutral"
                            : "warning"
                        }
                      >
                        {states[capability.state]}
                      </StatusPill>
                      <p>{reasons[capability.reason]}</p>
                      {capability.daily_allowance !== null &&
                      capability.attempts_charged !== null ? (
                        <p>
                          {capability.attempts_charged} of{" "}
                          {capability.daily_allowance} owner/provider attempts
                          charged today (UTC).
                        </p>
                      ) : null}
                      {capability.retry_at ? (
                        <p>
                          Next eligible check:{" "}
                          {formatDateTime(capability.retry_at)}
                        </p>
                      ) : null}
                      {!capability.canonical_publication_supported ? (
                        <p>
                          Canonical constituent publication is unavailable
                          without additional identity and currency evidence.
                        </p>
                      ) : null}
                    </dd>
                  </div>
                ))}
              </dl>
            </section>
          ))}
          <p className="settings-copy">
            Status observed {formatDateTime(value.observed_at)}. Reopening this
            page checks current access again.
          </p>
        </>
      )}
    </Surface>
  );
}
