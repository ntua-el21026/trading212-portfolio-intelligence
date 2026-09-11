import { NumberValue } from "./number-value";
import {
  ArrowRight,
  BriefcaseBusiness,
  RotateCw,
  ShieldCheck,
} from "lucide-react";
import Link from "./navigation-intent";

import { accountHref } from "../lib/account-selection";

import { EmptyState, Surface } from "@trading212/ui";

import type { OverviewBundle } from "../lib/contracts";
import { formatDateTime, formatPercent } from "../lib/format";
import { AllocationChart } from "./charts";
import { MetricCard, MoneyValue } from "./financial";
import { QualityBanner, TrustRail } from "./quality";

export function Overview({ bundle }: Readonly<{ bundle: OverviewBundle }>) {
  const { allocation, positions, reconciliation, summary } = bundle;
  return (
    <>
      <div className="mobile-context" aria-label="Portfolio context">
        <span>
          <BriefcaseBusiness aria-hidden="true" size={19} />
          {summary.account.display_name}
        </span>
        <span>
          <RotateCw aria-hidden="true" size={19} />
          <small>Last synced</small>
          {summary.account.last_refresh_at
            ? formatDateTime(summary.account.last_refresh_at)
            : "Not yet synchronized"}
        </span>
      </div>
      <QualityBanner quality={summary.data_quality} />
      <div className="overview-grid">
        <div className="overview-primary">
          <Surface className="overview-board">
            <div className="overview-metrics">
              <MetricCard
                label="Total portfolio value"
                metric={summary.total_value}
                primary
              />
              <MetricCard label="Cash" metric={summary.cash_balance} />
              <MetricCard
                label="Invested value"
                metric={summary.invested_value}
              />
              <MetricCard
                label="Net contributions"
                metric={summary.net_contributions}
                note="Cumulative"
              />
            </div>
            <div className="mobile-trust-summary">
              <div>
                <ShieldCheck aria-hidden="true" />
                <span>
                  <strong>
                    {reconciliation.status === "reconciled"
                      ? "Reconciled"
                      : "Review needed"}
                  </strong>
                  {reconciliation.status === "reconciled"
                    ? "All covered records agree."
                    : "Open discrepancies are present."}
                </span>
              </div>
              <div>
                <ShieldCheck aria-hidden="true" />
                <span>
                  <strong>
                    {summary.data_quality.state === "fresh"
                      ? "Fresh"
                      : "Review needed"}
                  </strong>
                  {summary.data_quality.warnings[0] ??
                    "No data-quality warnings."}
                </span>
              </div>
            </div>
            <section className="overview-section">
              <div className="section-heading-row">
                <div>
                  <h2>Direct allocation preview</h2>
                  <p className="allocation-preview-count">
                    Showing {allocation.returned_count} of {allocation.total}{" "}
                    canonical rows, including cash when available.
                  </p>
                </div>
                <Link
                  className="text-link"
                  href={accountHref("/allocation", summary.account.id)}
                >
                  Explore allocation <ArrowRight aria-hidden="true" size={15} />
                </Link>
              </div>
              {allocation.returned_count === 0 ? (
                <EmptyState
                  description="Allocation will appear after the first successful portfolio snapshot."
                  icon={<BriefcaseBusiness aria-hidden="true" size={21} />}
                  title="No allocation data"
                />
              ) : (
                <div className="allocation-overview">
                  <div className="allocation-chart-wrap">
                    <AllocationChart data={allocation.items} />
                    <div className="allocation-chart-center" aria-hidden="true">
                      <MoneyValue metric={summary.total_value} />
                      <small>{summary.account.reporting_currency} total</small>
                    </div>
                  </div>
                  <div
                    className="table-scroll"
                    role="region"
                    aria-label="Direct allocation by holding"
                    tabIndex={0}
                  >
                    <table className="data-table allocation-table">
                      <caption className="ui-visually-hidden">
                        Direct allocation by holding
                      </caption>
                      <thead>
                        <tr>
                          <th scope="col">Holding</th>
                          <th scope="col">
                            Value ({summary.account.reporting_currency})
                          </th>
                          <th scope="col">Weight</th>
                        </tr>
                      </thead>
                      <tbody>
                        {allocation.items.map((item, index) => (
                          <tr key={item.id}>
                            <th scope="row">
                              <span
                                aria-hidden="true"
                                className={`allocation-key allocation-key--${(index % 6) + 1}`}
                              />
                              {item.label}
                            </th>
                            <td>
                              <MoneyValue
                                metric={item.market_value}
                                showCurrency
                              />
                            </td>
                            <td>
                              <span
                                title={`Canonical ratio: ${item.weight ?? "Unavailable"}`}
                              >
                                {formatPercent(item.weight)}
                              </span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </section>
            <section className="overview-section holdings-preview">
              <div className="section-heading-row">
                <div>
                  <h2>Largest direct holdings preview</h2>
                  <p>
                    Showing {positions.items.length} of {positions.total} direct
                    positions, ordered by market value.
                  </p>
                </div>
                <Link
                  className="text-link"
                  href={accountHref("/holdings", summary.account.id)}
                >
                  View all <ArrowRight aria-hidden="true" size={15} />
                </Link>
              </div>
              {positions.items.length === 0 ? (
                <EmptyState
                  description="Positions will appear after a successful read-only synchronization."
                  icon={<BriefcaseBusiness aria-hidden="true" size={21} />}
                  title="No holdings yet"
                />
              ) : (
                <div
                  className="table-scroll"
                  role="region"
                  aria-label="Largest direct holdings"
                  tabIndex={0}
                >
                  <table className="data-table holdings-table">
                    <caption className="ui-visually-hidden">
                      Largest direct holdings
                    </caption>
                    <thead>
                      <tr>
                        <th scope="col">Instrument</th>
                        <th scope="col">Type</th>
                        <th scope="col">Currency</th>
                        <th scope="col">Quantity</th>
                        <th scope="col">Price</th>
                        <th scope="col">Market value</th>
                        <th scope="col">Weight</th>
                      </tr>
                    </thead>
                    <tbody>
                      {positions.items.slice(0, 5).map((position) => (
                        <tr key={position.id}>
                          <th scope="row">
                            <Link
                              href={accountHref(
                                `/holdings/${encodeURIComponent(position.id)}`,
                                summary.account.id,
                              )}
                            >
                              <strong>{position.ticker}</strong>
                              <span>{position.name}</span>
                            </Link>
                          </th>
                          <td>{position.instrument_type.toUpperCase()}</td>
                          <td>{position.trading_currency}</td>
                          <td>
                            <NumberValue
                              value={position.quantity}
                              minimumDigits={0}
                            />
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
                              metric={position.market_value}
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
              )}
            </section>
          </Surface>
        </div>
        <TrustRail
          metric={summary.total_value}
          quality={summary.data_quality}
          reconciliation={reconciliation}
        />
      </div>
    </>
  );
}
