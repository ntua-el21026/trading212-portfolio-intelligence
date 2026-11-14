import { keyboardClearance } from "./accessibility";
import { randomUUID } from "node:crypto";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  expect,
  test,
  type APIRequestContext,
  type Page,
} from "@playwright/test";
import {
  ActualVsTargetResultSchema,
  IntelligenceDataQualitySchema,
  localSessionSchema,
  snapshotDetailSchema,
  TargetValidationResponseSchema,
  TargetVersionResponseSchema,
  VirtualPortfolioResponseSchema,
  XrayExposuresResponseSchema,
  type IntelligenceDataQuality,
} from "@trading212/api-contracts";

const api = "http://127.0.0.1:18000/api/v1";
const account = "86ecdc4c-6c42-5593-84ed-de7bde3a6c4c";
const primary = "f0f5c66e-b128-59b2-a620-83bc8faa4a57";
const origin = "http://127.0.0.1:3001";

function label(value: string) {
  return value
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}
async function checkedLayout(page: Page) {
  await keyboardClearance(page);
  await expect(page.getByRole("main")).toHaveCount(1);
  await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
  expect(
    await page.evaluate(
      () =>
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
    ),
  ).toBeLessThanOrEqual(1);
  for (const table of await page.getByRole("table").all())
    await expect(table).toHaveAccessibleName(/\S/);
}
test.beforeEach(async ({ page }) => {
  page.setDefaultTimeout(20_000);
  await page.goto("/sign-in");
  await page
    .getByRole("button", { name: "Start local session", exact: true })
    .click();
  await expect(page).toHaveURL(origin + "/");
});
async function login(request: APIRequestContext) {
  const response = await request.post(api + "/auth/local-session");
  expect(response.status()).toBe(201);
  return localSessionSchema.parse(await response.json());
}
async function snapshotAndCompany(request: APIRequestContext) {
  const saved = await request.get(
    api + "/accounts/" + account + "/snapshots/latest",
  );
  expect(saved.status()).toBe(200);
  const snapshot = snapshotDetailSchema.parse(await saved.json());
  const result = await request.get(
    api + "/accounts/" + account + "/effective-exposure",
    {
      params: {
        snapshot_id: snapshot.id,
        source_cutoff_at: snapshot.source_cutoff_at,
        reporting_currency: "EUR",
        dimension: "company",
        view: "exposures",
      },
    },
  );
  expect(result.status()).toBe(200);
  const company = XrayExposuresResponseSchema.parse(await result.json());
  return { snapshot, company };
}
async function publishCashTarget(request: APIRequestContext) {
  const session = await login(request);
  const headers = () => ({
    Origin: origin,
    "X-CSRF-Token": session.csrf_token,
    "X-Idempotency-Key": randomUUID(),
  });
  const response = await request.post(api + "/virtual-portfolios", {
    headers: headers(),
    data: {
      name: "Company browser comparison",
      reporting_currency: "EUR",
      account_id: account,
    },
  });
  expect(response.status()).toBe(201);
  const portfolio = VirtualPortfolioResponseSchema.parse(await response.json());
  const draft = await request.post(
    api + "/virtual-portfolios/" + portfolio.id + "/target-versions",
    {
      headers: { ...headers(), "If-Match": response.headers().etag },
      data: {
        effective_at: "2026-08-31T12:00:00Z",
        content: {
          nodes: [
            { key: "cash", kind: "cash", name: "Cash", order: 0, weight: "1" },
          ],
        },
      },
    },
  );
  expect(draft.status()).toBe(201);
  const version = TargetVersionResponseSchema.parse(await draft.json());
  const validated = await request.post(
    api + "/target-versions/" + version.id + "/validate",
    {
      headers: { ...headers(), "If-Match": draft.headers().etag },
      data: { normalize: false },
    },
  );
  expect(validated.status()).toBe(200);
  const validation = TargetValidationResponseSchema.parse(
    await validated.json(),
  );
  expect(validation.valid).toBe(true);
  const published = await request.post(
    api + "/target-versions/" + version.id + "/publish",
    {
      headers: { ...headers(), "If-Match": validated.headers().etag },
      data: { validation_id: validation.id },
    },
  );
  expect(published.status()).toBe(200);
  return {
    portfolio,
    version: TargetVersionResponseSchema.parse(await published.json()),
  };
}

