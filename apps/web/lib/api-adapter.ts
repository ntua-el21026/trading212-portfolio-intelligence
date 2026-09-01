import "server-only";

import { randomUUID } from "node:crypto";
import { cache } from "react";

import {
  PortfolioApiClient,
  type Account,
  type Activity,
  type DirectAllocation,
  type Page,
  type PortfolioApiClientOptions,
  type Position,
  type ReconciliationIssue,
  type Snapshot,
} from "@trading212/api-contracts";
import Decimal from "decimal.js";
import { cookies } from "next/headers";

import type {
  DemoViewState,
  AllocationBundle,
  DividendBundle,
  OverviewBundle,
  PortfolioContext,
  PositionResponse,
  QualityBundle,
  QualityResponse,
  RefreshRunResponse,
  SettingsBundle,
  SynchronizationBundle,
} from "./contracts";
import { requireWebAccess } from "./auth";
import { demoRefreshRun, getDemoPortfolio } from "./demo-data";
import { apiBaseUrl, isExplicitDemoMode } from "./runtime";

function boundedFetch(
  input: RequestInfo | URL,
  init?: RequestInit,
): Promise<Response> {
  return fetch(input, {
    ...init,
    cache: "no-store",
    signal: init?.signal ?? AbortSignal.timeout(8_000),
  });
}

async function apiClient(): Promise<PortfolioApiClient> {
  const store = await cookies();
  const cookie = store
    .getAll()
    .map(({ name, value }) => `${name}=${value}`)
    .join("; ");
  const csrf = store.get("t212pi_csrf")?.value;
  const headers: HeadersInit = {
    ...(cookie ? { cookie } : {}),
    ...(csrf ? { "X-CSRF-Token": csrf } : {}),
  };
  const options: PortfolioApiClientOptions = {
    baseUrl: apiBaseUrl(),
    fetchImpl: boundedFetch,
    headers: () => headers,
  };
  return new PortfolioApiClient(options);
}

function chooseAccountId(accounts: Account[]): string {
  if (accounts.length === 0) {
    throw new Error("No portfolio account is available for this principal.");
  }

  const preferred = process.env.T212PI_ACCOUNT_ID?.trim();
  if (preferred) {
    const account = accounts.find(({ id }) => id === preferred);
    if (!account) {
      throw new Error(
        "The configured portfolio account is not available to this principal.",
      );
    }
    return account.id;
  }

  if (accounts.length !== 1) {
    throw new Error(
      "Multiple portfolio accounts are available; configure T212PI_ACCOUNT_ID explicitly.",
    );
  }
  return accounts[0].id;
}

async function accountIdFor(client: PortfolioApiClient): Promise<string> {
  return chooseAccountId(await client.listAccounts());
}

export function readDemoViewState(
  value: string | string[] | undefined,
): DemoViewState {
  const candidate = Array.isArray(value) ? value[0] : value;
  if (!isExplicitDemoMode()) {
    return "default";
  }
  return new Set<DemoViewState>([
    "empty",
    "stale",
    "partial",
    "unreconciled",
    "error",
  ]).has(candidate as DemoViewState)
    ? (candidate as DemoViewState)
    : "default";
}

async function authorizedClientAndAccount(): Promise<{
  accountId: string;
  client: PortfolioApiClient;
}> {
  await requireWebAccess();
  const client = await apiClient();
  return { accountId: await accountIdFor(client), client };
}

function demoCollectionPage<Item>(
  page: Page<Item>,
  resource: string,
  cursor: string | null,
  limit: number,
): Page<Item> {
  let start = 0;
  if (cursor) {
    try {
      const decoded = JSON.parse(
        Buffer.from(cursor, "base64url").toString("utf8"),
      ) as { resource?: unknown; start?: unknown };
      if (
        decoded.resource !== resource ||
        !Number.isInteger(decoded.start) ||
        Number(decoded.start) < 0
      ) {
        throw new Error("cursor binding mismatch");
      }
      start = Number(decoded.start);
    } catch {
      throw new Error("The synthetic collection cursor is invalid.");
    }
  }
  const items = page.items.slice(start, start + limit);
  const nextStart = start + items.length;
  return {
    items,
    limit,
    next_cursor:
      nextStart < page.total
        ? Buffer.from(
            JSON.stringify({ resource, start: nextStart }),
            "utf8",
          ).toString("base64url")
        : null,
    total: page.total,
  };
}

