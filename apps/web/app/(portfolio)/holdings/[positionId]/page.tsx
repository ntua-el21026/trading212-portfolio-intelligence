import { NumberValue } from "../../../../components/number-value";
import {
  AccountRequired,
  AccountView,
} from "../../../../components/account-context";
import { loadSelectedAccount } from "../../../../lib/api-adapter";
import { ArrowLeft, CircleHelp } from "lucide-react";
import Link from "../../../../components/navigation-intent";
import { notFound } from "next/navigation";

import { Surface } from "@trading212/ui";

import { MoneyValue, QualityStatus } from "../../../../components/financial";
import { PageHeader } from "../../../../components/page-header";
import { MethodologyDetails } from "../../../../components/quality";
import { loadPosition } from "../../../../lib/api-adapter";
import { formatPercent, titleCase } from "../../../../lib/format";

export default async function HoldingDetailPage({
  params: routeParams,
  searchParams,
}: Readonly<{
  params: Promise<{ positionId: string }>;
  searchParams: Promise<{ account?: string | string[] }>;
}>) {
  const params = await searchParams;
  const accountSelection = await loadSelectedAccount(params.account);
  if (!accountSelection.account)
    return <AccountRequired selection={accountSelection} />;
  const selectedAccountId = accountSelection.account.id;
  const position = await loadPosition(
    (await routeParams).positionId,
    selectedAccountId,
  );
  if (!position) {
    notFound();
  }
  return (
    <AccountView accountId={selectedAccountId}>
      <div className="page-stack">
        <Link
          className="back-link"
          href={`/holdings?account=${selectedAccountId}`}
        >
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
              <dd>
                <NumberValue value={position.quantity} minimumDigits={0} />
              </dd>
            </div>
            <div>
              <dt>Current price</dt>
              <dd>
                {position.current_price === null ? (
                  "Unavailable"
                ) : (
                  <NumberValue
                    value={position.current_price}
                    unit={position.trading_currency}
                  />
                )}
              </dd>
            </div>
            <div>
              <dt>Provider cost basis</dt>
              <dd>
                <MoneyValue
                  metric={position.provider_cost_basis}
                  showCurrency
                />
              </dd>
            </div>
            <div>
              <dt>Provider unrealized P/L</dt>
              <dd>
                <MoneyValue
                  metric={position.provider_unrealized_profit_loss}
                  showCurrency
                />
              </dd>
            </div>
            <div>
              <dt>Direct weight</dt>
              <dd>
                <span
                  title={`Canonical ratio: ${position.direct_weight ?? "Unavailable"}`}
                >
                  {formatPercent(position.direct_weight)}
                </span>
              </dd>
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
    </AccountView>
  );
}
