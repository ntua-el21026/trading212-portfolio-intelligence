import Link from "next/link";

import type {
  ActivityResponse,
  DividendResponse,
  PositionResponse,
  SnapshotResponse,
} from "../lib/contracts";
import {
  formatDate,
  formatDateTime,
  formatDecimal,
  formatMoney,
  formatPercent,
  titleCase,
} from "../lib/format";
import { QualityStatus } from "./financial";

export function PositionsTable({
  positions,
}: Readonly<{ positions: PositionResponse[] }>) {
  return (
    <div className="table-scroll">
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
                <Link href={`/holdings/${encodeURIComponent(position.id)}`}>
                  <strong>{position.ticker}</strong>
                  <span>{position.name}</span>
                </Link>
              </th>
              <td>{titleCase(position.instrument_type)}</td>
              <td>{formatDecimal(position.quantity)}</td>
              <td>
                {formatMoney(position.current_price)}{" "}
                {position.trading_currency}
              </td>
              <td>
                {formatMoney(position.provider_cost_basis.value)}{" "}
                {position.provider_cost_basis.reporting_currency}
              </td>
              <td>
                {formatMoney(position.market_value.value)}{" "}
                {position.market_value.reporting_currency}
              </td>
              <td>
                {formatMoney(position.provider_unrealized_profit_loss.value)}{" "}
                {position.provider_unrealized_profit_loss.reporting_currency}
              </td>
              <td>{formatPercent(position.direct_weight)}</td>
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
    <div className="table-scroll">
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
                {item.quantity === null ? "—" : formatDecimal(item.quantity)}
              </td>
              <td>
                {formatMoney(item.amount.value)}{" "}
                {item.amount.reporting_currency}
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
    <div className="table-scroll">
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
              <td>{formatDecimal(item.quantity)}</td>
              <td>
                {formatMoney(item.gross_amount.value)}{" "}
                {item.gross_amount.reporting_currency}
              </td>
              <td>
                {formatMoney(item.withholding_tax.value)}{" "}
                {item.withholding_tax.reporting_currency}
              </td>
              <td>
                {formatMoney(item.net_amount.value)}{" "}
                {item.net_amount.reporting_currency}
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
    <div className="table-scroll">
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
                {formatMoney(snapshot.total_value.value)}{" "}
                {snapshot.total_value.reporting_currency}
              </td>
              <td>
                {formatMoney(snapshot.cash_value.value)}{" "}
                {snapshot.cash_value.reporting_currency}
              </td>
              <td>
                {formatMoney(snapshot.invested_value.value)}{" "}
                {snapshot.invested_value.reporting_currency}
              </td>
              <td>
                {formatMoney(snapshot.net_contributions.value)}{" "}
                {snapshot.net_contributions.reporting_currency}
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
