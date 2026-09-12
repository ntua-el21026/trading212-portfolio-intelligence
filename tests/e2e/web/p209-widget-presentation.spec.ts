import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync } from "node:fs";
import { join, resolve } from "node:path";
import { tmpdir } from "node:os";
import { expect, test, type Page } from "@playwright/test";

const root = [process.cwd(), resolve(process.cwd(), "../..")].find(
  (directory) =>
    existsSync(resolve(directory, "apps/mcp/src/trading212_mcp/widget.py")),
);
if (!root) throw new Error("Unable to locate the canonical widget sources");

// Presentation fixtures only: these do not prove service authorization,
// financial calculations, report generation, or live host acceptance.
const id = "00000000-0000-4000-8000-000000000001";
const amount = "99999999999999999999.123456789012345678";
const instant = "2026-09-11T12:34:56.123456Z";
const money = (value = amount) => ({ amount: value, currency: "EUR" });
const metric = (value: string | ReturnType<typeof money>) => ({
  value,
  availability: "available",
  quality: "stale",
  reason: null,
  reason_code: null,
  bound: "exact",
});
const line = {
  node_key: "Synthetic holding",
  recommended_amount: money(),
  post_value: money("0"),
};
const point = {
  date: "2026-09-11",
  portfolio_value: metric(money()),
  cumulative_return: metric("0.000000000000000001"),
};
const exposure = {
  name: "Synthetic company",
  direct: metric(money()),
  indirect: metric(money("0")),
  effective: metric(money()),
};
const note = {
  code: "coverage_partial",
  message: "Synthetic incomplete coverage",
  severity: "warning",
};
function snapshot() {
  return {
    error: null,
    reporting_currency: "EUR",
    as_of: instant,
    data_quality: { state: "stale" },
    data: {
      total_value: { value: amount, reporting_currency: "EUR" },
      invested_value: {
        value: "0.000000000000000001",
        reporting_currency: "EUR",
      },
      cash_value: { value: "0", reporting_currency: "EUR" },
      net_contributions: { value: null, reporting_currency: "EUR" },
      synthetic_data: true,
      quality_disclosure: "Synthetic stale observation.",
    },
  };
}
function planning(items: unknown[] = [line]) {
  return {
    execution_allowed: false,
    error: null,
    pagination: { truncated: true },
    data: {
      job: {
        state: "succeeded",
        plan_id: id,
        request_id: id,
        execution_allowed: false,
      },
      content_digest: "a".repeat(64),
      result: {
        outcome: "feasible_nonoptimal",
        execution_allowed: false,
        contribution: money(),
        residual_cash: money("0.01"),
        bound_kind: "relaxation_lower_bound",
        explanations: [note],
        context: {
          availability: "partial",
          data_quality: { state: "unreconciled" },
          method: { name: "contribution_weighted_drift_v1", version: "1.0.0" },
          as_of: instant,
          source_cutoff_at: instant,
          calculated_at: instant,
          coverage: {
            complete: false,
            valued_total: money(),
            matched_total: money("0"),
            unclassified_total: money(),
          },
          warnings: Array.from({ length: 17 }, (_, n) => ({
            ...note,
            message: `Synthetic warning ${n}`,
          })),
          assumptions: [note],
        },
      },
      lines: { items },
    },
  };
}
function historical(series: unknown[] = [point]) {
  return {
    error: null,
    data: {
      context: {
        availability: "partial",
        quality: "fresh",
        window: {
          start_date: "2026-09-11",
          end_date: "2026-09-11",
          source_cutoff_at: instant,
          reporting_currency: "EUR",
        },
        method: { name: "performance_v2", version: "1.0.0" },
        calculated_at: instant,
        reconstruction: "point_in_time",
        access: { reproducibility: "reproducible" },
        content_digest: "b".repeat(64),
        source_count: 1,
        source_omitted_count: 0,
        warnings: [],
        coverage: {
          measures: [
            {
              key: "valuation_cells",
              expected_count: 1,
              available_count: 1,
              complete: true,
            },
          ],
        },
        assumptions: ["utc_accounting_boundaries"],
      },
      summary: {
        ending_value: metric(money()),
        investment_gain: metric(money("0")),
      },
      series,
    },
  };
}
function xray(items: unknown[] = [exposure]) {
  return {
    error: null,
    selection: { total: 2, returned: 1, omitted: 1 },
    data: {
      view: "exposures",
      context: {
        valuation_at: instant,
        source_cutoff_at: instant,
        quality_evaluated_at: instant,
        reporting_currency: "EUR",
        method: { name: "xray_v1", version: "1.1.0" },
        access: { reproducibility: "reproducible" },
        content_digest: "c".repeat(64),
        source_count: 0,
        source_omitted_count: 0,
        sources: [],
        warnings: [],
      },
      summary: {
        total: metric(money()),
        company_known_weight: metric("0.5"),
        unresolved_weight: { ...metric("0"), positive_below_quantum: true },
        duplicated_exposure: { ...metric("0.25"), bound: "lower_bound" },
        hhi: metric("0.125"),
      },
      dimension_summary: { dimension: "company" },
      exposures: { items },
    },
  };
}
function report(
  pins: unknown[] = [
    {
      family: "snapshot",
      role: "snapshot",
      subject_id: id,
      content_digest: "d".repeat(64),
    },
  ],
) {
  return {
    execution_allowed: false,
    error: null,
    data: {
      job_id: id,
      report_id: id,
      state: "succeeded",
      report_type: "portfolio_summary",
      formats: ["json"],
      expires_at: instant,
      failure_code: null,
      manifest_digest: "e".repeat(64),
      context: {
        snapshot_id: id,
        valuation_at: instant,
        source_cutoff_at: instant,
        reporting_currency: "EUR",
        input_digest: "f".repeat(64),
        pins,
        quality: {
          state: "partial",
          availability: "partial",
          warnings: [{ text: "Synthetic warning." }],
          warning_omitted_count: 0,
        },
      },
    },
  };
}
type Widget = {
  name: string;
  module: string;
  constant: string;
  fixture: () => unknown;
  malformed: () => unknown;
  oversized?: () => unknown;
};
const widgets: Widget[] = [
  {
    name: "snapshot",
    module: "widget",
    constant: "SNAPSHOT_WIDGET_HTML",
    fixture: snapshot,
    malformed: () => ({ ...snapshot(), data: [] }),
  },
  {
    name: "planning",
    module: "planning_widget",
    constant: "PLAN_WIDGET_HTML",
    fixture: planning,
    malformed: () => planning([null]),
    oversized: () => planning(Array(101).fill(line)),
  },
  {
    name: "historical",
    module: "historical_widget",
    constant: "HISTORICAL_WIDGET_HTML",
    fixture: historical,
    malformed: () => historical([null]),
    oversized: () => historical(Array(3662).fill(point)),
  },
  {
    name: "xray",
    module: "xray_widget",
    constant: "XRAY_WIDGET_HTML",
    fixture: xray,
    malformed: () => xray([null]),
    oversized: () => xray(Array(101).fill(exposure)),
  },
  {
    name: "report",
    module: "report_widget",
    constant: "REPORT_WIDGET_HTML",
    fixture: report,
    malformed: () => report([null]),
    oversized: () => report(Array(257).fill({})),
  },
];
function html(widget: Widget) {
  // Same installed SDK/workspace loading pattern as the existing P2 widget specs.
  return execFileSync(
    "uv",
    [
      "run",
      "python",
      "-c",
      `from trading212_mcp.${widget.module} import ${widget.constant}; print(${widget.constant})`,
    ],
    { cwd: root, encoding: "utf8" },
  );
}
async function notify(page: Page, method: string, params: unknown) {
  await page.evaluate(
    ({ method, params }) => {
      window.postMessage({ jsonrpc: "2.0", method, params }, "*");
    },
    { method, params },
  );
}
async function publish(page: Page, envelope: unknown) {
  await notify(page, "ui/notifications/tool-result", {
    structuredContent: envelope,
  });
}

