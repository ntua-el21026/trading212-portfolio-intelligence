import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  expect,
  test,
  type APIRequestContext,
  type Page,
} from "@playwright/test";

const api = "http://127.0.0.1:18000/api/v1";
const account = "f0f5c66e-b128-59b2-a620-83bc8faa4a57";

test.beforeEach(async ({ page }) => {
  page.setDefaultTimeout(15_000);
  await page.goto("/sign-in");
  await page.getByRole("button", { name: "Start local session" }).click();
  await expect(page).toHaveURL("http://127.0.0.1:3001/");
});

async function selection(request: APIRequestContext) {
  expect((await request.post(`${api}/auth/local-session`)).status()).toBe(201);
  const pies = await request.get(`${api}/virtual-portfolios`, {
    params: { account_id: account, state: "active" },
  });
  expect(pies.status()).toBe(200);
  const pie = (await pies.json()).items.find(
    (item: { active_version_id: string | null }) => item.active_version_id,
  );
  expect(pie).toBeTruthy();
  const snapshots = await request.get(`${api}/accounts/${account}/snapshots`, {
    params: { limit: 25 },
  });
  expect(snapshots.status()).toBe(200);
  const snapshot = (await snapshots.json()).items.at(-1);
  expect(snapshot).toBeTruthy();
  return new URLSearchParams({
    account,
    pie: pie.id,
    version: pie.active_version_id,
    snapshot: snapshot.id,
  });
}

async function assertPresentation(page: Page) {
  expect(
    await page.evaluate(
      () =>
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
    ),
  ).toBeLessThanOrEqual(1);
  expect(
    await page.evaluate(() => {
      const problems: string[] = [];
      const ids = [...document.querySelectorAll("[id]")].map((node) => node.id);
      if (ids.length !== new Set(ids).size) problems.push("duplicate ids");
      for (const element of document.querySelectorAll(
        "input,select,textarea",
      )) {
        if (
          element.getAttribute("type") !== "hidden" &&
          !element.closest("label") &&
          !element.getAttribute("aria-label")
        )
          problems.push("unlabelled control");
      }
      for (const table of document.querySelectorAll("table")) {
        if (
          !table.querySelector("caption") &&
          !table.getAttribute("aria-label")
        )
          problems.push("unnamed table");
      }
      if (
        document.querySelectorAll("main").length !== 1 ||
        document.querySelectorAll("h1").length !== 1
      )
        problems.push("landmark count");
      return problems;
    }),
  ).toEqual([]);
  const html = await page.content();
  for (const forbidden of [
    "downloadLink",
    "download_link",
    ["EXPORT", "URL", "CANARY"].join("_"),
  ])
    expect(html).not.toContain(forbidden);
}

async function waitForResult(page: Page, request: APIRequestContext) {
  await expect(page).toHaveURL(/\/planner\/[0-9a-f-]{36}$/);
  const plan = new URL(page.url()).pathname.split("/").at(-1)!;
  await expect(
    page.getByRole("heading", { name: "Allocation result", exact: true }),
  ).toBeVisible({ timeout: 40_000 });
  const detail = await request.get(`${api}/contribution-plans/${plan}`);
  expect(detail.status()).toBe(200);
  const canonical = await detail.json();
  expect(canonical.job.state).toBe("succeeded");
  expect(canonical.execution_allowed).toBe(false);
  expect(canonical.result.execution_allowed).toBe(false);
  const sources = page.getByText("Sources and revision details", {
    exact: true,
  });
  await sources.click();
  await expect(
    page.getByText(canonical.content_digest, { exact: true }),
  ).toBeVisible();
  await sources.click();
  return canonical;
}

