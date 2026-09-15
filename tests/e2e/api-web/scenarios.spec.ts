import {
  expect,
  test,
  type APIRequestContext,
  type Locator,
  type Page,
} from "@playwright/test";
import {
  ScenarioComparisonPageSchema,
  ScenarioRunResponseSchema,
  ScenarioVersionResponseSchema,
  snapshotDetailSchema,
  XrayExposuresResponseSchema,
  type ScenarioComponentView,
  type ScenarioMoneyView,
  type ScenarioRatioMetric,
  type ScenarioResultContextView,
  type ScenarioRunResponse,
} from "@trading212/api-contracts";
import { keyboardClearance } from "./accessibility";

const api = "http://127.0.0.1:18000/api/v1";
const account = "86ecdc4c-6c42-5593-84ed-de7bde3a6c4c";
const baseline = "f0f5c66e-b128-59b2-a620-83bc8faa4a57";
const alpha = "4a058969-a055-548a-9083-74eb9a4dfec8";
const cutoff = "2026-08-31T12:00:00Z";
const firstShock = "-0.123456789012345678";
const secondShock = "-0.2";

function href(extra: Record<string, string> = {}) {
  return `/scenarios?${new URLSearchParams({
    account,
    cutoff,
    currency: "EUR",
    ...extra,
  })}`;
}
function readable(value: string) {
  return value
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}
function selected(page: Page, key: string) {
  const value = new URL(page.url()).searchParams.get(key);
  expect(value, `Saved ${key} in the current URL`).toMatch(
    /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/,
  );
  return value!;
}
async function readRun(request: APIRequestContext, id: string) {
  const response = await request.get(`${api}/scenario-runs/${id}`);
  expect(response.status()).toBe(200);
  return ScenarioRunResponseSchema.parse(await response.json());
}
async function readVersion(request: APIRequestContext, id: string) {
  const response = await request.get(`${api}/scenario-versions/${id}`);
  expect(response.status()).toBe(200);
  return ScenarioVersionResponseSchema.parse(await response.json());
}

