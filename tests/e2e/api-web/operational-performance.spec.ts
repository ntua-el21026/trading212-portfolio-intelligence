import { createHash } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import { cpus, freemem, platform, release, totalmem } from "node:os";
import { join } from "node:path";
import { gzipSync } from "node:zlib";
import {
  expect,
  test,
  type APIRequestContext,
  type Browser,
  type Page,
  type TestInfo,
} from "@playwright/test";
import { z } from "zod";

// Frozen before execution; no warm-up sample is discarded.
const RUNS = 5;
const LCP_P75_MS = 2500;
const INTERACTION_P75_MS = 200;
const CLS_MAX = 0.1;
const APP_JS_MAX_BYTES = 350 * 1024;
const host = "http://127.0.0.1:18000";
const fixtureSchema = z.object({
  account_id: z.string().uuid(),
  snapshot_id: z.string().uuid(),
  run_id: z.string().uuid(),
  cutoff: z.string(),
  holdings: z.literal(100),
  events: z.literal(1000),
  source_versions: z.literal(1000),
  witnesses: z.literal(1000),
  retained_bytes: z.number().int().positive().max(268435456),
  setup_elapsed_seconds: z.number().nonnegative(),
  position_quality_states: z.array(z.string()).nonempty(),
  recipe_digest: z.string().length(64),
  published_revision_digest: z.string().length(64),
  xray_input_digest: z.string().length(64),
  xray_result_digest: z.string().length(64),
});
type Event = {
  name: string;
  startTime: number;
  duration: number;
  interactionId: number;
};
type Metrics = {
  supported: readonly string[];
  lcp: number;
  lcpCandidates: number[];
  cls: number;
  shifts: { value: number; startTime: number; recentInput: boolean }[];
  events: Event[];
  trustedGestures: number;
};
declare global {
  interface Window {
    __phase3Performance: Metrics;
  }
}
type Asset = {
  path: string;
  encodedBytes: number;
  decodedBytes: number;
  transferBytes: number;
  encoding: string;
};
type Sample = {
  route: string;
  ordinal: number;
  viewport: { width: number; height: number };
  metrics: Metrics;
  interactionMs: number;
  interactionCensoredBelowMs: number | null;
  filterCompletionMs: number;
  paginationCompletionMs: number;
  assets: Asset[];
  browserMetrics: unknown;
  processUsage: NodeJS.ResourceUsage;
  inlineScriptBytes: number;
};

async function preparedFixture(
  request: APIRequestContext,
  info: TestInfo,
  caseStarted: number,
) {
  const started = performance.now();
  const observations: { elapsedMs: number; status: number }[] = [];
  let outcome = "waiting";
  let errorType: string | undefined;
  let serverSetupSeconds: number | undefined;
  // The unchanged outer Playwright timeout also includes fixture setup. This
  // local poll never resets it or grants another preparation budget.
  const remaining = () => info.timeout - (performance.now() - caseStarted);
  try {
    while (true) {
      const budget = remaining();
      if (budget <= 0)
        throw new Error(
          "Preparation exhausted the existing total case budget.",
        );
      const response = await request.get(`${host}/__e2e__/web-performance`, {
        timeout: Math.min(5000, budget),
        failOnStatusCode: false,
      });
      observations.push({
        elapsedMs: performance.now() - started,
        status: response.status(),
      });
      expect(response.headers()["cache-control"]).toContain("no-store");
      if (response.status() === 503) {
        expect(await response.json()).toEqual({ state: "preparing" });
        const delay = Math.min(1000, remaining());
        if (delay <= 0)
          throw new Error(
            "Preparation exhausted the existing total case budget.",
          );
        await new Promise<void>((resolve) => setTimeout(resolve, delay));
        continue;
      }
      if (response.status() === 500) {
        const failure = z
          .strictObject({
            state: z.literal("failed"),
            error_type: z.string().regex(/^[A-Za-z_][A-Za-z0-9_]{0,63}$/),
          })
          .parse(await response.json());
        errorType = failure.error_type;
        throw new Error(`Performance preparation failed (${errorType}).`);
      }
      expect(response.status()).toBe(200);
      const fixture = fixtureSchema.parse(await response.json());
      outcome = "verified_complete";
      serverSetupSeconds = fixture.setup_elapsed_seconds;
      return fixture;
    }
  } catch (error) {
    outcome = "failed";
    errorType ??= error instanceof Error ? error.name : "unknown";
    throw error;
  } finally {
    await writeFile(
      info.outputPath("web-performance-preparation.json"),
      JSON.stringify(
        {
          outcome,
          errorType,
          caseBudgetMs: info.timeout,
          waitElapsedMs: performance.now() - started,
          caseCallbackElapsedMs: performance.now() - caseStarted,
          serverSetupSeconds,
          observations,
          scope:
            "fixture preparation only; no authentication or browser measurements yet",
        },
        null,
        2,
      ),
      { mode: 0o600 },
    );
  }
}

