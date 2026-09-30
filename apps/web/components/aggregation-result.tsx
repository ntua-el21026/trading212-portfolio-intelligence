import { Notice, Surface } from "@trading212/ui";
import type {
  Account,
  AggregateMoney,
  AggregateRunResponse,
} from "@trading212/api-contracts";
import type { AggregationQuery } from "../lib/aggregation-query";
import { aggregationHref } from "../lib/aggregation-query";
import { formatDateTime, formatMoney, formatDecimal } from "../lib/format";
import Link from "./navigation-intent";
import styles from "./aggregation.module.css";
function Money({ value }: Readonly<{ value: AggregateMoney }>) {
  return (
    <div
      data-money-value={value.value ?? "unavailable"}
      data-currency={value.currency}
    >
      <strong title={value.value ?? undefined}>
        {value.currency} {formatMoney(value.value)}
      </strong>
      {value.value === null ? (
        <p title={value.known_value}>
          Known subtotal: {value.currency} {formatMoney(value.known_value)}
        </p>
      ) : null}
      <p>
        {value.known_count} of {value.total_count} components covered ·{" "}
        {value.quality.replaceAll("_", " ")}
      </p>
      {value.reason ? <p>{value.reason.replaceAll("_", " ")}</p> : null}
    </div>
  );
}
export function AggregateResult({
  value,
  query,
  accounts,
  canReadActivity,
}: Readonly<{
  value: AggregateRunResponse;
  query: AggregationQuery;
  accounts: readonly Account[];
  canReadActivity: boolean;
}>) {
  const page = value.page;
  const name = (id: string) =>
    accounts.find((account) => account.id === id)?.display_name ?? id;
  if (!page)
    return (
      <Notice title="Aggregate expired">
        The financial copy is unavailable. Create a new calculation from
        currently permitted sources.
      </Notice>
    );
  return (
    <div className={styles.stack}>
      <nav className={styles.toolbar} aria-label="Aggregate result views">
        {(
          [
            "holdings",
            "components",
            "accounts",
            ...(canReadActivity ? ["transfers"] : []),
          ] as const
        ).map((table) => (
          <Link
            key={table}
            prefetch={false}
            aria-current={page.view === table ? "page" : undefined}
            href={aggregationHref({
              ...query,
              table: table as AggregationQuery["table"],
              cursor: undefined,
            })}
          >
            {table[0].toUpperCase() + table.slice(1)}
          </Link>
        ))}
      </nav>
      {page.view !== "transfers" ? (
        <>
          <div className="metric-grid">
            <Surface>
              <h2>Total value</h2>
              <Money value={page.context.total} />
            </Surface>
            <Surface>
              <h2>Securities</h2>
              <Money value={page.context.securities} />
            </Surface>
            <Surface>
              <h2>Cash</h2>
              <Money value={page.context.cash} />
            </Surface>
          </div>
          <Surface>
            <h2>Original valuation context</h2>
            <p>
              Source cutoff: {formatDateTime(page.context.source_cutoff_at)}.
              Values retain each account’s original valuation date.
            </p>
            <div className={styles.table}>
              <table>
                <caption>Included saved snapshots</caption>
                <thead>
                  <tr>
                    <th>Account</th>
                    <th>Valued at</th>
                    <th>Known at</th>
                    <th>Currency</th>
                    <th>Quality</th>
                  </tr>
                </thead>
                <tbody>
                  {page.context.snapshots.map((pin) => (
                    <tr key={pin.account_id}>
                      <th scope="row">{name(pin.account_id)}</th>
                      <td>{formatDateTime(pin.valuation_at)}</td>
                      <td>{formatDateTime(pin.source_cutoff_at)}</td>
                      <td>{pin.reporting_currency}</td>
                      <td>{pin.quality}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <details className={styles.proof}>
              <summary>Calculation and source provenance</summary>
              <p>
                Method: {page.context.method} {page.context.method_version}.
                Numeric profile: {page.context.numeric_profile}.
              </p>
              <p>Input digest: {page.context.input_digest}</p>
              <p>Result digest: {page.context.result_digest}</p>
              <p>
                Rounding residual:{" "}
                {page.context.rounding_residual ?? "Unavailable"}{" "}
                {page.context.reporting_currency}
              </p>
              <ul>
                {page.context.snapshots.map((pin) => (
                  <li key={pin.account_id}>
                    {name(pin.account_id)}: snapshot {pin.portfolio_snapshot_id}
                    , calculation {pin.calculation_run_id} (
                    {pin.calculation_version}), content {pin.content_digest}
                  </li>
                ))}
              </ul>
            </details>
          </Surface>
        </>
      ) : (
        <Surface>
          <h2>Transfer coverage</h2>
          <p>
            {page.complete
              ? "Complete declared window coverage"
              : "Incomplete or unrequested window coverage"}{" "}
            · {page.selected_count} selected records from {page.candidate_count}{" "}
            candidates.
          </p>
          {page.window ? (
            <p>
              {formatDateTime(page.window.start_at)} to{" "}
              {formatDateTime(page.window.end_at)}
            </p>
          ) : (
            <p>Activity was not requested for this calculation.</p>
          )}
          <ul>
            {page.reasons.map((reason) => (
              <li key={reason}>{reason.replaceAll("_", " ")}</li>
            ))}
          </ul>
          <p>
            Matching transfer legs alone does not establish complete activity
            coverage or portfolio performance.
          </p>
          {page.currency_totals.length ? (
            <div className={styles.table}>
              <table>
                <caption>Original currency flow totals</caption>
                <thead>
                  <tr>
                    <th>Currency</th>
                    <th>External net</th>
                    <th>Fees</th>
                  </tr>
                </thead>
                <tbody>
                  {page.currency_totals.map((row) => (
                    <tr key={row.currency}>
                      <th scope="row">{row.currency}</th>
                      <td title={row.external_net}>
                        {formatMoney(row.external_net)}
                      </td>
                      <td title={row.fees}>{formatMoney(row.fees)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
          <details className={styles.proof}>
            <summary>Transfer provenance</summary>
            <p>Holdings input: {page.holdings_input_digest}</p>
            <p>Activity input: {page.input_digest ?? "Not requested"}</p>
            <p>Activity result: {page.result_digest ?? "Not requested"}</p>
          </details>
        </Surface>
      )}
      <Surface>
        <h2>{page.view[0].toUpperCase() + page.view.slice(1)}</h2>
        {!page.items.length ? (
          <p>No rows on this page.</p>
        ) : page.view === "holdings" ? (
          <div className={styles.table}>
            <table>
              <caption>
                Consolidated instruments with distinct account contributions
              </caption>
              <thead>
                <tr>
                  <th>Canonical instrument</th>
                  <th>Quantity</th>
                  <th>Reporting value</th>
                  <th>Accounts</th>
                </tr>
              </thead>
              <tbody>
                {page.items.map((row) => (
                  <tr key={row.instrument_id}>
                    <th scope="row" className={styles.proof}>
                      {row.instrument_id}
                    </th>
                    <td title={row.quantity}>
                      {formatDecimal(row.quantity, 6)}
                    </td>
                    <td>
                      <Money value={row.money} />
                    </td>
                    <td>
                      {row.account_totals.map((part) => (
                        <div key={part.account_id}>
                          <strong>{name(part.account_id)}</strong>
                          <Money value={part.money} />
                        </div>
                      ))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : page.view === "components" ? (
          <div className={styles.table}>
            <table>
              <caption>
                Original holdings and cash with explicit conversion
              </caption>
              <thead>
                <tr>
                  <th>Account / component</th>
                  <th>Original value</th>
                  <th>Reporting value</th>
                  <th>Conversion and provenance</th>
                </tr>
              </thead>
              <tbody>
                {page.items.map((row) => (
                  <tr key={row.native.component_id}>
                    <th scope="row">
                      {name(row.native.account_id)}
                      <p>{row.native.kind}</p>
                    </th>
                    <td title={row.native.native_value ?? undefined}>
                      {row.native.native_currency}{" "}
                      {formatMoney(row.native.native_value)}
                    </td>
                    <td title={row.converted_value ?? undefined}>
                      {row.reporting_currency}{" "}
                      {formatMoney(row.converted_value)}
                      <p>
                        {row.quality} {row.reason?.replaceAll("_", " ")}
                      </p>
                    </td>
                    <td>
                      <p>
                        {row.fx_observation_id
                          ? row.inverted
                            ? "Inverse saved FX quote"
                            : "Direct saved FX quote"
                          : row.native.native_currency ===
                              row.reporting_currency
                            ? "Same currency"
                            : "FX unavailable"}
                      </p>
                      <details className={styles.proof}>
                        <summary>Original source identities</summary>
                        <p>Snapshot: {row.native.portfolio_snapshot_id}</p>
                        <p>
                          Instrument: {row.native.instrument_id ?? "Cash"};
                          listing: {row.native.listing_id ?? "Unavailable"}
                        </p>
                        <p>
                          Quantity: {row.native.quantity ?? "Not applicable"};
                          origin: {row.native.origin}
                        </p>
                        <p>FX observation: {row.fx_observation_id ?? "None"}</p>
                        <ul>
                          {row.native.source_record_ids.map((id) => (
                            <li key={id}>{id}</li>
                          ))}
                        </ul>
                      </details>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : page.view === "accounts" ? (
          <div className={styles.table}>
            <table>
              <caption>Whole account totals</caption>
              <thead>
                <tr>
                  <th>Account</th>
                  <th>Reporting value and coverage</th>
                </tr>
              </thead>
              <tbody>
                {page.items.map((row) => (
                  <tr key={row.account_id}>
                    <th scope="row">{name(row.account_id)}</th>
                    <td>
                      <Money value={row.money} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className={styles.table}>
            <table>
              <caption>Actual transfer and external-flow evidence</caption>
              <thead>
                <tr>
                  <th>Account / time</th>
                  <th>Original amount</th>
                  <th>Classification</th>
                  <th>Evidence</th>
                </tr>
              </thead>
              <tbody>
                {page.items.map(({ leg, match }) => (
                  <tr key={leg.source_record_id}>
                    <th scope="row">
                      {name(leg.account_id)}
                      <p>{formatDateTime(leg.occurred_at)}</p>
                    </th>
                    <td title={leg.amount ?? undefined}>
                      {leg.currency ?? "Currency unavailable"}{" "}
                      {formatMoney(leg.amount)}
                    </td>
                    <td>
                      {leg.classification.replaceAll("_", " ")}
                      <p>{leg.reason?.replaceAll("_", " ")}</p>
                    </td>
                    <td>
                      {match ? (
                        <p>
                          {name(match.outgoing_account_id)} →{" "}
                          {name(match.incoming_account_id)}. Reference:{" "}
                          {match.transfer_reference}
                        </p>
                      ) : (
                        <p>No proven internal match.</p>
                      )}
                      <details className={styles.proof}>
                        <summary>Original transfer proof</summary>
                        <p>
                          Source: {leg.source_record_id}; counterpart:{" "}
                          {leg.counterpart_record_id ?? "Unavailable"}
                        </p>
                        {match ? (
                          <>
                            <p>
                              Outgoing: {match.outgoing_currency}{" "}
                              {match.outgoing_principal}; incoming:{" "}
                              {match.incoming_currency}{" "}
                              {match.incoming_principal}.
                            </p>
                            <p>
                              FX:{" "}
                              {match.fx_rate ?? "Same currency / unavailable"}{" "}
                              {match.fx_base_currency ?? ""}/
                              {match.fx_quote_currency ?? ""}
                            </p>
                            <p>
                              Outgoing record: {match.outgoing_record_id};
                              incoming record: {match.incoming_record_id}.
                            </p>
                            <ul>
                              {match.fee_record_ids.map((id) => (
                                <li key={id}>Fee record: {id}</li>
                              ))}
                            </ul>
                          </>
                        ) : null}
                      </details>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p>
          {page.items.length} rows shown · {page.total} total rows.
        </p>
        {page.next_cursor ? (
          <Link
            prefetch={false}
            href={aggregationHref({ ...query, cursor: page.next_cursor })}
          >
            Next result page
          </Link>
        ) : null}
      </Surface>
    </div>
  );
}
