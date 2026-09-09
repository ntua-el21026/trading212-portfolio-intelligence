import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test, type Page } from "@playwright/test";

const root = [process.cwd(), resolve(process.cwd(), "../..")].find(
  (directory) =>
    existsSync(
      resolve(directory, "apps/mcp/src/trading212_mcp/xray_widget.py"),
    ),
);
if (!root) throw new Error("Unable to locate the canonical X-ray widget");
const html = execFileSync(
  "uv",
  [
    "run",
    "python",
    "-c",
    "from trading212_mcp.xray_widget import XRAY_WIDGET_HTML; print(XRAY_WIDGET_HTML)",
  ],
  { cwd: root, encoding: "utf8" },
);
// These are presentation-boundary fixtures, not evidence of calculated financial results.
const known = (value: string | { amount: string; currency: string }) => ({
  value,
  availability: "available",
  reason: null,
  quality: "fresh",
  bound: "exact",
});
const unavailable = {
  value: null,
  availability: "unavailable",
  reason: "missing_fx",
  quality: "partial",
  bound: "exact",
};
const amount = "99999999999999999999.123456789012345678";
const context = {
  valuation_at: "2026-08-31T12:00:00Z",
  source_cutoff_at: "2026-09-07T12:34:56.123456Z",
  quality_evaluated_at: "2026-08-31T12:00:00Z",
  method: { name: "xray_v1", version: "1.1.0" },
  access: { reproducibility: "reproducible" },
  content_digest: "a".repeat(64),
  source_count: 65,
  source_omitted_count: 1,
  sources: [
    {
      kind: "constituents",
      provider_name: "Synthetic source",
      source_at: "2026-08-01T12:00:00Z",
      quality: "stale",
      confidence: null,
    },
  ],
  warnings: [{ code: "<img src=x onerror=alert(1)>" }],
  warning_omitted_count: 2,
};
const summary = {
  total: known({ amount, currency: "EUR" }),
  company_known_weight: known("0.95"),
  unresolved_weight: {
    ...known("0"),
    quality: "partial",
    positive_below_quantum: true,
  },
  duplicated_exposure: { ...known("0.41"), bound: "lower_bound" },
  hhi: known("0.4657"),
  quality_coverage: {
    root_count: 7,
    valued_root_count: 7,
    direct_portfolio_value: known({ amount, currency: "EUR" }),
    direct_portfolio_weight: known("1"),
    inferred_mapping_count: 1,
    inferred_value: known({ amount: "50", currency: "EUR" }),
    inferred_weight: known("0.05"),
    stale_value: known({ amount: "500", currency: "EUR" }),
    stale_weight: known("0.5"),
  },
};
const exposure = {
  name: "Synthetic Alpha",
  direct: known({ amount: "200", currency: "EUR" }),
  indirect: unavailable,
  effective: known({ amount: "560", currency: "EUR" }),
};
async function publish(page: Page, data: object) {
  await page.evaluate(
    (value) =>
      window.postMessage(
        {
          jsonrpc: "2.0",
          method: "ui/notifications/tool-result",
          params: {
            structuredContent: {
              data: value,
              error: null,
              selection: { total: 2, returned: 1, omitted: 1 },
            },
          },
        },
        "*",
      ),
    data,
  );
}

test("X-ray widget displays exact money, unresolved mass and source provenance without network requests", async ({
  page,
}, testInfo) => {
  const requests: string[] = [],
    errors: string[] = [];
  page.on("request", (request) => requests.push(request.url()));
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  await page.setContent(html, { waitUntil: "domcontentloaded" });
  await publish(page, {
    view: "exposures",
    context,
    summary,
    dimension_summary: { dimension: "company" },
    exposures: { items: [exposure] },
  });
  await expect(page.locator("#total")).toHaveText(`${amount} EUR; fresh`);
  await expect(page.locator("#unresolved")).toContainText(
    "positive below display precision",
  );
  await expect(page.locator("#duplication")).toContainText(
    "0.41 (lower bound)",
  );
  await expect(page.locator("#rows tr")).toHaveCount(1);
  await expect(page.locator("#rows")).toContainText("Unavailable: missing_fx");
  await expect(page.locator("#sources")).toContainText(
    "confidence unknown; stale",
  );
  await expect(page.locator("#source-count")).toContainText(
    "65 pinned source references; 1 omitted",
  );
  await expect(page.locator("#warnings")).toContainText(
    "<img src=x onerror=alert(1)>",
  );
  await expect(page.locator("#warnings")).toContainText(
    "2 additional warnings",
  );
  await expect(page.locator("#cutoff")).toHaveText(context.source_cutoff_at);
  await expect(page.locator("#quality-at")).toHaveText(
    context.quality_evaluated_at,
  );
  await expect(page.locator("img,a,input,button,iframe")).toHaveCount(0);
  const region = page.getByRole("region", { name: "Effective exposure rows" });
  await region.focus();
  await expect(region).toBeFocused();
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
    path: `/tmp/t212-p2-05-${testInfo.project.name}-xray-widget.png`,
    fullPage: true,
  });
});

test("X-ray widget rejects untrusted and oversized input then preserves canonical overlap and omissions", async ({
  page,
}) => {
  await page.setContent(html, { waitUntil: "domcontentloaded" });
  const data = {
    view: "exposures",
    context,
    summary,
    dimension_summary: { dimension: "company" },
    exposures: { items: [exposure] },
  };
  await page.evaluate(
    (value) =>
      window.dispatchEvent(
        new MessageEvent("message", {
          source: null,
          data: {
            jsonrpc: "2.0",
            method: "ui/notifications/tool-result",
            params: { data: value },
          },
        }),
      ),
    data,
  );
  await expect(page.locator("#content")).toBeHidden();
  await publish(page, {
    ...data,
    exposures: { items: Array(101).fill(exposure) },
  });
  await expect(page.locator("#content")).toBeHidden();
  await expect(page.locator("#status")).toContainText("unavailable");
  await publish(page, {
    view: "mcp_top_pair",
    context,
    summary,
    pair: {
      left: { name: "Atlas", unit_coverage: known("0.9") },
      right: { name: "Horizon", unit_coverage: known("1") },
      overlap: { ...known("0.5"), bound: "lower_bound" },
    },
    omitted_common_weight: known("0.3"),
    common_entities: [
      {
        name: "Synthetic Alpha",
        left_weight: known("0.6"),
        right_weight: known("0.2"),
        common_weight: known("0.2"),
      },
    ],
  });
  await expect(page.locator("#pair-title")).toHaveText("Atlas / Horizon");
  await expect(page.locator("#pair-value")).toHaveText(
    "0.5 (lower bound); fresh",
  );
  await expect(page.locator("#omitted-weight")).toHaveText("0.3; fresh");
  await expect(page.locator("#selection")).toHaveText(
    "1 returned of 2; 1 not in this response.",
  );
  await expect(page.locator("#rows tr")).toHaveCount(1);
});