for (const widget of widgets) {
  test.describe(`P209 ${widget.name} presentation boundary`, () => {
    let resource: string;
    test.beforeAll(() => {
      resource = html(widget);
    });

    test("ships matching static CSP hashes and renders only text without external requests", async ({
      page,
    }, testInfo) => {
      const policy = resource.match(
        /http-equiv="Content-Security-Policy" content="([^"]+)"/,
      )?.[1];
      expect(policy).toBeDefined();
      for (const tag of ["script", "style"]) {
        const content = resource.match(
          new RegExp(`<${tag}>([\\s\\S]*?)</${tag}>`),
        )?.[1];
        expect(content).toBeDefined();
        const hash = createHash("sha256")
          .update(content ?? "")
          .digest("base64");
        expect(policy).toContain(`${tag}-src 'sha256-${hash}'`);
      }
      for (const directive of [
        "default",
        "connect",
        "img",
        "font",
        "frame",
        "object",
      ]) {
        expect(policy).toContain(`${directive}-src 'none'`);
      }
      expect(policy).toContain("base-uri 'none'");
      expect(policy).toContain("form-action 'none'");
      expect(policy).not.toContain("'unsafe-inline'");
      expect(policy).not.toContain("'unsafe-eval'");
      const requests: string[] = [];
      const errors: string[] = [];
      page.on("request", (request) => requests.push(request.url()));
      page.on("pageerror", (error) => errors.push(error.message));
      await page.setContent(resource);
      await publish(page, widget.fixture());
      await expect(page.locator("#content")).toBeVisible();
      // Page overflow alone misses a heading painting over the next column.
      const overflowingHeadings = await page
        .locator("th")
        .evaluateAll((headings) =>
          headings.flatMap((heading) => {
            const bounds = heading.getBoundingClientRect();
            const text = document.createRange();
            text.selectNodeContents(heading);
            return Array.from(text.getClientRects()).some(
              (rect) =>
                rect.left < bounds.left - 1 || rect.right > bounds.right + 1,
            )
              ? [heading.textContent]
              : [];
          }),
        );
      expect(overflowingHeadings).toEqual([]);
      await expect(
        page.locator(
          "img,iframe,object,embed,a[href],form,script[src],link[href]",
        ),
      ).toHaveCount(0);
      // An unhashed inline script must remain blocked even though the shipped script ran.
      await page.evaluate(() => {
        const script = document.createElement("script");
        script.textContent = "window.__p209InlineRan = true";
        document.body.append(script);
      });
      expect(
        await page.evaluate(
          () =>
            (window as Window & { __p209InlineRan?: boolean }).__p209InlineRan,
        ),
      ).toBeUndefined();
      expect(requests).toEqual([]);
      expect(errors).toEqual([]);
      await page.screenshot({
        path: join(
          tmpdir(),
          `t212-p209-widget-${widget.name}-${testInfo.project.name}.png`,
        ),
        fullPage: true,
      });
    });

    test("clears retained display on partial/full input and cancellation, then recovers", async ({
      page,
    }) => {
      await page.setContent(resource);
      for (const method of [
        "ui/notifications/tool-input-partial",
        "ui/notifications/tool-input",
        "ui/notifications/tool-cancelled",
      ]) {
        await publish(page, widget.fixture());
        await expect(page.locator("#content")).toBeVisible();
        await notify(page, method, {
          arguments: {
            secret_canary: "never-display-input",
            data: widget.fixture(),
          },
          reason: "never-display-input",
        });
        await expect(page.locator("#content")).toBeHidden();
        await expect(
          page.locator(widget.name === "snapshot" ? "#empty" : "#status"),
        ).toContainText(method.endsWith("cancelled") ? "cancelled" : "Waiting");
        await expect(page.locator("body")).not.toContainText(
          "never-display-input",
        );
        if (widget.name === "snapshot") {
          await expect(page.locator("#quality-badge")).toBeHidden();
          await expect(page.locator("#synthetic-badge")).toBeHidden();
        }
      }
      await publish(page, widget.fixture());
      await expect(page.locator("#content")).toBeVisible();
    });

    test("ignores forged sources and request-shaped notifications, honors error results", async ({
      page,
    }) => {
      await page.setContent(resource);
      await page.evaluate((envelope) => {
        window.dispatchEvent(
          new MessageEvent("message", {
            source: null,
            data: {
              jsonrpc: "2.0",
              method: "ui/notifications/tool-result",
              params: { structuredContent: envelope },
            },
          }),
        );
        window.postMessage(
          {
            jsonrpc: "2.0",
            id: "not-a-notification",
            method: "ui/notifications/tool-result",
            params: { structuredContent: envelope },
          },
          "*",
        );
      }, widget.fixture());
      // A non-protocol sentinel waits for earlier messages without changing widget state.
      await page.evaluate(
        () =>
          new Promise<void>((resolve) => {
            const listener = (event: MessageEvent) => {
              if (
                event.source === window &&
                event.data === "p209-message-drained"
              ) {
                window.removeEventListener("message", listener);
                resolve();
              }
            };
            window.addEventListener("message", listener);
            window.postMessage("p209-message-drained", "*");
          }),
      );
      await expect(page.locator("#content")).toBeHidden();
      for (const errorFlag of ["isError", "is_error"]) {
        await publish(page, widget.fixture());
        await expect(page.locator("#content")).toBeVisible();
        await notify(page, "ui/notifications/tool-result", {
          [errorFlag]: true,
          structuredContent: widget.fixture(),
          content: [{ type: "text", text: "private-error-canary" }],
        });
        await expect(page.locator("#content")).toBeHidden();
        await expect(page.locator("body")).not.toContainText(
          "private-error-canary",
        );
      }
    });

    test("rejects malformed and excessive displayed collections without throwing or retaining success", async ({
      page,
    }) => {
      const errors: string[] = [];
      page.on("pageerror", (error) => errors.push(error.message));
      await page.setContent(resource);
      for (const bad of [
        widget.malformed(),
        ...(widget.oversized ? [widget.oversized()] : []),
      ]) {
        await publish(page, widget.fixture());
        await expect(page.locator("#content")).toBeVisible();
        await publish(page, bad);
        await expect(page.locator("#content")).toBeHidden();
        await expect(
          page.locator(widget.name === "snapshot" ? "#empty" : "#status"),
        ).toContainText(/unavailable|does not match/);
      }
      await publish(page, widget.fixture());
      await expect(page.locator("#content")).toBeVisible();
      expect(errors).toEqual([]);
    });
  });
}

