import {
  expect,
  test,
  type APIRequestContext,
  type Page,
  type Request,
  type Response,
} from "@playwright/test";
import {
  PerformanceIntelligenceResponseSchema,
  BenchmarkComparisonResponseSchema,
  DividendIntelligenceResponseSchema,
  CashFlowIntelligenceResponseSchema,
  AttributionSummaryResponseSchema,
} from "@trading212/api-contracts";

const api = "http://127.0.0.1:18000/api/v1";
const annual = "9a85cdf8-eac9-57c7-be38-e500e4b9edb4";
const baseline = "f0f5c66e-b128-59b2-a620-83bc8faa4a57";
const windowQuery = {
  start_date: "2025-01-01",
  end_date: "2025-12-31",
  source_cutoff_at: "2026-09-07T12:00:00.123456Z",
  reporting_currency: "EUR",
};

function href(
  path: "/performance" | "/income",
  extra: Record<string, string> = {},
) {
  return `${path}?${new URLSearchParams({
    account: annual,
    start: windowQuery.start_date,
    end: windowQuery.end_date,
    cutoff: windowQuery.source_cutoff_at,
    currency: "EUR",
    ...extra,
  })}`;
}

test.beforeEach(async ({ page, request }) => {
  page.setDefaultTimeout(30_000);
  await page.goto("/sign-in");
  await page.getByRole("button", { name: "Start local session" }).click();
  await expect(page).toHaveURL("http://127.0.0.1:3001/");
  expect((await request.post(`${api}/auth/local-session`)).status()).toBe(201);
});

function errors(page: Page) {
  const messages: string[] = [];
  page.on("pageerror", (error) => messages.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") messages.push(message.text());
  });
  return messages;
}

async function presentation(page: Page) {
  const overflow = await page.evaluate(() => {
    const width = document.documentElement.clientWidth;
    return [...document.querySelectorAll<HTMLElement>(".historical-page *")]
      .filter((node) => !node.closest(".table-scroll"))
      .filter((node) => node.getBoundingClientRect().right > width + 1)
      .map((node) => ({
        tag: node.tagName,
        className: node.className,
        right: node.getBoundingClientRect().right,
        whiteSpace: getComputedStyle(node).whiteSpace,
      }));
  });
  expect(
    await page.evaluate(
      () =>
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
    ),
    JSON.stringify(overflow),
  ).toBeLessThanOrEqual(1);
  expect(
    await page.evaluate(() => {
      const failures: string[] = [];
      for (const table of document.querySelectorAll("table")) {
        if (
          !table.querySelector("caption") &&
          !table.getAttribute("aria-label")
        )
          failures.push("unnamed table");
      }
      for (const control of document.querySelectorAll(
        "input,select,textarea",
      )) {
        if (
          control.getAttribute("type") !== "hidden" &&
          !control.closest("label") &&
          !control.getAttribute("aria-label")
        )
          failures.push("unlabelled control");
      }
      if (
        document.querySelectorAll("main").length !== 1 ||
        document.querySelectorAll("h1").length !== 1
      )
        failures.push("landmark count");
      return failures;
    }),
  ).toEqual([]);
}

async function get(
  request: APIRequestContext,
  suffix: string,
  params: Record<string, string | number> = {},
) {
  const response = await request.get(`${api}/accounts/${annual}/${suffix}`, {
    params: { ...windowQuery, ...params },
  });
  expect(response.status()).toBe(200);
  return response.json();
}

