import { defineConfig, devices } from "@playwright/test";

import base from "./playwright.config";

export default defineConfig({
  ...base,
  testMatch: "snapshot-chart-visual.spec.ts",
  updateSnapshots: "none",
  projects: [
    ...(base.projects ?? []),
    {
      name: "chromium-tablet",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { height: 1024, width: 768 },
        deviceScaleFactor: 2,
      },
    },
  ],
  // A retained development server must not silently replace the fixed demo
  // fixture. ROOT must stop other consumers before this serial visual run.
  webServer: {
    command: "corepack pnpm dev --hostname 127.0.0.1",
    env: {
      PORTFOLIO_E2E_LARGE_COLLECTIONS: "1",
      PORTFOLIO_DEMO_MODE: "1",
    },
    reuseExistingServer: false,
    timeout: 120_000,
    url: "http://127.0.0.1:3000",
  },
});