test("snapshot preserves q18, zero, unavailable and source instant as accessible text", async ({
  page,
}) => {
  await page.setContent(html(widgets[0]));
  await publish(page, snapshot());
  await expect(page.locator("#total-value")).toHaveText(`${amount} EUR`);
  await expect(page.locator("#invested-value")).toHaveText(
    "0.000000000000000001 EUR",
  );
  await expect(page.locator("#cash-value")).toHaveText("0 EUR");
  await expect(page.locator("#contributions-value")).toHaveText("Unavailable");
  await expect(page.locator("#as-of")).toHaveText(`As of ${instant}`);
  const bad = snapshot();
  const markup = '<img src="https://example.invalid/canary" onerror="throw 1">';
  bad.data.quality_disclosure = markup;
  await publish(page, bad);
  await expect(page.locator("#quality-note")).toHaveText(markup);
  await expect(page.locator("img")).toHaveCount(0);
  bad.data.quality_disclosure = "x".repeat(100000);
  await publish(page, bad);
  await expect(page.locator("#quality-note")).toHaveText(
    "Data quality disclosure is unavailable.",
  );
  expect(
    await page.evaluate(
      () =>
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
    ),
  ).toBeLessThanOrEqual(1);
});

test("plan shows bounded explanations and pins separately from solver success and supports keyboard table access", async ({
  page,
}) => {
  await page.setContent(html(widgets[1]));
  await publish(page, planning());
  await expect(page.locator("#contribution")).toHaveText(`${amount} EUR`);
  await expect(page.locator("#outcome")).toHaveText("feasible_nonoptimal");
  await expect(page.locator("#method")).toHaveText(
    "contribution_weighted_drift_v1 / 1.0.0",
  );
  await expect(page.locator("#cutoff")).toHaveText(instant);
  await expect(page.locator("#bound")).toHaveText("relaxation_lower_bound");
  await expect(page.locator("#coverage-detail")).toContainText("incomplete");
  await expect(page.locator("#warnings")).toContainText(
    "17 records; 1 omitted",
  );
  await expect(page.locator("#warnings")).not.toContainText(
    "Synthetic warning 16",
  );
  const region = page.getByRole("region", { name: "Saved allocation page" });
  // This document has one native tab stop: the saved allocation region.
  // Exercise real keyboard traversal rather than assigning focus in the test.
  await page.keyboard.press("Tab");
  await expect(region).toBeFocused();
  await expect(region).toHaveCSS("outline-style", "solid");
  await expect(region).toHaveCSS("outline-width", "3px");
  for (const state of ["queued", "running", "failed", "expired", "cancelled"]) {
    const value = planning();
    await publish(page, {
      ...value,
      data: {
        ...value.data,
        job: { ...value.data.job, state },
        result: null,
        lines: { items: [] },
      },
    });
    await expect(page.locator("#status")).toContainText(state);
    await expect(page.locator("#outcome")).toHaveText("Not calculated");
    await expect(page.locator("#rows tr")).toHaveCount(0);
  }
});

