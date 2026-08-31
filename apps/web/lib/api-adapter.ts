import "server-only";

import { randomUUID } from "node:crypto";
import { cache } from "react";

import {
  PortfolioApiClient,
  type Account,
  type PortfolioApiClientOptions,
} from "@trading212/api-contracts";
import { cookies } from "next/headers";

import type {
  DemoViewState,
  PortfolioBundle,
  PositionResponse,
  QualityResponse,
  RefreshRunResponse,
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

export const loadPortfolioBundle = cache(
  async (state: DemoViewState = "default"): Promise<PortfolioBundle> => {
    await requireWebAccess();
    if (isExplicitDemoMode()) {
      return getDemoPortfolio(state);
    }
    const client = await apiClient();
    const accountId = await accountIdFor(client);
    const [
      summary,
      positions,
      activity,
      dividends,
      allocation,
      snapshots,
      reconciliation,
      quality,
    ] = await Promise.all([
      client.getSummary(accountId),
      client.listPositions(accountId, { limit: 50 }),
      client.listTransactions(accountId, { limit: 50 }),
      client.listDividends(accountId, { limit: 50 }),
      client.getAllocation(accountId),
      client.listSnapshots(accountId, { limit: 50 }),
      client.getReconciliation(accountId),
      client.getQuality(accountId),
    ]);
    return {
      summary,
      positions,
      activity,
      dividends,
      allocation,
      snapshots,
      reconciliation,
      quality,
    };
  },
);

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

export function qualityFrom(bundle: PortfolioBundle): QualityResponse {
  return bundle.quality;
}
