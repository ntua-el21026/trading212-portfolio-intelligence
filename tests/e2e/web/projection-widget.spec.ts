import { execFileSync } from "node:child_process";
import { resolve } from "node:path";
import { expect, test, type Page } from "@playwright/test";

// The local host fixture supplies real canonical presenter output. It exercises
// the packaged iframe bridge; it is not evidence of a live ChatGPT connection.
const fixture = JSON.parse(
  execFileSync(
    "uv",
    [
      "run",
      "python",
      "-c",
      [
        "import json",
        "from trading212_mcp.projection_widget import PROJECTION_WIDGET_HTML",
        "from trading212_domain.serialization import to_primitive",
        "from trading212_application.projection_presentation import project_goal_analysis, unavailable_goal_analysis",
        "from tests.unit.api.projection_factories import run, saved, queued",
        "print(json.dumps({'html': PROJECTION_WIDGET_HTML, 'run': to_primitive(run(limit=2)), 'next': to_primitive(run(offset=2, limit=2)), 'goal': to_primitive(project_goal_analysis(saved())), 'queued': to_primitive(queued()), 'pendingGoal': to_primitive(unavailable_goal_analysis(queued()))}))",
      ].join("; "),
    ],
    { cwd: resolve(process.cwd(), "../.."), encoding: "utf8" },
  ),
);
const account = fixture.run.account_id as string;
const runId = fixture.run.id as string;
const other = "00000000-0000-4000-8000-000000000099";
const envelope = (data: object) => ({
  data,
  error: null,
  execution_allowed: false,
});
const initial = envelope(fixture.run);
const pointMoney = [
  "nominal",
  "real",
  "contributions",
  "withdrawals_requested",
  "withdrawals_funded",
  "unpaid_withdrawals",
  "investment_effect",
  "fees",
  "tax_drag",
  "wealth_residual",
  "allocation_residual",
  "withdrawal_residual",
];

type Host = Window & {
  projectionCalls: {
    id: string;
    method: string;
    params: { name: string; arguments: Record<string, unknown> };
  }[];
};

async function mount(page: Page, serverTools = true) {
  await page.setContent(
    '<!doctype html><html lang="en"><head><title>Projection host fixture</title></head><body style="margin:0"><iframe title="Portfolio projections" style="border:0;width:100%;height:2200px"></iframe></body></html>',
  );
  await page.evaluate(
    ({ html, serverTools }) => {
      const host = window as unknown as Host;
      host.projectionCalls = [];
      const frame = document.querySelector("iframe")!;
      window.addEventListener("message", (event) => {
        if (
          event.source !== frame.contentWindow ||
          event.data?.jsonrpc !== "2.0"
        )
          return;
        const value = event.data;
        if (value.method === "ui/initialize")
          frame.contentWindow!.postMessage(
            {
              jsonrpc: "2.0",
              id: value.id,
              result: {
                protocolVersion: "2026-01-26",
                hostInfo: { name: "local-test", version: "1" },
                hostCapabilities: serverTools ? { serverTools: {} } : {},
                hostContext: {},
              },
            },
            "*",
          );
        if (value.method === "tools/call") host.projectionCalls.push(value);
      });
      frame.srcdoc = html;
    },
    { html: fixture.html as string, serverTools },
  );
  await expect(page.frameLocator("iframe").locator("#status")).toContainText(
    "Waiting",
  );
}
async function notify(page: Page, method: string, params: object) {
  await page.evaluate(
    ({ method, params }) =>
      document
        .querySelector("iframe")!
        .contentWindow!.postMessage({ jsonrpc: "2.0", method, params }, "*"),
    { method, params },
  );
}
async function publish(page: Page, value: object = initial) {
  await notify(page, "ui/notifications/tool-result", {
    structuredContent: value,
  });
}
async function select(page: Page) {
  await notify(page, "ui/notifications/tool-input", {
    arguments: { account_id: account, run_id: runId, point_limit: 2 },
  });
}
async function reply(page: Page, id: string, value: object) {
  await page.evaluate(
    ({ id, value }) =>
      document
        .querySelector("iframe")!
        .contentWindow!.postMessage({ jsonrpc: "2.0", id, result: value }, "*"),
    { id, value },
  );
}
async function calls(page: Page) {
  return page.evaluate(() => (window as unknown as Host).projectionCalls);
}