async function applyFilters(page: Page) {
  const started = performance.now();
  const elapsed = () => Math.round(performance.now() - started);
  // Only fixed route names may leave the observer, even after a redirect.
  const pathname = (url: string) => {
    try {
      const path = new URL(url).pathname;
      return ["/", "/performance", "/income", "/sign-in"].includes(path)
        ? path
        : "[redacted]";
    } catch {
      return "[unavailable]";
    }
  };
  // Observe submitted GET choices, not DOM defaults or normalized API values.
  // Only explicit enum literals and fixed markers may leave this observer.
  const submittedChoices = (url: string) => {
    let params: URLSearchParams | undefined;
    try {
      params = new URL(url).searchParams;
    } catch {
      // A malformed URL must not throw from the request listener.
    }
    const choice = (name: string, allowed: readonly string[]) => {
      if (!params) return "[unrecognized]";
      const values = params.getAll(name);
      if (values.length === 0) return "[missing]";
      return values.length === 1 && allowed.includes(values[0])
        ? values[0]
        : "[unrecognized]";
    };
    return {
      view: choice("view", [
        "summary",
        "benchmark",
        "series",
        "rolling",
        "calendar",
        "attribution",
        "income",
        "cash_flows",
      ]),
      method: choice("method", ["twr", "mwr", "modified_dietz"]),
      frequency: choice("frequency", ["daily", "monthly"]),
      rolling: choice("rolling", [
        "none",
        "calendar_days_30",
        "calendar_days_90",
        "calendar_days_365",
      ]),
      calendar: choice("calendar", ["none", "month", "quarter", "year"]),
      knowledge: choice("knowledge", ["as_of_cutoff", "point_in_time"]),
      coverage: choice("coverage", ["require_complete", "allow_degraded"]),
      // Presence alone includes an empty capture key; its value is never retained.
      capturePresent: params?.has("capture") ?? false,
    };
  };
  const documents = new Map<
    Request,
    {
      pathname: string;
      submittedChoices: ReturnType<typeof submittedChoices>;
      requestAtMs: number;
      responseAtMs: number | null;
      status: number | null;
      finishAtMs: number | null;
      failAtMs: number | null;
    }
  >();
  let truncated = false;
  let frameUnavailable = false;
  let clickCompletedAtMs: number | null = null;
  let loadAtMs: number | null = null;
  let loadRejectedAtMs: number | null = null;
  const onRequest = (request: Request) => {
    if (!request.isNavigationRequest() || request.resourceType() !== "document")
      return;
    // A navigation can precede frame creation or race page teardown.
    try {
      if (request.frame() !== page.mainFrame()) return;
    } catch {
      frameUnavailable = true;
      return;
    }
    if (documents.size === 8) {
      truncated = true;
      return;
    }
    documents.set(request, {
      pathname: pathname(request.url()),
      requestAtMs: elapsed(),
      submittedChoices: submittedChoices(request.url()),
      responseAtMs: null,
      status: null,
      finishAtMs: null,
      failAtMs: null,
    });
  };
  const onResponse = (response: Response) => {
    const entry = documents.get(response.request());
    if (entry) {
      entry.responseAtMs = elapsed();
      entry.status = response.status();
    }
  };
  const onFinished = (request: Request) => {
    const entry = documents.get(request);
    if (entry) entry.finishAtMs = elapsed();
  };
  const onFailed = (request: Request) => {
    const entry = documents.get(request);
    if (entry) entry.failAtMs = elapsed();
  };
  page.on("request", onRequest);
  page.on("response", onResponse);
  page.on("requestfinished", onFinished);
  page.on("requestfailed", onFailed);
  const loadWait = new AbortController();
  try {
    // These GET forms stream the server calculation. Wait for this document's
    // load event before reading results or submitting another form.
    const loaded = page
      .waitForEvent("load", { timeout: 30_000, signal: loadWait.signal })
      .then(() => {
        loadAtMs = elapsed();
      });
    // Observe rejection while click is pending; await below still propagates it.
    void loaded.catch(() => {
      loadRejectedAtMs = elapsed();
    });
    await page.getByRole("button", { name: "Apply filters" }).click();
    clickCompletedAtMs = elapsed();
    await loaded;
  } catch (error) {
    const failedAtMs = elapsed();
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      // Failure-only, synchronous DOM read; teardown or an unresponsive renderer
      // must not hold up the original failure. No DOM values or text are logged.
      const dom = page.isClosed()
        ? "page-closed"
        : await Promise.race([
            page
              .evaluate(() => {
                const form = document.querySelector("form.historical-filters");
                return {
                  readyState: document.readyState,
                  formPresent: form !== null,
                  // Unlike checkValidity(), this does not dispatch invalid events.
                  formValid: form?.matches(":valid") ?? null,
                  historicalResultPresent:
                    document.querySelector(".historical-context") !== null,
                  benchmarkResultPresent:
                    document.querySelector("#benchmark-series-table") !== null,
                };
              })
              .catch(() => "unavailable"),
            new Promise<string>((resolve) => {
              timer = setTimeout(() => resolve("timeout"), 250);
            }),
          ]);
      // Marker presence describes the current DOM, possibly the prior document;
      // it is diagnostic evidence, never a substitute for the load predicate.
      console.error(
        "historical.applyFilters.failure",
        JSON.stringify({
          failedAtMs,
          observedUntilMs: elapsed(),
          clickCompletedAtMs,
          loadAtMs,
          loadRejectedAtMs,
          nativeDocumentObserved: documents.size > 0,
          documents: [...documents.values()],
          truncated,
          frameUnavailable,
          dom,
        }),
      );
    } catch {
      // Even an unexpected diagnostic failure must preserve the original error.
    } finally {
      clearTimeout(timer);
    }
    throw error;
  } finally {
    page.off("request", onRequest);
    page.off("response", onResponse);
    page.off("requestfinished", onFinished);
    page.off("requestfailed", onFailed);
    loadWait.abort();
  }
}

