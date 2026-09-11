import { AccountRequired, AccountView } from "./account-context";
import { resolveAccountSelection } from "../lib/account-selection";
import Link from "./navigation-intent";
import { Button, Notice, Surface } from "@trading212/ui";
import {
  PortfolioApiError,
  XrayApiError,
  type XrayEffectiveExposureResponse,
  type XrayEtfOverlapResponse,
} from "@trading212/api-contracts";
import { requireWebAccess } from "../lib/auth";
import { xrayClients, xrayData } from "../lib/xray-adapter";
import {
  readXrayQuery,
  xrayDimensions,
  xrayHref,
  xrayRunQuery,
  XrayQueryError,
  type XrayQuery,
  type XraySearch,
} from "../lib/xray-query";
import { titleCase } from "../lib/format";
import { PageHeader } from "./page-header";
import { XrayContextDetails, XrayResults, XraySummary } from "./xray-results";

async function load(
  clients: Awaited<ReturnType<typeof xrayClients>>,
  account: string,
  query: XrayQuery,
): Promise<XrayEffectiveExposureResponse | XrayEtfOverlapResponse> {
  const request = xrayRunQuery(query);
  if (query.view === "pairs" || query.view === "common_entities")
    return xrayData(
      await clients.xray.get_etf_overlap(account, {
        ...request,
        view: query.view,
        fund_ids: query.fund_ids,
        left_fund_id: query.view === "common_entities" ? query.left : undefined,
        right_fund_id:
          query.view === "common_entities" ? query.right : undefined,
      }),
    );
  return xrayData(
    await clients.xray.get_effective_exposure(account, {
      ...request,
      view: query.view,
      dimension: query.view === "held_funds" ? undefined : query.dimension,
      normalized_known_only:
        query.view === "held_funds" ? undefined : query.normalized,
      exposure_id: query.view === "paths" ? query.exposure : undefined,
    }),
  );
}

export async function XrayPage({ search }: Readonly<{ search: XraySearch }>) {
  const access = await requireWebAccess();
  const header = (
    <PageHeader
      title="Portfolio X-ray"
      description="Trace direct holdings and fund constituents to their underlying economic exposure."
    />
  );
  if (access.isDemo)
    return (
      <div className="page-stack">
        {header}
        <Notice title="X-ray requires the connected runtime">
          Sign in to the local API to inspect retained constituent sources and
          reproducible calculations.
        </Notice>
      </div>
    );
  const clients = await xrayClients();
  const accounts = await clients.portfolio.listAccounts();
  const initialAccount = resolveAccountSelection(
    accounts,
    search.account,
    process.env.T212PI_ACCOUNT_ID,
  );
  let query: XrayQuery;
  try {
    query = readXrayQuery(search, {
      now: new Date(),
      currency: initialAccount.account?.reporting_currency ?? "EUR",
    });
  } catch (error) {
    if (!(error instanceof XrayQueryError)) throw error;
    return (
      <div className="page-stack">
        {header}
        <Notice title="Invalid X-ray filters">
          {error.message}{" "}
          <Link prefetch={false} href="/xray">
            Reset filters
          </Link>
          .
        </Notice>
      </div>
    );
  }
  const accountSelection = resolveAccountSelection(
    accounts,
    search.account,
    process.env.T212PI_ACCOUNT_ID,
  );
  const account = accountSelection.account;
  if (!account) return <AccountRequired selection={accountSelection} />;
  let data: XrayEffectiveExposureResponse | XrayEtfOverlapResponse | undefined;
  let failure: string | undefined;
  try {
    const snapshot = query.snapshot
      ? await clients.portfolio.getSnapshot(account.id, query.snapshot)
      : await clients.portfolio.getLatestSnapshot(account.id);
    query = {
      ...query,
      account: account.id,
      snapshot: snapshot.id,
      currency:
        typeof search.currency === "string"
          ? query.currency
          : snapshot.reporting_currency,
    };
    data = await load(clients, account.id, query);
    query = { ...query, run: data.context.run_id };
  } catch (error) {
    if (
      !(error instanceof XrayApiError) &&
      !(error instanceof PortfolioApiError)
    )
      throw error;
    failure = error.message;
  }
  return (
    <AccountView accountId={account.id}>
      <div className="page-stack xray-page">
        {header}
        <Surface>
          <h2>Account and snapshot</h2>
          <form action="/xray" method="get" className="target-form">
            <label>
              <span>Account</span>
              <select name="account" defaultValue={account.id}>
                {accounts.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.display_name}
                  </option>
                ))}
              </select>
            </label>
            <Button type="submit" variant="secondary">
              Choose account
            </Button>
          </form>
          <p>
            Analysis account: <strong>{account.display_name}</strong>
          </p>
          <form
            action="/xray"
            method="get"
            className="target-form historical-filters"
          >
            <input type="hidden" name="account" value={account.id} />
            <label>
              <span>Snapshot ID</span>
              <input
                name="snapshot"
                defaultValue={query.snapshot}
                maxLength={36}
                required
                aria-describedby="xray-snapshot-help"
              />
            </label>
            <label>
              <span>Knowledge cutoff (UTC)</span>
              <input
                name="cutoff"
                defaultValue={query.cutoff}
                maxLength={40}
                required
              />
            </label>
            <label>
              <span>Reporting currency</span>
              <input
                name="currency"
                defaultValue={query.currency}
                minLength={3}
                maxLength={3}
                pattern="[A-Z]{3}"
                required
              />
            </label>
            <label>
              <span>Exposure dimension</span>
              <select name="dimension" defaultValue={query.dimension}>
                {xrayDimensions.map((dimension) => (
                  <option key={dimension} value={dimension}>
                    {titleCase(dimension)}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span>Weight presentation</span>
              <select name="normalized" defaultValue={String(query.normalized)}>
                <option value="false">Absolute portfolio weights</option>
                <option value="true">Also show known-only weights</option>
              </select>
            </label>
            <Button type="submit">Analyze snapshot</Button>
          </form>
          <p id="xray-snapshot-help">
            The latest authorized snapshot is selected initially. Paste an older
            snapshot ID to reproduce its exposure with an explicit source
            cutoff.
          </p>
        </Surface>
        {data ? (
          <>
            <nav className="collection-pagination" aria-label="X-ray views">
              <Link
                prefetch={false}
                aria-current={query.view === "exposures" ? "page" : undefined}
                href={xrayHref(query, { view: "exposures" })}
              >
                Effective exposure
              </Link>
              <Link
                prefetch={false}
                aria-current={query.view === "paths" ? "page" : undefined}
                href={xrayHref(query, { view: "paths", exposure: undefined })}
              >
                All exposure paths
              </Link>
              <Link
                prefetch={false}
                aria-current={query.view === "held_funds" ? "page" : undefined}
                href={xrayHref(query, { view: "held_funds" })}
              >
                Held funds and overlap
              </Link>
            </nav>
            <XraySummary summary={data.summary} />
            <XrayResults data={data} query={query} />
            <XrayContextDetails context={data.context} query={query} />
          </>
        ) : (
          <Notice title="X-ray unavailable">
            {failure ?? "The selected inputs are unavailable."}
          </Notice>
        )}
      </div>
    </AccountView>
  );
}
