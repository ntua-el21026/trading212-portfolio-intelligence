import "server-only";

import { notFound } from "next/navigation";
import { z } from "zod";

import { firstSearchParam, readOpaqueCursor } from "./collection-query";
import { planningClients } from "./planning-adapter";
import { targetData } from "./target-adapter";

export type PlanningSearch = Record<string, string | string[] | undefined>;

export function planningUuid(value: string | string[] | undefined) {
  const parsed = z
    .string()
    .uuid()
    .optional()
    .safeParse(firstSearchParam(value) || undefined);
  if (!parsed.success) notFound();
  return parsed.data;
}

export function planningHref(
  pathname: string,
  values: Readonly<Record<string, string | null | undefined>>,
) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    if (value) query.set(key, value);
  }
  return query.size ? `${pathname}?${query}` : pathname;
}

export async function loadPlanningSelection(query: PlanningSearch) {
  const clients = await planningClients();
  const accounts = await clients.portfolio.listAccounts();
  const accountId =
    planningUuid(query.account) ??
    process.env.T212PI_ACCOUNT_ID ??
    accounts[0]?.id;
  const account = accounts.find((item) => item.id === accountId);
  if (!account) return { clients, accounts, account: null, selection: null };
  const requestedPie = planningUuid(query.pie);
  const requestedVersion = planningUuid(query.version);
  const requestedSnapshot = planningUuid(query.snapshot);
  const browse =
    !requestedPie ||
    !requestedVersion ||
    !requestedSnapshot ||
    firstSearchParam(query.choose) === "1" ||
    Boolean(
      query.pies_cursor || query.versions_cursor || query.snapshots_cursor,
    );
  const [piesResponse, snapshots] = await Promise.all([
    browse
      ? clients.targets.list_virtual_portfolios({
          account_id: account.id,
          state: "all",
          sort: "name_asc",
          limit: 25,
          cursor: readOpaqueCursor(query.pies_cursor),
        })
      : null,
    browse
      ? clients.portfolio.listSnapshots(account.id, {
          limit: 25,
          cursor: readOpaqueCursor(query.snapshots_cursor) ?? undefined,
        })
      : null,
  ]);
  const pies = piesResponse ? targetData(piesResponse) : null;
  const pieId =
    requestedPie ??
    pies?.items.find((item) => item.active_version_id)?.id ??
    pies?.items[0]?.id;
  const pie = pieId
    ? (pies?.items.find((item) => item.id === pieId) ??
      targetData(await clients.targets.get_virtual_portfolio(pieId)))
    : null;
  if (pie && pie.account_id !== account.id) notFound();
  const versions =
    pie && browse
      ? targetData(
          await clients.targets.list_target_versions(pie.id, {
            state: "all",
            limit: 25,
            cursor: readOpaqueCursor(query.versions_cursor),
          }),
        )
      : null;
  const versionId =
    requestedVersion ??
    pie?.active_version_id ??
    versions?.items.find((item) => item.published_at)?.id;
  const version = versionId
    ? targetData(await clients.targets.get_target_version(versionId))
    : null;
  if (version && version.portfolio_id !== pie?.id) notFound();
  const snapshotId = requestedSnapshot ?? snapshots?.items[0]?.id;
  const snapshot = snapshotId
    ? (snapshots?.items.find((item) => item.id === snapshotId) ??
      (await clients.portfolio.getSnapshot(account.id, snapshotId)))
    : null;
  return {
    clients,
    accounts,
    account,
    selection: { browse, pies, pie, versions, version, snapshots, snapshot },
  };
}

export type PlanningSelection = Awaited<
  ReturnType<typeof loadPlanningSelection>
>;