test("historical metric quality differs from run quality and partial values keep exact units", async ({
  page,
}) => {
  await page.setContent(html(widgets[2]));
  const value = historical();
  await publish(page, {
    ...value,
    data: {
      ...value.data,
      summary: {
        ...value.data.summary,
        investment_gain: {
          ...metric(money("0")),
          availability: "partial",
          reason_code: "partial_period_coverage",
        },
      },
    },
  });
  await expect(page.locator("#status")).toContainText("Quality: fresh");
  await expect(page.locator("#primary")).toHaveText(
    `${amount} EUR; quality stale`,
  );
  await expect(page.locator("#secondary")).toHaveText(
    "0 EUR (partial: partial_period_coverage); quality stale",
  );
  await expect(page.locator("#currency")).toHaveText("EUR");
  await expect(page.locator("#assumptions")).toHaveText(
    "utc_accounting_boundaries",
  );
});

test("X-ray Top bound is 50 and its full-scope overlap is never recomputed from a sample", async ({
  page,
}) => {
  await page.setContent(html(widgets[3]));
  const value = xray();
  const common = {
    name: "Synthetic company",
    left_weight: metric("0.2"),
    right_weight: metric("0.3"),
    common_weight: metric("0.2"),
  };
  const top = {
    ...value,
    data: {
      ...value.data,
      view: "mcp_top_pair",
      common_entities: [common],
      pair: {
        left: { name: "Left", unit_coverage: metric("0.8") },
        right: { name: "Right", unit_coverage: metric("1") },
        overlap: { ...metric("0.7"), bound: "lower_bound" },
      },
      omitted_common_weight: metric("0.5"),
    },
  };
  await publish(page, top);
  await expect(page.locator("#pair-value")).toHaveText(
    "0.7 (lower bound); stale",
  );
  await expect(page.locator("#omitted-weight")).toHaveText("0.5; stale");
  await expect(page.locator("#unresolved")).toContainText(
    "positive below display precision",
  );
  await expect(page.locator("#rows tr")).toHaveCount(1);
  await publish(page, {
    ...top,
    data: { ...top.data, common_entities: Array(51).fill(common) },
  });
  await expect(page.locator("#content")).toBeHidden();
});

