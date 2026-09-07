import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test } from "@playwright/test";

const root = [process.cwd(), resolve(process.cwd(), "../..")].find(
  (directory) =>
    existsSync(
      resolve(directory, "apps/mcp/src/trading212_mcp/historical_widget.py"),
    ),
);
if (!root) throw new Error("Unable to locate the canonical historical widget");
const html = execFileSync(
  "uv",
  [
    "run",
    "python",
    "-c",
    "from trading212_mcp.historical_widget import HISTORICAL_WIDGET_HTML; print(HISTORICAL_WIDGET_HTML)",
  ],
  { cwd: root, encoding: "utf8" },
);
const known = (value: string | { amount: string; currency: string }) => ({
  value,
  availability: "available",
  reason_code: null,
});
const unavailable = {
  value: null,
  availability: "unavailable",
  reason_code: "unavailable_fx",
};
const context = {
  availability: "partial",
  quality: "partial",
  window: {
    start_date: "2025-01-01",
    end_date: "2025-12-31",
    source_cutoff_at: "2026-08-31T12:34:56.123456Z",
  },
  method: { name: "performance_v2", version: "1.0.0" },
  reconstruction: "restated",
  access: { reproducibility: "reproducible" },
  content_digest: "a".repeat(64),
  source_count: 67,
  source_omitted_count: 3,
  warnings: [{ reason_code: "<img src=x onerror=alert(1)>" }],
  warning_omitted_count: 2,
  coverage: {
    measures: [
      {
        key: "valuation_cells",
        available_count: 363,
        expected_count: 365,
        complete: false,
      },
    ],
  },
};

test("historical widget preserves exact values, coverage and warnings without network or calculations", async ({
  page,
}, testInfo) => {
  const requests: string[] = [];
  const errors: string[] = [];
  page.on("request", (request) => requests.push(request.url()));
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  await page.setContent(html, { waitUntil: "domcontentloaded" });
  const amount = "99999999999999999999.123456789012345678";
  await page.evaluate(
    (value) =>
      window.postMessage(
        {
          jsonrpc: "2.0",
          method: "ui/notifications/tool-result",
          params: { structuredContent: value },
        },
        "*",
      ),
    {
      error: null,
      data: {
        context,
        summary: {
          ending_value: known({ amount, currency: "EUR" }),
          investment_gain: known({ amount: "0.000001", currency: "EUR" }),
        },
        series: [
          {
            date: "2025-01-01",
            portfolio_value: known({ amount: "0", currency: "EUR" }),
            cumulative_return: known("0"),
          },
          {
            date: "2025-12-31",
            portfolio_value: unavailable,
            cumulative_return: unavailable,
          },
        ],
      },
    },
  );
  await expect(page.locator("#primary")).toHaveText(`${amount} EUR`);
  await expect(page.locator("#secondary")).toHaveText("0.000001 EUR");
  await expect(page.locator("#rows tr")).toHaveCount(2);
  await expect(page.locator("#rows tr").first()).toContainText("0 EUR");
  await expect(page.locator("#rows tr").last()).toContainText(
    "Unavailable: unavailable_fx",
  );
  await expect(page.locator("#coverage-note")).toHaveText(
    "valuation_cells: 363/365 (incomplete)",
  );
  await expect(page.locator("#source-note")).toContainText("3 omitted");
  await expect(page.locator("#warning-note")).toContainText(
    "<img src=x onerror=alert(1)>",
  );
  await expect(page.locator("#warning-note")).toContainText(
    "2 additional warnings omitted",
  );
  await expect(page.locator("#access")).toHaveText("reproducible");
  await expect(page.locator("img,a,input,button,iframe")).toHaveCount(0);
  await page.getByRole("region", { name: "Historical observations" }).focus();
  await expect(
    page.getByRole("region", { name: "Historical observations" }),
  ).toBeFocused();
  expect(
    await page.evaluate(
      () =>
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
    ),
  ).toBeLessThanOrEqual(1);
  expect(requests).toEqual([]);
  expect(errors).toEqual([]);
  await page.screenshot({
    path: `/tmp/t212-p2-04-${testInfo.project.name}-historical-widget.png`,
    fullPage: true,
  });
});

test("historical widget rejects untrusted messages and oversized series then renders canonical comparison ratios", async ({
  page,
}) => {
  await page.setContent(html, { waitUntil: "domcontentloaded" });
  const comparison = {
    context,
    summary: {
      portfolio_return: known("0.123456789012345678"),
      benchmark_return: known("0"),
    },
    series: [
      {
        date: "2025-12-31",
        portfolio_wealth: known("1.123456789012345678"),
        benchmark_wealth: known("1"),
      },
    ],
  };
  await page.evaluate(
    (data) =>
      window.dispatchEvent(
        new MessageEvent("message", {
          source: null,
          data: {
            jsonrpc: "2.0",
            method: "ui/notifications/tool-result",
            params: { data },
          },
        }),
      ),
    comparison,
  );
  await expect(page.locator("#content")).toBeHidden();
  for (const data of [
    { ...comparison, series: Array(3662).fill(comparison.series[0]) },
    comparison,
  ]) {
    await page.evaluate(
      (value) =>
        window.postMessage(
          {
            jsonrpc: "2.0",
            method: "ui/notifications/tool-result",
            params: { data: value, error: null },
          },
          "*",
        ),
      data,
    );
    if (data.series.length > 3661) {
      await expect(page.locator("#content")).toBeHidden();
      await expect(page.locator("#status")).toContainText("unavailable");
    } else {
      await expect(page.locator("#primary")).toHaveText("0.123456789012345678");
      await expect(page.locator("#secondary")).toHaveText("0");
      await expect(page.locator("#rows tr")).toHaveCount(1);
      await expect(page.locator("#rows tr")).toContainText(
        "1.123456789012345678",
      );
    }
  }
});