export interface HoldingsQuery {
  cursor: string | null;
  search?: string;
  sort: "market_value_desc" | "ticker_asc" | "weight_desc";
}

export interface ActivityQuery {
  activityType?:
    | "all"
    | "buy"
    | "sell"
    | "deposit"
    | "withdrawal"
    | "dividend"
    | "interest"
    | "fee"
    | "tax"
    | "fx_conversion"
    | "unknown";
  cursor: string | null;
  endDate?: string;
  startDate?: string;
}

export interface DividendQuery {
  cursor: string | null;
  endDate?: string;
  startDate?: string;
}

function compareNullableDecimalDescending(
  left: string | null,
  right: string | null,
): number {
  if (left === null) return right === null ? 0 : 1;
  if (right === null) return -1;
  return new Decimal(right).comparedTo(new Decimal(left));
}

function boundedDirectAllocation(
  allocation: DirectAllocation,
  positionLimit: number,
): DirectAllocation {
  const positions: DirectAllocation["items"] = [];
  const cash: DirectAllocation["items"] = [];
  for (const item of allocation.items) {
    if (item.asset_type.toLocaleLowerCase("en-US") === "cash") {
      cash.push(item);
    } else {
      positions.push(item);
    }
  }
  const items = [...positions.slice(0, positionLimit), ...cash.slice(0, 1)];
  return {
    items,
    returned_count: items.length,
    total: allocation.total,
    limit: positionLimit,
    truncated: allocation.total > items.length,
  };
}

export const loadPortfolioContext = cache(
  async (state: DemoViewState = "default"): Promise<PortfolioContext> => {
    await requireWebAccess();
    if (isExplicitDemoMode()) {
      return { summary: getDemoPortfolio(state).summary };
    }
    const { accountId, client } = await authorizedClientAndAccount();
    return { summary: await client.getSummary(accountId) };
  },
);

export const loadOverview = cache(
  async (state: DemoViewState = "default"): Promise<OverviewBundle> => {
    await requireWebAccess();
    if (isExplicitDemoMode()) {
      const bundle = getDemoPortfolio(state);
      const orderedPositions = [...bundle.positions.items].sort(
        (left, right) =>
          compareNullableDecimalDescending(
            left.market_value.value,
            right.market_value.value,
          ) || left.id.localeCompare(right.id),
      );
      return {
        allocation: boundedDirectAllocation(bundle.allocation, 5),
        positions: demoCollectionPage(
          { ...bundle.positions, items: orderedPositions },
          "positions:market_value_desc",
          null,
          5,
        ),
        reconciliation: bundle.reconciliation,
        summary: bundle.summary,
      };
    }
    const { accountId, client } = await authorizedClientAndAccount();
    const [summary, positions, allocation, reconciliation] = await Promise.all([
      client.getSummary(accountId),
      client.listPositions(accountId, { limit: 5, sort: "market_value_desc" }),
      client.getAllocation(accountId, { limit: 5 }),
      client.getReconciliation(accountId),
    ]);
    return { allocation, positions, reconciliation, summary };
  },
);

export async function loadHoldingsPage(
  query: HoldingsQuery,
  state: DemoViewState = "default",
): Promise<{ positions: Page<Position>; summary: OverviewBundle["summary"] }> {
  await requireWebAccess();
  if (isExplicitDemoMode()) {
    const bundle = getDemoPortfolio(state);
    let items = [...bundle.positions.items];
    if (query.search) {
      const normalized = query.search.toLocaleLowerCase("en-US");
      items = items.filter((item) =>
        `${item.ticker} ${item.name}`
          .toLocaleLowerCase("en-US")
          .includes(normalized),
      );
    }
    items.sort((left, right) => {
      if (query.sort === "ticker_asc") {
        return (
          left.ticker.localeCompare(right.ticker) ||
          left.id.localeCompare(right.id)
        );
      }
      const field =
        query.sort === "weight_desc" ? "direct_weight" : "market_value";
      const leftValue =
        field === "direct_weight"
          ? left.direct_weight
          : left.market_value.value;
      const rightValue =
        field === "direct_weight"
          ? right.direct_weight
          : right.market_value.value;
      return (
        compareNullableDecimalDescending(leftValue, rightValue) ||
        left.id.localeCompare(right.id)
      );
    });
    const page: Page<Position> = {
      ...bundle.positions,
      items,
      total: items.length,
    };
    return {
      positions: demoCollectionPage(
        page,
        `positions:${query.sort}:${query.search ?? ""}`,
        query.cursor,
        50,
      ),
      summary: bundle.summary,
    };
  }
  const { accountId, client } = await authorizedClientAndAccount();
  const [summary, positions] = await Promise.all([
    client.getSummary(accountId),
    client.listPositions(accountId, { ...query, limit: 50 }),
  ]);
  return { positions, summary };
}