for (const width of [1440, 768, 360]) {
  test(`projection exact tables and keyboard layout at ${width}px`, async ({
    page,
  }, info) => {
    await page.setViewportSize({ width, height: 900 });
    await page.emulateMedia({ reducedMotion: "reduce" });
    const errors: string[] = [],
      requests: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    page.on("console", (message) => {
      if (["error", "warning"].includes(message.type()))
        errors.push(message.text());
    });
    page.on("request", (request) => requests.push(request.url()));
    await mount(page);
    await select(page);
    await publish(page);
    const app = page.frameLocator("iframe");
    await expect(app.locator("#status")).toContainText(
      "Completed saved projection",
    );
    await expect(app.locator("#method")).toContainText(
      "premium_decimal96_q18_v1",
    );
    await expect(app.locator("#points tr")).toHaveCount(2);
    await expect(app.locator("#points")).toContainText(
      "100.123456789012345678 EUR",
    );
    await expect(app.locator("#point-money tr")).toHaveCount(pointMoney.length);
    const first = fixture.run.result.points.items[0].point;
    for (const field of pointMoney)
      await expect(
        app.locator("#point-money tr").filter({
          has: app.getByRole("rowheader", { name: field, exact: true }),
        }),
      ).toContainText(`${first[field].amount} ${first[field].currency}`);
    await expect(app.locator("#distribution tr")).toHaveCount(
      fixture.run.result.variants[0].distributions.length,
    );
    await expect(app.locator("#goals tr")).toHaveCount(3);
    await app
      .getByLabel("Select a saved variant", { exact: true })
      .selectOption({ index: 2 });
    await expect(app.locator("#distribution")).toContainText(
      fixture.run.result.variants[2].distributions.at(-1).nominal_mean.amount,
    );
    await app
      .getByText("Saved assumptions and dated schedule", { exact: true })
      .click();
    await expect(app.locator("#assumptions tr")).toHaveCount(
      fixture.run.result.context.assumptions.assets.length,
    );
    await expect(app.locator("#schedule")).toContainText("75 EUR");
    await app.getByRole("button", { name: "Refresh saved view" }).focus();
    await page.keyboard.press("Tab");
    await expect(
      app.getByRole("button", { name: "Start point pages" }),
    ).toBeFocused();
    expect(
      await app
        .locator("body")
        .evaluate(
          () =>
            document.documentElement.scrollWidth -
            document.documentElement.clientWidth,
        ),
    ).toBeLessThanOrEqual(1);
    expect(
      await app
        .locator("table")
        .evaluateAll(
          (tables) =>
            tables.filter((table) => !table.querySelector("caption")).length,
        ),
    ).toBe(0);
    const distributions = app.getByRole("region", {
      name: "Projection distributions",
      exact: true,
    });
    if (width === 360) {
      await distributions.focus();
      await page.keyboard.press("ArrowRight");
      await expect
        .poll(() => distributions.evaluate((region) => region.scrollLeft))
        .toBeGreaterThan(0);
      await distributions.evaluate((region) => {
        region.scrollLeft = 0;
      });
    }
    await app.locator("body").evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({
      path: info.outputPath(`projection-widget-${width}.png`),
      fullPage: true,
    });
    expect(requests).toEqual([]);
    expect(errors).toEqual([]);
  });
}

