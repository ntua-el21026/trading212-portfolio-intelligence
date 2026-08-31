import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

import { expect, test } from "@playwright/test";

const widgetPath = [
  resolve(process.cwd(), "apps/mcp/src/trading212_mcp/widget.py"),
  resolve(process.cwd(), "../../apps/mcp/src/trading212_mcp/widget.py"),
].find(existsSync);
if (!widgetPath)
  throw new Error("Unable to locate the versioned MCP widget source");
const widgetSource = readFileSync(widgetPath, "utf8");
const match = widgetSource.match(
  /SNAPSHOT_WIDGET_HTML = r"""([\s\S]*?)"""\.strip\(\)/,
);
if (!match) throw new Error("Unable to extract the versioned MCP widget HTML");

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
  const html = match[1].replace("<head>", `<head>${bootstrap}`);

  await page.setContent(html, { waitUntil: "domcontentloaded" });

  await expect(
    page.getByRole("heading", { name: "Portfolio snapshot" }),
  ).toBeVisible();
  await expect(page.getByText("Read-only", { exact: true })).toBeVisible();
  await expect(page.getByText("Synthetic data", { exact: true })).toBeVisible();
  await expect(page.getByText("Quality: fresh", { exact: true })).toBeVisible();
  await expect(page.getByText(/€248,431\.27/)).toBeVisible();
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