async function view(page: Page, label: string, value: string) {
  await page.getByRole("link", { name: label, exact: true }).click();
  // Next keeps the prior form mounted while loading a tab. Match the committed
  // view before editing controls shared by both tabs.
  await expect(page.locator('form input[name="view"]')).toHaveValue(value, {
    timeout: 30_000,
  });
}

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

test("performance charts preserve canonical values, exact replay and bounded series across method and period filters", async ({
  page,
  request,
}, testInfo) => {
  test.setTimeout(180_000);
  const failures = errors(page);
  await page.goto(href("/performance"));
  await expect(
    page.getByRole("heading", { name: "Value and return history" }),
  ).toBeVisible({ timeout: 30_000 });
  const data = PerformanceIntelligenceResponseSchema.parse(
    await get(request, "performance/intelligence"),
  );
  expect(data.context.availability).toBe("available");
  await expect(
    page
      .locator(".metric-card")
      .filter({ has: page.getByText("Ending value", { exact: true }) }),
  ).toContainText("2,191.280575 EUR");
  await expect(
    page.getByRole("img", { name: "Portfolio value with external flows" }),
  ).toBeVisible();
  await expect(page.locator("#performance-series-table tbody tr")).toHaveCount(
    data.series.length,
  );
  const ending = data.series.at(-1)!.portfolio_value.value!;
  await expect(
    page
      .locator("#performance-series-table tbody tr")
      .last()
      .locator("td")
      .first()
      .locator("[title]"),
  ).toHaveAttribute("title", `${ending.amount} ${ending.currency}`);
  await showSection(page, "Value and return history");
  await presentation(page);
  await page.screenshot({
    path: `/tmp/t212-p2-04-${testInfo.project.name}-performance.png`,
    fullPage: false,
  });

  await page.getByRole("link", { name: "Replay these exact inputs" }).click();
  await expect(page).toHaveURL(/capture=[0-9a-f-]{36}/);
  expect(new URL(page.url()).searchParams.get("capture")).toBe(
    data.context.input_snapshot_id,
  );
  await page
    .getByText("Coverage, assumptions and source evidence", { exact: true })
    .click();
  await expect(
    page.getByText(data.context.content_digest, { exact: true }),
  ).toBeVisible();
  await page
    .getByText("Coverage, assumptions and source evidence", { exact: true })
    .click();
  await expect(page.getByLabel(/^Knowledge cutoff \(UTC\)/)).toHaveValue(
    windowQuery.source_cutoff_at,
  );

  await view(page, "Series", "series");
  await page.getByLabel("Rows per page").fill("2");
  await applyFilters(page);
  await expect(page.locator("#performance-series-table tbody tr")).toHaveCount(
    2,
  );
  const firstDate = await page
    .locator("#performance-series-table tbody tr")
    .first()
    .locator("th")
    .textContent();
  await page
    .getByRole("navigation", { name: "Historical pagination" })
    .getByRole("link", { name: "Next page" })
    .click();
  await expect(page).toHaveURL(/cursor=/);
  await expect(page.locator("#performance-series-table tbody tr")).toHaveCount(
    2,
  );
  expect(
    await page
      .locator("#performance-series-table tbody tr")
      .first()
      .locator("th")
      .textContent(),
  ).not.toBe(firstDate);
  expect(new URL(page.url()).searchParams.get("capture")).toBeTruthy();
  await page
    .getByRole("navigation", { name: "Historical pagination" })
    .getByRole("link", { name: "First page" })
    .click();
  await expect(
    page.locator("#performance-series-table tbody tr").first(),
  ).toContainText(firstDate!);

  await view(page, "Summary", "summary");
  await page
    .getByRole("combobox", { name: "Return method", exact: true })
    .selectOption("mwr");
  await applyFilters(page);
  await expect(page).toHaveURL(/method=mwr/);
  await expect(
    page.getByRole("heading", { name: "Value and return history" }),
  ).toBeVisible({ timeout: 30_000 });
  const mwr = PerformanceIntelligenceResponseSchema.parse(
    await get(request, "performance/intelligence", { method: "mwr" }),
  );
  const lastMwr = mwr.series.at(-1)!.cumulative_return.value!;
  await expect(
    page
      .locator("#performance-series-table tbody tr")
      .last()
      .locator("td")
      .nth(5)
      .locator("[title]"),
  ).toHaveAttribute("title", lastMwr);
  await view(page, "Rolling", "rolling");
  await expect(
    page.getByRole("heading", { name: "Rolling returns", exact: true }),
  ).toBeVisible();
  expect(new URL(page.url()).searchParams.has("capture")).toBe(false);
  await view(page, "Calendar", "calendar");
  await expect(
    page.getByRole("heading", { name: "Calendar returns", exact: true }),
  ).toBeVisible();
  await presentation(page);
  expect(failures).toEqual([]);
});

