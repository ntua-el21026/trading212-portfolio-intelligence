import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test, type Page } from "@playwright/test";

const root = [process.cwd(), resolve(process.cwd(), "../..")].find(
  (directory) =>
    existsSync(
      resolve(directory, "apps/mcp/src/trading212_mcp/report_widget.py"),
    ),
);
if (!root) throw new Error("Unable to locate the canonical report widget");
const html = execFileSync(
  "uv",
  [
    "run",
    "python",
    "-c",
    "from trading212_mcp.report_widget import REPORT_WIDGET_HTML; print(REPORT_WIDGET_HTML)",
  ],
  { cwd: root, encoding: "utf8" },
);
const id = "00000000-0000-4000-8000-000000000001";
// Presentation fixtures, not financial calculation or report generation evidence.
const job = {
  job_id: id,
  report_id: null,
  state: "queued",
  report_type: "portfolio_summary",
  formats: ["pdf", "json"],
  expires_at: "2026-09-14T12:00:00Z",
  failure_code: null,
  manifest_digest: null,
  context: {
    snapshot_id: id,
    valuation_at: "2026-09-07T12:00:00Z",
    source_cutoff_at: "2026-09-07T12:00:00Z",
    reporting_currency: "EUR",
    input_digest: "a".repeat(64),
    pins: [
      {
        family: "snapshot",
        role: "snapshot",
        subject_id: id,
        content_digest: "b".repeat(64),
      },
    ],
    quality: {
      state: "partial",
      availability: "partial",
      warnings: [{ text: "Synthetic coverage is partial." }],
      warning_omitted_count: 2,
    },
  },
};
async function publish(page: Page, envelope: object) {
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
    envelope,
  );
}

test("report widget preserves saved pins, partial state and counted warnings without network or grant actions", async ({
  page,
}) => {
  const requests: string[] = [],
    errors: string[] = [];
  page.on("request", (request) => requests.push(request.url()));
  page.on("pageerror", (error) => errors.push(error.message));
  await page.setContent(html, { waitUntil: "domcontentloaded" });
  await publish(page, { data: job, error: null, execution_allowed: false });
  await expect(page.locator("#status")).toHaveText("Report state: queued.");
  await expect(page.locator("#snapshot")).toHaveText(id);
  await expect(page.locator("#quality")).toHaveText("partial");
  await page.getByText("Immutable input pins", { exact: true }).click();
  await expect(page.locator("#pins")).toContainText("b".repeat(64));
  await page.getByText("Warnings", { exact: true }).click();
  await expect(page.locator("#warnings")).toHaveText(
    "Synthetic coverage is partial.",
  );
  await expect(page.locator("#warning-note")).toContainText(
    "2 additional warning records",
  );
  expect(await page.locator("button, form, a[href]").count()).toBe(0);
  expect(requests).toEqual([]);
  expect(errors).toEqual([]);
});

test("report widget renders all terminal states and clears purged source detail", async ({
  page,
}) => {
  await page.setContent(html, { waitUntil: "domcontentloaded" });
  for (const state of [
    "queued",
    "running",
    "succeeded",
    "failed",
    "expired",
    "cancelled",
  ]) {
    await publish(page, {
      data: {
        ...job,
        state,
        context: ["expired", "cancelled"].includes(state) ? null : job.context,
      },
      error: null,
      execution_allowed: false,
    });
    await expect(page.locator("#status")).toHaveText(`Report state: ${state}.`);
    await expect(page.locator("#content")).toBeVisible();
    if (["expired", "cancelled"].includes(state)) {
      await expect(page.locator("#snapshot")).toHaveText(
        "Expired or purged source detail",
      );
      await expect(page.locator("#pins li")).toHaveCount(0);
    }
  }
  await publish(page, {
    data: { ...job, context: null },
    error: null,
    execution_allowed: false,
  });
  await expect(page.locator("#content")).toBeHidden();
  await expect(page.locator("#status")).toContainText(
    "does not match its contract",
  );
});

test("report widget treats injected markup as text and hides stale results on errors", async ({
  page,
}) => {
  await page.setContent(html, { waitUntil: "domcontentloaded" });
  const malicious = '<img src="https://private.invalid/" onerror="alert(1)">';
  await publish(page, {
    data: {
      ...job,
      context: {
        ...job.context,
        quality: { ...job.context.quality, warnings: [{ text: malicious }] },
      },
    },
    error: null,
    execution_allowed: false,
  });
  await page.getByText("Warnings", { exact: true }).click();
  await expect(page.locator("#warnings")).toHaveText(malicious);
  await expect(page.locator("img")).toHaveCount(0);
  await publish(page, {
    data: null,
    error: { code: "ACCESS_DENIED", message: "private-token-canary" },
    execution_allowed: false,
  });
  await expect(page.locator("#content")).toBeHidden();
  await expect(page.locator("#status")).toContainText(
    "Report data is unavailable",
  );
  await expect(page.locator("body")).not.toContainText("private-token-canary");
});
