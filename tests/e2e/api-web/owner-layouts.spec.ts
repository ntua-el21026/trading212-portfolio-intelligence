import { expect, test, type Page, type TestInfo } from "@playwright/test";
import {
  PremiumProviderStatusResponseSchema,
  OwnerLayoutPageSchema,
  OwnerLayoutViewSchema,
  XrayExposuresResponseSchema,
  accountSummarySchema,
  directAllocationSchema,
  pageSchema,
  positionSchema,
  snapshotDetailSchema,
} from "@trading212/api-contracts";
import { keyboardClearance } from "./accessibility";
import { assertAccessible } from "./axe";
const api = "http://127.0.0.1:18000/api/v1";
const account = "86ecdc4c-6c42-5593-84ed-de7bde3a6c4c";
const otherAccount = "f0f5c66e-b128-59b2-a620-83bc8faa4a57";
const href = (values: Record<string, string>) =>
  `/settings/layouts?${new URLSearchParams(values)}`;
async function capture(page: Page, info: TestInfo, name: string) {
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth - innerWidth,
    ),
  ).toBeLessThanOrEqual(1);
  await expect(page.getByRole("main")).toHaveCount(1);
  await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
  await assertAccessible(page);
  await keyboardClearance(page);
  await page.evaluate(() => {
    if (document.activeElement instanceof HTMLElement)
      document.activeElement.blur();
    scrollTo(0, 0);
  });
  await page.screenshot({
    path: info.outputPath(`owner-layout-${name}.png`),
    fullPage: true,
  });
}