test("benchmark and group attribution keep published source identities and sourced sector classifications", async ({
  page,
  request,
}, testInfo) => {
  test.setTimeout(180_000);
  const failures = errors(page);
  await page.goto(href("/performance", { view: "benchmark" }));
  await expect(
    page.getByText("Choose a benchmark version", { exact: true }),
  ).toBeVisible();
  const selector = page.getByRole("combobox", {
    name: "Benchmark version",
    exact: true,
  });
  const benchmark = await selector
    .locator("option")
    .filter({ hasText: "Synthetic annual 60/40 benchmark" })
    .getAttribute("value");
  expect(benchmark).toBeTruthy();
  await selector.selectOption(benchmark!);
  await page
    .getByRole("combobox", { name: "Calendar period", exact: true })
    .selectOption("year");
  await applyFilters(page);
  await expect(
    page.getByRole("heading", { name: "Aligned benchmark comparison" }),
  ).toBeVisible({ timeout: 30_000 });
  const data = BenchmarkComparisonResponseSchema.parse(
    await get(request, "benchmark-comparison", {
      benchmark_version_id: benchmark!,
      calendar_period: "year",
    }),
  );
  expect(data.composite_snapshot?.kind).toBe("composite");
  await expect(
    page.getByRole("img", { name: "Portfolio and benchmark returns" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", {
      name: "Calendar benchmark comparisons",
      exact: true,
    }),
  ).toBeVisible();
  await presentation(page);
  await showSection(page, "Aligned benchmark comparison");
  await page.screenshot({
    path: `/tmp/t212-p2-04-${testInfo.project.name}-benchmark.png`,
    fullPage: false,
  });
  const returnTo = page.url();
  await page
    .getByRole("link", {
      name: "Inspect immutable composite inputs and levels",
    })
    .click();
  await expect(
    page.getByRole("heading", { name: "Composite benchmark snapshot" }),
  ).toBeVisible();
  await expect(
    page.getByText(data.composite_snapshot!.content_digest, { exact: true }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Next page", exact: true }).click();
  await expect(page).toHaveURL(/cursor=/);
  await presentation(page);
  await page.goto(returnTo);

  await view(page, "Attribution", "attribution");
  await page
    .getByRole("combobox", { name: "Grouping", exact: true })
    .selectOption("group");
  const targets = page.getByRole("combobox", {
    name: "Published target for group comparison",
    exact: true,
  });
  const target = await targets
    .locator("option")
    .filter({ hasText: "Synthetic annual historical groups" })
    .getAttribute("value");
  expect(target).toBeTruthy();
  await targets.selectOption(target!);
  await applyFilters(page);
  await expect(
    page.getByRole("heading", { name: "Contribution by selected grouping" }),
  ).toBeVisible({ timeout: 30_000 });
  const components = page.getByRole("region", {
    name: "Attribution components table",
  });
  await expect(components).toContainText(/eur/i);
  await expect(components).toContainText(/usd/i);
  await expect(
    page.getByRole("combobox", { name: "Target timing", exact: true }),
  ).toHaveValue("explicit_comparison");
  await page
    .getByRole("combobox", { name: "Grouping", exact: true })
    .selectOption("sector");
  await applyFilters(page);
  const sectors = AttributionSummaryResponseSchema.parse(
    await get(request, "attribution", {
      grouping: "sector",
      target_version_id: target!,
      benchmark_version_id: benchmark!,
    }),
  );
  expect(sectors.rows.map((row) => row.label)).toEqual(
    expect.arrayContaining(["industrials", "technology"]),
  );
  await expect(components.locator("tbody tr")).toHaveCount(sectors.rows.length);
  for (const row of sectors.rows) {
    const displayed = components.locator("tbody tr").filter({
      has: page.getByRole("rowheader", { name: row.label, exact: true }),
    });
    await expect(displayed).toContainText(
      row.unresolved ? "Unresolved classification" : "Assigned",
    );
    if (row.amount.value)
      await expect(
        displayed.locator("td").first().locator("[title]"),
      ).toHaveAttribute(
        "title",
        `${row.amount.value.amount} ${row.amount.value.currency}`,
      );
  }
  await presentation(page);
  expect(failures).toEqual([]);
});

test("income retains native totals and grouped results while the cash-flow timeline pages separately from unavailable inputs", async ({
  page,
  request,
}, testInfo) => {
  test.setTimeout(180_000);
  const failures = errors(page);
  await page.goto(href("/income"));
  await expect(
    page.getByRole("heading", { name: "Income by original currency" }),
  ).toBeVisible({ timeout: 30_000 });
  const data = DividendIntelligenceResponseSchema.parse(
    await get(request, "dividend-intelligence"),
  );
  expect(data.summary.net_income.value).not.toBeNull();
  const native = page.getByRole("table", { name: "Original currency totals" });
  await expect(native).toContainText("USD");
  await expect(native).toContainText("EUR");
  await expect(
    page.getByRole("table", { name: "Sourced reporting-currency totals" }),
  ).toContainText("EUR");
  await expect(
    page.getByRole("img", { name: "Income by period" }),
  ).toBeVisible();
  await showSection(page, "Income by original currency");
  await presentation(page);
  await page.screenshot({
    path: `/tmp/t212-p2-04-${testInfo.project.name}-income.png`,
    fullPage: false,
  });
  await page
    .getByRole("combobox", { name: "Grouping", exact: true })
    .selectOption("group");
  const targets = page.getByRole("combobox", {
    name: "Published target for group comparison",
    exact: true,
  });
  const target = await targets
    .locator("option")
    .filter({ hasText: "Synthetic annual historical groups" })
    .getAttribute("value");
  await targets.selectOption(target!);
  await applyFilters(page);
  await expect(
    page.getByRole("region", { name: "Income components table" }),
  ).toContainText(/eur/i);
  await expect(
    page.getByRole("region", { name: "Income components table" }),
  ).toContainText(/usd/i);

  await view(page, "Cash Flows", "cash_flows");
  await page.getByLabel("Rows per page").fill("2");
  await applyFilters(page);
  await expect(
    page.getByRole("heading", { name: "Cash-flow timeline" }),
  ).toBeVisible({ timeout: 30_000 });
  const flows = CashFlowIntelligenceResponseSchema.parse(
    await get(request, "cash-flow-intelligence", { limit: 2 }),
  );
  const table = page
    .getByRole("region", { name: "Cash-flow event table" })
    .locator("table");
  await expect(table.locator("tbody tr")).toHaveCount(2);
  await expect(table.locator("tbody tr").first()).toContainText(
    flows.events.items[0].classification === "external"
      ? "External"
      : "Internal",
  );
  const firstRow = await table.locator("tbody tr").first().textContent();
  await page
    .getByRole("navigation", { name: "Historical pagination" })
    .getByRole("link", { name: "Next page" })
    .click();
  await expect(page).toHaveURL(/cursor=/);
  expect(await table.locator("tbody tr").first().textContent()).not.toBe(
    firstRow,
  );
  await page
    .getByRole("combobox", { name: "Event kind", exact: true })
    .selectOption("dividend");
  await applyFilters(page);
  expect(new URL(page.url()).searchParams.has("cursor")).toBe(false);
  for (const row of await table.locator("tbody tr").all())
    await expect(row).toContainText("Dividend");
  await presentation(page);
  await showSection(page, "Cash-flow timeline");
  await page.screenshot({
    path: `/tmp/t212-p2-04-${testInfo.project.name}-cash-flows.png`,
    fullPage: false,
  });

  await page.goto(href("/performance", { account: baseline }));
  await expect(
    page
      .locator(".metric-card")
      .filter({ has: page.getByText("Ending value", { exact: true }) }),
  ).toContainText("Unavailable");
  await expect(
    page.getByRole("combobox", { name: "Account", exact: true }),
  ).toHaveValue(baseline);
  await page.goto(
    href("/performance", { private_canary: "private-value-canary" }),
  );
  await expect(
    page.getByText("Invalid historical filters", { exact: true }),
  ).toBeVisible();
  await expect(page.locator("body")).not.toContainText("private-value-canary");
  expect(failures).toEqual([]);
});
