import { HistoricalPage } from "../../../components/historical-page";
import type { HistoricalSearch } from "../../../lib/historical-query";

export default async function IncomePage({
  searchParams,
}: Readonly<{ searchParams: Promise<HistoricalSearch> }>) {
  return <HistoricalPage pathname="/income" search={await searchParams} />;
}
