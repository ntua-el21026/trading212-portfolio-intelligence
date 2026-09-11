import {
  AccountRequired,
  AccountView,
} from "../../../components/account-context";
import { loadSelectedAccount } from "../../../lib/api-adapter";
import { CheckCircle2, Clock3, RefreshCw } from "lucide-react";

import { Surface } from "@trading212/ui";

import { PageHeader } from "../../../components/page-header";
import { QualityStatus } from "../../../components/financial";
import { RefreshControl } from "../../../components/refresh-control";
import { loadSynchronization } from "../../../lib/api-adapter";
import { formatDateTime } from "../../../lib/format";
import { isExplicitDemoMode } from "../../../lib/runtime";

export default async function SynchronizationPage({
  searchParams,
}: Readonly<{ searchParams: Promise<{ account?: string | string[] }> }>) {
  const params = await searchParams;
  const accountSelection = await loadSelectedAccount(params.account);
  if (!accountSelection.account)
    return <AccountRequired selection={accountSelection} />;
  const selectedAccountId = accountSelection.account.id;
  const bundle = await loadSynchronization(selectedAccountId);
  const lastRefresh = bundle.summary.account.last_refresh_at;
  return (
    <AccountView accountId={selectedAccountId}>
      <div className="page-stack">
        <PageHeader
          description="Start a bounded read-only ingestion run and inspect its declared coverage."
          title="Synchronization"
        />
        <div className="sync-layout">
          <Surface className="sync-command" compact>
            <span className="feature-icon">
              <RefreshCw aria-hidden="true" size={22} />
            </span>
            <div>
              <h2>Portfolio synchronization</h2>
              <p>
                Reads the allowlisted account, position, transaction, and
                dividend capabilities. It cannot invoke broker write operations.
              </p>
            </div>
            <RefreshControl
              accountId={selectedAccountId}
              demo={isExplicitDemoMode()}
            />
          </Surface>
          <Surface className="sync-status" compact>
            <h2>Current status</h2>
            <dl className="settings-list">
              <div>
                <dt>
                  <CheckCircle2 aria-hidden="true" size={17} /> Connection
                </dt>
                <dd>
                  {bundle.summary.account.connection_state.replaceAll("_", " ")}
                </dd>
              </div>
              <div>
                <dt>
                  <Clock3 aria-hidden="true" size={17} /> Last completed
                </dt>
                <dd>
                  {lastRefresh
                    ? formatDateTime(lastRefresh)
                    : "Not yet synchronized"}
                </dd>
              </div>
              <div>
                <dt>Aggregate quality</dt>
                <dd>
                  <QualityStatus quality={bundle.quality} />
                </dd>
              </div>
            </dl>
          </Surface>
        </div>
      </div>
    </AccountView>
  );
}
