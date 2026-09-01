import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "../../tests/e2e/web",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  // A flaky browser assertion is a failed Phase 1 evidence gate, including in CI.
  retries: 0,
  // Bound route-compilation concurrency so Next dev HMR cannot replace a page
  // between an interaction and its same-origin request on smaller CI runners.
  workers: process.env.CI ? 2 : 4,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: "http://127.0.0.1:3000",
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium-desktop",
      use: { ...devices["Desktop Chrome"] },
    },
    {
      name: "chromium-mobile",
      use: {
        ...devices["Pixel 7"],
        deviceScaleFactor: 2,
        viewport: { height: 910, width: 432 },
      },
    },
  ],
  webServer: {
    command: "corepack pnpm dev --hostname 127.0.0.1",
    env: {
      PORTFOLIO_E2E_LARGE_COLLECTIONS: "1",
      PORTFOLIO_DEMO_MODE: "1",
    },
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
    url: "http://127.0.0.1:3000",
  },
});
