import {
  AccountRequired,
  AccountView,
} from "../../../components/account-context";
import { loadSelectedAccount } from "../../../lib/api-adapter";
import {
  Database,
  KeyRound,
  LockKeyhole,
  Server,
  UserRound,
} from "lucide-react";

import { Notice, StatusPill, Surface } from "@trading212/ui";

import Link from "../../../components/navigation-intent";
import { PwaSettings } from "../../../components/pwa-settings";
import { PremiumProviderStatusCard } from "../../../components/premium-provider-status";
import { loadPremiumProviderStatus } from "../../../lib/premium-provider-adapter";
import { PageHeader } from "../../../components/page-header";
import { loadSettings } from "../../../lib/api-adapter";
import { requireWebAccess } from "../../../lib/auth";
import { formatDateTime, titleCase } from "../../../lib/format";

export default async function SettingsPage({
  searchParams,
}: Readonly<{ searchParams: Promise<{ account?: string | string[] }> }>) {
  const params = await searchParams;
  const access = await requireWebAccess();
  const layoutsCard = access.principal.scopes.includes("preferences:read") ? (
    <Surface className="settings-card" compact>
      <h2>Saved layouts</h2>
      <p>
        Save owner templates, current portfolio previews and exact owned views.
      </p>
      <Link prefetch={false} href="/settings/layouts">
        Manage saved layouts
      </Link>
    </Surface>
  ) : null;
  if (!access.principal.scopes.includes("portfolio:read"))
    return (
      <div className="page-stack">
        <PageHeader
          title="Settings"
          description="Manage your owner preferences."
        />
        {layoutsCard}
        <Notice title="Portfolio access required">
          Connection settings require current portfolio access.
        </Notice>
      </div>
    );
  const accountSelection = await loadSelectedAccount(params.account);
  if (!accountSelection.account)
    return (
      <div className="page-stack">
        {layoutsCard}
        <AccountRequired selection={accountSelection} />
      </div>
    );
  const selectedAccountId = accountSelection.account.id;
  const [bundle, providers] = await Promise.all([
    loadSettings(selectedAccountId),
    loadPremiumProviderStatus(selectedAccountId),
  ]);
  const account = bundle.summary.account;
  return (
    <AccountView accountId={selectedAccountId}>
      <div className="page-stack">
        <PageHeader
          description="Inspect account scope and connection posture. Broker secrets are never exposed here."
          title="Connection & settings"
        />
        <div className="settings-grid">
          <PwaSettings />
          {layoutsCard}
          <PremiumProviderStatusCard
            accountId={selectedAccountId}
            result={providers}
          />
          <Surface className="settings-card" compact>
            <h2>
              <UserRound aria-hidden="true" size={19} /> Access
            </h2>
            <dl className="settings-list">
              <div>
                <dt>Principal</dt>
                <dd>{access.principal.principal_id}</dd>
              </div>
              <div>
                <dt>Owner scope</dt>
                <dd>{access.principal.owner_id}</dd>
              </div>
              <div>
                <dt>Permissions</dt>
                <dd>{access.principal.scopes.join(", ")}</dd>
              </div>
            </dl>
          </Surface>
          <Surface className="settings-card" compact>
            <h2>
              <Database aria-hidden="true" size={19} /> Portfolio account
            </h2>
            <dl className="settings-list">
              <div>
                <dt>Name</dt>
                <dd>{account.display_name}</dd>
              </div>
              <div>
                <dt>Provider</dt>
                <dd>{titleCase(account.provider)}</dd>
              </div>
              <div>
                <dt>Environment</dt>
                <dd>{titleCase(account.environment)}</dd>
              </div>
              <div>
                <dt>Last refresh</dt>
                <dd>
                  {account.last_refresh_at
                    ? formatDateTime(account.last_refresh_at)
                    : "Never"}
                </dd>
              </div>
            </dl>
          </Surface>
          <Surface className="settings-card" compact>
            <h2>
              <Server aria-hidden="true" size={19} /> Connection posture
            </h2>
            {bundle.connections.length === 0 ? (
              <p className="settings-copy">
                No broker connection is configured.
              </p>
            ) : (
              bundle.connections.map((connection) => (
                <div className="connection-status" key={connection.id}>
                  <StatusPill
                    tone={
                      ["active", "connected", "connected_read_only"].includes(
                        connection.state,
                      )
                        ? "positive"
                        : "warning"
                    }
                  >
                    {titleCase(connection.state)}
                  </StatusPill>
                  <dl className="settings-list">
                    <div>
                      <dt>Provider</dt>
                      <dd>{titleCase(connection.provider)}</dd>
                    </div>
                    <div>
                      <dt>Environment</dt>
                      <dd>{titleCase(connection.environment)}</dd>
                    </div>
                    <div>
                      <dt>Access</dt>
                      <dd>
                        {connection.read_only ? "Read-only" : "Unavailable"}
                      </dd>
                    </div>
                    <div>
                      <dt>Credential state</dt>
                      <dd>{titleCase(connection.credential_state)}</dd>
                    </div>
                    <div>
                      <dt>Last successful refresh</dt>
                      <dd>
                        {connection.last_successful_refresh_at
                          ? formatDateTime(
                              connection.last_successful_refresh_at,
                            )
                          : "Never"}
                      </dd>
                    </div>
                  </dl>
                </div>
              ))
            )}
            <p className="settings-copy">
              The browser receives canonical portfolio responses only. Provider
              credentials remain behind the server-side adapter boundary.
            </p>
          </Surface>
          <Surface className="settings-card" compact>
            <h2>
              <KeyRound aria-hidden="true" size={19} /> Session
            </h2>
            <p className="settings-copy">
              This session is account-scoped and read-only. Sign out when you
              finish using this private workspace.
            </p>
            <form action="/api/auth/sign-out" method="post">
              <button className="sign-out-button" type="submit">
                Sign out
              </button>
            </form>
          </Surface>
        </div>
        <Notice title="Strictly read-only" tone="info">
          <p>
            <LockKeyhole aria-hidden="true" size={16} /> No order placement,
            cancellation, amendment, transfer, or other broker mutation is
            available in this product.
          </p>
        </Notice>
      </div>
    </AccountView>
  );
}