function percentile75(values: number[]) {
  if (values.length !== RUNS || values.some((value) => !Number.isFinite(value)))
    throw new Error("All five actual samples are required.");
  return [...values].sort((left, right) => left - right)[
    Math.ceil(0.75 * values.length) - 1
  ];
}
async function installObservers(page: Page) {
  await page.addInitScript(() => {
    const supported = PerformanceObserver.supportedEntryTypes;
    const data: Metrics = {
      supported,
      lcp: 0,
      lcpCandidates: [],
      cls: 0,
      shifts: [],
      events: [],
      trustedGestures: 0,
    };
    window.__phase3Performance = data;
    let sessionStart: number | null = null,
      previous = 0,
      sessionValue = 0;
    if (supported.includes("largest-contentful-paint"))
      new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) {
          data.lcp = entry.startTime;
          data.lcpCandidates.push(entry.startTime);
        }
      }).observe({ type: "largest-contentful-paint", buffered: true });
    if (supported.includes("layout-shift"))
      new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) {
          const shift = entry as PerformanceEntry & {
            value: number;
            hadRecentInput: boolean;
          };
          data.shifts.push({
            value: shift.value,
            startTime: shift.startTime,
            recentInput: shift.hadRecentInput,
          });
          if (shift.hadRecentInput) continue;
          if (
            sessionStart === null ||
            shift.startTime - previous > 1000 ||
            shift.startTime - sessionStart > 5000
          ) {
            sessionStart = shift.startTime;
            sessionValue = 0;
          }
          sessionValue += shift.value;
          previous = shift.startTime;
          data.cls = Math.max(data.cls, sessionValue);
        }
      }).observe({ type: "layout-shift", buffered: true });
    if (supported.includes("event"))
      new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) {
          const event = entry as PerformanceEntry & { interactionId: number };
          if (event.interactionId && data.events.length < 256)
            data.events.push({
              name: event.name,
              startTime: event.startTime,
              duration: event.duration,
              interactionId: event.interactionId,
            });
        }
      }).observe({
        type: "event",
        buffered: true,
        durationThreshold: 16,
      } as PerformanceObserverInit & { durationThreshold: number });
    for (const name of ["click", "keydown"])
      document.addEventListener(
        name,
        (event) => {
          if (event.isTrusted) data.trustedGestures += 1;
        },
        { capture: true },
      );
  });
}
async function noOverflow(page: Page) {
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth - window.innerWidth,
    ),
  ).toBeLessThanOrEqual(1);
}
async function ready(page: Page, route: string) {
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    route === "research" ? "Research" : "Holdings",
  );
  if (route === "research") {
    await expect(
      page.getByRole("heading", {
        level: 2,
        name: "Exposure-ranked research",
        exact: true,
      }),
    ).toBeVisible();
    await expect(page.getByTestId("research-item")).toHaveCount(25);
    await expect(
      page.getByLabel("research items pagination", { exact: true }),
    ).toContainText("25 of 1000 research items");
    await expect(
      page.getByText(/1000 matching source revisions/),
    ).toBeVisible();
    for (const value of await page
      .getByTestId("research-portfolio-facts")
      .all())
      await expect(value).toContainText("10 EUR");
  } else {
    await expect(
      page
        .getByRole("table", { name: "Direct portfolio holdings", exact: true })
        .locator("tbody tr"),
    ).toHaveCount(50);
    await expect(page.getByLabel("Collection pagination")).toContainText(
      "100 matching records",
    );
  }
  await noOverflow(page);
}

