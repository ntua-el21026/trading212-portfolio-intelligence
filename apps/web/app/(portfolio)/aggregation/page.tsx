import { AggregationPage } from "../../../components/aggregation-page";
import type { HistoricalSearch } from "../../../lib/historical-query";
export default async function Page({
  searchParams,
}: Readonly<{ searchParams: Promise<HistoricalSearch> }>) {
  return <AggregationPage search={await searchParams} />;
}
