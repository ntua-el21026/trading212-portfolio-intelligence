import { keyboardClearance } from "./accessibility";
import { expect, test, type Page } from "@playwright/test";
import {
  snapshotDetailSchema,
  XrayCommonEntitiesResponseSchema,
  XrayExposuresResponseSchema,
  XrayHeldFundsResponseSchema,
  XrayPathsResponseSchema,
  XrayOverlapPairsResponseSchema,
} from "@trading212/api-contracts";

const api = "http://127.0.0.1:18000/api/v1";
const account = "86ecdc4c-6c42-5593-84ed-de7bde3a6c4c";
const baseline = "f0f5c66e-b128-59b2-a620-83bc8faa4a57";
const cutoff = "2026-08-31T12:00:00Z";
function href(extra: Record<string, string> = {}) {
  return `/xray?${new URLSearchParams({ account, cutoff, currency: "EUR", ...extra })}`;
}
async function presentation(page: Page) {
  await keyboardClearance(page);
  expect(
    await page.evaluate(
      () =>
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
    ),
  ).toBeLessThanOrEqual(1);
  expect(
    await page
      .locator("table")
      .evaluateAll((tables) =>
        tables.every(
          (table) =>
            table.querySelector("caption") || table.getAttribute("aria-label"),
        ),
      ),
  ).toBe(true);
  await expect(page.getByRole("main")).toHaveCount(1);
  await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
}
test.beforeEach(async ({ page, request }) => {
  page.setDefaultTimeout(30_000);
  await page.goto("/sign-in");
  await page.getByRole("button", { name: "Start local session" }).click();
  await expect(page).toHaveURL("http://127.0.0.1:3001/");
  expect((await request.post(`${api}/auth/local-session`)).status()).toBe(201);
});

