import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test } from "@playwright/test";

const root = [process.cwd(), resolve(process.cwd(), "../..")].find(
  (directory) =>
    existsSync(resolve(directory, "apps/mcp/src/trading212_mcp/widget.py")),
);
if (!root) throw new Error("Unable to locate the versioned MCP widget source");
const widgetHtml = execFileSync(
  "uv",
  [
    "run",
    "python",
    "-c",
    "from trading212_mcp.widget import SNAPSHOT_WIDGET_HTML; print(SNAPSHOT_WIDGET_HTML)",
  ],
  { cwd: root, encoding: "utf8" },
);

const fixture = {
  as_of: "2026-08-31T10:00:00Z",
  reporting_currency: "EUR",
  data_quality: {
    state: "fresh",
  },
  error: null,
  data: {
    total_value: { value: "248431.27", reporting_currency: "EUR" },
    invested_value: { value: "236086.6", reporting_currency: "EUR" },
    cash_value: { value: "12344.67", reporting_currency: "EUR" },
    net_contributions: { value: "200000", reporting_currency: "EUR" },
    synthetic_data: true,
    quality_disclosure:
      "Quality is fresh; source cutoff is 2026-08-31T09:58:00Z.",
  },
};

test("versioned MCP snapshot widget renders a safe responsive fallback", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  const bootstrap = `<script>window.openai = { toolOutput: ${JSON.stringify(
    fixture,
  )} };</script>`;
  const html = widgetHtml.replace("<head>", `<head>${bootstrap}`);

  await page.setContent(html, { waitUntil: "domcontentloaded" });

  await expect(
    page.getByRole("heading", { name: "Portfolio snapshot" }),
  ).toBeVisible();
  await expect(page.getByText("Read-only", { exact: true })).toBeVisible();
  await expect(page.getByText("Synthetic data", { exact: true })).toBeVisible();
  await expect(page.getByText("Quality: fresh", { exact: true })).toBeVisible();
  await expect(page.locator("#total-value")).toHaveText("248431.27 EUR");
  await expect(page.getByText(/cannot place trades/i)).toBeVisible();
  await expect(page.locator("#empty")).toBeHidden();

  const overflow = await page.evaluate(
    () =>
      document.documentElement.scrollWidth -
      document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(1);
  expect(errors).toEqual([]);
});
