import { NumberValue } from "./number-value";
import Link from "./navigation-intent";

import { accountHref } from "../lib/account-selection";

import type {
  ActivityResponse,
  DividendResponse,
  PositionResponse,
  SnapshotResponse,
} from "../lib/contracts";
import {
  formatDate,
  formatDateTime,
  formatPercent,
  titleCase,
} from "../lib/format";
import { MoneyValue, QualityStatus } from "./financial";

export function PositionsTable({
  positions,
  accountId,
}: Readonly<{ positions: PositionResponse[]; accountId: string }>) {
  return (
    <div
      className="table-scroll"
      role="region"
      aria-label="Direct portfolio holdings"
      tabIndex={0}
    >
      <table className="data-table data-table--roomy">
        <caption className="ui-visually-hidden">
          Direct portfolio holdings
        </caption>
        <thead>
          <tr>
            <th scope="col">Instrument</th>
            <th scope="col">Type</th>
            <th scope="col">Quantity</th>
            <th scope="col">Price</th>
            <th scope="col">Cost basis</th>
            <th scope="col">Market value</th>
            <th scope="col">Unrealized P/L</th>
            <th scope="col">Weight</th>
          </tr>
        </thead>
        <tbody>
          {positions.map((position) => (
            <tr key={position.id}>
              <th scope="row">
                <Link
                  href={accountHref(
                    `/holdings/${encodeURIComponent(position.id)}`,
                    accountId,
                  )}
                >
                  <strong>{position.ticker}</strong>
                  <span>{position.name}</span>
                </Link>
              </th>
              <td>{titleCase(position.instrument_type)}</td>
              <td>
                <NumberValue value={position.quantity} minimumDigits={0} />
              </td>
              <td>
                {position.current_price === null ? (
                  "Unavailable"
                ) : (
                  <NumberValue
                    value={position.current_price}
                    unit={position.trading_currency}
                  />
                )}
              </td>
              <td>
                <MoneyValue
                  metric={position.provider_cost_basis}
                  showCurrency
                />
              </td>
              <td>
                <MoneyValue metric={position.market_value} showCurrency />
              </td>
              <td>
                <MoneyValue
                  metric={position.provider_unrealized_profit_loss}
                  showCurrency
                />
              </td>
              <td>
                <span
                  title={`Canonical ratio: ${position.direct_weight ?? "Unavailable"}`}
                >
                  {formatPercent(position.direct_weight)}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ActivityTable({
  activity,
}: Readonly<{ activity: ActivityResponse[] }>) {
  return (
    <div
      className="table-scroll"
      role="region"
      aria-label="Canonical portfolio activity"
      tabIndex={0}
    >
      <table className="data-table data-table--roomy">
        <caption className="ui-visually-hidden">
          Canonical portfolio activity
        </caption>
        <thead>
          <tr>
            <th scope="col">Date</th>
            <th scope="col">Activity</th>
            <th scope="col">Instrument</th>
            <th scope="col">Direction</th>
            <th scope="col">Quantity</th>
            <th scope="col">Amount</th>
            <th scope="col">Quality</th>
          </tr>
        </thead>
        <tbody>
          {activity.map((item) => (
            <tr key={item.id}>
              <td>{formatDateTime(item.occurred_at)}</td>
              <th scope="row">
                <strong>{item.description}</strong>
                <span>{titleCase(item.activity_type)}</span>
              </th>
              <td>{item.ticker ?? "—"}</td>
              <td>{titleCase(item.direction)}</td>
              <td>
                {item.quantity === null ? (
                  "Unavailable"
                ) : (
                  <NumberValue value={item.quantity} minimumDigits={0} />
                )}
              </td>
              <td>
                <MoneyValue metric={item.amount} showCurrency />
              </td>
              <td>
                <QualityStatus quality={item.data_quality} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function DividendsTable({
  dividends,
}: Readonly<{ dividends: DividendResponse[] }>) {
  return (
    <div
      className="table-scroll"
      role="region"
      aria-label="Canonical dividend records"
      tabIndex={0}
    >
      <table className="data-table data-table--roomy">
        <caption className="ui-visually-hidden">
          Canonical dividend records
        </caption>
        <thead>
          <tr>
            <th scope="col">Paid on</th>
            <th scope="col">Instrument</th>
            <th scope="col">Quantity</th>
            <th scope="col">Gross</th>
            <th scope="col">Withholding tax</th>
            <th scope="col">Net received</th>
            <th scope="col">Quality</th>
          </tr>
        </thead>
        <tbody>
          {dividends.map((item) => (
            <tr key={item.id}>
              <td>{formatDate(item.paid_on)}</td>
              <th scope="row">{item.ticker}</th>
              <td>
                {item.quantity === null ? (
                  "Unavailable"
                ) : (
                  <NumberValue value={item.quantity} minimumDigits={0} />
                )}
              </td>
              <td>
                <MoneyValue metric={item.gross_amount} showCurrency />
              </td>
              <td>
                <MoneyValue metric={item.withholding_tax} showCurrency />
              </td>
              <td>
                <MoneyValue metric={item.net_amount} showCurrency />
              </td>
              <td>
                <QualityStatus quality={item.data_quality} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function SnapshotsTable({
  snapshots,
}: Readonly<{ snapshots: SnapshotResponse[] }>) {
  return (
    <div
      className="table-scroll"
      role="region"
      aria-label="Immutable portfolio snapshots"
      tabIndex={0}
    >
      <table className="data-table data-table--roomy">
        <caption className="ui-visually-hidden">
          Immutable portfolio snapshots
        </caption>
        <thead>
          <tr>
            <th scope="col">Valuation time</th>
            <th scope="col">Source cutoff</th>
            <th scope="col">Total value</th>
            <th scope="col">Cash</th>
            <th scope="col">Invested</th>
            <th scope="col">Net contributions</th>
            <th scope="col">Quality</th>
          </tr>
        </thead>
        <tbody>
          {snapshots.map((snapshot) => (
            <tr key={snapshot.id}>
              <th scope="row">{formatDateTime(snapshot.valuation_at)}</th>
              <td>{formatDateTime(snapshot.source_cutoff_at)}</td>
              <td>
                <MoneyValue metric={snapshot.total_value} showCurrency />
              </td>
              <td>
                <MoneyValue metric={snapshot.cash_value} showCurrency />
              </td>
              <td>
                <MoneyValue metric={snapshot.invested_value} showCurrency />
              </td>
              <td>
                <MoneyValue metric={snapshot.net_contributions} showCurrency />
              </td>
              <td>
                <QualityStatus quality={snapshot.data_quality} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
