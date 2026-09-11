import {
  AccountRequired,
  AccountSelect,
  AccountView,
} from "../../../components/account-context";
import { resolveAccountSelection } from "../../../lib/account-selection";
import Link from "../../../components/navigation-intent";
import { Button, Notice, Surface } from "@trading212/ui";
import {
  AlertApiError,
  type AlertEventPage,
  type AlertRulePage,
  type NotificationDestinationPage,
} from "@trading212/api-contracts";
import { PageHeader } from "../../../components/page-header";
import { AlertEditor } from "../../../components/alert-editor";
import { AlertQueryBoundary } from "../../../components/alert-query-boundary";
import { AlertCommandScope } from "../../../components/alert-commands";
import {
  AlertEventPanel,
  AlertRulePanel,
} from "../../../components/alert-history";
import { requireWebAccess } from "../../../lib/auth";
import { alertClients, alertData } from "../../../lib/alert-adapter";
import {
  ALERT_FAMILIES,
  ALERT_RULE_STATES,
  ALERT_SEVERITIES,
  alertHref,
  parseAlertQuery,
  type AlertQuery,
  type AlertSearch,
} from "../../../lib/alert-query";
import { formatDateTime, titleCase } from "../../../lib/format";
import styles from "../../../components/alert-view.module.css";

const description =
  "Versioned monitoring rules, inspectable evaluations and durable notification history.";
function InvalidSelection() {
  return (
    <div className="page-stack">
      <PageHeader title="Alerts" description={description} />
      <Notice title="Invalid alert selection" tone="danger">
        <Link href="/alerts">Reset alert filters</Link>
      </Notice>
    </div>
  );
}
function Failure({ error }: Readonly<{ error: unknown }>) {
  return (
    <Notice
      title={
        error instanceof AlertApiError ? error.code : "Alert data unavailable"
      }
      tone="danger"
    >
      {error instanceof AlertApiError
        ? error.message
        : "The alert read could not complete. Your filters remain in the URL for retry."}
    </Notice>
  );
}

export default async function AlertsPage({
  searchParams,
}: Readonly<{ searchParams: Promise<AlertSearch> }>) {
  const access = await requireWebAccess();
  if (access.isDemo)
    return (
      <div className="page-stack">
        <PageHeader title="Alerts" description={description} />
        <Notice title="Alerts require the connected runtime">
          Sign in to the local API to create monitoring rules and inspect actual
          evaluations.
        </Notice>
      </div>
    );
  let query: AlertQuery;
  try {
    query = parseAlertQuery(await searchParams);
  } catch {
    return <InvalidSelection />;
  }
  const scopes = access.principal.scopes;
  if (!scopes.includes("alerts:read"))
    return (
      <div className="page-stack">
        <PageHeader title="Alerts" description={description} />
        <Notice title="Alert access required">
          The current session needs alerts:read to inspect rules and history.
        </Notice>
      </div>
    );
  let content;
  try {
    content = await renderAlerts(
      query,
      scopes.includes("alerts:write") && scopes.includes("analytics:read"),
    );
  } catch (error) {
    return (
      <div className="page-stack">
        <PageHeader title="Alerts" description={description} />
        <Failure error={error} />
      </div>
    );
  }
  return (
    <AlertQueryBoundary fallback={<InvalidSelection />}>
      <AlertCommandScope
        key={`${query.account ?? "default"}:${query.view}:${query.rule ?? "new"}:${query.event ?? "none"}`}
      >
        {content}
      </AlertCommandScope>
    </AlertQueryBoundary>
  );
}