test("persisted X-ray consolidates share classes and receipt with honest unresolved mass and full path evidence", async ({
  page,
  request,
}, testInfo) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const snapshotResponse = await request.get(
    `${api}/accounts/${account}/snapshots/latest`,
  );
  expect(snapshotResponse.status()).toBe(200);
  const snapshot = snapshotDetailSchema.parse(await snapshotResponse.json());
  const params = {
    snapshot_id: snapshot.id,
    source_cutoff_at: cutoff,
    reporting_currency: "EUR",
  };
  const response = await request.get(
    `${api}/accounts/${account}/effective-exposure`,
    { params },
  );
  expect(response.status()).toBe(200);
  const data = XrayExposuresResponseSchema.parse(await response.json());
  expect(data.summary.total.value).toEqual({ amount: "1000", currency: "EUR" });
  expect(data.summary.company_known_weight.value).toBe("0.95");
  expect(data.summary.unresolved_weight.value).toBe("0.05");
  expect(data.summary.cash_weight.value).toBe("0");
  expect(data.summary.duplicated_exposure.value).toBe("0.41");
  expect(data.summary.hhi.value).toBe("0.4657");
  expect(data.context.warnings.map((warning) => warning.code)).toEqual(
    expect.arrayContaining(["source_date_mismatch", "stale_source"]),
  );
  const alpha = data.exposures.items.find(
    (row) => row.name === "Synthetic Alpha",
  );
  expect(alpha?.direct.value?.amount).toBe("200");
  expect(alpha?.indirect.value?.amount).toBe("360");
  expect(alpha?.effective.value?.amount).toBe("560");
  await page.goto(href({ snapshot: snapshot.id, run: data.context.run_id }));
  await expect(
    page.getByRole("heading", { name: "Portfolio X-ray", exact: true }),
  ).toBeVisible();
  await expect(page.getByText("Analysis account:")).toContainText(
    "Synthetic X-ray Portfolio",
  );
  const row = page
    .getByRole("table", { name: "Effective exposure", exact: true })
    .getByRole("row")
    .filter({ hasText: "Synthetic Alpha" });
  await expect(row).toContainText("560.00 EUR");
  const warnings = page.getByRole("status").filter({
    has: page.getByText("X-ray warnings", { exact: true }),
  });
  await expect(warnings).toContainText("Source Date Mismatch");
  await expect(warnings).toContainText("Stale Source");
  await presentation(page);
  await page.screenshot({
    path: `/tmp/t212-p2-05-${testInfo.project.name}-xray-effective.png`,
    fullPage: true,
  });
  await row.getByRole("link", { name: /paths$/ }).click();
  await expect(
    page.getByRole("heading", { name: "Exposure paths", exact: true }),
  ).toBeVisible();
  expect(new URL(page.url()).searchParams.get("run")).toBe(data.context.run_id);
  const pathsResponse = await request.get(
    `${api}/accounts/${account}/effective-exposure`,
    {
      params: {
        ...params,
        run_id: data.context.run_id,
        view: "paths",
        exposure_id: alpha!.id,
      },
    },
  );
  expect(pathsResponse.status()).toBe(200);
  const paths = XrayPathsResponseSchema.parse(await pathsResponse.json());
  expect(paths.paths.total).toBe(6);
  expect(
    paths.paths.items.some((path) =>
      path.sources.some((source) => source.kind === "broker_fx"),
    ),
  ).toBe(true);
  const fundsResponse = await request.get(
    `${api}/accounts/${account}/effective-exposure`,
    {
      params: {
        ...params,
        run_id: data.context.run_id,
        view: "held_funds",
      },
    },
  );
  expect(fundsResponse.status()).toBe(200);
  const funds = XrayHeldFundsResponseSchema.parse(await fundsResponse.json());
  const atlas = funds.held_funds.items.find(
    (fund) => fund.name === "Synthetic Atlas Fund",
  );
  expect(atlas).toBeDefined();
  // Path order follows root identity, so the first fund path need not be Atlas.
  const atlasEdges = paths.paths.items.flatMap((path) =>
    path.fund_edges.filter(
      (edge) => edge.fund_instrument_id === atlas!.instrument_id,
    ),
  );
  expect(atlasEdges).toHaveLength(1);
  const sourceHref = `/xray/sources/${atlasEdges[0].candidate_id}?${new URLSearchParams({ account, run: data.context.run_id })}`;
  const sourceLink = page
    .getByRole("link", {
      name: "Constituent source",
      exact: true,
      includeHidden: true,
    })
    .and(page.locator(`a[href="${sourceHref}"]`));
  const detail = page.locator(".xray-page details").filter({ has: sourceLink });
  await expect(detail).toHaveCount(1);
  await detail.locator("summary").first().click();
  await sourceLink.click();
  await expect(page).toHaveURL(new URL(sourceHref, page.url()).toString());
  await expect(
    page.getByRole("heading", { name: "Constituent source", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Synthetic Atlas Fund", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "License and attribution", exact: true }),
  ).toBeVisible();
  await expect(
    page
      .getByRole("table", { name: "Constituent holdings", exact: true })
      .locator("tbody tr"),
  ).toHaveCount(3);
  await expect(
    page.getByRole("row").filter({ hasText: "atlas-unresolved" }),
  ).toContainText("10.0%");
  await presentation(page);
  await page.screenshot({
    path: `/tmp/t212-p2-05-${testInfo.project.name}-xray-source.png`,
    fullPage: true,
  });
  expect(errors).toEqual([]);
});

test("held-fund comparison and common-entity drilldown retain one canonical run", async ({
  page,
  request,
}, testInfo) => {
  await page.goto(href({ view: "held_funds", limit: "1" }));
  await expect(
    page.getByRole("heading", { name: "Held funds", exact: true }),
  ).toBeVisible();
  const choices = page.getByRole("group", {
    name: "Funds on this page",
    exact: true,
  });
  await expect(choices.getByRole("checkbox")).toHaveCount(1);
  await choices.getByRole("checkbox").check();
  await expect(
    page.getByRole("status").filter({ hasText: /^1 funds selected$/ }),
  ).toBeVisible();
  const nextFunds = page.getByRole("link", { name: "Next funds" });
  const nextFundsUrl = new URL(
    (await nextFunds.getAttribute("href"))!,
    page.url(),
  );
  const originalRun = nextFundsUrl.searchParams.get("run");
  expect(originalRun).toBeTruthy();
  await nextFunds.click();
  await expect(page).toHaveURL(nextFundsUrl.toString());
  await expect(
    page.getByRole("status").filter({ hasText: /^1 funds selected$/ }),
  ).toBeVisible();
  await expect(choices.getByRole("checkbox")).toHaveCount(1);
  await expect(choices.getByRole("checkbox")).not.toBeChecked();
  await choices.getByRole("checkbox").check();
  await expect(
    page.getByRole("status").filter({ hasText: /^2 funds selected$/ }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Compare selected funds" }).click();
  await expect(
    page.getByRole("heading", { name: "Fund overlap", exact: true }),
  ).toBeVisible();
  const selected = new URL(page.url());
  const run = selected.searchParams.get("run")!;
  expect(run).toBe(originalRun);
  expect(selected.searchParams.has("cursor")).toBe(false);
  expect(selected.searchParams.getAll("fund_ids")).toHaveLength(2);
  const overlapQuery = new URLSearchParams({
    snapshot_id: selected.searchParams.get("snapshot")!,
    source_cutoff_at: cutoff,
    reporting_currency: "EUR",
    run_id: run,
  });
  for (const id of selected.searchParams.getAll("fund_ids"))
    overlapQuery.append("fund_ids", id);
  const pairs = await request.get(
    `${api}/accounts/${account}/etf-overlap?${overlapQuery}`,
  );
  expect(pairs.status()).toBe(200);
  const result = XrayOverlapPairsResponseSchema.parse(await pairs.json());
  expect(result.pairs.items[0].overlap.value).toBe("0.5");
  expect(result.pairs.items[0].overlap.bound).toBe("lower_bound");
  expect(result.context.run_id).toBe(run);
  await expect(
    page.getByRole("table", { name: "Fund overlap pairs", exact: true }),
  ).toContainText("50.0%");
  await expect(
    page.getByText("Lower bound", { exact: true }).first(),
  ).toBeVisible();
  await presentation(page);
  await page.screenshot({
    path: `/tmp/t212-p2-05-${testInfo.project.name}-xray-overlap.png`,
    fullPage: true,
  });
  await page.getByRole("link", { name: "2 common entities" }).click();
  const commonTable = page.getByRole("table", {
    name: "Common fund entities",
    exact: true,
  });
  await expect(commonTable).toBeVisible();
  const atlasBasis = page.getByRole("region", {
    name: "Synthetic Atlas Fund composition basis",
    exact: true,
  });
  await expect(atlasBasis).toBeVisible();
  await expect(
    atlasBasis
      .locator("dt")
      .filter({ hasText: "Known unit coverage" })
      .locator("+ dd"),
  ).toContainText("90.0%");
  await expect(
    atlasBasis
      .locator("dt")
      .filter({ hasText: "Unresolved unit weight" })
      .locator("+ dd"),
  ).toContainText("10.0%");
  await expect(
    atlasBasis
      .locator("dt")
      .filter({ hasText: "Cash unit weight" })
      .locator("+ dd"),
  ).toContainText("0.0%");
  await expect(atlasBasis).toContainText("Representative position");
  await expect(atlasBasis.locator("code")).toContainText("position:");
  await expect(
    atlasBasis.getByRole("link", { name: "Inspect constituent source" }),
  ).toBeVisible();
  expect(new URL(page.url()).searchParams.get("run")).toBe(run);
  overlapQuery.set("view", "common_entities");
  overlapQuery.set("left_fund_id", result.pairs.items[0].left.instrument_id);
  overlapQuery.set("right_fund_id", result.pairs.items[0].right.instrument_id);
  const commonResponse = await request.get(
    `${api}/accounts/${account}/etf-overlap?${overlapQuery}`,
  );
  expect(commonResponse.status()).toBe(200);
  const common = XrayCommonEntitiesResponseSchema.parse(
    await commonResponse.json(),
  );
  expect(common.context.run_id).toBe(run);
  expect(common.common_entities.total).toBe(2);
  expect(common.common_entities.items.map((item) => item.name).sort()).toEqual([
    "Synthetic Alpha",
    "Synthetic Beta",
  ]);
  // The page-size choice carries into common entities; verify both pages.
  await expect(commonTable.locator("tbody tr")).toHaveCount(1);
  await expect(commonTable).toContainText(common.common_entities.items[0].name);
  await page
    .getByRole("navigation", { name: "X-ray pagination", exact: true })
    .getByRole("link", { name: "Next page", exact: true })
    .click();
  await expect(commonTable).toContainText(common.common_entities.items[1].name);
  expect(new URL(page.url()).searchParams.get("run")).toBe(run);
  await expect(commonTable.locator("tbody tr")).toHaveCount(1);
  await presentation(page);
});

test("projection changes retain identity and incompatible account pins fail visibly", async ({
  page,
  request,
}) => {
  await page.goto(href());
  const replay = page.getByRole("link", {
    name: "Replay this retained calculation",
  });
  const retained = new URL(
    (await replay.getAttribute("href"))!,
    "http://127.0.0.1:3001",
  );
  const run = retained.searchParams.get("run")!;
  retained.searchParams.set("dimension", "currency");
  retained.searchParams.set("normalized", "true");
  await page.goto(retained.pathname + retained.search);
  await expect(
    page
      .getByRole("table", { name: "Effective exposure", exact: true })
      .getByRole("columnheader", { name: "Known-only weight" }),
  ).toBeVisible();
  await expect(
    page.getByRole("table", { name: "Effective exposure", exact: true }),
  ).toContainText("USD");
  expect(
    new URL(
      (await page
        .getByRole("link", { name: "Replay this retained calculation" })
        .getAttribute("href"))!,
      retained,
    ).searchParams.get("run"),
  ).toBe(run);
  await page
    .getByRole("table", { name: "Effective exposure", exact: true })
    .getByRole("link", { name: /paths$/ })
    .first()
    .click();
  await expect(
    page.getByRole("heading", { name: "Exposure paths", exact: true }),
  ).toBeVisible();
  expect(new URL(page.url()).searchParams.get("normalized")).toBe("true");
  expect(new URL(page.url()).searchParams.get("run")).toBe(run);
  const normalizedPath = page
    .locator(".xray-page details")
    .filter({ hasText: "Root-relative weight" })
    .first();
  await normalizedPath.locator(":scope > summary").click();
  await expect(normalizedPath.getByText("Known-only weight")).toBeVisible();
  await expect(normalizedPath.getByText("Known-only weight")).not.toContainText(
    "Unavailable",
  );
  const denied = await request.get(
    `${api}/accounts/${baseline}/effective-exposure`,
    {
      params: {
        snapshot_id: retained.searchParams.get("snapshot")!,
        run_id: run,
        source_cutoff_at: cutoff,
        reporting_currency: "EUR",
      },
    },
  );
  expect(denied.status()).toBe(404);
  const incompatible = new URL(retained);
  incompatible.searchParams.set("account", baseline);
  await page.goto(incompatible.pathname + incompatible.search);
  await expect(
    page.getByRole("status").filter({
      has: page.getByText("X-ray unavailable", { exact: true }),
    }),
  ).toBeVisible();
  await page.goto(href({ private_key: "should-not-reflect-canary" }));
  await expect(
    page.getByRole("status").filter({
      has: page.getByText("Invalid X-ray filters", { exact: true }),
    }),
  ).toBeVisible();
  await expect(page.getByRole("main")).not.toContainText(
    "should-not-reflect-canary",
  );
});
