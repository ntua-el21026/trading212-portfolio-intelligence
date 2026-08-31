import { ArrowLeft, CircleHelp } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

import { Surface } from "@trading212/ui";

import { MoneyValue, QualityStatus } from "../../../../components/financial";
import { PageHeader } from "../../../../components/page-header";
import { MethodologyDetails } from "../../../../components/quality";
import { loadPosition } from "../../../../lib/api-adapter";
import {
  formatDecimal,
  formatMoney,
  formatPercent,
  titleCase,
} from "../../../../lib/format";

export default async function HoldingDetailPage({
  params,
}: Readonly<{ params: Promise<{ positionId: string }> }>) {
  const position = await loadPosition((await params).positionId);
  if (!position) {
    notFound();
  }
  return (
    <div className="page-stack">
      <Link className="back-link" href="/holdings">
        <ArrowLeft aria-hidden="true" size={16} /> Back to holdings
      </Link>
      <PageHeader
        description={`${position.ticker} · ${titleCase(position.instrument_type)} · ${position.trading_currency}`}
        title={position.name}
      />
      <Surface className="detail-panel">
        <div className="detail-hero">
          <div>
            <span>Market value</span>
            <MoneyValue metric={position.market_value} showCurrency />
          </div>
          <QualityStatus quality={position.data_quality} />
        </div>
        <dl className="detail-grid">
          <div>
            <dt>Quantity</dt>
            <dd>{formatDecimal(position.quantity)}</dd>
          </div>
          <div>
            <dt>Current price</dt>
            <dd>
              {formatMoney(position.current_price)} {position.trading_currency}
            </dd>
          </div>
          <div>
            <dt>Provider cost basis</dt>
            <dd>
              {formatMoney(position.provider_cost_basis.value)}{" "}
              {position.provider_cost_basis.reporting_currency}
            </dd>
          </div>
          <div>
            <dt>Provider unrealized P/L</dt>
            <dd>
              {formatMoney(position.provider_unrealized_profit_loss.value)}{" "}
              {position.provider_unrealized_profit_loss.reporting_currency}
            </dd>
          </div>
          <div>
            <dt>Direct weight</dt>
            <dd>{formatPercent(position.direct_weight)}</dd>
          </div>
          <div>
            <dt>Availability</dt>
            <dd>
              {position.market_value.value === null ? (
                <CircleHelp aria-hidden="true" />
              ) : null}
              {titleCase(position.market_value.availability)}
            </dd>
          </div>
        </dl>
        <MethodologyDetails metric={position.market_value} />
      </Surface>
    </div>
  );
}