test("company comparison preserves exact full company weights, source pins and direct totals", async ({
  page,
  request,
}, info) => {
  test.setTimeout(180_000);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const { portfolio, version } = await publishCashTarget(request);
  const { snapshot, company } = await snapshotAndCompany(request);
  const params = {
    virtual_portfolio_id: portfolio.id,
    target_version_id: version.id,
    snapshot_id: snapshot.id,
    reporting_currency: "EUR",
    limit: 25,
  };
  const baseResponse = await request.get(
    api + "/accounts/" + account + "/actual-vs-target",
    { params },
  );
  expect(baseResponse.status()).toBe(200);
  const base = ActualVsTargetResultSchema.parse(await baseResponse.json());
  const query = new URLSearchParams({
    account,
    pie: portfolio.id,
    version: version.id,
    snapshot: snapshot.id,
  });
  await page.goto("/drift?" + query);
  await page
    .getByRole("link", { name: "Include company actual weights", exact: true })
    .click();
  await expect(page).toHaveURL(
    (url) =>
      url.searchParams.get("company") === "include" &&
      url.searchParams.get("xray_run") === company.context.run_id,
  );
  const enrichedResponse = await request.get(
    api + "/accounts/" + account + "/actual-vs-target",
    {
      params: { ...params, xray_run_id: company.context.run_id },
    },
  );
  expect(enrichedResponse.status(), await enrichedResponse.text()).toBe(200);
  const enriched = ActualVsTargetResultSchema.parse(
    await enrichedResponse.json(),
  );
  expect(enriched.content_digest).toBe(base.content_digest);
  expect(enriched.totals).toEqual(base.totals);
  expect(enriched.company_basis?.xray_run_id).toBe(company.context.run_id);
  const table = page.getByRole("table", {
    name: "Direct actual versus target for the selected hierarchy scope",
    exact: true,
  });
  const rows = table.locator("tbody tr");
  await expect(rows).toHaveCount(enriched.rows.items.length);
  // The independent full exposure response, rather than the planning echo, is
  // the numeric oracle. Four held roots share Alpha's complete portfolio weight.
  expect(company.exposures.next_cursor).toBeNull();
  const alpha = company.exposures.items.find(
    (row) => row.name === "Synthetic Alpha",
  );
  expect(alpha).toBeDefined();
  expect(alpha!.absolute_weight.value).toMatch(/^0[.]56(?:0*)$/);
  const alphaRows = enriched.rows.items.filter(
    (row) => row.company?.entity_id === alpha!.bucket_key,
  );
  expect(alphaRows).toHaveLength(4);
  // An unmatched target row has the canonical "Unclassified holding" label.
  // Use the independently declared fixture listing identities for this proof.
  const ordinaryListingIds = [
    "56e6d8da-e0cb-5fff-9c95-465b39f5c181",
    "0bcd3d34-3785-5dd3-9e8b-560f263a8ce1",
  ];
  const ordinary = alphaRows.filter(
    (row) =>
      row.listing_id !== null && ordinaryListingIds.includes(row.listing_id),
  );
  expect(ordinary).toHaveLength(2);
  expect(new Set(ordinary.map((row) => row.listing_id)).size).toBe(2);
  expect(new Set(ordinary.map((row) => row.instrument_id)).size).toBe(1);
  expect(ordinary.every((row) => row.listing_id && row.instrument_id)).toBe(
    true,
  );
  for (const row of alphaRows) {
    expect(row.company!.metric).toEqual(alpha!.absolute_weight);
    expect(row.effective_weight).toBe(alpha!.absolute_weight.value);
    expect(row.company!.semantics).toBe("full_portfolio_company_non_additive");
  }
  for (const [index, row] of enriched.rows.items.entries()) {
    const rendered = rows.nth(index);
    await expect(rendered.getByRole("rowheader")).toContainText(row.name);
    if (row.listing_id) {
      const identity = rendered.locator(".planning-holding-identity");
      await identity.getByText("Holding identity", { exact: true }).click();
      await expect(identity).toContainText(row.listing_id);
      if (row.instrument_id)
        await expect(identity).toContainText(row.instrument_id);
      await identity.getByText("Holding identity", { exact: true }).click();
    }
    const cell = rendered.getByRole("cell").nth(3);
    const weight = row.company;
    expect(weight).toBeTruthy();
    if (weight?.metric?.value !== null && weight?.metric) {
      const canonical = company.exposures.items.find(
        (bucket) => bucket.bucket_key === weight.entity_id,
      );
      expect(canonical).toBeDefined();
      expect(weight.metric).toEqual(canonical!.absolute_weight);
      await expect(cell.locator(".historical-value")).toHaveAttribute(
        "title",
        canonical!.absolute_weight.value!,
      );
      if (canonical!.absolute_weight.bound === "lower_bound")
        await expect(cell).toContainText("Lower bound");
      if (canonical!.absolute_weight.positive_below_quantum)
        await expect(cell).toContainText("Positive below display precision");
      if (canonical!.absolute_weight.quality !== "fresh")
        await expect(cell).toContainText(
          label(canonical!.absolute_weight.quality),
        );
    } else if (weight && !weight.metric)
      await expect(cell).toContainText(label(weight.reason));
  }
  await expect(
    page.getByText(enriched.projection_digest!, { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText(/these repeated cells must not be added together/),
  ).toBeVisible();
  const retained = page.getByRole("link", {
    name: "Inspect the retained company calculation",
    exact: true,
  });
  expect(
    new URL((await retained.getAttribute("href"))!, origin).searchParams.get(
      "run",
    ),
  ).toBe(company.context.run_id);
  const beforeRank = page.url();
  await page
    .getByRole("combobox", { name: "Ranked drift basis", exact: true })
    .selectOption("effective");
  await page
    .getByRole("button", { name: "Apply drift view", exact: true })
    .click();
  await expect(page).toHaveURL(
    (url) =>
      url.searchParams.get("basis") === "effective" &&
      url.searchParams.get("xray_run") === company.context.run_id &&
      url.searchParams.get("account") === account,
  );
  await expect(
    page.getByText(/company drift remains unavailable/i).first(),
  ).toBeVisible();
  await page.goBack();
  await expect(page).toHaveURL(beforeRank);
  await page.reload();
  await expect(
    page.getByText(enriched.projection_digest!, { exact: true }),
  ).toBeVisible();
  await checkedLayout(page);
  await page.screenshot({
    path: join(tmpdir(), "t212-p2-08-company-" + info.project.name + ".png"),
    fullPage: true,
  });
  await page
    .getByRole("link", {
      name: "Create a report with this company basis",
      exact: true,
    })
    .click();
  await expect(page).toHaveURL(
    (url) =>
      url.pathname === "/reports" &&
      url.searchParams.get("account") === account &&
      url.searchParams.get("snapshot") === snapshot.id &&
      url.searchParams.get("target_version_id") === version.id &&
      url.searchParams.get("xray_run_id") === company.context.run_id,
  );
  await expect(
    page.getByRole("textbox", {
      name: "Retained company calculation",
      exact: true,
    }),
  ).toHaveValue(company.context.run_id);
  await expect(
    page.getByRole("combobox", { name: "Report type", exact: true }),
  ).toHaveValue("target_drift");
  await checkedLayout(page);
  expect(errors).toEqual([]);
});

function sourceIdentities(data: IntelligenceDataQuality) {
  return data.sources.items.map(
    (source) =>
      [
        source.identity.kind,
        source.identity.id,
        source.identity.parent_id,
      ] as const,
  );
}
async function assertSourcePage(page: Page, data: IntelligenceDataQuality) {
  const rows = page
    .getByRole("table", {
      name: "Current status of the pinned visible sources",
      exact: true,
    })
    .locator("tbody tr");
  await expect(rows).toHaveCount(data.sources.items.length);
  if (data.selection)
    await expect(
      page
        .locator(".settings-list > div")
        .filter({
          has: page.locator("dt", {
            hasText: "Selected " + label(data.selection.kind),
          }),
        })
        .locator("dd"),
    ).toHaveText(data.selection.id);
  for (const [index, source] of data.sources.items.entries()) {
    const row = rows.nth(index);
    await expect(row.getByRole("rowheader")).toContainText(
      label(source.identity.kind),
    );
    await expect(row.getByRole("rowheader").locator("p")).toHaveText(
      source.identity.id,
    );
    const details = row.locator("details");
    if (
      !(await details.evaluate(
        (element) => (element as HTMLDetailsElement).open,
      ))
    )
      await details
        .getByText("Source dates, license and coverage", { exact: true })
        .click();
    await expect(
      details
        .locator(".settings-list > div")
        .filter({ has: page.locator("dt", { hasText: /^Parent source$/ }) })
        .locator("dd"),
    ).toHaveText(source.identity.parent_id ?? "None reported");
    const summary = details.locator("summary");
    await expect(summary).toHaveText("Source dates, license and coverage");
    await expect(summary).toBeVisible();
    const layout = await summary.evaluate((element) => ({
      height: Math.max(
        element.getBoundingClientRect().height,
        element.scrollHeight,
      ),
      lineHeight: Number.parseFloat(getComputedStyle(element).lineHeight),
    }));
    expect(layout.lineHeight).toBeGreaterThan(0);
    expect(
      layout.height,
      "Source disclosure summary wraps beyond three lines",
    ).toBeLessThanOrEqual(3 * layout.lineHeight + 1);
  }
}

test("quality inventories agree with the API for all families and preserve pinned source pagination", async ({
  page,
  request,
}, info) => {
  test.setTimeout(180_000);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await login(request);
  await snapshotAndCompany(request);
  const kinds = [
    "valuation",
    "actual_vs_target",
    "drift",
    "performance",
    "benchmark",
    "income",
    "attribution",
    "cash_flow",
    "xray",
  ] as const;
  const counts = [5, 10, 10, 17, 11, 10, 12, 5, 9];
  for (const [index, kind] of kinds.entries()) {
    const selected = kind === "xray" ? account : primary;
    const response = await request.get(
      api + "/accounts/" + selected + "/intelligence-data-quality",
      {
        params: { analytics_kind: kind, limit: 1 },
      },
    );
    expect(response.status()).toBe(200);
    expect(response.headers()["cache-control"]).toContain("no-store");
    const data = IntelligenceDataQualitySchema.parse(await response.json());
    expect(data.metrics).toHaveLength(counts[index]);
    const query = new URLSearchParams({
      account: selected,
      analytics_kind: kind,
      sources_limit: "1",
      state: "default",
    });
    await page.goto("/quality?" + query);
    await expect(
      page.getByRole("combobox", { name: "Portfolio account", exact: true }),
    ).toHaveValue(selected);
    const table = page.getByRole("table", {
      name: "Complete metric status inventory for " + label(kind),
      exact: true,
    });
    const rows = table.locator("tbody tr");
    await expect(rows).toHaveCount(data.metrics.length);
    for (const [rowIndex, metric] of data.metrics.entries()) {
      const row = rows.nth(rowIndex);
      await expect(row.getByRole("rowheader")).toHaveText(label(metric.key));
      const cells = row.getByRole("cell");
      await expect(cells.nth(0)).toHaveText(
        metric.recorded_availability
          ? label(metric.recorded_availability)
          : "Not recorded",
      );
      await expect(cells.nth(1)).toHaveText(
        metric.recorded_quality
          ? label(metric.recorded_quality)
          : "Not recorded",
      );
      await expect(cells.nth(3)).toHaveText(label(metric.current_usability));
    }
    if (!data.selection)
      await expect(
        page.getByText("No retained calculation", { exact: true }),
      ).toBeVisible();
    await checkedLayout(page);
  }
  const firstResponse = await request.get(
    api + "/accounts/" + account + "/intelligence-data-quality",
    {
      params: { analytics_kind: "xray", limit: 1 },
    },
  );
  expect(firstResponse.status()).toBe(200);
  const first = IntelligenceDataQualitySchema.parse(await firstResponse.json());
  expect(first.selection).not.toBeNull();
  await page.goto(
    "/quality?" +
      new URLSearchParams({
        account,
        analytics_kind: "xray",
        sources_limit: "1",
        state: "default",
      }),
  );
  await assertSourcePage(page, first);
  const next = page.getByRole("link", {
    name: "Next source page",
    exact: true,
  });
  await expect(next).toBeVisible();
  const nextURL = new URL((await next.getAttribute("href"))!, origin);
  expect(nextURL.searchParams.get("state")).toBe("default");
  expect(nextURL.searchParams.get("analytics_kind")).toBe("xray");
  const cursor = nextURL.searchParams.get("sources_cursor");
  expect(cursor).toBeTruthy();
  const response = await request.get(
    api + "/accounts/" + account + "/intelligence-data-quality",
    {
      params: { analytics_kind: "xray", limit: 1, cursor: cursor! },
    },
  );
  expect(response.status()).toBe(200);
  const second = IntelligenceDataQualitySchema.parse(await response.json());
  expect(second.selection).toEqual(first.selection);
  expect(second.sources.exact_total).toBe(first.sources.exact_total);
  const firstIdentities = new Set(
    sourceIdentities(first).map((identity) => JSON.stringify(identity)),
  );
  expect(
    sourceIdentities(second).every(
      (identity) => !firstIdentities.has(JSON.stringify(identity)),
    ),
  ).toBe(true);
  await next.click();
  await expect(page).toHaveURL(nextURL.toString());
  await assertSourcePage(page, second);
  const currentPage = page.url();
  await page.reload();
  await expect(page).toHaveURL(currentPage);
  await assertSourcePage(page, second);
  // A replay of the UI-issued cursor retains the actual selection boundary,
  // while a fresh first-page query is allowed to establish a new boundary.
  const replayResponse = await request.get(
    api + "/accounts/" + account + "/intelligence-data-quality",
    {
      params: { analytics_kind: "xray", limit: 1, cursor: cursor! },
    },
  );
  expect(replayResponse.status()).toBe(200);
  const replay = IntelligenceDataQualitySchema.parse(
    await replayResponse.json(),
  );
  expect(replay.selection_at).toBe(second.selection_at);
  expect(replay.selection).toEqual(second.selection);
  expect(replay.sources.exact_total).toBe(second.sources.exact_total);
  expect(sourceIdentities(replay)).toEqual(sourceIdentities(second));
  await page
    .getByRole("link", { name: "First source page", exact: true })
    .click();
  await expect(page).toHaveURL(
    (url) =>
      url.searchParams.get("analytics_kind") === "xray" &&
      url.searchParams.get("state") === "default" &&
      !url.searchParams.has("sources_cursor"),
  );
  await assertSourcePage(page, first);
  await page.goBack();
  await expect(page).toHaveURL(currentPage);
  await assertSourcePage(page, second);
  await checkedLayout(page);
  // Frame the disclosure only after the unmodified native keyboard checks.
  await page
    .getByRole("heading", { name: "Quality & reconciliation", exact: true })
    .click();
  const header = await page.getByRole("banner").boundingBox();
  await page
    .getByRole("heading", { name: "Visible source references", exact: true })
    .evaluate(
      (heading, offset) => {
        heading.scrollIntoView({ block: "start", behavior: "instant" });
        window.scrollBy(0, -offset);
      },
      (header?.height ?? 0) + 24,
    );
  await page
    .getByRole("region", { name: "Intelligence source quality", exact: true })
    .evaluate((region) => {
      region.scrollTop = 0;
      region.scrollLeft = region.scrollWidth;
    });
  await expect(
    page
      .getByRole("region", { name: "Intelligence source quality", exact: true })
      .locator("summary")
      .first(),
  ).toBeInViewport({ ratio: 1 });
  await page.screenshot({
    path: join(tmpdir(), "t212-p2-08-quality-" + info.project.name + ".png"),
    fullPage: false,
  });
  expect(errors).toEqual([]);
});
