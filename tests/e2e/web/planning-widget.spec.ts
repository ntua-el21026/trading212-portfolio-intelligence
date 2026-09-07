import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test } from "@playwright/test";

const root = [process.cwd(), resolve(process.cwd(), "../..")].find(
  (directory) =>
    existsSync(
      resolve(directory, "apps/mcp/src/trading212_mcp/planning_widget.py"),
    ),
);
if (!root) throw new Error("Unable to locate the canonical planning widget");
const html = execFileSync(
  "uv",
  [
    "run",
    "python",
    "-c",
    "from trading212_mcp.planning_widget import PLAN_WIDGET_HTML; print(PLAN_WIDGET_HTML)",
  ],
  { cwd: root, encoding: "utf8" },
);
const job = {
  plan_id: "00000000-0000-0000-0000-000000000001",
  request_id: "00000000-0000-0000-0000-000000000002",
  state: "queued",
  execution_allowed: false,
};

test("planning widget distinguishes pending results and renders exact saved values without network or execution", async ({
  page,
}) => {
  const requests: string[] = [];
  const errors: string[] = [];
  page.on("request", (request) => requests.push(request.url()));
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  await page.setContent(html, { waitUntil: "domcontentloaded" });
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
    { data: job, error: null, execution_allowed: false },
  );
  await expect(page.locator("#status")).toHaveText(
    "Job state: queued. Execution is disabled.",
  );
  await expect(page.locator("#outcome")).toHaveText("Not calculated");
  await expect(page.locator("#rows tr")).toHaveCount(0);
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
      data: {
        job: { ...job, state: "succeeded" },
        content_digest: "a".repeat(64),
        result: {
          outcome: "feasible_nonoptimal",
          execution_allowed: false,
          contribution: { amount, currency: "EUR" },
          residual_cash: { amount: "0.01", currency: "EUR" },
          context: {
            availability: "partial",
            data_quality: { state: "unreconciled" },
            method: { name: "contribution_weighted_drift_v1" },
          },
        },
        lines: {
          items: [
            {
              node_key: "<img src=x onerror=alert(1)>",
              recommended_amount: { amount, currency: "EUR" },
              post_value: { amount: "1.000000000000000001", currency: "EUR" },
            },
          ],
        },
      },
      pagination: { truncated: true },
      error: null,
      execution_allowed: false,
    },
  );
  await expect(page.locator("#contribution")).toHaveText(`${amount} EUR`);
  await expect(page.locator("#quality")).toHaveText("unreconciled");
  await expect(page.locator("#coverage")).toHaveText("partial");
  await expect(page.locator("#outcome")).toHaveText("feasible_nonoptimal");
  await expect(page.locator("#rows td").first()).toHaveText(
    "<img src=x onerror=alert(1)>",
  );
  await expect(page.locator("img,button,a,input,iframe")).toHaveCount(0);
  await expect(page.locator("#page-note")).toContainText(
    "Totals describe the complete saved plan",
  );
  expect(
    await page.evaluate(
      () =>
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
    ),
  ).toBeLessThanOrEqual(1);
  expect(requests).toEqual([]);
  expect(errors).toEqual([]);
});

test("planning widget rejects untrusted message sources and execution-capable payloads", async ({
  page,
}) => {
  await page.setContent(html, { waitUntil: "domcontentloaded" });
  await page.evaluate(
    (value) =>
      window.dispatchEvent(
        new MessageEvent("message", {
          source: null,
          data: {
            jsonrpc: "2.0",
            method: "ui/notifications/tool-result",
            params: value,
          },
        }),
      ),
    { data: job, error: null, execution_allowed: false },
  );
  await expect(page.locator("#content")).toBeHidden();
  await page.evaluate(
    (value) =>
      window.postMessage(
        {
          jsonrpc: "2.0",
          method: "ui/notifications/tool-result",
          params: value,
        },
        "*",
      ),
    {
      data: { ...job, execution_allowed: true },
      error: null,
      execution_allowed: false,
    },
  );
  await expect(page.locator("#status")).toHaveText(
    "The planning response does not match its contract.",
  );
  await expect(page.locator("#content")).toBeHidden();
});