async function sample(
  browser: Browser,
  route: "holdings" | "research",
  ordinal: number,
  target: string,
  viewport: { width: number; height: number },
  info: TestInfo,
): Promise<Sample> {
  // Authentication uses only the context's in-memory cookie jar; no authenticated
  // page or JavaScript asset is visited before this cold-browser navigation.
  const context = await browser.newContext({ viewport, deviceScaleFactor: 1 });
  const partial: Record<string, unknown> = {
    route,
    ordinal,
    viewport,
    startedAt: new Date().toISOString(),
    outcome: "started",
  };
  try {
    expect(
      (
        await context.request.post(`${host}/api/v1/auth/local-session`)
      ).status(),
    ).toBe(201);
    const page = await context.newPage();
    const failures: string[] = [];
    const encodings = new Map<string, string>();
    page.on("pageerror", (error) => failures.push(error.message));
    page.on("console", (message) => {
      if (["error", "warning"].includes(message.type()))
        failures.push(message.text());
    });
    page.on("response", (response) => {
      const path = new URL(response.url()).pathname;
      if (path.startsWith("/_next/static/") && path.endsWith(".js"))
        encodings.set(
          path,
          response.headers()["content-encoding"] ?? "identity",
        );
    });
    await installObservers(page);
    const cdp = await context.newCDPSession(page);
    await cdp.send("Network.enable");
    await cdp.send("Network.setCacheDisabled", { cacheDisabled: true });
    await cdp.send("Performance.enable");
    await page.goto(target, { waitUntil: "networkidle" });
    await ready(page, route);
    const initial = await page.evaluate(() => ({
      assets: performance
        .getEntriesByType("resource")
        .filter((value) => {
          const path = new URL(value.name).pathname;
          return path.startsWith("/_next/static/") && path.endsWith(".js");
        })
        .map((value) => {
          const item = value as PerformanceResourceTiming;
          return {
            path: new URL(item.name).pathname,
            encodedBytes: item.encodedBodySize,
            decodedBytes: item.decodedBodySize,
            transferBytes: item.transferSize,
          };
        }),
      inlineScriptBytes: [...document.scripts]
        .filter((element) => !element.src)
        .reduce(
          (sum, element) =>
            sum + new TextEncoder().encode(element.textContent ?? "").length,
          0,
        ),
    }));
    expect(initial.assets.length).toBeGreaterThan(0);
    for (const asset of initial.assets)
      expect(asset.encodedBytes).toBeGreaterThan(0);
    await page
      .getByRole("button", { name: "Open command palette", exact: true })
      .click();
    await expect(
      page.getByRole("dialog", { name: "Go to a workspace" }),
    ).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog")).not.toBeVisible();
    const filter =
      route === "research"
        ? page.getByRole("combobox", { name: "Source kind", exact: true })
        : page.getByRole("combobox", { name: "Sort", exact: true });
    await expect(filter).toBeVisible();
    await filter.focus();
    await filter.press("ArrowDown");
    // Allow the browser's Event Timing observer delivery, outside its measured durations.
    await page.waitForTimeout(250);
    const metrics = await page.evaluate(() => window.__phase3Performance);
    for (const kind of ["largest-contentful-paint", "layout-shift", "event"])
      expect(metrics.supported).toContain(kind);
    expect(metrics.lcp).toBeGreaterThan(0);
    expect(metrics.trustedGestures).toBeGreaterThanOrEqual(3);
    const durations = new Map<number, number>();
    for (const event of metrics.events)
      durations.set(
        event.interactionId,
        Math.max(durations.get(event.interactionId) ?? 0, event.duration),
      );
    // With supported Event Timing and real gestures in this same live document,
    // omitted sub-threshold entries provide a conservative <16 ms bound, not zero.
    const interactionMs = durations.size ? Math.max(...durations.values()) : 16;
    const interactionCensoredBelowMs = durations.size ? null : 16;
    Object.assign(partial, {
      metrics,
      initial,
      interactionMs,
      interactionCensoredBelowMs,
      outcome: "measured_initial_document",
    });
    const started = Date.now();
    await page
      .getByRole("button", {
        name: route === "research" ? "Load research" : "Apply",
        exact: true,
      })
      .click();
    await page.waitForLoadState("networkidle");
    await ready(page, route);
    const filterCompletionMs = Date.now() - started;
    const next = Date.now();
    await page
      .getByRole("link", {
        name: route === "research" ? "Next research items" : "Next page",
        exact: route === "research",
      })
      .click();
    await expect
      .poll(() => new URL(page.url()).searchParams.has("cursor"))
      .toBe(true);
    await ready(page, route);
    if (route === "holdings") {
      await expect(page.getByRole("link", { name: "Next page" })).toHaveCount(
        0,
      );
      await expect(page.getByLabel("Collection pagination")).toContainText(
        "End of collection",
      );
    } else {
      await expect(
        page.getByRole("link", { name: "Next research items", exact: true }),
      ).toBeVisible();
    }
    const paginationCompletionMs = Date.now() - next;
    if (ordinal === 1)
      await page.screenshot({
        path: info.outputPath(`${route}-${viewport.width}.png`),
        fullPage: true,
      });
    expect(failures).toEqual([]);
    const result = {
      route,
      ordinal,
      viewport,
      metrics,
      interactionMs,
      interactionCensoredBelowMs,
      filterCompletionMs,
      paginationCompletionMs,
      assets: initial.assets.map((asset) => ({
        ...asset,
        encoding: encodings.get(asset.path) ?? "identity",
      })),
      inlineScriptBytes: initial.inlineScriptBytes,
      browserMetrics: await cdp.send("Performance.getMetrics"),
      processUsage: process.resourceUsage(),
    };
    Object.assign(partial, result, { outcome: "completed" });
    return result;
  } catch (error) {
    partial.outcome = "failed";
    partial.errorType = error instanceof Error ? error.name : "unknown";
    throw error;
  } finally {
    await writeFile(
      info.outputPath(`web-performance-${route}-${ordinal}.json`),
      JSON.stringify(partial, null, 2),
      { mode: 0o600 },
    );
    await context.close();
  }
}

