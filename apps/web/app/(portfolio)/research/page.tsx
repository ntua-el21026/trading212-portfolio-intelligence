import { ResearchPage } from "../../../components/research-page";
import type { HistoricalSearch } from "../../../lib/historical-query";

export default async function Page({
  searchParams,
}: Readonly<{ searchParams: Promise<HistoricalSearch> }>) {
  return <ResearchPage search={await searchParams} />;
}
