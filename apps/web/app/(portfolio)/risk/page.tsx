import { RiskPage } from "../../../components/risk-page";
import type { HistoricalSearch } from "../../../lib/historical-query";
export default async function Page({
  searchParams,
}: Readonly<{ searchParams: Promise<HistoricalSearch> }>) {
  return <RiskPage search={await searchParams} />;
}