export async function loadActivityPage(
  query: ActivityQuery,
  state: DemoViewState = "default",
): Promise<{ activity: Page<Activity>; quality: QualityResponse }> {
  await requireWebAccess();
  if (isExplicitDemoMode()) {
    const bundle = getDemoPortfolio(state);
    const items = bundle.activity.items
      .filter((item) => {
        const date = item.occurred_at.slice(0, 10);
        return (
          (!query.startDate || date >= query.startDate) &&
          (!query.endDate || date <= query.endDate) &&
          (!query.activityType ||
            query.activityType === "all" ||
            item.activity_type === query.activityType)
        );
      })
      .sort(
        (left, right) =>
          right.occurred_at.localeCompare(left.occurred_at) ||
          right.id.localeCompare(left.id),
      );
    return {
      activity: demoCollectionPage(
        { ...bundle.activity, items, total: items.length },
        `activity:${query.startDate ?? ""}:${query.endDate ?? ""}:${query.activityType ?? "all"}`,
        query.cursor,
        50,
      ),
      quality: bundle.quality,
    };
  }
  const { accountId, client } = await authorizedClientAndAccount();
  const [activity, qualitySummary] = await Promise.all([
    client.listTransactions(accountId, {
      ...query,
      activityType:
        query.activityType === "all" ? undefined : query.activityType,
      limit: 50,
    }),
    client.getQuality(accountId),
  ]);
  return { activity, quality: qualitySummary.data_quality };
}

export async function loadDividendsPage(
  query: DividendQuery,
  state: DemoViewState = "default",
): Promise<DividendBundle> {
  await requireWebAccess();
  if (isExplicitDemoMode()) {
    const bundle = getDemoPortfolio(state);
    const items = bundle.dividends.items
      .filter(
        (item) =>
          (!query.startDate || item.paid_on >= query.startDate) &&
          (!query.endDate || item.paid_on <= query.endDate),
      )
      .sort(
        (left, right) =>
          right.paid_on.localeCompare(left.paid_on) ||
          right.id.localeCompare(left.id),
      );
    return {
      dividends: demoCollectionPage(
        { ...bundle.dividends, items, total: items.length },
        `dividends:${query.startDate ?? ""}:${query.endDate ?? ""}`,
        query.cursor,
        50,
      ),
      quality: bundle.quality,
      summary: bundle.summary,
    };
  }
  const { accountId, client } = await authorizedClientAndAccount();
  const [summary, dividends, qualitySummary] = await Promise.all([
    client.getSummary(accountId),
    client.listDividends(accountId, { ...query, limit: 50 }),
    client.getQuality(accountId),
  ]);
  return { dividends, quality: qualitySummary.data_quality, summary };
}

export async function loadSnapshotsPage(
  cursor: string | null,
  state: DemoViewState = "default",
): Promise<{ quality: QualityResponse; snapshots: Page<Snapshot> }> {
  await requireWebAccess();
  if (isExplicitDemoMode()) {
    const bundle = getDemoPortfolio(state);
    const snapshots = [...bundle.snapshots.items].sort(
      (left, right) =>
        right.valuation_at.localeCompare(left.valuation_at) ||
        right.id.localeCompare(left.id),
    );
    return {
      quality: bundle.quality,
      snapshots: demoCollectionPage(
        { ...bundle.snapshots, items: snapshots },
        "snapshots",
        cursor,
        50,
      ),
    };
  }
  const { accountId, client } = await authorizedClientAndAccount();
  const [snapshots, qualitySummary] = await Promise.all([
    client.listSnapshots(accountId, { cursor, limit: 50 }),
    client.getQuality(accountId),
  ]);
  return { quality: qualitySummary.data_quality, snapshots };
}