async function renderAlerts(query: AlertQuery, canWrite: boolean) {
  const clients = await alertClients();
  const accounts = await clients.portfolio.listAccounts();
  const accountSelection = resolveAccountSelection(
    accounts,
    query.account,
    process.env.T212PI_ACCOUNT_ID,
  );
  const account = accountSelection.account;
  if (!account) return <AccountRequired selection={accountSelection} />;
  const selected = { ...query, account: account.id };
  let list: AlertRulePage | AlertEventPage | undefined;
  let listError: unknown;
  try {
    list =
      query.view === "rules"
        ? alertData(
            await clients.alerts.list_alert_rules({
              account_id: account.id,
              state: query.rule_state,
              family: query.family,
              cursor: query.cursor,
              limit: query.limit ?? 25,
            }),
          )
        : alertData(
            await clients.alerts.list_alert_events({
              account_id: account.id,
              rule_id: query.rule,
              state: query.event_state,
              severity: query.severity,
              start_date: query.start_date,
              end_date: query.end_date,
              cursor: query.cursor,
              limit: query.limit ?? 25,
            }),
          );
  } catch (error) {
    listError = error;
  }
  let rule;
  let event;
  let detailError: unknown;
  try {
    if (query.view === "rules" && query.rule)
      rule = alertData(
        await clients.alerts.get_alert_rule(query.rule, {
          evaluation_cursor: query.evaluation_cursor,
          evaluation_limit: query.evaluation_limit ?? 25,
          version_cursor: query.version_cursor,
          version_limit: query.version_limit ?? 25,
        }),
      );
    if (query.view === "events" && query.event)
      event = alertData(await clients.alerts.get_alert_event(query.event));
    if (
      (rule && rule.account_id !== account.id) ||
      (event && event.account_id !== account.id)
    )
      throw new AlertApiError(
        "NOT_FOUND",
        404,
        "The selected alert belongs to another account.",
      );
  } catch (error) {
    detailError = error;
    rule = undefined;
    event = undefined;
  }
  let destinations: NotificationDestinationPage | undefined;
  let destinationError: unknown;
  if (query.view === "rules") {
    try {
      destinations = alertData(
        await clients.alerts.list_notification_destinations({
          account_id: account.id,
          cursor: query.destination_cursor,
          limit: 100,
        }),
      );
    } catch (error) {
      destinationError = error;
    }
  }
  let summary;
  let summaryError: unknown;
  try {
    summary = alertData(
      await clients.alerts.get_alert_summary(account.id, {
        state: "all",
        severity: "all",
        top_n: 5,
      }),
    );
  } catch (error) {
    summaryError = error;
  }
  return (
    <AccountView accountId={account.id}>
      <div className="page-stack">
        <PageHeader title="Alerts" description={description} />
        <Surface className={styles.surface}>
          <form
            action="/alerts"
            className={styles.form}
            aria-label="Alert filters"
          >
            <label>
              Account
              <AccountSelect label="Account" name="account" />
            </label>
            <label>
              View
              <select name="view" defaultValue={query.view}>
                <option value="rules">Rules and evaluations</option>
                <option value="events">Alert history</option>
              </select>
            </label>
            {query.view === "rules" ? (
              <>
                <label>
                  Rule state
                  <select name="rule_state" defaultValue={query.rule_state}>
                    {["all", ...ALERT_RULE_STATES].map((value) => (
                      <option key={value} value={value}>
                        {titleCase(value)}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Family filter
                  <select name="family" defaultValue={query.family}>
                    {["all", ...ALERT_FAMILIES].map((value) => (
                      <option key={value} value={value}>
                        {titleCase(value)}
                      </option>
                    ))}
                  </select>
                </label>
              </>
            ) : (
              <>
                <label>
                  Event state
                  <select name="event_state" defaultValue={query.event_state}>
                    {["all", "open", "resolved"].map((value) => (
                      <option key={value} value={value}>
                        {titleCase(value)}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Severity filter
                  <select name="severity" defaultValue={query.severity}>
                    {["all", ...ALERT_SEVERITIES].map((value) => (
                      <option key={value} value={value}>
                        {titleCase(value)}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Rule ID filter (optional)
                  <input
                    name="rule"
                    defaultValue={query.rule ?? ""}
                    maxLength={36}
                  />
                </label>
                <label>
                  History start date
                  <input
                    type="date"
                    name="start_date"
                    defaultValue={query.start_date ?? ""}
                  />
                </label>
                <label>
                  History end date
                  <input
                    type="date"
                    name="end_date"
                    defaultValue={query.end_date ?? ""}
                  />
                </label>
              </>
            )}
            <Button type="submit">Apply alert filters</Button>
          </form>
          <nav className={styles.navigation} aria-label="Alert views">
            <Link href={alertHref({ account: account.id, view: "rules" })}>
              Rules and evaluations
            </Link>
            <Link href={alertHref({ account: account.id, view: "events" })}>
              Alert history
            </Link>
            <Link href={alertHref({ account: account.id, view: "rules" })}>
              New rule
            </Link>
          </nav>
        </Surface>
        {summary ? (
          <Surface className={styles.surface}>
            <h2>Current alert summary</h2>
            <p>
              All severities and states as of{" "}
              {formatDateTime(summary.source_cutoff_at)}. Acknowledgment
              overlaps open and resolved states.
            </p>
            <dl className={styles.facts}>
              <dt>Total events</dt>
              <dd>{summary.counts.total_count}</dd>
              <dt>Open</dt>
              <dd>{summary.counts.open_count}</dd>
              <dt>Resolved</dt>
              <dd>{summary.counts.resolved_count}</dd>
              <dt>Acknowledged</dt>
              <dd>{summary.counts.acknowledged_count}</dd>
            </dl>
            <p>
              {summary.returned_count} recent events sampled;{" "}
              {summary.omitted_count} omitted from the sample. History provides
              complete pagination.
            </p>
          </Surface>
        ) : (
          <Failure error={summaryError} />
        )}
        {list ? (
          <Surface className={styles.surface}>
            <h2>{query.view === "rules" ? "Saved rules" : "Alert history"}</h2>
            {list.items.length === 0 ? (
              <Notice title="No matching records">
                No stored records match these filters. Empty history does not
                claim a successful evaluation.
              </Notice>
            ) : (
              list.items.map((item) => (
                <article className={styles.entry} key={item.id}>
                  {"latest_version" in item ? (
                    <>
                      <h3>
                        <Link
                          href={alertHref({
                            ...selected,
                            rule: item.id,
                            evaluation_cursor: undefined,
                            version_cursor: undefined,
                          })}
                        >
                          {item.latest_version.definition.name}
                        </Link>
                      </h3>
                      <p>
                        {titleCase(item.lifecycle)} ·{" "}
                        {titleCase(
                          item.latest_version.definition.predicate.metric,
                        )}{" "}
                        · latest version {item.latest_version.version_number} ·
                        active version{" "}
                        {item.active_version?.version_number ?? "none"}
                      </p>
                    </>
                  ) : (
                    <>
                      <h3>
                        <Link href={alertHref({ ...selected, event: item.id })}>
                          {titleCase(item.severity)} ·{" "}
                          {formatDateTime(item.occurred_at)}
                        </Link>
                      </h3>
                      <p>
                        {titleCase(item.episode_state)} ·{" "}
                        {item.acknowledgment
                          ? "Acknowledged"
                          : "Not acknowledged"}{" "}
                        · {titleCase(item.evaluation.outcome)} · delivery{" "}
                        {titleCase(item.delivery.notification_state)}
                      </p>
                    </>
                  )}
                </article>
              ))
            )}
            <nav
              className={styles.navigation}
              aria-label="Alert collection pagination"
            >
              <p>
                {list.items.length} records on this page / {list.total} matching
                records.
              </p>
              {list.next_cursor ? (
                <Link
                  prefetch={false}
                  href={alertHref({ ...selected, cursor: list.next_cursor })}
                >
                  Next alert page
                </Link>
              ) : (
                <p>End of collection.</p>
              )}
            </nav>
          </Surface>
        ) : (
          <Failure error={listError} />
        )}
        {detailError ? <Failure error={detailError} /> : null}
        {rule ? (
          <AlertRulePanel rule={rule} query={selected} canWrite={canWrite} />
        ) : null}
        {event ? <AlertEventPanel event={event} canWrite={canWrite} /> : null}
        {destinationError ? <Failure error={destinationError} /> : null}
        {query.view === "rules" && (!query.rule || rule) && destinations ? (
          <>
            {destinations.next_cursor ? (
              <Notice title="Destination list continues">
                Showing {destinations.items.length} of {destinations.total}{" "}
                configured destination records.{" "}
                <Link
                  href={alertHref({
                    ...selected,
                    destination_cursor: destinations.next_cursor,
                  })}
                >
                  Next destination page
                </Link>
              </Notice>
            ) : null}
            <AlertEditor
              key={`${account.id}:${rule?.latest_version.id ?? "new"}:${query.destination_cursor ?? "first"}`}
              accountId={account.id}
              rule={rule}
              destinations={destinations.items}
              now={new Date().toISOString()}
              canWrite={canWrite}
            />
          </>
        ) : null}
      </div>
    </AccountView>
  );
}
