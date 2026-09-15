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
        "from trading212_mcp.risk_widget import RISK_WIDGET_HTML",
        "from trading212_domain.serialization import to_primitive",
        "from tests.unit.api.risk_factories import run, matrix",
        "print(json.dumps({'html':RISK_WIDGET_HTML,'run':to_primitive(run()),'matrix':to_primitive(matrix())}))",
      ].join("; "),
    ],
    { cwd: resolve(process.cwd(), "../.."), encoding: "utf8" },
  ),
);
const initial = { data: fixture.run, error: null, execution_allowed: false };
const account = fixture.run.account_id as string;
const runId = fixture.run.id as string;
const other = "00000000-0000-4000-8000-000000000099";

type Host = Window & {
  riskCalls: {
    id: string;
    method: string;
    params: { name: string; arguments: object };
  }[];
};
async function mount(page: Page, serverTools = true) {
  await page.setContent(
    '<!doctype html><html lang="en"><head><title>Risk host fixture</title></head><body style="margin:0"><iframe title="Portfolio risk" style="border:0;width:100%;height:1800px"></iframe></body></html>',
  );
  await page.evaluate(
    ({ html, serverTools }) => {
      const host = window as Host;
      host.riskCalls = [];
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
        if (value.method === "tools/call") host.riskCalls.push(value);
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
  return page.evaluate(() => (window as Host).riskCalls);
}

for (const width of [1440, 768, 360])
  test(`risk widget exact tables, keyboard and reduced motion at ${width}px`, async ({
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
    await expect(
      app.getByRole("heading", { name: "Portfolio risk", exact: true }),
    ).toBeVisible();
    await expect(app.locator("#observed")).toContainText(
      fixture.run.result.observed.volatility_annualized.value,
    );
    await expect(app.locator("#observed")).toContainText("Unavailable");
    await expect(app.locator("#content")).toBeVisible();
    await expect(app.locator("#status")).toHaveText(
      "Completed canonical risk estimates.",
    );
    await app.getByLabel("Matrix measure").selectOption("covariance_periodic");
    await expect(app.locator("#matrix-count")).toContainText(
      "No asset universe selected",
    );
    await app.getByRole("button", { name: "Refresh risk summary" }).focus();
    await expect(
      app.getByRole("button", { name: "Refresh risk summary" }),
    ).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(
      app.getByRole("button", { name: "Read risk matrix" }),
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
    await page.screenshot({
      path: info.outputPath(`risk-widget-${width}.png`),
      fullPage: true,
    });
    expect(requests).toEqual([]);
    expect(errors).toEqual([]);
  });

test("risk widget host refresh is closed and late foreign-account responses are discarded", async ({
  page,
}) => {
  await mount(page);
  await publish(page);
  const app = page.frameLocator("iframe");
  await app.getByRole("button", { name: "Refresh risk summary" }).click();
  await expect.poll(async () => (await calls(page)).length).toBe(1);
  const first = (await calls(page))[0];
  expect(first.params).toEqual({
    name: "get_risk_summary",
    arguments: { account_id: account, run_id: runId },
  });
  await expect(app.locator("#content")).toBeHidden();
  await notify(page, "ui/notifications/tool-input", {
    arguments: { account_id: other, run_id: other },
  });
  await reply(page, first.id, { structuredContent: initial });
  await expect(app.locator("#content")).toBeHidden();
  await expect(app.locator("#identity")).toHaveText("");
  const changed = structuredClone(initial);
  changed.data.account_id = other;
  changed.data.id = other;
  changed.data.result.historical_context.account_id = other;
  await publish(page, changed);
  await expect(app.locator("#identity")).toContainText(other);
  await app.getByRole("button", { name: "Read risk matrix" }).click();
  await expect.poll(async () => (await calls(page)).length).toBe(2);
  const next = (await calls(page))[1];
  expect(next.params).toEqual({
    name: "get_risk_matrix",
    arguments: { account_id: other, run_id: other },
  });
  const matrix = structuredClone(fixture.matrix);
  matrix.account_id = other;
  matrix.run_id = other;
  matrix.historical_context.account_id = other;
  // Synthetic presentation cells exercise selection; this is not a calculation oracle.
  const metric = (value: string) => ({ value, reason: null });
  matrix.matrix = {
    ...matrix.matrix,
    keys: [runId, other],
    requested_intervals: 20,
    used_intervals: 20,
    omitted_intervals: 0,
    correlation: [
      [metric("1"), metric("-0.5")],
      [metric("-0.5"), metric("1")],
    ],
    covariance_periodic: [
      [metric("0.04"), metric("-0.02")],
      [metric("-0.02"), metric("0.04")],
    ],
    regularized_covariance_periodic: [
      [metric("0.04"), metric("-0.01")],
      [metric("-0.01"), metric("0.04")],
    ],
  };
  await reply(page, next.id, {
    structuredContent: { data: matrix, error: null, execution_allowed: false },
  });
  await expect(app.locator("#status")).toHaveText("Canonical risk matrix.");
  await expect(app.locator("#matrix-rows")).toContainText("-0.5");
  await app
    .getByLabel("Matrix measure")
    .selectOption("regularized_covariance_periodic");
  await expect(app.locator("#matrix-rows")).toContainText("-0.01");
  await expect(app.locator("#summary")).toBeHidden();
  await notify(page, "ui/notifications/tool-cancelled", {});
  await publish(page, changed);
  await expect(app.locator("#content")).toBeHidden();
});

test("risk widget rejects partial inputs, malformed financial values and non-parent messages", async ({
  page,
}) => {
  await mount(page);
  await publish(page);
  const app = page.frameLocator("iframe");
  await notify(page, "ui/notifications/tool-input-partial", {
    arguments: { account_id: account },
  });
  await publish(page);
  await expect(app.locator("#content")).toBeHidden();
  await notify(page, "ui/notifications/tool-input", {
    arguments: { account_id: account, run_id: runId },
  });
  const invalid = structuredClone(initial);
  invalid.data.result.observed.volatility_annualized.value = 0.1;
  await publish(page, invalid);
  await expect(app.locator("#status")).toContainText("does not match");
  await publish(page);
  await expect(app.locator("#content")).toBeVisible();
  await app.locator("body").evaluate(() =>
    window.postMessage(
      {
        jsonrpc: "2.0",
        method: "ui/notifications/tool-cancelled",
        params: {},
      },
      "*",
    ),
  );
  await expect(app.locator("#content")).toBeVisible();
  const injected = structuredClone(initial);
  injected.data.result.definition.name =
    '<img src="https://private.invalid" onerror="alert(1)">';
  await publish(page, injected);
  await expect(app.locator("#assumptions")).toContainText("<img");
  await expect(app.locator("img,script[src],form,a[href]")).toHaveCount(0);
});

test("risk widget bounds a stalled host read and clears state on teardown", async ({
  page,
}) => {
  await page.clock.install();
  await mount(page);
  await publish(page);
  const app = page.frameLocator("iframe");
  await app.getByRole("button", { name: "Refresh risk summary" }).click();
  await expect.poll(async () => (await calls(page)).length).toBe(1);
  await page.clock.fastForward(16000);
  await expect(app.locator("#status")).toContainText("could not complete");
  await expect(
    app.getByRole("button", { name: "Refresh risk summary" }),
  ).toBeEnabled();
  await page.evaluate(() =>
    document.querySelector("iframe")!.contentWindow!.postMessage(
      {
        jsonrpc: "2.0",
        id: "teardown",
        method: "ui/resource-teardown",
        params: {},
      },
      "*",
    ),
  );
  await expect(app.locator("#status")).toHaveText("Risk view closed.");
  await publish(page);
  await expect(app.locator("#content")).toBeHidden();
  await expect(
    app.getByRole("button", { name: "Refresh risk summary" }),
  ).toBeDisabled();
});

test("risk widget feature-detects the compatibility bridge without network access", async ({
  page,
}) => {
  await mount(page, false);
  await publish(page);
  const app = page.frameLocator("iframe");
  await expect(
    app.getByRole("button", { name: "Refresh risk summary" }),
  ).toBeDisabled();
  await app.locator("body").evaluate((_element, value) => {
    const target = window as Window & {
      openai?: { callTool: (name: string, args: object) => Promise<object> };
      fallbackCalls?: object[];
    };
    target.fallbackCalls = [];
    target.openai = {
      callTool: async (name, args) => {
        target.fallbackCalls!.push({ name, args });
        return { structuredContent: value };
      },
    };
    window.dispatchEvent(
      new CustomEvent("openai:set_globals", {
        detail: { globals: { toolOutput: value } },
      }),
    );
  }, initial);
  await expect(
    app.getByRole("button", { name: "Refresh risk summary" }),
  ).toBeEnabled();
  await app.getByRole("button", { name: "Refresh risk summary" }).click();
  await expect(app.locator("#status")).toHaveText(
    "Completed canonical risk estimates.",
  );
  expect(
    await app
      .locator("body")
      .evaluate(
        () => (window as Window & { fallbackCalls: object[] }).fallbackCalls,
      ),
  ).toEqual([
    { name: "get_risk_summary", args: { account_id: account, run_id: runId } },
  ]);
});

test("risk widget distinguishes absent results and enforces its UTF-8 result bound", async ({
  page,
}) => {
  await mount(page);
  const app = page.frameLocator("iframe");
  for (const state of ["queued", "running", "failed", "expired", "cancelled"]) {
    const data = {
      ...fixture.run,
      state,
      result: null,
      result_availability: ["queued", "running"].includes(state)
        ? "pending"
        : state === "expired"
          ? "expired"
          : "unavailable",
    };
    await publish(page, { data, error: null, execution_allowed: false });
    await expect(app.locator("#status")).toContainText(`Risk state: ${state};`);
    await expect(app.locator("#content")).toBeHidden();
  }
  await publish(page);
  await expect(app.locator("#content")).toBeVisible();
  await publish(page, { ...initial, padding: "界".repeat(720000) });
  await expect(app.locator("#content")).toBeHidden();
  await expect(app.locator("#status")).toContainText("does not match");
});

test("risk widget canonicalizes input UUIDs and blocks incomplete or invalid selections", async ({
  page,
}) => {
  await mount(page);
  await publish(page);
  const app = page.frameLocator("iframe");
  const nextAccount = "abcdefab-1234-4567-89ab-abcdefabcdef";
  const nextRun = "fedcbafe-1234-4567-89ab-fedcbafedcba";
  await notify(page, "ui/notifications/tool-input", {
    arguments: {
      account_id: nextAccount.toUpperCase(),
      run_id: nextRun.toUpperCase(),
    },
  });
  await publish(page);
  await expect(app.locator("#content")).toBeHidden();
  const changed = structuredClone(initial);
  changed.data.account_id = nextAccount;
  changed.data.id = nextRun;
  changed.data.result.historical_context.account_id = nextAccount;
  await publish(page, changed);
  await expect(app.locator("#identity")).toContainText(nextAccount);
  await app.getByRole("button", { name: "Refresh risk summary" }).click();
  await expect.poll(async () => (await calls(page)).length).toBe(1);
  expect((await calls(page))[0].params.arguments).toEqual({
    account_id: nextAccount,
    run_id: nextRun,
  });
  for (const args of [
    {},
    { account_id: "bad", run_id: runId },
    { account_id: account },
    { account_id: account, run_id: "bad" },
    { account_id: account, run_id: null },
    {
      account_id: account,
      definition_version_id: fixture.run.definition_version_id,
    },
    {
      account_id: account,
      definition_version_id: fixture.run.definition_version_id,
      portfolio_snapshot_id: fixture.run.portfolio_snapshot_id,
      historical_input_snapshot_id: fixture.run.historical_input_snapshot_id,
      xray_run_id: "invalid",
    },
  ]) {
    await notify(page, "ui/notifications/tool-input", { arguments: args });
    await publish(page);
    await expect(app.locator("#content")).toBeHidden();
    await expect(app.locator("#identity")).toHaveText("");
    await expect(
      app.getByRole("button", { name: "Refresh risk summary" }),
    ).toBeDisabled();
  }
  const pins = {
    account_id: account.toUpperCase(),
    definition_version_id: fixture.run.definition_version_id.toUpperCase(),
    portfolio_snapshot_id: fixture.run.portfolio_snapshot_id.toUpperCase(),
    historical_input_snapshot_id:
      fixture.run.historical_input_snapshot_id.toUpperCase(),
    xray_run_id: nextRun.toUpperCase(),
  };
  await notify(page, "ui/notifications/tool-input", { arguments: pins });
  await publish(page);
  await expect(app.locator("#content")).toBeHidden();
  const withXray = structuredClone(initial);
  withXray.data.xray_run_id = nextRun;
  await publish(page, withXray);
  await expect(app.locator("#content")).toBeVisible();
});
