import { ScenarioPage } from "../../../components/scenario-page";
import type { HistoricalSearch } from "../../../lib/historical-query";

export default async function Page({
  searchParams,
}: Readonly<{ searchParams: Promise<HistoricalSearch> }>) {
  return <ScenarioPage search={await searchParams} />;
}