test("production 100-holding 1000-event workload retains five raw lab samples and route byte budgets", async ({
  browser,
  request,
}, info) => {
  const caseStarted = performance.now();
  test.setTimeout(600_000);
  const viewport = info.project.name.includes("mobile")
    ? { width: 360, height: 800 }
    : info.project.name.includes("tablet")
      ? { width: 768, height: 1024 }
      : { width: 1440, height: 900 };
  const fixture = await preparedFixture(request, info, caseStarted);
  const web = process.cwd();
  const buildBytes = await readFile(join(web, ".next/build-manifest.json"));
  const build = z
    .object({
      rootMainFiles: z.array(z.string()),
      polyfillFiles: z.array(z.string()),
    })
    .parse(JSON.parse(buildBytes.toString("utf8")));
  const runtime = new Set(
    [...build.rootMainFiles, ...build.polyfillFiles].map(
      (path) => `/_next/${path}`,
    ),
  );
  const samples: Sample[] = [];
  const declared = {
    schema: "phase3_web_lab_v1",
    build: {
      id: (await readFile(join(web, ".next/BUILD_ID"), "utf8")).trim(),
      manifestSha256: createHash("sha256").update(buildBytes).digest("hex"),
    },
    runs: RUNS,
    percentile: "nearest_rank_ceiling_0.75_n",
    thresholds: {
      lcpP75Ms: LCP_P75_MS,
      interactionP75Ms: INTERACTION_P75_MS,
      clsMaximum: CLS_MAX,
      appJsBytes: APP_JS_MAX_BYTES,
    },
    scopes: {
      routes: ["holdings", "research"],
      coldBrowserContexts: true,
      browserCacheDisabled: true,
      serverDatabaseCache:
        "seeded; first research read includes normal item admission",
      measuredInteractions: [
        "palette open",
        "palette close",
        "native filter choice",
      ],
      navigationCompletion: "recorded separately; not Event Timing",
      fieldCWV: false,
      compressedBudget:
        "actual encoded JS body bytes, excluding only build rootMainFiles/polyfillFiles; shared application code included",
      runtimePaths: [...runtime],
      regressionBaseline:
        "not measured by this harness; requires a matching previous source/build/fixture cohort",
    },
    hardware: {
      platform: platform(),
      release: release(),
      cpuModels: [...new Set(cpus().map((cpu) => cpu.model))],
      logicalCpus: cpus().length,
      totalMemory: totalmem(),
      availableMemoryAtStart: freemem(),
      node: process.version,
      browser: browser.version(),
      viewport,
      deviceScaleFactor: 1,
    },
    fixture,
  };
  try {
    for (const route of ["holdings", "research"] as const)
      for (let ordinal = 1; ordinal <= RUNS; ordinal += 1) {
        const query = new URLSearchParams({
          account: fixture.account_id,
          ...(route === "research"
            ? { xray: fixture.run_id, cutoff: fixture.cutoff }
            : {}),
        });
        samples.push(
          await sample(
            browser,
            route,
            ordinal,
            `http://127.0.0.1:3001/${route}?${query}`,
            viewport,
            info,
          ),
        );
        await writeFile(
          info.outputPath("web-performance-raw.json"),
          JSON.stringify({ ...declared, samples }, null, 2),
          { mode: 0o600 },
        );
      }
    // Compression/hash work is deliberately after all timed navigations.
    const inventory = [];
    for (const path of [
      ...new Set(
        samples.flatMap((sample) => sample.assets.map((asset) => asset.path)),
      ),
    ].sort()) {
      if (
        !/^\/_next\/static\/[A-Za-z0-9._/-]+\.js$/.test(path) ||
        path.split("/").includes("..")
      )
        throw new Error("Unexpected public asset path.");
      const contents = await readFile(
        join(web, ".next", path.slice("/_next/".length)),
      );
      inventory.push({
        path,
        classification: runtime.has(path)
          ? "framework_bootstrap"
          : "counted_application",
        sha256: createHash("sha256").update(contents).digest("hex"),
        decodedBytes: contents.length,
        gzip9Bytes: gzipSync(contents, { level: 9 }).length,
      });
    }
    const holdingsAssets = new Set(
      samples
        .filter((sample) => sample.route === "holdings")
        .flatMap((sample) =>
          sample.assets
            .filter((asset) => !runtime.has(asset.path))
            .map((asset) => asset.path),
        ),
    );
    const cohorts = ["holdings", "research"].map((route) => {
      const values = samples.filter((sample) => sample.route === route);
      const compressed = values.map((sample) =>
        sample.assets
          .filter((asset) => !runtime.has(asset.path))
          .reduce((sum, asset) => sum + asset.encodedBytes, 0),
      );
      const shared = values.map((sample) =>
        sample.assets
          .filter(
            (asset) =>
              !runtime.has(asset.path) && holdingsAssets.has(asset.path),
          )
          .reduce((sum, asset) => sum + asset.encodedBytes, 0),
      );
      const incremental = values.map((sample) =>
        sample.assets
          .filter(
            (asset) =>
              !runtime.has(asset.path) && !holdingsAssets.has(asset.path),
          )
          .reduce((sum, asset) => sum + asset.encodedBytes, 0),
      );
      return {
        route,
        lcpP75Ms: percentile75(values.map((sample) => sample.metrics.lcp)),
        interactionP75Ms: percentile75(
          values.map((sample) => sample.interactionMs),
        ),
        clsMaximum: Math.max(...values.map((sample) => sample.metrics.cls)),
        appCompressedBytesMaximum: Math.max(...compressed),
        runtimeCompressedBytes: values.map((sample) =>
          sample.assets
            .filter((asset) => runtime.has(asset.path))
            .reduce((sum, asset) => sum + asset.encodedBytes, 0),
        ),
        sharedApplicationBytes: shared,
        incrementalApplicationBytes: incremental,
      };
    });
    await writeFile(
      info.outputPath("web-performance-summary.json"),
      JSON.stringify(
        { ...declared, cohorts, assetInventory: inventory },
        null,
        2,
      ),
      { mode: 0o600 },
    );
    for (const cohort of cohorts) {
      expect
        .soft(cohort.lcpP75Ms, `${cohort.route} LCP p75`)
        .toBeLessThanOrEqual(LCP_P75_MS);
      expect
        .soft(cohort.interactionP75Ms, `${cohort.route} lab interaction p75`)
        .toBeLessThanOrEqual(INTERACTION_P75_MS);
      expect
        .soft(cohort.clsMaximum, `${cohort.route} every-run CLS`)
        .toBeLessThanOrEqual(CLS_MAX);
      if (cohort.route === "research")
        expect
          .soft(
            cohort.appCompressedBytesMaximum,
            "Research first-load application JS, including shared application code",
          )
          .toBeLessThanOrEqual(APP_JS_MAX_BYTES);
    }
  } finally {
    await writeFile(
      info.outputPath("web-performance-raw.json"),
      JSON.stringify({ ...declared, samples }, null, 2),
      { mode: 0o600 },
    );
  }
});
