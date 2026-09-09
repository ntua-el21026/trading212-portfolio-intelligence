import { XrayPage } from "../../../components/xray-page";
import type { XraySearch } from "../../../lib/xray-query";

export default async function Page({
  searchParams,
}: Readonly<{ searchParams: Promise<XraySearch> }>) {
  return <XrayPage search={await searchParams} />;
}
