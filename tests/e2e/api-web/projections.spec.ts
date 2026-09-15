import {
  expect,
  test,
  type APIRequestContext,
  type Page,
} from "@playwright/test";
import {
  AssumptionVersionResponseSchema,
  GoalVersionResponseSchema,
  ProjectionRunResponseSchema,
  snapshotDetailSchema,
  type ProjectionPointRow,
} from "@trading212/api-contracts";
import { keyboardClearance } from "./accessibility";

const api = "http://127.0.0.1:18000/api/v1";
const account = "86ecdc4c-6c42-5593-84ed-de7bde3a6c4c";
const otherAccount = "f0f5c66e-b128-59b2-a620-83bc8faa4a57";
const anchor = "2026-09-15";
const targetDate = "2026-12-15";
function href(fields: Record<string, string> = {}) {
  return `/projections?${new URLSearchParams({ account, ...fields })}`;
}
function pin(page: Page, key: string) {
  const value = new URL(page.url()).searchParams.get(key);
  expect(value).toMatch(/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/);
  return value!;
}
async function run(request: APIRequestContext, id: string, cursor?: string) {
  const response = await request.get(`${api}/projection-runs/${id}`, {
    params: { point_limit: 25, ...(cursor ? { point_cursor: cursor } : {}) },
  });
  expect(response.status()).toBe(200);
  return ProjectionRunResponseSchema.parse(await response.json());
}
async function presentation(page: Page) {
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth - window.innerWidth,
    ),
  ).toBeLessThanOrEqual(1);
  expect(
    await page.locator("table").evaluateAll((tables) =>
      tables
        .filter(
          (table) =>
            // React streaming leaves hidden, empty table shells after moving rows.
            // The actual captured browser DOM contains no user-facing content there.
            !(
              table.hidden &&
              !table.textContent?.trim() &&
              !table.querySelector("tr,th,td")
            ) &&
            !table.querySelector("caption") &&
            !table.getAttribute("aria-label"),
        )
        .map((table) => ({
          html: table.outerHTML.slice(0, 1400),
          hiddenAncestor: table.closest("[hidden]")?.outerHTML.slice(0, 1400),
        })),
    ),
  ).toEqual([]);
  await keyboardClearance(page);
}
async function points(page: Page, values: readonly ProjectionPointRow[]) {
  const details = page
    .locator("details")
    .filter({ has: page.locator("summary", { hasText: /^Point \d+ ·/ }) });
  await expect(details).toHaveCount(values.length);
  const names = [
    ["nominal", "Nominal wealth"],
    ["real", "Real wealth"],
    ["contributions", "Cumulative contributions"],
    ["withdrawals_requested", "Requested withdrawals"],
    ["withdrawals_funded", "Funded withdrawals"],
    ["unpaid_withdrawals", "Unpaid withdrawals"],
    ["investment_effect", "Investment effect"],
    ["fees", "Cumulative fees"],
    ["tax_drag", "Modeled tax drag"],
    ["wealth_residual", "Wealth rounding residual"],
    ["allocation_residual", "Allocation rounding residual"],
    ["withdrawal_residual", "Withdrawal rounding residual"],
  ] as const;
  for (const [index, value] of values.entries()) {
    const item = details.nth(index);
    await expect(item.locator(":scope > summary")).toContainText(
      `Point ${value.ordinal} ·`,
    );
    await item.locator(":scope > summary").click();
    for (const [field, name] of names) {
      const expected = value.point[field];
      await expect(
        item
          .locator("dt", { hasText: new RegExp(`^${name}$`) })
          .locator("..")
          .locator("dd"),
      ).toHaveText(`${expected.amount} ${expected.currency}`);
    }
    const assetRows = item
      .getByRole("table", {
        name: `Asset amounts for retained point ${value.ordinal}`,
        exact: true,
      })
      .locator("tbody tr");
    await expect(assetRows).toHaveCount(value.point.assets.length);
    for (const [assetIndex, asset] of value.point.assets.entries()) {
      await expect(assetRows.nth(assetIndex).locator("th")).toHaveText(
        asset.key,
      );
      await expect(assetRows.nth(assetIndex).locator("td")).toHaveText(
        `${asset.value.amount} ${asset.value.currency}`,
      );
    }
    await item.locator(":scope > summary").click();
  }
}

