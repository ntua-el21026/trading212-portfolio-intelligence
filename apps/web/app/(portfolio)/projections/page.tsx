import { ProjectionPage } from "../../../components/projection-page";
import type { HistoricalSearch } from "../../../lib/historical-query";
export default async function Page({
  searchParams,
}: Readonly<{ searchParams: Promise<HistoricalSearch> }>) {
  return <ProjectionPage search={await searchParams} />;
}