test("manual planner preserves invalid input and retains immutable history after cash-only recalculation", async ({
  page,
  request,
}, testInfo) => {
  test.setTimeout(120_000);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (["error", "warning"].includes(message.type()))
      errors.push(message.text());
  });
  const pins = await selection(request);
  await page.goto(`/drift?${pins}`);
  await expect(
    page.getByRole("heading", { name: "Actual versus target", exact: true }),
  ).toBeVisible();
  await assertPresentation(page);
  await page
    .getByRole("link", { name: "Plan a contribution", exact: true })
    .click();
  await page.getByLabel("Contribution (EUR)", { exact: true }).fill("1e2");
  await page
    .getByRole("button", { name: "Calculate contribution plan", exact: true })
    .click();
  await expect(
    page.getByText("Plan could not be queued", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByLabel("Contribution (EUR)", { exact: true }),
  ).toHaveValue("1e2");
  await page.getByLabel("Contribution (EUR)", { exact: true }).fill("20");
  await page
    .getByRole("combobox", { name: "Coverage policy", exact: true })
    .selectOption("allow_degraded");
  await page
    .getByText("Eligible holdings, exclusions and listing preferences", {
      exact: true,
    })
    .click();
  await page.getByLabel("Choose an explicit set of eligible holdings").check();
  await page
    .getByRole("button", { name: "Calculate contribution plan", exact: true })
    .click();
  const original = await waitForResult(page, request);
  expect(original.request.options.mode).toBe("global");
  expect(original.request.options.eligible_holding_ids.length).toBeGreaterThan(
    0,
  );
  for (const line of original.lines.items) {
    expect(line.holding_id).not.toBe(line.node_id);
    expect(original.request.options.eligible_holding_ids).toContain(
      line.holding_id,
    );
  }
  await assertPresentation(page);
  await page.screenshot({
    path: join(tmpdir(), `t212-p2-02-${testInfo.project.name}-plan.png`),
    fullPage: false,
  });
  await page
    .getByRole("link", { name: "Calculate a new revision", exact: true })
    .click();
  await page
    .getByRole("combobox", { name: "Optimization mode", exact: true })
    .selectOption("cash_only");
  await page.getByLabel("Contribution (EUR)", { exact: true }).fill("25");
  await page
    .getByRole("button", { name: "Calculate new revision", exact: true })
    .click();
  const revised = await waitForResult(page, request);
  expect(revised.job.plan_id).toBe(original.job.plan_id);
  expect(revised.job.request_revision).toBe(2);
  expect(revised.request.options.mode).toBe("cash_only");
  expect(revised.result.residual_cash.amount).toBe("25");
  expect(revised.job.plan_revision_id).not.toBe(original.job.plan_revision_id);
  await page
    .getByRole("link", { name: "Revision history", exact: true })
    .click();
  await page.getByRole("link", { name: /^Revision 1 · / }).click();
  const historicalSources = page.getByText("Sources and revision details", {
    exact: true,
  });
  await historicalSources.click();
  await expect(
    page.getByText(original.content_digest, { exact: true }),
  ).toBeVisible();
  await historicalSources.click();
  await expect(
    page.getByRole("heading", { name: /^EUR 20(?:\.00)?$/ }),
  ).toBeVisible();
  await assertPresentation(page);
  expect(errors).toEqual([]);
});

test("hierarchical and restricted modes use saved target groups and explicit effective-coverage disclosure", async ({
  page,
  request,
}) => {
  test.setTimeout(120_000);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const pins = await selection(request);
  await page.goto(`/planner?${pins}`);
  await page.getByLabel("Contribution (EUR)", { exact: true }).fill("10");
  await page
    .getByRole("combobox", { name: "Coverage policy", exact: true })
    .selectOption("allow_degraded");
  await page
    .getByRole("combobox", { name: "Optimization mode", exact: true })
    .selectOption("hierarchical");
  await page
    .getByRole("button", { name: "Calculate contribution plan", exact: true })
    .click();
  const hierarchical = await waitForResult(page, request);
  expect(hierarchical.request.options.mode).toBe("hierarchical");
  await page
    .getByRole("link", { name: "Calculate a new revision", exact: true })
    .click();
  await page
    .getByRole("combobox", { name: "Optimization mode", exact: true })
    .selectOption("restricted");
  await page.getByRole("checkbox", { name: "Growth", exact: true }).check();
  await page
    .getByRole("button", { name: "Calculate new revision", exact: true })
    .click();
  const restricted = await waitForResult(page, request);
  expect(restricted.request.options.mode).toBe("restricted");
  expect(restricted.request.options.restricted_group_ids).toHaveLength(1);
  await page
    .getByRole("link", { name: "View source drift", exact: true })
    .click();
  await page
    .getByRole("combobox", { name: "Ranked drift basis", exact: true })
    .selectOption("effective");
  await page
    .getByRole("button", { name: "Apply drift view", exact: true })
    .click();
  await expect(
    page.getByText("Effective exposure coverage", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText(/Effective weights remain unavailable/),
  ).toBeVisible();
  await assertPresentation(page);
  expect(errors).toEqual([]);
});