async function exactMoney(cell: Locator, metric: ScenarioMoneyView) {
  // These are canonical API strings, including tiny values and unavailable states.
  // Do not calculate, round or convert financial values in the browser oracle.
  const value = cell.locator(":scope > div").first();
  await expect(value.locator(":scope > span")).toHaveText(
    metric.value === null
      ? "Unavailable"
      : `${metric.value.amount} ${metric.value.currency}`,
  );
  await expect(value.locator(":scope > small")).toHaveText([
    `${readable(metric.quality)}${metric.reason ? ` · ${readable(metric.reason)}` : ""}`,
    `Confidence: ${metric.confidence ?? "Unavailable"}`,
  ]);
  const references = value.locator(":scope > details > div");
  await expect(references.locator(":scope > p")).toHaveText(
    `Source references: ${metric.source_reference_ids.items.length} shown${
      metric.source_reference_ids.omitted_count
        ? `; ${metric.source_reference_ids.omitted_count} additional references retained`
        : ""
    }.`,
  );
  await expect(references.locator(":scope > ul > li > code")).toHaveText(
    metric.source_reference_ids.items,
  );
}
async function exactRatio(cell: Locator, metric: ScenarioRatioMetric) {
  const value = cell.locator(":scope > span");
  await expect(value.locator(":scope > span")).toHaveText(
    metric.value ?? "Unavailable",
  );
  await expect(value.locator(":scope > small")).toHaveText(
    `${readable(metric.quality)}${metric.reason ? ` · ${readable(metric.reason)}` : ""}`,
  );
}
async function exactEffects(
  container: Locator,
  effects: ScenarioComponentView["effects"],
) {
  const rows = container
    .getByRole("table", { name: "Scenario effect channels", exact: true })
    .locator(":scope > tbody > tr");
  await expect(rows).toHaveCount(4);
  for (const [index, key] of (["price", "factor", "fx"] as const).entries()) {
    await exactRatio(
      rows.nth(index).locator(":scope > td").nth(0),
      effects[`${key}_ratio`],
    );
    await exactMoney(
      rows.nth(index).locator(":scope > td").nth(1),
      effects[key],
    );
  }
  await expect(rows.nth(3).locator(":scope > td").nth(0)).toHaveText(
    "Defined by calculation mode",
  );
  await exactMoney(
    rows.nth(3).locator(":scope > td").nth(1),
    effects.interaction,
  );
}
async function exactContext(
  page: Page,
  label: string,
  context: ScenarioResultContextView,
) {
  const panel = page
    .getByRole("heading", { name: label, exact: true })
    .locator("..");
  const rows = panel
    .getByRole("table", { name: `${label} values`, exact: true })
    .locator(":scope > tbody > tr");
  const metrics = [
    ["Terminal pre-value", context.summary.terminal_pre_value],
    ["Post-value", context.summary.post_value],
    ["Impact", context.summary.impact],
    ["Covered pre-value", context.summary.covered_pre_value],
    ["Uncovered pre-value", context.summary.uncovered_pre_value],
    ["Excluded pre-value", context.summary.excluded_pre_value],
    ["Covered post-value", context.summary.covered_post_value],
    ["Excluded post-value", context.summary.excluded_post_value],
    [
      "Provably unchanged uncovered value",
      context.summary.provably_unchanged_uncovered_value,
    ],
    ["Output rounding residual", context.summary.rounding_residual],
    ["Component sum residual", context.summary.component_sum_residual],
    ["Upstream portfolio value", context.upstream_portfolio_value],
    ["Upstream partition difference", context.upstream_partition_difference],
  ] as const;
  await expect(rows).toHaveCount(metrics.length);
  for (const [index, [name, metric]] of metrics.entries()) {
    await expect(rows.nth(index).locator(":scope > th")).toHaveText(name);
    await exactMoney(rows.nth(index).locator(":scope > td"), metric);
  }
  const proof = panel.locator(":scope > details");
  await proof.locator(":scope > summary").click();
  await exactEffects(proof, context.summary.effects);
  for (const pin of [
    context.run_id,
    context.result_id,
    context.saved_result_digest,
    context.input_digest,
    context.pins.portfolio_snapshot_id,
    context.pins.xray_run_id,
    context.pins.xray_input_digest,
    context.pins.xray_result_digest,
    context.pins.source_cutoff_at,
    context.numerical_profile,
  ]) {
    await expect(proof.getByText(pin, { exact: true }).first()).toBeVisible();
  }
  await proof.locator(":scope > summary").click();
}
async function exactComponentProof(
  proof: Locator,
  component: ScenarioComponentView,
) {
  await proof.locator(":scope > summary").click();
  const residual = proof
    .locator(":scope > dl > dt")
    .filter({ hasText: /^Rounding residual$/ })
    .locator("+ dd");
  await exactMoney(residual, component.rounding_residual);
  await exactEffects(proof, component.effects);
  // This journey has price/entity shocks, so no sensitivity or replay money is hidden.
  expect(component.sensitivity_uses).toEqual([]);
  expect(component.replay_change).toBeNull();
  await proof.locator(":scope > summary").click();
}
async function exactResult(page: Page, run: ScenarioRunResponse) {
  expect(run.state).toBe("succeeded");
  expect(run.result).not.toBeNull();
  const result = run.result!;
  expect(result.components.component_limit).toBe(25);
  expect(result.components.start_ordinal).toBe(0);
  expect(result.components.next_cursor).toBeNull();
  expect(result.components.total).toBe(result.components.items.length);
  await exactContext(page, "Scenario summary", result.context);
  const rows = page
    .getByRole("table", {
      name: "Saved scenario terminal components",
      exact: true,
    })
    .locator(":scope > tbody > tr");
  await expect(rows).toHaveCount(result.components.items.length);
  expect(
    await rows
      .first()
      .locator(":scope > th")
      .evaluate((cell) => cell.getBoundingClientRect().width),
  ).toBeLessThanOrEqual(320);
  const summaryTable = page.getByRole("table", {
    name: "Scenario summary values",
    exact: true,
  });
  expect(
    await summaryTable.evaluate(
      (table) => table.scrollWidth - table.parentElement!.clientWidth,
    ),
  ).toBeLessThanOrEqual(1);

  for (const [index, component] of result.components.items.entries()) {
    const row = rows.nth(index),
      cells = row.locator(":scope > td");
    await expect(row.locator(":scope > th > code")).toHaveText(
      component.exposure.path_key,
    );
    await expect(row.locator(":scope > th > p")).toHaveText(
      readable(component.partition),
    );
    await exactMoney(cells.nth(0), component.exposure.pre_value);
    await exactMoney(cells.nth(1), component.post_value);
    await exactMoney(cells.nth(2), component.impact);
    await exactComponentProof(
      cells.nth(3).locator(":scope > details"),
      component,
    );
  }
  await expect(
    page.getByText(result.content_digest, { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Cancel scenario run", exact: true }),
  ).toHaveCount(0);
}
async function captureScreen(
  page: Page,
  options: Parameters<Page["screenshot"]>[0],
) {
  // Interaction assertions may scroll nested tables and focus the skip link.
  // Capture the normal top-of-page state without changing application styles.
  await page.evaluate(async () => {
    if (document.activeElement instanceof HTMLElement)
      document.activeElement.blur();
    for (const element of document.querySelectorAll<HTMLElement>("*")) {
      if (element.scrollLeft !== 0) element.scrollLeft = 0;
      if (element.scrollTop !== 0) element.scrollTop = 0;
    }
    window.scrollTo({ top: 0, left: 0, behavior: "instant" });
    await new Promise<void>((resolve) =>
      requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
    );
  });
  await page.screenshot(options);
}
async function presentation(page: Page) {
  await expect(page).toHaveTitle("Portfolio Intelligence");
  await expect(page.getByRole("main")).toHaveCount(1);
  await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
  await expect(
    page.locator("nextjs-portal").getByText(/Runtime Error|Build Error/),
  ).toHaveCount(0);
  expect(
    await page.evaluate(
      () =>
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
    ),
  ).toBeLessThanOrEqual(1);
  expect(
    await page.locator("table").evaluateAll((tables) =>
      tables
        .filter(
          (table) =>
            // React streaming leaves empty hidden table containers. Every
            // populated table, including collapsed proof, still needs a name.
            !(
              table.hidden &&
              !table.querySelector("th,td") &&
              !table.textContent?.trim()
            ) &&
            !table.querySelector("caption") &&
            !table.getAttribute("aria-label"),
        )
        .map((table) => table.outerHTML.slice(0, 600)),
    ),
  ).toEqual([]);
}

// The existing runner executes this journey at 1440, 768 and 360 CSS pixels,
// serially, with a fresh database on the same PostgreSQL container for each viewport.
test("owned scenario revisions execute from saved X-ray pins and compare immutable API results", async ({
  page,
  request,
}, testInfo) => {
  test.setTimeout(300_000);
  page.setDefaultTimeout(30_000);
  const width = testInfo.project.name.includes("mobile")
    ? 360
    : testInfo.project.name.includes("tablet")
      ? 768
      : 1440;
  await page.setViewportSize({ width, height: 900 });
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error" || message.type() === "warning")
      errors.push(message.text());
  });
  await page.goto("/sign-in");
  await page.getByRole("button", { name: "Start local session" }).click();
  await expect(page).toHaveURL("http://127.0.0.1:3001/");
  expect((await request.post(`${api}/auth/local-session`)).status()).toBe(201);

  // The only API-created financial prerequisite is this explicit saved X-ray.
  // Later UI preparation supplies its exact run ID; it must not calculate another.
  const snapshotResponse = await request.get(
    `${api}/accounts/${account}/snapshots/latest`,
  );
  expect(snapshotResponse.status()).toBe(200);
  const snapshot = snapshotDetailSchema.parse(await snapshotResponse.json());
  const xrayResponse = await request.get(
    `${api}/accounts/${account}/effective-exposure`,
    {
      params: {
        snapshot_id: snapshot.id,
        source_cutoff_at: cutoff,
        reporting_currency: "EUR",
      },
    },
  );
  expect(xrayResponse.status()).toBe(200);
  const xray = XrayExposuresResponseSchema.parse(await xrayResponse.json());
  expect(xray.context.account_id).toBe(account);
  expect(xray.summary.total.value).toEqual({ amount: "1000", currency: "EUR" });

  await page.goto(href({ view: "definitions" }));
  await expect(
    page.getByRole("heading", { name: "Scenarios", exact: true }),
  ).toBeVisible();
  await page
    .getByLabel("Name", { exact: true })
    .fill("Browser scenario assumptions");
  await page.getByLabel("Calculation mode").selectOption("compounded");
  await page.getByRole("button", { name: "Add shock", exact: true }).click();
  await page.getByLabel("Shock channel").selectOption("price");
  await page.getByLabel("Match by").selectOption("entity");
  await page.getByLabel("Economic entity ID").fill(alpha);
  await page.getByLabel("Simple return shock").fill(firstShock);
  await presentation(page);
  await captureScreen(page, {
    path: testInfo.outputPath("scenario-definition.png"),
    fullPage: true,
  });
  await page
    .getByRole("button", { name: "Create scenario", exact: true })
    .click();
  await expect(page).toHaveURL(/definition=[0-9a-f-]+/);
  const definitionId = selected(page, "definition"),
    firstVersionId = selected(page, "version");
  const firstVersion = await readVersion(request, firstVersionId);
  expect(firstVersion.account_id).toBe(account);
  expect(firstVersion.definition_id).toBe(definitionId);
  expect(firstVersion.version_number).toBe(1);
  expect(firstVersion.content.shocks).toEqual([
    {
      kind: "price",
      size: firstShock,
      selector: { kind: "entity", entity_id: alpha },
    },
  ]);

  await page
    .getByLabel("Name", { exact: true })
    .fill("Revised browser scenario");
  await page.getByLabel("Simple return shock").fill(secondShock);
  await page
    .getByRole("button", { name: "Save new scenario version", exact: true })
    .click();
  await expect(
    page.getByText("Based on saved version 2", { exact: true }),
  ).toBeVisible();
  const secondVersionId = selected(page, "version");
  expect(secondVersionId).not.toBe(firstVersionId);
  const secondVersion = await readVersion(request, secondVersionId);
  expect(secondVersion.definition_id).toBe(definitionId);
  expect(secondVersion.version_number).toBe(2);
  expect(secondVersion.content.shocks).toEqual([
    {
      kind: "price",
      size: secondShock,
      selector: { kind: "entity", entity_id: alpha },
    },
  ]);
  expect(await readVersion(request, firstVersionId)).toEqual(firstVersion);

  const runs: ScenarioRunResponse[] = [];
  for (const [version, ordinal] of [
    [firstVersion, "first"],
    [secondVersion, "second"],
  ] as const) {
    await page
      .getByRole("link", {
        name: new RegExp(`^Version ${version.version_number} ·`),
      })
      .click();
    await expect(
      page.getByText(`Based on saved version ${version.version_number}`, {
        exact: true,
      }),
    ).toBeVisible();
    await page
      .getByRole("link", {
        name: "Use selected version in a new run",
        exact: true,
      })
      .click();
    await page
      .getByRole("combobox", { name: "Portfolio snapshot", exact: true })
      .selectOption(snapshot.id);
    await page
      .getByLabel("Saved X-ray run ID", { exact: true })
      .fill(xray.context.run_id);
    await page.getByLabel("Reporting currency", { exact: true }).fill("EUR");
    await page
      .getByLabel("X-ray knowledge cutoff (ISO timestamp)", { exact: true })
      .fill(cutoff);
    await page
      .getByRole("combobox", { name: "Run basis", exact: true })
      .selectOption("none");
    await page
      .getByRole("button", { name: "Verify saved input pins", exact: true })
      .click();
    await expect(
      page.getByRole("heading", {
        name: "Verified saved X-ray selection",
        exact: true,
      }),
    ).toBeVisible();
    const prepared = page
      .getByRole("heading", {
        name: "Verified saved X-ray selection",
        exact: true,
      })
      .locator("..");
    await expect(
      prepared.getByText(xray.context.run_id, { exact: true }),
    ).toBeVisible();
    await expect(prepared).toContainText(snapshot.id);
    expect(selected(page, "version")).toBe(version.id);
    expect(selected(page, "xray")).toBe(xray.context.run_id);
    await expect(
      page.getByRole("button", { name: "Create scenario run", exact: true }),
    ).toBeEnabled();
    await presentation(page);
    await captureScreen(page, {
      path: testInfo.outputPath(`scenario-${ordinal}-inputs.png`),
      fullPage: true,
    });
    await page
      .getByRole("button", { name: "Create scenario run", exact: true })
      .click();
    await expect(page).toHaveURL(/view=result/);
    await expect(
      page.getByRole("heading", { name: "Scenario summary", exact: true }),
    ).toBeVisible({ timeout: 120_000 });
    const run = await readRun(request, selected(page, "run"));
    expect(run.account_id).toBe(account);
    expect(run.scenario_version_id).toBe(version.id);
    expect(run.portfolio_snapshot_id).toBe(snapshot.id);
    expect(run.xray_run_id).toBe(xray.context.run_id);
    expect(run.result!.context.pins).toMatchObject({
      scenario_version_id: version.id,
      scenario_version_digest: version.content_digest,
      xray_run_id: xray.context.run_id,
      xray_input_digest: xray.context.input_digest,
      xray_result_digest: xray.context.content_digest,
      source_cutoff_at: xray.context.source_cutoff_at,
    });
    expect(
      run.result!.components.items.some(
        (item) =>
          item.exposure.entity.subject_id === alpha &&
          item.impact.value !== null &&
          item.impact.value.amount.startsWith("-"),
      ),
    ).toBe(true);
    await exactResult(page, run);
    await presentation(page);
    await captureScreen(page, {
      path: testInfo.outputPath(`scenario-${ordinal}-result.png`),
      fullPage: true,
    });
    runs.push(run);
    if (ordinal === "first") {
      await page
        .getByRole("navigation", { name: "Scenario views", exact: true })
        .getByRole("link", { name: "Definitions", exact: true })
        .click();
      await expect(
        page.getByRole("heading", { name: "Version history", exact: true }),
      ).toBeVisible();
    }
  }
  const [first, second] = runs;
  expect(first.id).not.toBe(second.id);
  expect(first.result!.context.saved_result_digest).not.toBe(
    second.result!.context.saved_result_digest,
  );

  // Real bounded pages preserve whole rows and the saved result identity.
  const firstPageResponse = await request.get(
    `${api}/scenario-runs/${first.id}`,
    { params: { component_limit: "1" } },
  );
  expect(firstPageResponse.status()).toBe(200);
  const firstPage = ScenarioRunResponseSchema.parse(
    await firstPageResponse.json(),
  ).result!;
  expect(firstPage.context).toEqual(first.result!.context);
  expect(firstPage.components.items).toEqual(
    first.result!.components.items.slice(0, 1),
  );
  expect(firstPage.components.start_ordinal).toBe(0);
  expect(firstPage.components.component_limit).toBe(1);
  expect(firstPage.components.next_cursor).not.toBeNull();
  const nextResponse = await request.get(`${api}/scenario-runs/${first.id}`, {
    params: {
      component_limit: "1",
      component_cursor: firstPage.components.next_cursor!,
    },
  });
  expect(nextResponse.status()).toBe(200);
  const nextPage = ScenarioRunResponseSchema.parse(
    await nextResponse.json(),
  ).result!;
  expect(nextPage.context).toEqual(first.result!.context);
  expect(nextPage.components.start_ordinal).toBe(1);
  expect(nextPage.components.items).toEqual(
    first.result!.components.items.slice(1, 2),
  );

  await page
    .getByRole("link", { name: "Compare this saved result", exact: true })
    .click();
  await page.getByLabel("First saved run", { exact: true }).fill(first.id);
  await page.getByLabel("Second saved run", { exact: true }).fill(second.id);
  await page
    .getByRole("button", { name: "Compare saved results", exact: true })
    .click();
  await expect(
    page.getByText("Compatible saved bases", { exact: true }),
  ).toBeVisible();
  const comparisonQuery = new URLSearchParams({ component_limit: "25" });
  comparisonQuery.append("run_ids", first.id);
  comparisonQuery.append("run_ids", second.id);
  const comparisonResponse = await request.get(
    `${api}/accounts/${account}/scenario-comparison?${comparisonQuery}`,
  );
  expect(comparisonResponse.status()).toBe(200);
  const comparison = ScenarioComparisonPageSchema.parse(
    await comparisonResponse.json(),
  );
  expect(comparison.compatible).toBe(true);
  expect(comparison.mismatches).toEqual([]);
  expect(comparison.before).toEqual(first.result!.context);
  expect(comparison.after).toEqual(second.result!.context);
  expect(comparison.components.total).toBe(comparison.components.items.length);
  expect(comparison.components.next_cursor).toBeNull();
  await exactContext(page, "First saved result", comparison.before);
  await exactContext(page, "Second saved result", comparison.after);
  const totals = page
    .getByRole("table", { name: "Scenario comparison totals", exact: true })
    .locator(":scope > tbody > tr");
  await expect(totals).toHaveCount(2);
  for (const [index, delta] of [
    comparison.post_value,
    comparison.impact,
  ].entries()) {
    for (const [column, metric] of [
      delta.before,
      delta.after,
      delta.difference,
    ].entries())
      await exactMoney(
        totals.nth(index).locator(":scope > td").nth(column),
        metric,
      );
  }
  const components = page
    .getByRole("table", {
      name: "Scenario comparison terminal components",
      exact: true,
    })
    .locator(":scope > tbody > tr");
  await expect(components).toHaveCount(comparison.components.items.length);
  for (const [index, component] of comparison.components.items.entries()) {
    const row = components.nth(index),
      cells = row.locator(":scope > td");
    await expect(row.locator(":scope > th > code")).toHaveText(
      component.path_key,
    );
    for (const [column, metric] of [
      component.post_value.before,
      component.post_value.after,
      component.post_value.difference,
      component.impact.difference,
    ].entries())
      await exactMoney(cells.nth(column), metric);
    expect(component.before).not.toBeNull();
    expect(component.after).not.toBeNull();
    for (const [side, original] of [
      component.before!,
      component.after!,
    ].entries()) {
      const retained = cells.nth(4).locator(":scope > details").nth(side);
      await retained.locator(":scope > summary").click();
      await exactComponentProof(retained.locator(":scope > details"), original);
      await retained.locator(":scope > summary").click();
    }
  }
  await expect(
    page.getByText(comparison.content_digest, { exact: true }),
  ).toBeVisible();
  expect(await readRun(request, first.id)).toEqual(first);
  expect(await readRun(request, second.id)).toEqual(second);
  expect(await readVersion(request, firstVersionId)).toEqual(firstVersion);
  expect(await readVersion(request, secondVersionId)).toEqual(secondVersion);
  await presentation(page);
  await keyboardClearance(page);
  await captureScreen(page, {
    path: testInfo.outputPath("scenario-comparison.png"),
    fullPage: true,
  });

  await page
    .getByRole("combobox", { name: "Portfolio account", exact: true })
    .selectOption(baseline);
  await expect
    .poll(() => new URL(page.url()).searchParams.get("account"))
    .toBe(baseline);
  for (const pin of [
    "definition",
    "version",
    "run",
    "before",
    "after",
    "snapshot",
    "xray",
    "capture",
    "definitions_cursor",
    "versions_cursor",
    "runs_cursor",
    "snapshots_cursor",
    "component_cursor",
  ])
    expect(
      new URL(page.url()).searchParams.has(pin),
      `Cleared ${pin} after account switch`,
    ).toBe(false);
  for (const heading of [
    "Scenario summary",
    "First saved result",
    "Second saved result",
    "Verified saved X-ray selection",
  ])
    await expect(
      page.getByRole("heading", { name: heading, exact: true }),
    ).toHaveCount(0);
  for (const digest of [
    first.result!.context.saved_result_digest,
    second.result!.context.saved_result_digest,
  ])
    await expect(page.getByText(digest, { exact: true })).toHaveCount(0);
  await presentation(page);
  await captureScreen(page, {
    path: testInfo.outputPath("scenario-account-switch.png"),
    fullPage: true,
  });
  expect(errors).toEqual([]);
});
