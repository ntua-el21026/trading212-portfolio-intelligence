import "server-only";

import { cookies, headers } from "next/headers";
import {
  PortfolioApiClient,
  TargetApiClient,
  TargetApiError,
  type TargetApiResponse,
} from "@trading212/api-contracts";

import { requireWebAccess, SESSION_COOKIE, CSRF_COOKIE } from "./auth";
import { apiBaseUrl } from "./runtime";

export async function targetClients(mutating = false) {
  const access = await requireWebAccess();
  if (access.isDemo) {
    throw new TargetApiError(
      "TARGETS_UNAVAILABLE",
      503,
      "Pies require the connected local API and PostgreSQL runtime.",
    );
  }
  const store = await cookies();
  const session = store.get(SESSION_COOKIE)?.value;
  const requestHeaders: Record<string, string> = {
    ...(session ? { cookie: `${SESSION_COOKIE}=${session}` } : {}),
  };
  if (mutating) {
    const incoming = await headers();
    const origin = incoming.get("origin");
    const host = incoming.get("host");
    const csrf = store.get(CSRF_COOKIE)?.value;
    if (!origin || !host || new URL(origin).host !== host || !csrf) {
      throw new TargetApiError(
        "ACCESS_DENIED",
        403,
        "The form session could not be verified.",
      );
    }
    requestHeaders.Origin = origin;
    requestHeaders["X-CSRF-Token"] = csrf;
  }
  const options = {
    baseUrl: apiBaseUrl(),
    headers: () => requestHeaders,
    fetchImpl: (input: RequestInfo | URL, init?: RequestInit) =>
      fetch(input, {
        ...init,
        cache: "no-store",
        redirect: "error",
        signal: init?.signal ?? AbortSignal.timeout(8_000),
      }),
  };
  return {
    targets: new TargetApiClient(options),
    portfolio: new PortfolioApiClient(options),
    access,
  };
}

export function targetData<T>(response: TargetApiResponse<T>): T {
  if (response.notModified) {
    throw new TargetApiError(
      "INVALID_RESPONSE",
      502,
      "The target response had no content.",
    );
  }
  return response.data;
}