test("report markup remains text and purged context removes prior pins and warnings", async ({
  page,
}) => {
  const errors: string[] = [],
    requests: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("request", (request) => requests.push(request.url()));
  await page.setContent(html(widgets[4]));
  const value = report();
  const payload =
    '<img src="https://example.invalid/canary" onerror="throw 1">';
  value.data.context.quality.warnings[0].text = payload;
  await publish(page, value);
  await page.getByText("Warnings", { exact: true }).click();
  await expect(page.locator("#warnings")).toHaveText(payload);
  await expect(page.locator("img")).toHaveCount(0);
  for (const state of ["expired", "cancelled"]) {
    await publish(page, {
      ...value,
      data: { ...value.data, state, context: null },
    });
    await expect(page.locator("#content")).toBeVisible();
    await expect(page.locator("#pins li,#warnings li")).toHaveCount(0);
    await expect(page.locator("#snapshot")).toHaveText(
      "Expired or purged source detail",
    );
  }
  expect(errors).toEqual([]);
  expect(requests).toEqual([]);
});

test("snapshot retains the legacy decimal lexical range and distinguishes partial from unavailable", async ({
  page,
}) => {
  await page.setContent(html(widgets[0]));
  const value = snapshot();
  const legacy = "123456789012345678901.1234567890123456789";
  await publish(page, {
    ...value,
    data: {
      ...value.data,
      total_value: {
        value: legacy,
        reporting_currency: "EUR",
        availability: "partial",
        unavailable_reason: "missing position",
      },
      cash_value: {
        value: "0",
        reporting_currency: "EUR",
        availability: "unavailable",
      },
    },
  });
  await expect(page.locator("#total-value")).toHaveText(
    `${legacy} EUR (partial: missing position)`,
  );
  await expect(page.locator("#cash-value")).toHaveText("Unavailable");
  await publish(page, {
    ...value,
    data: {
      ...value.data,
      total_value: { value: "1".repeat(513), reporting_currency: "EUR" },
    },
  });
  await expect(page.locator("#total-value")).toHaveText(
    "Value exceeds widget display limit; see the structured tool result.",
  );
});

