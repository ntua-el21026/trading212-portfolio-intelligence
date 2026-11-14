import { expect, test, type Page, type TestInfo } from "@playwright/test";
import Decimal from "decimal.js";
import {
  AggregateSelectionResponseSchema,
  AggregateRunResponseSchema,
  snapshotDetailSchema,
} from "@trading212/api-contracts";
import { assertAccessible } from "./axe";
import { keyboardClearance } from "./accessibility";
const api = "http://127.0.0.1:18000/api/v1";
const eur = "68a4be96-3a55-596f-8a2d-3c9d8edc47ee";
const usd = "1c9ebf57-80ca-5998-9202-05653a331b80";
async function capture(page: Page, info: TestInfo, state: string) {
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth - innerWidth,
    ),
  ).toBeLessThanOrEqual(1);
  await expect(page.getByRole("main")).toHaveCount(1);
  await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
  await assertAccessible(page);
  await keyboardClearance(page);
  for (const region of await page
    .getByRole("region")
    .filter({ has: page.getByRole("table") })
    .all()) {
    const { left, remaining } = await region.evaluate((element) => ({
      left: element.scrollLeft,
      remaining: element.scrollWidth - element.clientWidth - element.scrollLeft,
    }));
    if (left + remaining <= 1) continue;
    await region.focus();
    await expect(region).toBeFocused();
    await region.press(remaining > 1 ? "ArrowRight" : "ArrowLeft");
    await expect
      .poll(() => region.evaluate((element) => element.scrollLeft))
      .not.toBe(left);
    // Frame the screenshot only after the native key has moved the table.
    await region.evaluate((element, offset) => {
      element.scrollLeft = offset;
    }, left);
  }
  await page.evaluate(() => {
    if (document.activeElement instanceof HTMLElement)
      document.activeElement.blur();
    scrollTo(0, 0);
  });
  await page.screenshot({
    path: info.outputPath(`aggregation-${state}.png`),
    fullPage: true,
  });
}
test("native broker accounts consolidate exact saved sources with explicit FX and coverage", async ({
  page,
  request,
}, info) => {
  test.setTimeout(240_000);
  page.setDefaultTimeout(30_000);
  const width = info.project.name.includes("mobile")
    ? 360
    : info.project.name.includes("tablet")
      ? 768
      : 1440;
  await page.setViewportSize({
    width,
    height: width === 360 ? 800 : width === 768 ? 1024 : 900,
  });
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/sign-in");
  await page.getByRole("button", { name: "Start local session" }).click();
  await expect(page).toHaveURL("http://127.0.0.1:3001/");
  expect((await request.post(`${api}/auth/local-session`)).status()).toBe(201);
  const eurSnapshot = snapshotDetailSchema.parse(
    await (await request.get(`${api}/accounts/${eur}/snapshots/latest`)).json(),
  );
  const usdSnapshot = snapshotDetailSchema.parse(
    await (await request.get(`${api}/accounts/${usd}/snapshots/latest`)).json(),
  );
  const cutoff = new Date().toISOString();
  const title = `Explicit native aggregate ${width}`;
  await page.goto("/aggregation?view=new");
  await page.getByLabel("Aggregate name", { exact: true }).fill(title);
  await page.getByLabel("Reporting currency", { exact: true }).fill("EUR");
  await page
    .getByLabel("Source cutoff (ISO timestamp)", { exact: true })
    .fill(cutoff);
  await page
    .getByRole("combobox", { name: "Included account 1", exact: true })
    .selectOption(eur);
  await expect(
    page.getByRole("combobox", { name: "Saved snapshot 1", exact: true }),
  ).toBeEnabled();
  await page
    .getByRole("combobox", { name: "Saved snapshot 1", exact: true })
    .selectOption(eurSnapshot.id);
  await page.getByRole("button", { name: "Add account", exact: true }).click();
  await page
    .getByRole("combobox", { name: "Included account 2", exact: true })
    .selectOption(usd);
  await expect(
    page.getByRole("combobox", { name: "Saved snapshot 2", exact: true }),
  ).toBeEnabled();
  await page
    .getByRole("combobox", { name: "Saved snapshot 2", exact: true })
    .selectOption(usdSnapshot.id);
  await capture(page, info, "selection");
  await page
    .getByRole("button", { name: "Save aggregate selection", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: title, exact: true }),
  ).toBeVisible();
  const selectionId = new URL(page.url()).searchParams.get("selection");
  expect(selectionId).toBeTruthy();
  const selected = AggregateSelectionResponseSchema.parse(
    await (
      await request.get(`${api}/aggregate-selections/${selectionId}`)
    ).json(),
  );
  expect(selected.content.members).toEqual([
    { account_id: eur, portfolio_snapshot_id: eurSnapshot.id },
    { account_id: usd, portfolio_snapshot_id: usdSnapshot.id },
  ]);
  expect(selected.content.reporting_currency).toBe("EUR");
  expect(new Date(selected.content.source_cutoff_at).toISOString()).toBe(
    cutoff,
  );
  await page
    .getByRole("button", { name: "Calculate aggregate", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Total value", exact: true }),
  ).toBeVisible();
  const firstRun = new URL(page.url()).searchParams.get("run");
  expect(firstRun).toBeTruthy();
  const missingResponse = await request.get(
    `${api}/aggregate-runs/${firstRun}`,
    { params: { view: "holdings", limit: 25 } },
  );
  expect(missingResponse.headers()["cache-control"]).toContain("no-store");
  const missing = AggregateRunResponseSchema.parse(
    await missingResponse.json(),
  );
  if (!missing.page || missing.page.view !== "holdings")
    throw new Error("Expected holdings page");
  expect(missing.page.context.total.value).toBeNull();
  expect(missing.page.context.total.known_count).toBeLessThan(
    missing.page.context.total.total_count,
  );
  await expect(page.getByText(/Known subtotal:/).first()).toBeVisible();
  await capture(page, info, "missing-fx");
  await page
    .getByRole("link", { name: "Selection and calculations", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Add saved FX reference", exact: true })
    .click();
  await page
    .getByRole("combobox", { name: "FX account 1", exact: true })
    .selectOption(usd);
  await page.getByLabel("Original currency 1", { exact: true }).fill("USD");
  await page
    .getByRole("button", { name: "Load saved FX sources 1", exact: true })
    .click();
  const source = page.getByRole("combobox", {
    name: "Saved FX source 1",
    exact: true,
  });
  await expect(source).toBeEnabled();
  await expect(source).toHaveValue("");
  const sourceId = await source
    .locator("option")
    .filter({ hasText: "Synthetic aggregation FX" })
    .getAttribute("value");
  expect(sourceId).toBeTruthy();
  await source.selectOption(sourceId!);
  const observation = page.getByRole("combobox", {
    name: "Saved FX observation 1",
    exact: true,
  });
  await expect(observation).toBeEnabled();
  await expect(observation).toHaveValue("");
  const observationId = await observation
    .locator("option")
    .filter({ hasText: /0\.8(?:0+)? EUR\/USD/ })
    .getAttribute("value");
  expect(observationId).toBeTruthy();
  await observation.selectOption(observationId!);
  await capture(page, info, "explicit-fx");
  await page
    .getByRole("button", { name: "Calculate aggregate", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Total value", exact: true }),
  ).toBeVisible();
  const runId = new URL(page.url()).searchParams.get("run");
  expect(runId).toBeTruthy();
  expect(runId).not.toBe(firstRun);
  const complete = AggregateRunResponseSchema.parse(
    await (
      await request.get(`${api}/aggregate-runs/${runId}`, {
        params: { view: "holdings", limit: 25 },
      })
    ).json(),
  );
  if (!complete.page || complete.page.view !== "holdings")
    throw new Error("Expected holdings page");
  expect(complete.page.context.total.value).not.toBeNull();
  expect(
    new Decimal(complete.page.context.total.value!).equals("248575.27"),
  ).toBe(true);
  expect(complete.page.items).toHaveLength(1);
  expect(new Decimal(complete.page.items[0].quantity).equals("403")).toBe(true);
  expect(complete.page.items[0].account_totals).toHaveLength(2);
  expect(
    complete.page.context.snapshots.map((pin) => pin.valuation_at),
  ).toContain(eurSnapshot.valuation_at);
  expect(
    complete.page.context.snapshots.map((pin) => pin.valuation_at),
  ).toContain(usdSnapshot.valuation_at);
  await expect(
    page
      .locator(`[data-money-value="${complete.page.context.total.value}"]`)
      .first(),
  ).toBeVisible();
  await capture(page, info, "holdings");
  await page
    .getByRole("navigation", { name: "Aggregate result views" })
    .getByRole("link", { name: "Components", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Components", exact: true }),
  ).toBeVisible();
  const usdComponent = page
    .getByRole("table", {
      name: "Original holdings and cash with explicit conversion",
    })
    .getByRole("row")
    .filter({ hasText: "Aggregation USD custody account" })
    .first();
  await usdComponent
    .getByText("Original source identities", { exact: true })
    .click();
  await expect(
    usdComponent.getByText(`FX observation: ${observationId}`, { exact: true }),
  ).toBeVisible();
  await capture(page, info, "components");
  await page.goBack();
  await expect(
    page.getByRole("heading", { name: "Holdings", exact: true }),
  ).toBeVisible();
  await page.goForward();
  await expect(
    page.getByRole("heading", { name: "Components", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("navigation", { name: "Aggregate result views" })
    .getByRole("link", { name: "Accounts", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Accounts", exact: true }),
  ).toBeVisible();
  await capture(page, info, "accounts");
  await page
    .getByRole("navigation", { name: "Aggregate result views" })
    .getByRole("link", { name: "Transfers", exact: true })
    .click();
  await expect(
    page.getByText("Activity was not requested for this calculation.", {
      exact: true,
    }),
  ).toBeVisible();
  await capture(page, info, "unrequested-activity");
  await page
    .getByRole("link", { name: "Selection and calculations", exact: true })
    .click();
  await page.getByLabel("Include transfer evidence", { exact: true }).check();
  const end = [
    eurSnapshot.source_cutoff_at,
    usdSnapshot.source_cutoff_at,
  ].sort()[0];
  const start = new Date(new Date(end).getTime() - 86400000).toISOString();
  await page
    .getByLabel("Activity start (ISO timestamp)", { exact: true })
    .fill(start);
  await page
    .getByLabel("Activity end (ISO timestamp)", { exact: true })
    .fill(end);
  await page
    .getByRole("button", { name: "Calculate aggregate", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Total value", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("navigation", { name: "Aggregate result views" })
    .getByRole("link", { name: "Transfers", exact: true })
    .click();
  await expect(
    page.getByText(/Incomplete or unrequested window coverage/),
  ).toBeVisible();
  await expect(
    page.getByText(
      "Matching transfer legs alone does not establish complete activity coverage or portfolio performance.",
      { exact: true },
    ),
  ).toBeVisible();
  await capture(page, info, "incomplete-activity");
  await page
    .locator('select[aria-label="Portfolio account"]:visible')
    .first()
    .selectOption(usd);
  await expect(
    page.getByRole("heading", {
      name: "Saved aggregate selections",
      exact: true,
    }),
  ).toBeVisible();
  const switched = new URL(page.url()).searchParams;
  expect(switched.get("account")).toBe(usd);
  for (const key of ["selection", "run", "cursor", "table", "view"])
    expect(switched.has(key)).toBe(false);
  await expect(
    page.getByRole("heading", { name: "Transfer coverage", exact: true }),
  ).toHaveCount(0);
  const denied = await request.get(
    `${api}/aggregate-selections/00000000-0000-4000-8000-000000000099`,
  );
  expect([403, 404]).toContain(denied.status());
  expect(await denied.text()).not.toContain(title);
  await page.goto(
    `/aggregation?view=result&selection=${selectionId}&run=${runId}&unexpected=1`,
  );
  await expect(
    page
      .getByRole("status")
      .getByText("Invalid aggregate selection", { exact: true }),
  ).toBeVisible();
  await page.goto(`/settings?account=${usd}`);
  await expect(
    page.getByRole("heading", { name: "Connection & settings", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(page).toHaveURL(/\/sign-in/);
  await page.goto(
    `/aggregation?view=result&selection=${selectionId}&run=${runId}`,
  );
  await expect(page).toHaveURL(/\/sign-in/);
  expect(errors).toEqual([]);
});
