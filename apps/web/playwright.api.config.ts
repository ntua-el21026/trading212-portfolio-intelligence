import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "../../tests/e2e/api-web",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  // The insertion-stability scenario mutates one deterministic account fixture;
  // serialize projects so desktop and mobile each begin from the same baseline.
  workers: 1,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: "http://127.0.0.1:3001",
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "api-chromium-desktop",
      use: { ...devices["Desktop Chrome"] },
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
      timeout: 120_000,
      // Readiness intentionally stays fail-closed without a live dispatcher;
      // this browser suite needs only the API process liveness probe.
      url: "http://127.0.0.1:18000/health/live",
    },
    {
      command: "corepack pnpm dev --hostname 127.0.0.1 --port 3001",
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
