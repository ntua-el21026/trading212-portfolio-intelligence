import { OwnerLayoutsPage } from "../../../../components/owner-layout-page";
import type { HistoricalSearch } from "../../../../lib/historical-query";

export default async function Page({
  searchParams,
}: Readonly<{ searchParams: Promise<HistoricalSearch> }>) {
  return <OwnerLayoutsPage search={await searchParams} />;
}