test("durable owner layouts preserve exact views, canonical previews, immutable versions and account privacy", async ({
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
  const snapshot = snapshotDetailSchema.parse(
    await (
      await request.get(`${api}/accounts/${account}/snapshots/latest`)
    ).json(),
  );
  const xrayParams = {
    snapshot_id: snapshot.id,
    source_cutoff_at: snapshot.source_cutoff_at,
    reporting_currency: "EUR",
    limit: 25,
  };
  const xray = XrayExposuresResponseSchema.parse(
    await (
      await request.get(`${api}/accounts/${account}/effective-exposure`, {
        params: xrayParams,
      })
    ).json(),
  );
  const summary = accountSummarySchema.parse(
    await (await request.get(`${api}/accounts/${account}/summary`)).json(),
  );
  const allocation = directAllocationSchema.parse(
    await (
      await request.get(`${api}/accounts/${account}/allocation`, {
        params: { limit: 5 },
      })
    ).json(),
  );
  const positions = pageSchema(positionSchema).parse(
    await (
      await request.get(`${api}/accounts/${account}/positions`, {
        params: { limit: 5, sort: "market_value_desc" },
      })
    ).json(),
  );

  // First prove an owner template can be persisted with no account selection.
  await page.goto(href({ mode: "edit" }));
  await page.getByLabel("Layout name", { exact: true }).fill("Owner template");
  await page
    .getByRole("button", { name: "Create layout", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Owner template", exact: true }),
  ).toBeVisible();
  expect(new URL(page.url()).searchParams.has("account")).toBe(false);
  await expect(
    page.getByRole("status").getByText("Choose an account", { exact: true }),
  ).toBeVisible();
  await capture(page, info, "template");

  await page.goto(href({ mode: "edit", account }));
  await page
    .getByLabel("Layout name", { exact: true })
    .fill("Daily saved portfolio");
  await page
    .getByLabel("Description", { exact: true })
    .fill("Explicit original views; owner-authored description.");
  for (const kind of [
    "direct_allocation",
    "holdings_preview",
    "data_quality",
    "saved_view",
  ]) {
    await page.getByRole("button", { name: "Add widget", exact: true }).click();
    await page
      .getByRole("combobox", { name: "Widget type", exact: true })
      .last()
      .selectOption(kind);
  }
  await page
    .getByRole("combobox", { name: "Selection type", exact: true })
    .selectOption("saved_run");
  await page
    .getByRole("combobox", { name: "Saved run family", exact: true })
    .selectOption("xray");
  await page
    .getByLabel("Saved run ID", { exact: true })
    .fill(xray.context.run_id);
  await page
    .getByLabel("Original X-ray snapshot ID", { exact: true })
    .fill(snapshot.id);
  await page
    .getByLabel("Original X-ray cutoff (ISO timestamp)", { exact: true })
    .fill(xray.context.source_cutoff_at);
  await page
    .getByLabel("Original X-ray reporting currency", { exact: true })
    .fill(xray.context.reporting_currency);
  // The explicit move controls work with a keyboard without drag support.
  await page
    .getByRole("button", { name: "Move widget 5 up", exact: true })
    .focus();
  await page.keyboard.press("Enter");
  await expect(
    page.getByRole("combobox", { name: "Widget type", exact: true }).nth(3),
  ).toHaveValue("saved_view");
  await capture(page, info, "editor");
  await page
    .getByRole("button", { name: "Create layout", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Daily saved portfolio", exact: true }),
  ).toBeVisible();
  const layoutId = new URL(page.url()).searchParams.get("layout");
  expect(layoutId).not.toBeNull();
  const originalResponse = await request.get(
    `${api}/preferences/layouts/${layoutId}`,
  );
  expect(originalResponse.status()).toBe(200);
  expect(originalResponse.headers()["cache-control"]).toContain("no-store");
  const original = OwnerLayoutViewSchema.parse(await originalResponse.json());
  expect(original.content.account_id).toBe(account);
  expect(original.content.widgets.map((widget) => widget.kind)).toEqual([
    "portfolio_summary",
    "direct_allocation",
    "holdings_preview",
    "saved_view",
    "data_quality",
  ]);
  expect(original.content.widgets[3].selection).toEqual({
    kind: "saved_run",
    family: "xray",
    run_id: xray.context.run_id,
    pane: "result",
    snapshot_id: snapshot.id,
    source_cutoff_at: xray.context.source_cutoff_at,
    reporting_currency: xray.context.reporting_currency,
  });
  for (const [label, metric] of [
    ["Total portfolio value", summary.total_value],
    ["Cash", summary.cash_balance],
    ["Invested value", summary.invested_value],
    ["Net contributions", summary.net_contributions],
  ] as const)
    await expect(page.locator(`[data-layout-metric="${label}"]`)).toHaveText(
      `${metric.value ?? "Unavailable"} ${metric.reporting_currency}`,
    );
  const allocationRows = page
    .getByRole("table", {
      name: "Exact direct allocation preview",
      exact: true,
    })
    .locator("tbody tr");
  await expect(allocationRows).toHaveCount(allocation.items.length);
  for (const [index, row] of allocation.items.entries()) {
    await expect(allocationRows.nth(index)).toContainText(row.label);
    await expect(allocationRows.nth(index)).toContainText(
      `${row.market_value.value ?? "Unavailable"} ${row.market_value.reporting_currency}`,
    );
    await expect(allocationRows.nth(index).locator("td").last()).toHaveText(
      row.weight ?? "Unavailable",
    );
  }
  const positionRows = page
    .getByRole("table", { name: "Exact holdings preview", exact: true })
    .locator("tbody tr");
  await expect(positionRows).toHaveCount(positions.items.length);
  for (const [index, row] of positions.items.entries()) {
    await expect(positionRows.nth(index).locator("td").nth(0)).toHaveText(
      row.quantity,
    );
    await expect(positionRows.nth(index)).toContainText(
      `${row.current_price ?? "Unavailable"} ${row.trading_currency}`,
    );
    await expect(positionRows.nth(index)).toContainText(
      `${row.market_value.value ?? "Unavailable"} ${row.market_value.reporting_currency}`,
    );
  }
  await capture(page, info, "canonical-preview");
  const savedLink = page.getByRole("link", {
    name: "Open saved view 4",
    exact: true,
  });
  const savedHref = await savedLink.getAttribute("href");
  expect(savedHref).not.toBeNull();
  const savedQuery = new URL(savedHref!, "http://127.0.0.1:3001").searchParams;
  expect(Object.fromEntries(savedQuery)).toEqual({
    account,
    run: xray.context.run_id,
    view: "exposures",
    snapshot: snapshot.id,
    cutoff: xray.context.source_cutoff_at,
    currency: xray.context.reporting_currency,
  });
  await savedLink.click();
  await expect(page).toHaveURL(new RegExp(`/xray\\?`));
  expect(new URL(page.url()).searchParams.get("run")).toBe(xray.context.run_id);
  await page.goBack();
  await expect(
    page.getByRole("heading", { name: "Daily saved portfolio", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("link", { name: "Edit as new version", exact: true })
    .click();
  await page
    .getByLabel("Layout name", { exact: true })
    .fill("Daily saved portfolio revised");
  await page
    .getByRole("button", { name: "Save as new version", exact: true })
    .click();
  await expect(
    page.getByRole("heading", {
      name: "Daily saved portfolio revised",
      exact: true,
    }),
  ).toBeVisible();
  const revised = OwnerLayoutViewSchema.parse(
    await (await request.get(`${api}/preferences/layouts/${layoutId}`)).json(),
  );
  expect(revised.revision).toBe(2);
  expect(revised.version.id).not.toBe(original.version.id);
  expect(revised.content.widgets).toEqual(original.content.widgets);
  const firstVersion = OwnerLayoutViewSchema.parse(
    await (
      await request.get(`${api}/preferences/layouts/${layoutId}`, {
        params: { version_id: original.version.id },
      })
    ).json(),
  );
  expect(firstVersion.version).toEqual(original.version);
  expect(firstVersion.content).toEqual(original.content);
  await page.getByText("Immutable version history", { exact: true }).click();
  await page.getByRole("link", { name: "Version 1", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Daily saved portfolio", exact: true }),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Daily saved portfolio", exact: true }),
  ).toBeVisible();
  await capture(page, info, "immutable-history");
  await page
    .getByRole("combobox", { name: "Portfolio account", exact: true })
    .selectOption(otherAccount);
  await expect
    .poll(() => new URL(page.url()).searchParams.get("account"))
    .toBe(otherAccount);
  expect([...new URL(page.url()).searchParams.keys()]).toEqual(["account"]);
  await expect(page.locator("[data-layout-metric]")).toHaveCount(0);
  await page.goto(
    href({ account: otherAccount, layout: layoutId!, mode: "view" }),
  );
  await expect(
    page.getByText("Layout account differs", { exact: true }),
  ).toBeVisible();
  await expect(page.locator("[data-layout-metric]")).toHaveCount(0);
  await capture(page, info, "account-denial");
  await page.goto(href({ account, layout: layoutId!, mode: "view" }));
  await page
    .getByRole("button", { name: "Archive layout", exact: true })
    .click();
  await expect
    .poll(() => new URL(page.url()).searchParams.get("archived"))
    .toBe("true");
  const listed = OwnerLayoutPageSchema.parse(
    await (
      await request.get(`${api}/preferences/layouts`, {
        params: { include_archived: true },
      })
    ).json(),
  );
  expect(listed.items.find((item) => item.id === layoutId)).toMatchObject({
    revision: 3,
    state: "archived",
  });
  const afterXray = XrayExposuresResponseSchema.parse(
    await (
      await request.get(`${api}/accounts/${account}/effective-exposure`, {
        params: { ...xrayParams, run_id: xray.context.run_id },
      })
    ).json(),
  );
  expect(afterXray.context.content_digest).toBe(xray.context.content_digest);
  expect(afterXray.exposures).toEqual(xray.exposures);
  const storage = await page.evaluate(async () => {
    const cachedRequests: string[] = [];
    for (const name of await caches.keys())
      for (const entry of await (await caches.open(name)).keys())
        cachedRequests.push(entry.url);
    return {
      local: { ...localStorage },
      session: { ...sessionStorage },
      cachedRequests,
    };
  });
  const stored = JSON.stringify(storage);
  expect(stored).not.toContain(layoutId!);
  expect(stored).not.toContain("Daily saved portfolio");
  expect(
    storage.cachedRequests.some(
      (url) =>
        url.includes("/api/v1/preferences") || url.includes("/api/v1/accounts"),
    ),
  ).toBe(false);
  await page.goto(`/settings?account=${account}`);
  const statusResponse = await request.get(
    `${api}/accounts/${account}/premium-providers`,
  );
  expect(statusResponse.status()).toBe(200);
  expect(statusResponse.headers()["cache-control"]).toContain("no-store");
  const providerStatus = PremiumProviderStatusResponseSchema.parse(
    await statusResponse.json(),
  );
  expect(providerStatus.account_id).toBe(account);
  expect(providerStatus.credential_verification).toBe("unavailable");
  expect(providerStatus.live_verification).toBe("unavailable");
  expect(
    providerStatus.providers.flatMap((provider) => provider.capabilities),
  ).toHaveLength(5);
  expect(
    providerStatus.providers.map((provider) => ({
      provider: provider.provider,
      reasons: provider.capabilities.map((capability) => capability.reason),
      states: provider.capabilities.map((capability) => capability.state),
    })),
  ).toEqual([
    {
      provider: "alpha_vantage",
      reasons: Array(4).fill("credential_configuration_required"),
      states: Array(4).fill("not_configured"),
    },
    {
      provider: "ecb",
      reasons: ["outbound_disabled"],
      states: ["not_configured"],
    },
  ]);
  await expect(
    page.getByRole("heading", { name: "Premium provider status", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Provider acquisition is disabled.", { exact: true }),
  ).toHaveCount(1);
  await expect(
    page.getByText(
      "A credential port must be configured. No credential has been checked.",
      { exact: true },
    ),
  ).toHaveCount(4);
  await capture(page, info, "provider-settings");
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(page).toHaveURL(/\/sign-in/);
  await page.goto(href({ account, layout: layoutId!, mode: "view" }));
  await expect(page).toHaveURL(/\/sign-in/);
  await expect(
    page.getByText("Daily saved portfolio revised", { exact: true }),
  ).toHaveCount(0);
  expect(errors).toEqual([]);
});