test("point pages and goal reads preserve account, cursor, limit and saved result", async ({
  page,
}) => {
  await mount(page);
  await select(page);
  await publish(page);
  const app = page.frameLocator("iframe");
  await app.getByRole("button", { name: "Next points", exact: true }).click();
  await expect.poll(async () => (await calls(page)).length).toBe(1);
  const pending = (await calls(page))[0];
  expect(pending.params).toEqual({
    name: "get_projection",
    arguments: {
      account_id: account,
      run_id: runId,
      point_limit: 2,
      point_cursor: fixture.run.result.points.next_cursor,
    },
  });
  await expect(app.locator("#content")).toBeHidden();
  await reply(page, pending.id, { structuredContent: envelope(fixture.next) });
  await expect(app.locator("#page-count")).toContainText("ordinal 2");
  await expect(app.locator("#points tr")).toHaveCount(2);
  await expect(app.locator("#points")).toContainText(
    fixture.next.result.points.items[0].point.nominal.amount,
  );
  await app
    .getByLabel("Inspect every field of a point on this page", { exact: true })
    .selectOption({ index: 1 });
  await expect(app.locator("#point-identity")).toContainText("ordinal 3");
  await app
    .getByRole("button", { name: "Read saved goal analysis", exact: true })
    .click();
  await expect.poll(async () => (await calls(page)).length).toBe(2);
  const goalCall = (await calls(page))[1];
  expect(goalCall.params).toEqual({
    name: "get_goal_analysis",
    arguments: { account_id: account, run_id: runId },
  });
  await reply(page, goalCall.id, { structuredContent: envelope(fixture.goal) });
  await expect(app.locator("#status")).toContainText("Saved goal analysis");
  await expect(app.locator("#point-section")).toBeHidden();
  await expect(app.locator("#goals")).toContainText(
    fixture.goal.variants[0].estimate.interval_low,
  );
  await expect(app.locator("#goals")).toContainText(
    "Automatic acceptance: false",
  );
  expect((await calls(page)).map((call) => call.params.name)).toEqual([
    "get_projection",
    "get_goal_analysis",
  ]);
});

test("foreign, skipped or changed-result point replies fail closed", async ({
  page,
}) => {
  await mount(page);
  const app = page.frameLocator("iframe");
  for (const field of ["account", "ordinal", "savedDigest"]) {
    await select(page);
    await publish(page);
    await app.getByRole("button", { name: "Next points", exact: true }).click();
    await expect
      .poll(async () => (await calls(page)).length)
      .toBe(["account", "ordinal", "savedDigest"].indexOf(field) + 1);
    const bad = structuredClone(fixture.next);
    if (field === "account") bad.account_id = other;
    if (field === "ordinal") bad.result.points.start_ordinal = 3;
    if (field === "savedDigest")
      bad.result.context.saved_result_digest = "a".repeat(64);
    await reply(page, (await calls(page)).at(-1)!.id, {
      structuredContent: envelope(bad),
    });
    await expect(app.locator("#content")).toBeHidden();
    await expect(app.locator("#points tr")).toHaveCount(0);
  }
});

test("pending and cancelled results never fabricate zero money", async ({
  page,
}) => {
  await mount(page);
  await publish(page, envelope(fixture.queued));
  const app = page.frameLocator("iframe");
  await expect(app.locator("#status")).toContainText("queued");
  await expect(app.locator("#content")).toBeHidden();
  await select(page);
  await publish(page, envelope(fixture.pendingGoal));
  await expect(app.locator("#status")).toContainText("run_pending");
  await expect(app.locator("#point-money tr")).toHaveCount(0);
  await select(page);
  await publish(page);
  await app
    .getByRole("button", { name: "Refresh saved view", exact: true })
    .click();
  await expect.poll(async () => (await calls(page)).length).toBe(1);
  const prior = (await calls(page))[0];
  await notify(page, "ui/notifications/tool-input", {
    arguments: { account_id: other, run_id: other },
  });
  await reply(page, prior.id, { structuredContent: initial });
  await expect(app.locator("#content")).toBeHidden();
  await publish(page);
  await expect(app.locator("#identity")).toHaveText("");
  await select(page);
  await publish(page);
  await notify(page, "ui/notifications/tool-input-partial", {
    arguments: { account_id: account },
  });
  await publish(page);
  await expect(app.locator("#content")).toBeHidden();
  await select(page);
  await publish(page);
  await notify(page, "ui/notifications/tool-cancelled", {});
  await expect(app.locator("#status")).toContainText("cancelled");
  await expect(app.locator("#points tr")).toHaveCount(0);
});

