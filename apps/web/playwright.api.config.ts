import { defineConfig, devices } from "@playwright/test";

const production = process.env.T212PI_E2E_PRODUCTION ?? "0";
if (!["0", "1"].includes(production))
  throw new Error("The production browser fixture selector must be 0 or 1.");

export default defineConfig({
  testDir: "../../tests/e2e/api-web",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  // A flaky browser assertion is a failed Phase 1 evidence gate, including in CI.
  retries: 0,
  // test:e2e starts each spec file and viewport in a separate process and DB.
  // This preserves the real 64-snapshot quota across independent test lifecycles.
  // Tests within one spec/viewport share mutable fixtures and run serially.
  workers: 1,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: "http://127.0.0.1:3001",
    // Authenticated traces retain cookies and request headers. Keep visual failure evidence only.
    trace: "off",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "api-chromium-desktop",
      use: { ...devices["Desktop Chrome"] },
    },
    {
      name: "api-chromium-tablet",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { height: 1024, width: 768 },
        deviceScaleFactor: 2,
      },
    },
    {
      name: "api-chromium-mobile",
      use: {
        ...devices["Pixel 7"],
        deviceScaleFactor: 2,
        viewport: { height: 910, width: 432 },
      },
    },
  ],
  webServer: [
    {
      command: "uv run python ../../scripts/run_api_backed_e2e.py",
      reuseExistingServer: false,
      // Allow the fixture to drop only its own disposable database at shutdown.
      gracefulShutdown: { signal: "SIGTERM", timeout: 10_000 },
      timeout: 120_000,
      // Readiness intentionally stays fail-closed without a live dispatcher;
      // this browser suite needs only the API process liveness probe.
      url: "http://127.0.0.1:18000/health/live",
    },
    {
      command:
        production === "1"
          ? "node ../../scripts/run_production_web_e2e.mjs"
          : "corepack pnpm dev --hostname 127.0.0.1 --port 3001",
      env: {
        PORTFOLIO_DEMO_MODE: "0",
        T212PI_ACCOUNT_ID: "f0f5c66e-b128-59b2-a620-83bc8faa4a57",
        T212PI_API_BASE_URL: "http://127.0.0.1:18000",
        T212PI_LOCAL_API_AUTH_ENABLED: "1",
        T212PI_WEB_ENVIRONMENT: "test",
      },
      reuseExistingServer: false,
      timeout: 120_000,
      url: "http://127.0.0.1:3001/sign-in",
    },
  ],
});
