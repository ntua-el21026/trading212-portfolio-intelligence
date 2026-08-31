import "server-only";

const LOCAL_HOSTS = new Set(["127.0.0.1", "localhost", "::1"]);
const LOCAL_ENVIRONMENTS = new Set(["local", "test"]);

function runtimeEnvironment(): string {
  const configured = process.env.T212PI_WEB_ENVIRONMENT;
  if (configured) {
    if (!new Set(["local", "test", "staging", "production"]).has(configured)) {
      throw new Error("The web runtime environment is invalid.");
    }
    return configured;
  }
  return process.env.NODE_ENV === "production" ? "production" : "local";
}

function isLocalEnvironment(): boolean {
  return LOCAL_ENVIRONMENTS.has(runtimeEnvironment());
}

export function isExplicitDemoMode(): boolean {
  if (process.env.PORTFOLIO_DEMO_MODE !== "1") {
    return false;
  }
  if (!isLocalEnvironment()) {
    throw new Error(
      "Local demo mode is forbidden outside local or test environments.",
    );
  }
  return true;
}

export function isLocalApiAuthEnabled(): boolean {
  if (process.env.T212PI_LOCAL_API_AUTH_ENABLED !== "1") {
    return false;
  }
  if (!isLocalEnvironment()) {
    throw new Error(
      "Local API authentication is forbidden outside local or test environments.",
    );
  }
  return !isExplicitDemoMode();
}

export function apiBaseUrl(): string {
  const configured = process.env.T212PI_API_BASE_URL;
  if (!configured) {
    throw new Error("The portfolio API base URL is not configured.");
  }
  const parsed = new URL(configured);
  if (!new Set(["http:", "https:"]).has(parsed.protocol)) {
    throw new Error("The portfolio API base URL must use HTTP or HTTPS.");
  }
  if (!isLocalEnvironment() && parsed.protocol !== "https:") {
    throw new Error("Production portfolio API access requires HTTPS.");
  }
  parsed.pathname = parsed.pathname.replace(/\/$/, "");
  parsed.search = "";
  parsed.hash = "";
  return parsed.toString().replace(/\/$/, "");
}

export function assertSameOrigin(request: Request): void {
  const origin = request.headers.get("origin");
  const host = request.headers.get("host");
  const originUrl = origin ? new URL(origin) : null;
  if (!originUrl || !host || originUrl.host !== host) {
    throw new Error("Cross-origin form submission rejected.");
  }
  if (isExplicitDemoMode() && !LOCAL_HOSTS.has(originUrl.hostname)) {
    throw new Error("Local demo mode accepts only loopback hosts.");
  }
}