test("late snapshot initialize failure cannot restore stale compatibility output after new input", async ({
  page,
}) => {
  const bootstrap = `<script>window.openai = { toolOutput: ${JSON.stringify(snapshot())} };</script>`;
  await page.setContent(
    html(widgets[0]).replace("<head>", `<head>${bootstrap}`),
  );
  await expect(page.locator("#content")).toBeVisible();
  await notify(page, "ui/notifications/tool-input", { arguments: {} });
  await expect(page.locator("#content")).toBeHidden();
  await page.evaluate(
    () =>
      new Promise<void>((resolve) => {
        const listener = (event: MessageEvent) => {
          if (
            event.source === window &&
            event.data === "p209-initialize-drained"
          ) {
            window.removeEventListener("message", listener);
            resolve();
          }
        };
        window.addEventListener("message", listener);
        window.postMessage(
          {
            jsonrpc: "2.0",
            id: 1,
            error: {
              code: -32603,
              message: "Synthetic initialization failure",
            },
          },
          "*",
        );
        window.postMessage("p209-initialize-drained", "*");
      }),
  );
  await expect(page.locator("#content")).toBeHidden();
  await expect(page.locator("#quality-badge")).toBeHidden();
  await expect(page.locator("#empty")).toContainText("Waiting");
});
