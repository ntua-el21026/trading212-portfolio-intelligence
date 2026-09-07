import { HistoricalPage } from "../../../components/historical-page";
import type { HistoricalSearch } from "../../../lib/historical-query";

export default async function PerformancePage({
  searchParams,
}: Readonly<{ searchParams: Promise<HistoricalSearch> }>) {
  return <HistoricalPage pathname="/performance" search={await searchParams} />;
}