test("finance floats and oversized payloads reject; untrusted labels remain text", async ({
  page,
}) => {
  await mount(page);
  await select(page);
  const app = page.frameLocator("iframe");
  const textOnly = structuredClone(fixture.run);
  textOnly.result.context.selection.schedule.entries[0].key =
    '<img src=x onerror="alert(1)">';
  await publish(page, envelope(textOnly));
  await expect(app.locator("#content")).toBeVisible();
  await app
    .getByText("Saved assumptions and dated schedule", { exact: true })
    .click();
  await expect(app.locator("#schedule")).toContainText(
    '<img src=x onerror="alert(1)">',
  );
  await expect(app.locator("img")).toHaveCount(0);
  const malformed = structuredClone(fixture.run);
  malformed.result.points.items[0].point.nominal.amount = 0.1;
  await publish(page, envelope(malformed));
  await expect(app.locator("#content")).toBeHidden();
  await publish(page, { ...initial, extra: "x".repeat(2097153) });
  await expect(app.locator("#content")).toBeHidden();
  await publish(page, {
    data: null,
    error: { code: "SOURCE_UNAVAILABLE", message: "private-source-canary" },
    execution_allowed: false,
  });
  await expect(app.locator("#status")).toContainText("SOURCE_UNAVAILABLE");
  await expect(app.locator("body")).not.toContainText("private-source-canary");
});

test("finite timeout ignores old replies and permits a new explicit read", async ({
  page,
}) => {
  await page.clock.install();
  await mount(page);
  await select(page);
  await publish(page);
  const app = page.frameLocator("iframe");
  await app
    .getByRole("button", { name: "Refresh saved view", exact: true })
    .click();
  await expect.poll(async () => (await calls(page)).length).toBe(1);
  const prior = (await calls(page))[0];
  await page.clock.fastForward(16000);
  await expect(app.locator("#content")).toBeHidden();
  await expect(
    app.getByRole("button", { name: "Refresh saved view", exact: true }),
  ).toBeEnabled();
  await app
    .getByRole("button", { name: "Refresh saved view", exact: true })
    .click();
  await expect.poll(async () => (await calls(page)).length).toBe(2);
  await reply(page, prior.id, { structuredContent: initial });
  await expect(app.locator("#content")).toBeHidden();
  await reply(page, (await calls(page))[1].id, { structuredContent: initial });
  await expect(app.locator("#content")).toBeVisible();
});

test("bridge-free tables and feature-detected compatibility reads stay usable", async ({
  page,
}) => {
  await mount(page, false);
  await select(page);
  await publish(page);
  const app = page.frameLocator("iframe");
  await expect(app.locator("#content")).toBeVisible();
  await expect(
    app.getByRole("button", { name: "Refresh saved view", exact: true }),
  ).toBeDisabled();
  expect(await calls(page)).toEqual([]);
  const frame = page.frames().find((value) => value.parentFrame())!;
  await frame.evaluate(() => {
    const local = window as unknown as {
      openai: { callTool: (name: string, args: object) => Promise<object> };
      compatCalls: unknown[];
    };
    local.compatCalls = [];
    local.openai = {
      callTool: (name, args) => {
        local.compatCalls.push({ name, args });
        return new Promise(() => {});
      },
    };
  });
  await publish(page);
  await app
    .getByRole("button", { name: "Refresh saved view", exact: true })
    .click();
  await expect
    .poll(() =>
      frame.evaluate(
        () =>
          (window as unknown as { compatCalls: unknown[] }).compatCalls.length,
      ),
    )
    .toBe(1);
  await page.evaluate(() =>
    document.querySelector("iframe")!.contentWindow!.postMessage(
      {
        jsonrpc: "2.0",
        id: "close",
        method: "ui/resource-teardown",
        params: {},
      },
      "*",
    ),
  );
  await expect(app.locator("#status")).toContainText("closed");
  await publish(page);
  await expect(app.locator("#content")).toBeHidden();
  await expect(
    app.getByRole("button", { name: "Refresh saved view", exact: true }),
  ).toBeDisabled();
});