export const loadAllocation = cache(
  async (state: DemoViewState = "default"): Promise<AllocationBundle> => {
    await requireWebAccess();
    if (isExplicitDemoMode()) {
      const bundle = getDemoPortfolio(state);
      return {
        allocation: boundedDirectAllocation(bundle.allocation, 50),
        summary: bundle.summary,
      };
    }
    const { accountId, client } = await authorizedClientAndAccount();
    const [summary, allocation] = await Promise.all([
      client.getSummary(accountId),
      client.getAllocation(accountId, { limit: 50 }),
    ]);
    return { allocation, summary };
  },
);

export const loadQualityView = cache(
  async (
    cursor: string | null,
    state: DemoViewState = "default",
  ): Promise<QualityBundle> => {
    await requireWebAccess();
    if (isExplicitDemoMode()) {
      const bundle = getDemoPortfolio(state);
      return {
        discrepancies: demoCollectionPage<ReconciliationIssue>(
          {
            items: bundle.reconciliation.issues,
            limit: 50,
            next_cursor: null,
            total: bundle.reconciliation.discrepancy_count,
          },
          "reconciliation-discrepancies",
          cursor,
          50,
        ),
        quality: bundle.quality,
        reconciliation: bundle.reconciliation,
        summary: bundle.summary,
      };
    }
    const { accountId, client } = await authorizedClientAndAccount();
    const [summary, reconciliation, discrepancies, qualitySummary] =
      await Promise.all([
        client.getSummary(accountId),
        client.getReconciliation(accountId),
        client.listReconciliationDiscrepancies(accountId, {
          cursor,
          limit: 50,
        }),
        client.getQuality(accountId),
      ]);
    return {
      discrepancies,
      quality: qualitySummary.data_quality,
      reconciliation,
      summary,
    };
  },
);

export const loadSynchronization = cache(
  async (): Promise<SynchronizationBundle> => {
    await requireWebAccess();
    if (isExplicitDemoMode()) {
      const bundle = getDemoPortfolio();
      return { quality: bundle.quality, summary: bundle.summary };
    }
    const { accountId, client } = await authorizedClientAndAccount();
    const [summary, qualitySummary] = await Promise.all([
      client.getSummary(accountId),
      client.getQuality(accountId),
    ]);
    return { quality: qualitySummary.data_quality, summary };
  },
);

export const loadSettings = cache(async (): Promise<SettingsBundle> => {
  await requireWebAccess();
  if (isExplicitDemoMode()) {
    const bundle = getDemoPortfolio();
    return {
      connections: [
        {
          credential_state: "not_configured",
          environment: "synthetic",
          id: "synthetic-demo-connection",
          last_successful_refresh_at: bundle.summary.account.last_refresh_at,
          provider: "synthetic",
          read_only: true,
          state: "connected_read_only",
          status: "active",
        },
      ],
      summary: bundle.summary,
    };
  }
  const { accountId, client } = await authorizedClientAndAccount();
  const [summary, connections] = await Promise.all([
    client.getSummary(accountId),
    client.listConnections(),
  ]);
  return { connections, summary };
});

export async function loadPosition(
  positionId: string,
): Promise<PositionResponse | null> {
  if (!/^[A-Za-z0-9._:-]{1,255}$/.test(positionId)) {
    return null;
  }
  await requireWebAccess();
  if (isExplicitDemoMode()) {
    return (
      getDemoPortfolio().positions.items.find(
        (item) => item.id === positionId,
      ) ?? null
    );
  }
  const client = await apiClient();
  return client.getPosition(await accountIdFor(client), positionId);
}

export async function requestRefresh(): Promise<RefreshRunResponse> {
  await requireWebAccess();
  if (isExplicitDemoMode()) {
    return {
      ...demoRefreshRun,
      capabilities: [...demoRefreshRun.capabilities],
      warnings: [...demoRefreshRun.warnings],
    };
  }
  const client = await apiClient();
  return client.refresh(await accountIdFor(client), {
    idempotencyKey: randomUUID(),
    scope: "all",
    mode: "incremental",
    createSnapshot: true,
  });
}
