import {
  ArrowRight,
  BriefcaseBusiness,
  RotateCw,
  ShieldCheck,
} from "lucide-react";
import Link from "next/link";

import { EmptyState, Surface } from "@trading212/ui";

import type { PortfolioBundle } from "../lib/contracts";
import {
  formatDateTime,
  formatDecimal,
  formatMoney,
  formatPercent,
} from "../lib/format";
import { AllocationChart } from "./charts";
import { MetricCard, MoneyValue } from "./financial";
import { QualityBanner, TrustRail } from "./quality";

export function Overview({ bundle }: Readonly<{ bundle: PortfolioBundle }>) {
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
                  <h2>Direct allocation</h2>
                  <p>Canonical position weights, including cash.</p>
                </div>
                <Link className="text-link" href="/allocation">
                  Explore allocation <ArrowRight aria-hidden="true" size={15} />
                </Link>
              </div>
              {allocation.length === 0 ? (
                <EmptyState
                  description="Allocation will appear after the first successful portfolio snapshot."
                  icon={<BriefcaseBusiness aria-hidden="true" size={21} />}
                  title="No allocation data"
                />
              ) : (
                <div className="allocation-overview">
                  <div className="allocation-chart-wrap">
                    <AllocationChart data={allocation} />
                    <div className="allocation-chart-center" aria-hidden="true">
                      <MoneyValue metric={summary.total_value} />
                      <small>{summary.account.reporting_currency} total</small>
                    </div>
                  </div>
                  <div className="table-scroll">
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
                        {allocation.map((item, index) => (
                          <tr key={item.id}>
                            <th scope="row">
                              <span
                                aria-hidden="true"
                                className={`allocation-key allocation-key--${(index % 6) + 1}`}
                              />
                              {item.label}
                            </th>
                            <td>{formatMoney(item.market_value.value)}</td>
                            <td>{formatPercent(item.weight)}</td>
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
                  <h2>Holdings</h2>
                  <p>{positions.total} direct positions in this portfolio.</p>
                </div>
                <Link className="text-link" href="/holdings">
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
                <div className="table-scroll">
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
                              href={`/holdings/${encodeURIComponent(position.id)}`}
                            >
                              <strong>{position.ticker}</strong>
                              <span>{position.name}</span>
                            </Link>
                          </th>
                          <td>{position.instrument_type.toUpperCase()}</td>
                          <td>{position.trading_currency}</td>
                          <td>{formatDecimal(position.quantity)}</td>
                          <td>{formatMoney(position.current_price)}</td>
                          <td>{formatMoney(position.market_value.value)}</td>
                          <td>{formatPercent(position.direct_weight)}</td>
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