test("owned immutable assumptions and goals execute and page exact saved projections", async ({
  page,
  request,
}, info) => {
  test.setTimeout(300_000);
  page.setDefaultTimeout(30_000);
  const width = info.project.name.includes("mobile")
    ? 360
    : info.project.name.includes("tablet")
      ? 768
      : 1440;
  await page.setViewportSize({ width, height: 900 });
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (["error", "warning"].includes(message.type()))
      errors.push(message.text());
  });
  await page.goto("/sign-in");
  await page.getByRole("button", { name: "Start local session" }).click();
  await expect(page).toHaveURL("http://127.0.0.1:3001/");
  expect((await request.post(`${api}/auth/local-session`)).status()).toBe(201);
  await page.goto(href({ view: "assumptions" }));
  const assumptions = page.getByRole("form", {
    name: "Projection assumptions",
  });
  await assumptions
    .getByLabel("Assumption name", { exact: true })
    .fill("Browser saved assumptions");
  await assumptions
    .getByLabel("Annual mean log return", { exact: true })
    .fill("-0.000000000000000001");
  await assumptions
    .getByLabel("Annual volatility", { exact: true })
    .fill("0.2");
  await assumptions
    .getByLabel("Annual inflation (ratio)", { exact: true })
    .fill("0.02");
  await assumptions
    .getByLabel("Annual fee (ratio)", { exact: true })
    .fill("0.001");
  await assumptions
    .getByRole("button", { name: "Create assumption set", exact: true })
    .click();
  await expect
    .poll(() => new URL(page.url()).searchParams.get("version"))
    .not.toBeNull();
  const firstVersion = pin(page, "version"),
    setId = pin(page, "set");
  const firstResponse = await request.get(
    `${api}/assumption-versions/${firstVersion}`,
  );
  expect(firstResponse.status()).toBe(200);
  const original = AssumptionVersionResponseSchema.parse(
    await firstResponse.json(),
  );
  expect(original.content.assets[0].annual_mean_log_return).toBe(
    "-0.000000000000000001",
  );
  await assumptions
    .getByLabel("Annual mean log return", { exact: true })
    .fill("0.04");
  await assumptions
    .getByRole("button", { name: "Save assumption version", exact: true })
    .click();
  await expect
    .poll(() => new URL(page.url()).searchParams.get("version"))
    .not.toBe(firstVersion);
  const secondVersion = pin(page, "version");
  await presentation(page);
  await page.screenshot({
    path: info.outputPath("projection-assumptions.png"),
    fullPage: true,
  });

  await page.goto(href({ view: "goals", set: setId, version: firstVersion }));
  const goals = page.getByRole("form", { name: "Projection goal" });
  await goals
    .getByLabel("Goal name", { exact: true })
    .fill("Browser saved goal");
  await goals
    .getByLabel("Target amount (EUR)", { exact: true })
    .fill("50.123456789012345678");
  await goals.getByLabel("Target date", { exact: true }).fill(targetDate);
  await goals.getByLabel("Goal horizon (months)", { exact: true }).fill("3");
  await goals
    .getByLabel("Base monthly contribution", { exact: true })
    .fill("10.000000000000000001");
  await goals
    .getByRole("button", { name: "Add dated cash flow", exact: true })
    .click();
  await goals.getByLabel("Entry key", { exact: true }).fill("withdrawal-one");
  await goals.getByLabel("Entry date", { exact: true }).fill("2026-10-15");
  await goals
    .getByRole("combobox", { name: "Entry type", exact: true })
    .selectOption("withdrawal");
  await goals
    .getByLabel("Entry amount", { exact: true })
    .fill("75.000000000000000001");
  await goals.getByRole("button", { name: "Create goal", exact: true }).click();
  await expect
    .poll(() => new URL(page.url()).searchParams.get("goal_version"))
    .not.toBeNull();
  const goalVersion = pin(page, "goal_version"),
    goalId = pin(page, "goal");
  const goalResponse = await request.get(`${api}/goal-versions/${goalVersion}`);
  expect(goalResponse.status()).toBe(200);
  const goal = GoalVersionResponseSchema.parse(await goalResponse.json());
  expect(goal.content.assumption_version_id).toBe(firstVersion);
  await presentation(page);
  await page.screenshot({
    path: info.outputPath("projection-goal.png"),
    fullPage: true,
  });

  await page.goto(
    href({ view: "new", version: firstVersion, goal_version: goalVersion }),
  );
  const form = page.getByRole("form", { name: "Create projection run" });
  await form
    .getByLabel("Modeled initial value (EUR)", { exact: true })
    .fill("100.123456789012345678");
  await form.getByLabel("Modeled anchor date", { exact: true }).fill(anchor);
  await expect(
    form.getByLabel("Projection horizon (months)", { exact: true }),
  ).toBeDisabled();
  await form.getByLabel("Saved path count", { exact: true }).fill("7");
  await form.getByLabel("Random seed", { exact: true }).fill("23");
  await form
    .getByLabel("Retained months (comma separated)", { exact: true })
    .fill("0,1,2,3");
  await form
    .getByLabel("Include contribution and mean-return variants", {
      exact: true,
    })
    .check();
  await form
    .getByLabel("Monthly contribution delta (EUR)", { exact: true })
    .fill("2");
  await form
    .getByLabel("Annual mean log return delta", { exact: true })
    .fill("0.005");
  await presentation(page);
  await page.screenshot({
    path: info.outputPath("projection-inputs.png"),
    fullPage: true,
  });
  await form
    .getByRole("button", { name: "Create projection run", exact: true })
    .click();
  await expect
    .poll(() => new URL(page.url()).searchParams.get("run"))
    .not.toBeNull();
  const runId = pin(page, "run");
  await expect
    .poll(async () => (await run(request, runId)).state, { timeout: 120_000 })
    .toBe("succeeded");
  await page.goto(href({ view: "result", run: runId }));
  const saved = await run(request, runId);
  expect(saved.assumption_version_id).toBe(firstVersion);
  expect(saved.goal_version_id).toBe(goalVersion);
  expect(saved.result!.points.total).toBe(84);
  expect(saved.result!.variants).toHaveLength(3);
  expect(saved.result!.context.snapshot_valuation_at).toBeNull();
  expect(saved.result!.context.source_cutoff_at).toBeNull();
  await expect(
    page.getByRole("heading", {
      name: "Complete retained point rows",
      exact: true,
    }),
  ).toBeVisible();
  await points(page, saved.result!.points.items);
  await presentation(page);
  await page.screenshot({
    path: info.outputPath("projection-result.png"),
    fullPage: true,
  });
  const ordinals = saved.result!.points.items.map((row) => row.ordinal);
  while (
    await page.getByRole("link", { name: "Next points", exact: true }).count()
  ) {
    const nextHref = await page
      .getByRole("link", { name: "Next points", exact: true })
      .getAttribute("href");
    const cursor = new URL(nextHref!, page.url()).searchParams.get(
      "point_cursor",
    )!;
    await page.getByRole("link", { name: "Next points", exact: true }).click();
    await expect
      .poll(() => new URL(page.url()).searchParams.get("point_cursor"))
      .toBe(cursor);
    const next = await run(request, runId, cursor);
    await points(page, next.result!.points.items);
    ordinals.push(...next.result!.points.items.map((row) => row.ordinal));
  }
  expect(ordinals).toEqual(Array.from({ length: 84 }, (_, index) => index));
  await page.goBack();
  await expect(
    page.getByRole("link", { name: "Next points", exact: true }),
  ).toBeVisible();
  await page.goForward();
  await expect(
    page.getByText("End of retained points.", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("link", { name: "Saved goal analysis", exact: true })
    .click();
  await expect
    .poll(() => new URL(page.url()).searchParams.get("view"))
    .toBe("goal");
  await expect(
    page.getByText("50.123456789012345678 EUR", { exact: true }).first(),
  ).toBeVisible();
  await presentation(page);
  await page.screenshot({
    path: info.outputPath("projection-goal-analysis.png"),
    fullPage: true,
  });

  await page.goto(
    href({
      view: "goals",
      goal: goalId,
      goal_version: goalVersion,
      version: secondVersion,
    }),
  );
  await goals.getByLabel("Target amount (EUR)", { exact: true }).fill("200");
  await goals
    .getByRole("button", { name: "Save goal version", exact: true })
    .click();
  await expect
    .poll(() => new URL(page.url()).searchParams.get("goal_version"))
    .not.toBe(goalVersion);
  const reread = await run(request, runId);
  // New first-page cursors bind their own read cutoff; saved financial bytes do not change.
  expect(reread.result!.context).toEqual(saved.result!.context);
  expect(reread.result!.variants).toEqual(saved.result!.variants);
  expect(reread.result!.points.items).toEqual(saved.result!.points.items);
  expect(reread.result!.points.total).toBe(saved.result!.points.total);
  expect(reread.assumption_version_id).toBe(firstVersion);
  expect(reread.goal_version_id).toBe(goalVersion);
  expect(
    AssumptionVersionResponseSchema.parse(
      await (
        await request.get(`${api}/assumption-versions/${firstVersion}`)
      ).json(),
    ),
  ).toEqual(original);
  expect(
    GoalVersionResponseSchema.parse(
      await (await request.get(`${api}/goal-versions/${goalVersion}`)).json(),
    ),
  ).toEqual(goal);

  // Exercise observed snapshot preparation and cancel before any delivery.
  const snapshotResponse = await request.get(
    `${api}/accounts/${account}/snapshots/latest`,
  );
  expect(snapshotResponse.status()).toBe(200);
  const snapshot = snapshotDetailSchema.parse(await snapshotResponse.json());
  expect(
    (
      await request.post(
        "http://127.0.0.1:18000/__e2e__/pause-projection-delivery",
      )
    ).status(),
  ).toBe(200);
  await page.goto(
    href({ view: "new", version: secondVersion, snapshot: snapshot.id }),
  );
  await expect(
    form.getByRole("combobox", { name: "Initial value source", exact: true }),
  ).toHaveValue("observed_snapshot");
  await expect(form).toContainText(snapshot.source_cutoff_at);
  await expect(form).toContainText(snapshot.valuation_at);
  await form
    .getByLabel("Projection horizon (months)", { exact: true })
    .fill("1");
  await form
    .getByLabel("Retained months (comma separated)", { exact: true })
    .fill("0,1");
  await form.getByLabel("Saved path count", { exact: true }).fill("1");
  await form
    .getByRole("button", { name: "Create projection run", exact: true })
    .click();
  await expect
    .poll(() => new URL(page.url()).searchParams.get("run"))
    .not.toBeNull();
  const cancelledId = pin(page, "run");
  await page
    .getByRole("button", { name: "Cancel projection run", exact: true })
    .click();
  await expect
    .poll(async () => (await run(request, cancelledId)).state)
    .toBe("cancelled");
  expect((await run(request, cancelledId)).result).toBeNull();
  await page.screenshot({
    path: info.outputPath("projection-cancelled.png"),
    fullPage: true,
  });
  await page
    .getByRole("combobox", { name: "Portfolio account", exact: true })
    .selectOption(otherAccount);
  await expect
    .poll(() => new URL(page.url()).searchParams.get("account"))
    .toBe(otherAccount);
  expect([...new URL(page.url()).searchParams.keys()]).toEqual(["account"]);
  await expect(page.getByText(runId, { exact: true })).toHaveCount(0);
  await presentation(page);
  await page.screenshot({
    path: info.outputPath("projection-account-switch.png"),
    fullPage: true,
  });
  expect(errors).toEqual([]);
});
