import { execFileSync } from "node:child_process";
import { resolve } from "node:path";
import { expect, test, type Page } from "@playwright/test";

const fixture = JSON.parse(
  execFileSync(
    "uv",
    [
      "run",
      "python",
      "-c",
      [
        "import json",
        "from trading212_mcp.scenario_widget import SCENARIO_WIDGET_HTML",
        "from trading212_domain.serialization import to_primitive",
        "from tests.unit.api.scenario_factories import run, comparison",
        "print(json.dumps({'html': SCENARIO_WIDGET_HTML, 'run': to_primitive(run()), 'comparison': to_primitive(comparison())}))",
      ].join("; "),
    ],
    { cwd: resolve(process.cwd(), "../.."), encoding: "utf8" },
  ),
);
const account = fixture.run.account_id as string;
const runId = fixture.run.id as string;
const secondId = fixture.comparison.after.run_id as string;
const other = "00000000-0000-4000-8000-000000000099";
const envelope = (data: object) => ({
  data,
  error: null,
  execution_allowed: false,
});
const initial = envelope(fixture.run);

type Host = Window & {
  scenarioCalls: {
    id: string;
    method: string;
    params: { name: string; arguments: Record<string, unknown> };
  }[];
};

async function mount(page: Page, serverTools = true) {
  await page.setContent(
    '<!doctype html><html lang="en"><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Scenario host fixture</title></head><body style="margin:0"><iframe title="Portfolio scenarios" style="border:0;width:100%;height:1900px"></iframe></body></html>',
  );
  await page.evaluate(
    ({ html, serverTools }) => {
      const host = window as unknown as Host;
      host.scenarioCalls = [];
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
        if (value.method === "tools/call") host.scenarioCalls.push(value);
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
  return page.evaluate(() => (window as unknown as Host).scenarioCalls);
}

for (const width of [1440, 768, 360])
  test(`scenario exact tables and safe layout at ${width}px`, async ({
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
    await publish(page);
    const app = page.frameLocator("iframe");
    expect(await page.evaluate(() => innerWidth)).toBe(width);
    expect(await app.locator("body").evaluate(() => innerWidth)).toBe(width);
    await expect(app.locator("#status")).toHaveText(
      "Completed saved scenario analysis.",
    );
    await expect(app.locator("#summary")).toContainText(
      fixture.run.result.context.summary.post_value.value.amount,
    );
    await expect(app.locator("#components tr")).toHaveCount(
      fixture.run.result.components.items.length,
    );
    await expect(app.locator("#method")).toContainText(
      "premium_decimal96_q18_v1",
    );
    await expect(app.locator("#source-count")).toContainText(
      "explicit omissions",
    );
    await expect(app.locator("#component-detail")).toContainText(
      "economic currency EUR",
    );
    await app.getByRole("button", { name: "Refresh saved result" }).focus();
    await expect(
      app.getByRole("button", { name: "Refresh saved result" }),
    ).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(
      app.getByRole("button", { name: "Start components" }),
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
          (tables) => tables.filter((t) => !t.querySelector("caption")).length,
        ),
    ).toBe(0);
    const summaries = app.getByRole("region", { name: "Scenario summaries" });
    expect(
      await summaries.locator("table").evaluate((table) => table.clientWidth),
    ).toBeGreaterThanOrEqual(720);
    if (width === 360) {
      expect(
        await summaries.evaluate(
          (region) => region.scrollWidth - region.clientWidth,
        ),
      ).toBeGreaterThan(0);
      await summaries.focus();
      await expect(summaries).toBeFocused();
      await page.keyboard.press("ArrowRight");
      await expect
        .poll(() => summaries.evaluate((region) => region.scrollLeft))
        .toBeGreaterThan(0);
      await summaries.evaluate((region) => {
        region.scrollLeft = 0;
      });
    }
    await page.screenshot({
      path: info.outputPath(`scenario-widget-${width}.png`),
      fullPage: true,
    });
    expect(requests).toEqual([]);
    expect(errors).toEqual([]);
  });

test("component pagination retains exact IDs, page size, digest and whole rows", async ({
  page,
}) => {
  await mount(page);
  const first = structuredClone(fixture.run),
    next = structuredClone(fixture.run);
  const all = first.result.components.items;
  first.result.components = {
    items: [all[0]],
    next_cursor: "synthetic-next",
    component_limit: 1,
    total: all.length,
    start_ordinal: 0,
  };
  next.result.components = {
    items: all.slice(1),
    next_cursor: null,
    component_limit: 1,
    total: all.length,
    start_ordinal: 1,
  };
  next.result.content_digest = "b".repeat(64);
  await notify(page, "ui/notifications/tool-input", {
    arguments: { account_id: account, run_id: runId, component_limit: 1 },
  });
  await publish(page, envelope(first));
  const app = page.frameLocator("iframe");
  await app.getByRole("button", { name: "Next components" }).click();
  await expect.poll(async () => (await calls(page)).length).toBe(1);
  const pending = (await calls(page))[0];
  expect(pending.params).toEqual({
    name: "get_scenario_result",
    arguments: {
      account_id: account,
      run_id: runId,
      component_limit: 1,
      component_cursor: "synthetic-next",
    },
  });
  await expect(app.locator("#content")).toBeHidden();
  await reply(page, pending.id, { structuredContent: envelope(next) });
  await expect(app.locator("#page-count")).toContainText("ordinal 1");
  await expect(app.locator("#components tr")).toHaveCount(1);
  await expect(app.locator("#components")).toContainText(
    all[1].exposure.path_key,
  );
  await expect(
    app.getByRole("button", { name: "Next components" }),
  ).toBeDisabled();
  await app.getByRole("button", { name: "Start components" }).click();
  await expect.poll(async () => (await calls(page)).length).toBe(2);
  expect((await calls(page))[1].params.arguments).toEqual({
    account_id: account,
    run_id: runId,
    component_limit: 1,
  });
});

test("comparison uses two ordered saved IDs and preserves incompatible sides", async ({
  page,
}) => {
  await mount(page);
  await publish(page);
  const app = page.frameLocator("iframe");
  await app.getByLabel("Compare with another saved run ID").fill(secondId);
  await app.getByRole("button", { name: "Compare saved runs" }).click();
  await expect.poll(async () => (await calls(page)).length).toBe(1);
  const pending = (await calls(page))[0];
  expect(pending.params).toEqual({
    name: "compare_scenarios",
    arguments: {
      account_id: account,
      run_ids: [runId, secondId],
      component_limit: 25,
    },
  });
  await reply(page, pending.id, {
    structuredContent: envelope(fixture.comparison),
  });
  await expect(app.locator("#status")).toHaveText("Saved scenario comparison.");
  await expect(app.locator("#summary")).toContainText(
    fixture.comparison.before.summary.post_value.value.amount,
  );
  await expect(app.locator("#summary")).toContainText(
    fixture.comparison.after.summary.post_value.value.amount,
  );
  const incompatible = structuredClone(fixture.comparison);
  incompatible.compatible = false;
  incompatible.mismatches = [
    { field: "source_cutoff", left: "2026-08-30", right: "2026-08-31" },
  ];
  for (const item of [incompatible, ...incompatible.components.items])
    for (const key of ["post_value", "impact"])
      item[key].difference = {
        ...item[key].difference,
        value: null,
        reason: "incompatible_basis",
        quality: "partial",
      };
  await publish(page, envelope(incompatible));
  await expect(app.locator("#basis")).toContainText(
    "Incompatible retained bases",
  );
  await expect(app.locator("#components")).toContainText(
    "Unavailable: incompatible_basis",
  );
});

test("late foreign-account results, partial input and cancellation clear finance", async ({
  page,
}) => {
  await mount(page);
  await publish(page);
  const app = page.frameLocator("iframe");
  await app.getByRole("button", { name: "Refresh saved result" }).click();
  await expect.poll(async () => (await calls(page)).length).toBe(1);
  const first = (await calls(page))[0];
  await notify(page, "ui/notifications/tool-input", {
    arguments: { account_id: other, run_id: other },
  });
  await reply(page, first.id, { structuredContent: initial });
  await expect(app.locator("#content")).toBeHidden();
  await expect(app.locator("#identity")).toHaveText("");
  await publish(page);
  await expect(app.locator("#content")).toBeHidden();
  await notify(page, "ui/notifications/tool-input", {
    arguments: { account_id: account, run_id: runId },
  });
  await publish(page);
  await expect(app.locator("#content")).toBeVisible();
  await notify(page, "ui/notifications/tool-input-partial", {
    arguments: { account_id: account },
  });
  await publish(page);
  await expect(app.locator("#content")).toBeHidden();
  await notify(page, "ui/notifications/tool-input", {
    arguments: { account_id: account, run_id: runId },
  });
  await publish(page);
  await notify(page, "ui/notifications/tool-cancelled", {});
  await expect(app.locator("#status")).toContainText("cancelled");
  await expect(app.locator("#components tr")).toHaveCount(0);
});

test("financial floats fail closed, labels remain text and denied reads hide values", async ({
  page,
}) => {
  await mount(page);
  const htmlLabel = structuredClone(fixture.run);
  htmlLabel.result.context.definition.name = '<img src=x onerror="alert(1)">';
  await publish(page, envelope(htmlLabel));
  const app = page.frameLocator("iframe");
  await expect(app.locator("#method")).toContainText(
    '<img src=x onerror="alert(1)">',
  );
  await expect(app.locator("img")).toHaveCount(0);
  const malformed = structuredClone(fixture.run);
  malformed.result.context.summary.post_value.value.amount = 0.1;
  await publish(page, envelope(malformed));
  await expect(app.locator("#content")).toBeHidden();
  await expect(app.locator("#status")).toContainText("contract");
  await publish(page, {
    data: null,
    error: { code: "ACCESS_DENIED", message: "private-scenario-canary" },
    execution_allowed: false,
  });
  await expect(app.locator("#status")).toContainText("ACCESS_DENIED");
  await expect(app.locator("body")).not.toContainText(
    "private-scenario-canary",
  );
});

test("text and table fallback needs no host tool bridge or network", async ({
  page,
}) => {
  await mount(page, false);
  await publish(page);
  const app = page.frameLocator("iframe");
  await expect(app.locator("#content")).toBeVisible();
  await expect(app.locator("#bridge")).toContainText("Ask the conversation");
  await expect(
    app.getByRole("button", { name: "Refresh saved result" }),
  ).toBeDisabled();
  expect(await calls(page)).toEqual([]);
});

test("compatibility bridge is bounded and teardown invalidates pending responses", async ({
  page,
}) => {
  await mount(page, false);
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
  const app = page.frameLocator("iframe");
  await app.getByRole("button", { name: "Refresh saved result" }).click();
  await expect
    .poll(async () =>
      frame.evaluate(
        () =>
          (window as unknown as { compatCalls: unknown[] }).compatCalls.length,
      ),
    )
    .toBe(1);
  await expect(
    app.getByRole("button", { name: "Refresh saved result" }),
  ).toBeDisabled();
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
    app.getByRole("button", { name: "Refresh saved result" }),
  ).toBeDisabled();
});

test("stalled read has a finite timeout and permits a fresh explicit retry", async ({
  page,
}) => {
  await page.clock.install();
  await mount(page);
  await publish(page);
  const app = page.frameLocator("iframe");
  await app.getByRole("button", { name: "Refresh saved result" }).click();
  await expect.poll(async () => (await calls(page)).length).toBe(1);
  const previous = (await calls(page))[0];
  await page.clock.fastForward(16000);
  await expect(app.locator("#content")).toBeHidden();
  await expect(app.locator("#status")).toContainText("unavailable");
  await expect(
    app.getByRole("button", { name: "Refresh saved result" }),
  ).toBeEnabled();
  await app.getByRole("button", { name: "Refresh saved result" }).click();
  await expect.poll(async () => (await calls(page)).length).toBe(2);
  await reply(page, previous.id, { structuredContent: initial });
  await expect(app.locator("#content")).toBeHidden();
  await reply(page, (await calls(page))[1].id, { structuredContent: initial });
  await expect(app.locator("#content")).toBeVisible();
});
