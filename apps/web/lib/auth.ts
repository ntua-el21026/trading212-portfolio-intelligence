import "server-only";

import { randomUUID } from "node:crypto";

import { PortfolioApiClient } from "@trading212/api-contracts";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { cache } from "react";

import type { PrincipalResponse } from "./contracts";
import {
  apiBaseUrl,
  isExplicitDemoMode,
  isLocalApiAuthEnabled,
} from "./runtime";

export const SESSION_COOKIE = "t212pi_session";
export const CSRF_COOKIE = "t212pi_csrf";
const SESSION_TTL_MS = 60 * 60 * 1000;
const LOCAL_SYNTHETIC_OWNER_ID = "f9da1e93-85d5-5c1b-8221-ff997ffb035e";
const LOCAL_SYNTHETIC_PRINCIPAL_ID = "86c2ebdb-8e90-5279-b0e8-5f747a091c31";

interface LocalSession {
  expiresAt: number;
  principal: PrincipalResponse;
}

declare global {
  // Process-local by design: local demo sessions never leave the dev server.
  var __t212piDemoSessions: Map<string, LocalSession> | undefined;
}

const sessions =
  globalThis.__t212piDemoSessions ?? new Map<string, LocalSession>();
globalThis.__t212piDemoSessions = sessions;

export interface WebAccess {
  displayName: string;
  isDemo: boolean;
  principal: PrincipalResponse;
}

function pruneSessions(now: number): void {
  for (const [token, session] of sessions) {
    if (session.expiresAt <= now) {
      sessions.delete(token);
    }
  }
}

function sessionCookieFrom(response: Response): string {
  const setCookies = response.headers.getSetCookie();
  for (const rawCookie of setCookies) {
    const pair = rawCookie.split(";", 1)[0] ?? "";
    const separator = pair.indexOf("=");
    if (separator < 1 || pair.slice(0, separator) !== SESSION_COOKIE) {
      continue;
    }
    const value = pair.slice(separator + 1);
    if (
      value.length > 0 &&
      value.length <= 512 &&
      /^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/.test(value)
    ) {
      return value;
    }
  }
  throw new Error("The portfolio API did not issue a valid session cookie.");
}

function upstreamFetch(
  onResponse?: (response: Response) => void,
): typeof fetch {
  return async (input, init) => {
    const response = await fetch(input, {
      ...init,
      cache: "no-store",
      redirect: "error",
      signal: init?.signal ?? AbortSignal.timeout(5_000),
    });
    onResponse?.(response);
    return response;
  };
}

export async function createLocalDemoSession(): Promise<{
  expiresAt: Date;
  token: string;
}> {
  if (!isExplicitDemoMode()) {
    throw new Error("Local demo authentication is disabled.");
  }
  const now = Date.now();
  pruneSessions(now);
  const token = randomUUID();
  const expiresAt = new Date(now + SESSION_TTL_MS);
  sessions.set(token, {
    expiresAt: expiresAt.getTime(),
    principal: {
      principal_id: LOCAL_SYNTHETIC_PRINCIPAL_ID,
      owner_id: LOCAL_SYNTHETIC_OWNER_ID,
      scopes: [
        "portfolio:read",
        "activity:read",
        "portfolio:refresh",
        "configuration:read",
      ],
    },
  });
  return { expiresAt, token };
}

export async function createLocalApiSession(): Promise<{
  csrfToken: string;
  expiresAt: Date;
  token: string;
}> {
  if (!isLocalApiAuthEnabled()) {
    throw new Error("Local API authentication is disabled.");
  }
  let sessionCookie: string | null = null;
  const client = new PortfolioApiClient({
    baseUrl: apiBaseUrl(),
    fetchImpl: upstreamFetch((response) => {
      if (response.ok) sessionCookie = sessionCookieFrom(response);
    }),
  });
  const session = await client.createLocalSession();
  if (!sessionCookie) {
    throw new Error("The portfolio API session could not be established.");
  }
  if (session.csrf_token.length < 20 || session.csrf_token.length > 512) {
    throw new Error("The portfolio API issued an invalid CSRF token.");
  }
  return {
    csrfToken: session.csrf_token,
    expiresAt: new Date(session.expires_at),
    token: sessionCookie,
  };
}

export async function revokeLocalDemoSession(
  token: string | undefined,
): Promise<void> {
  if (token) {
    sessions.delete(token);
  }
}

export async function revokeApiSession(
  cookieHeader: string,
  csrfToken: string,
): Promise<void> {
  const client = new PortfolioApiClient({
    baseUrl: apiBaseUrl(),
    fetchImpl: upstreamFetch(),
    headers: () => ({
      cookie: cookieHeader,
      "X-CSRF-Token": csrfToken,
    }),
  });
  await client.logout();
}

async function readLocalAccess(): Promise<WebAccess | null> {
  const token = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!token) {
    return null;
  }
  const now = Date.now();
  pruneSessions(now);
  const session = sessions.get(token);
  if (!session || session.expiresAt <= now) {
    return null;
  }
  return {
    displayName: "Demo Account",
    isDemo: true,
    principal: session.principal,
  };
}

async function readApiAccess(): Promise<WebAccess | null> {
  let baseUrl: string;
  try {
    baseUrl = apiBaseUrl();
  } catch {
    return null;
  }
  const cookieHeader = (await cookies())
    .getAll()
    .map(({ name, value }) => `${name}=${value}`)
    .join("; ");
  if (!cookieHeader) {
    return null;
  }
  const client = new PortfolioApiClient({
    baseUrl,
    fetchImpl: upstreamFetch(),
    headers: () => ({ cookie: cookieHeader }),
  });
  const principal = await client.me().catch(() => null);
  if (!principal) {
    return null;
  }
  return {
    displayName: "Portfolio owner",
    isDemo: false,
    principal,
  };
}

export const getWebAccess = cache(async (): Promise<WebAccess | null> =>
  isExplicitDemoMode() ? readLocalAccess() : readApiAccess(),
);

export async function requireWebAccess(): Promise<WebAccess> {
  const access = await getWebAccess();
  if (!access) {
    redirect("/sign-in");
  }
  return access;
}
