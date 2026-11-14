import { keyboardClearance } from "./accessibility";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  expect,
  test,
  type APIRequestContext,
  type Locator,
  type Page,
} from "@playwright/test";
import {
  ContributionPlanDetailSchema,
  type PlanningMoney,
} from "@trading212/api-contracts";
import { formatPercent } from "../../../apps/web/lib/format";
import { formatPlanningMoney } from "../../../apps/web/lib/planning-format";

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
  await keyboardClearance(page);
  expect(
    await page.evaluate(
      () =>
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
    ),
  ).toBeLessThanOrEqual(1);
  for (const table of await page.getByRole("table").all())
    await expect(table).toHaveAccessibleName(/\S/);
  for (const control of await page
    .locator('input:not([type="hidden"]),select,textarea')
    .all()) {
    if (await control.isVisible())
      await expect(control).toHaveAccessibleName(/\S/);
  }
  expect(
    await page.evaluate(() => {
      const problems: string[] = [];
      const ids = [...document.querySelectorAll("[id]")].map((node) => node.id);
      if (ids.length !== new Set(ids).size) problems.push("duplicate ids");
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

// Capture positioning only; callers must finish native keyboard assertions first.
async function showSection(page: Page, heading: string) {
  const banner = await page.getByRole("banner").boundingBox();
  await page.getByRole("heading", { name: heading, exact: true }).evaluate(
    (node, offset) => {
      node.scrollIntoView({ block: "start", behavior: "instant" });
      for (
        let parent = node.parentElement;
        parent;
        parent = parent.parentElement
      ) {
        if (
          /auto|scroll/.test(getComputedStyle(parent).overflowY) &&
          parent.scrollHeight > parent.clientHeight
        ) {
          parent.scrollBy(0, -24);
          return;
        }
      }
      window.scrollBy(0, -offset);
    },
    (banner?.height ?? 0) + 24,
  );
}

function normalizedAmount(value: string) {
  const plain = value.replaceAll(",", "").replace("−", "-");
  expect(plain).toMatch(/^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$/);
  const [whole, fraction = ""] = plain.split(".");
  const significant = fraction.replace(/0+$/, "");
  const normalized = whole + (significant ? `.${significant}` : "");
  return normalized === "-0" ? "0" : normalized;
}

async function exactMoney(value: Locator, money: PlanningMoney | null) {
  if (money === null) {
    await expect(value).toHaveText("Unavailable");
    return;
  }
  await expect(value).toHaveText(
    `${money.currency} ${formatPlanningMoney(money.amount)}`,
  );
  // Independently compare every significant digit after removing display notation.
  // This catches lost precision even if the shared formatter regresses.
  const displayed = (await value.innerText())
    .trim()
    .slice(money.currency.length + 1);
  expect(normalizedAmount(displayed)).toBe(normalizedAmount(money.amount));
}

async function waitForResult(
  page: Page,
  request: APIRequestContext,
  expectedRevision = 1,
) {
  await expect(page).toHaveURL(
    (url) =>
      /^\/planner\/[0-9a-f-]{36}$/u.test(url.pathname) &&
      /^[0-9a-f-]{36}$/u.test(url.searchParams.get("account") ?? "") &&
      !url.searchParams.has("edit") &&
      !url.searchParams.has("revision"),
  );
  const plan = new URL(page.url()).pathname.split("/").at(-1)!;
  await expect(
    page.getByRole("heading", { name: "Allocation result", exact: true }),
  ).toBeVisible({ timeout: 40_000 });
  // A saved plan keeps its previous result visible while a revision is queued.
  await expect
    .poll(
      async () => {
        const response = await request.get(`${api}/contribution-plans/${plan}`);
        expect(response.status()).toBe(200);
        const detail = await response.json();
        return {
          state: detail.job.state,
          revision: detail.job.request_revision,
        };
      },
      { timeout: 40_000 },
    )
    .toEqual({ state: "succeeded", revision: expectedRevision });
  const detail = await request.get(`${api}/contribution-plans/${plan}`);
  expect(detail.status()).toBe(200);
  const canonical = await detail.json();
  const observed = ContributionPlanDetailSchema.parse(canonical);
  if (
    !observed.result ||
    !observed.content_digest ||
    !observed.job.plan_revision_id
  )
    throw new Error(
      "A finalized plan must retain its result, digest and revision.",
    );
  expect(canonical.job.request_revision).toBe(expectedRevision);
  expect(new URL(page.url()).searchParams.get("account")).toBe(
    canonical.job.account_id,
  );
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
  await expect(
    sources.locator("..").locator(".planning-identities dd"),
  ).toHaveText([
    observed.request.snapshot_id,
    observed.request.target_version_id,
    observed.job.input_digest,
    observed.content_digest,
    observed.job.plan_revision_id,
  ]);
  await sources.click();
  const allocation = page
    .getByRole("heading", { name: "Allocation result", exact: true })
    .locator("..");
  for (const [label, money] of [
    ["Residual contribution cash", observed.result.residual_cash],
    ["Total cash after contribution", observed.result.post_cash],
    ["Portfolio after contribution", observed.result.post_total],
  ] as const) {
    await exactMoney(
      allocation.getByText(label, { exact: true }).locator("+ dd"),
      money,
    );
  }
  const rows = allocation
    .getByRole("region", { name: "Contribution allocation lines", exact: true })
    .locator("tbody tr");
  await expect(rows).toHaveCount(observed.lines.items.length);
  expect(
    await rows
      .locator("th")
      .evaluateAll((nodes) =>
        nodes.map((node) => node.firstChild?.textContent?.trim()),
      ),
  ).toEqual(observed.lines.items.map((line) => line.node_key));
  for (const [index, line] of observed.lines.items.entries()) {
    const row = rows.nth(index);
    const cells = row.locator("td");
    await expect(cells).toHaveCount(7);
    await expect(row.locator("th > span")).toHaveText(
      line.excluded
        ? "Excluded from funding"
        : (line.listing_id ?? "Unresolved listing"),
    );
    await exactMoney(cells.nth(0), line.current_value);
    await exactMoney(cells.nth(2), line.recommended_amount);
    await exactMoney(cells.nth(3), line.post_value);
    for (const [column, weight] of [
      [1, line.target_weight],
      [4, line.post_weight],
    ] as const) {
      await expect(cells.nth(column)).toHaveAttribute("title", weight);
      await expect(cells.nth(column)).toHaveText(formatPercent(weight));
    }
    expect(line.value_increment.currency).toBe(
      line.minimum_funded_amount.currency,
    );
    await expect(cells.nth(5)).toHaveText(
      `${line.minimum_funded_amount.currency} ${line.minimum_funded_amount.amount} / ${line.value_increment.amount}`,
    );
    await expect(cells.nth(6)).toHaveText(
      line.binding_constraint_keys.join(", ") || "None binding",
    );
  }
  if (observed.lines.items.length === 0)
    await expect(
      allocation.getByText("No allocation recommendations", { exact: true }),
    ).toBeVisible();
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
  const revised = await waitForResult(page, request, 2);
  expect(revised.job.plan_id).toBe(original.job.plan_id);
  expect(revised.job.request_revision).toBe(2);
  expect(revised.request.options.mode).toBe("cash_only");
  expect(revised.result.residual_cash.amount).toBe("25");
  expect(revised.job.plan_revision_id).not.toBe(original.job.plan_revision_id);
  await page
    .getByRole("link", { name: "Revision history", exact: true })
    .click();
  const firstRevision = page.getByRole("link", { name: /^Revision 1 · / });
  const revisionHref = await firstRevision.getAttribute("href");
  expect(revisionHref).not.toBeNull();
  const revisionUrl = new URL(revisionHref!, page.url());
  expect(revisionUrl.searchParams.get("account")).toBe(account);
  expect(revisionUrl.searchParams.get("revision")).toBe(
    original.job.plan_revision_id,
  );
  await firstRevision.click();
  await expect(page).toHaveURL(revisionUrl.href);
  await expect(
    page.getByRole("heading", { name: /^EUR 20(?:\.00)?$/ }),
  ).toBeVisible();
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
}, testInfo) => {
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
  const restricted = await waitForResult(page, request, 2);
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
    page.getByText(
      /Company drift requires company targets and remains unavailable when only listing targets exist/,
    ),
  ).toBeVisible();
  await assertPresentation(page);
  await showSection(page, "Actual versus target");
  await page.screenshot({
    path: join(tmpdir(), `t212-p2-08-${testInfo.project.name}-drift.png`),
    fullPage: false,
  });
  expect(errors).toEqual([]);
});
