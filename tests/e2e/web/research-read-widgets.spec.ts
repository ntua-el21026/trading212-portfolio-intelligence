import { execFileSync } from "node:child_process";
import { resolve } from "node:path";
import { expect, test, type Page } from "@playwright/test";

// Packaged iframe tests use explicit synthetic canonical presenters. Actual signed
// transport, owner/license authority and PostgreSQL are covered by the Python gate.
const fixtures = JSON.parse(
  execFileSync(
    "uv",
    ["run", "python", "-m", "tests.unit.mcp.research_widget_fixtures"],
    { cwd: resolve(process.cwd(), "../.."), encoding: "utf8" },
  ),
);
type Kind = "research" | "allocation" | "drift";
type HostCall = {
  id: string;
  method: string;
  params: { name: string; arguments: Record<string, unknown> };
};
type Host = Window & { readCalls: HostCall[] };
const foreign = "00000000-0000-4000-8000-000000000999";
async function notify(page: Page, method: string, params: object) {
  await page.evaluate(
    ({ method, params }) =>
      document
        .querySelector("iframe")!
        .contentWindow!.postMessage({ jsonrpc: "2.0", method, params }, "*"),
    { method, params },
  );
}
async function mount(page: Page, kind: Kind, serverTools = true) {
  await page.setContent(
    '<!doctype html><html lang="en"><head><title>Local read widget host</title></head><body style="margin:0"><iframe title="Portfolio read" style="width:100%;height:2200px;border:0"></iframe></body></html>',
  );
  await page.evaluate(
    ({ html, serverTools }) => {
      const host = window as unknown as Host;
      host.readCalls = [];
      const iframe = document.querySelector("iframe")!;
      window.addEventListener("message", (event) => {
        if (
          event.source !== iframe.contentWindow ||
          event.data?.jsonrpc !== "2.0"
        )
          return;
        const d = event.data;
        if (d.method === "ui/initialize")
          iframe.contentWindow!.postMessage(
            {
              jsonrpc: "2.0",
              id: d.id,
              result: {
                protocolVersion: "2026-01-26",
                hostCapabilities: serverTools ? { serverTools: {} } : {},
              },
            },
            "*",
          );
        if (d.method === "tools/call") host.readCalls.push(d);
      });
      iframe.srcdoc = html;
    },
    { html: fixtures[kind].html as string, serverTools },
  );
  await expect(page.frameLocator("iframe").locator("#status")).toContainText(
    "Waiting",
  );
  await notify(page, "ui/notifications/tool-input", {
    arguments: fixtures[kind].args,
  });
  await notify(page, "ui/notifications/tool-result", fixtures[kind].result);
}
async function calls(page: Page) {
  return page.evaluate(() => (window as unknown as Host).readCalls);
}
async function reply(page: Page, id: string, result: object) {
  await page.evaluate(
    ({ id, result }) =>
      document
        .querySelector("iframe")!
        .contentWindow!.postMessage({ jsonrpc: "2.0", id, result }, "*"),
    { id, result },
  );
}

for (const kind of ["research", "allocation", "drift"] as const)
  for (const width of [1440, 768, 360]) {
    test(`${kind} exact offline table and focus at ${width}px`, async ({
      page,
    }, info) => {
      await page.setViewportSize({ width, height: 900 });
      await page.emulateMedia({ reducedMotion: "reduce" });
      const errors: string[] = [],
        requests: string[] = [];
      page.on("pageerror", (e) => errors.push(e.message));
      page.on("request", (r) => requests.push(r.url()));
      await mount(page, kind);
      const app = page.frameLocator("iframe");
      await expect(app.locator("#status")).toContainText(
        "Authorized result loaded",
      );
      await expect(app.getByRole("table").first()).toBeVisible();
      if (kind === "research") {
        await expect(app.locator("#content")).toContainText(
          "100.000000000000000001 EUR",
        );
        await expect(app.locator("#content")).toContainText(
          "<script>untrusted_research()</script>",
        );
        await expect(app.locator("#content script")).toHaveCount(0);
        await expect(app.locator("#content a")).toHaveCount(0);
        await expect(app.locator("#content")).toContainText(
          "Optional synthesis unavailable",
        );
      }
      if (kind === "drift")
        await expect(app.locator("#content")).toContainText(
          fixtures.drift.result.structuredContent.data.leaves[0].actual_value
            .amount,
        );
      if (kind === "allocation")
        await expect(app.locator("#content")).toContainText(
          fixtures.allocation.result.structuredContent.data.allocations[0]
            .market_value.value,
        );
      const region = app.getByRole("region").first();
      await region.focus();
      await expect(region).toBeFocused();
      const frame = page.frames().find((f) => f.parentFrame() !== null)!;
      expect(
        await frame.evaluate(
          () =>
            document.documentElement.scrollWidth -
            document.documentElement.clientWidth,
        ),
      ).toBeLessThanOrEqual(1);
      expect(errors).toEqual([]);
      expect(requests).toEqual([]);
      await frame.evaluate(() => {
        (document.activeElement as HTMLElement | null)?.blur();
        window.scrollTo(0, 0);
        for (const e of document.querySelectorAll(".table-wrap"))
          e.scrollLeft = 0;
      });
      await page.screenshot({
        path: info.outputPath(`${kind}-${width}.png`),
        fullPage: true,
      });
    });
  }

for (const kind of ["research", "allocation", "drift"] as const) {
  test(`${kind} clears partial pins and rejects late account reads`, async ({
    page,
  }) => {
    await mount(page, kind);
    const app = page.frameLocator("iframe");
    await app.getByRole("button", { name: "Refresh authorized view" }).click();
    await expect.poll(async () => (await calls(page)).length).toBe(1);
    const pending = (await calls(page))[0];
    await notify(page, "ui/notifications/tool-input", {
      arguments: { ...fixtures[kind].args, account_id: foreign },
    });
    await reply(page, pending.id, fixtures[kind].result);
    await notify(page, "ui/notifications/tool-result", fixtures[kind].result);
    await expect(app.locator("#content")).toBeHidden();
    await notify(page, "ui/notifications/tool-input-partial", {
      arguments: { account_id: fixtures[kind].args.account_id },
    });
    await notify(page, "ui/notifications/tool-result", fixtures[kind].result);
    await expect(app.locator("#content")).toBeHidden();
    await notify(page, "ui/notifications/tool-input", { arguments: null });
    await notify(page, "ui/notifications/tool-result", fixtures[kind].result);
    await expect(app.locator("#content")).toBeHidden();
  });
}

test("allocation rejects missing widget-only account provenance", async ({
  page,
}) => {
  await mount(page, "allocation");
  const result = structuredClone(fixtures.allocation.result);
  delete result._meta.accountId;
  await notify(page, "ui/notifications/tool-result", result);
  await expect(page.frameLocator("iframe").locator("#content")).toBeHidden();
});

test("research host read remains closed and malformed money clears whole content", async ({
  page,
}) => {
  await mount(page, "research");
  const app = page.frameLocator("iframe");
  await app.getByRole("button", { name: "Refresh authorized view" }).click();
  await expect.poll(async () => (await calls(page)).length).toBe(1);
  const call = (await calls(page))[0];
  expect(call.params.name).toBe("get_research_summary");
  expect(call.params.arguments.account_id).toBe(
    fixtures.research.args.account_id,
  );
  expect(call.params.arguments.xray_run_id).toBe(
    fixtures.research.args.xray_run_id,
  );
  const bad = structuredClone(fixtures.research.result);
  bad.structuredContent.data.items[0].portfolio.effective_exposure.amount = 100;
  await reply(page, call.id, bad);
  await expect(app.locator("#content")).toBeHidden();
});

test("research cancellation, unavailable bridge and teardown clear content", async ({
  page,
}) => {
  await mount(page, "research", false);
  const app = page.frameLocator("iframe");
  await expect(
    app.getByRole("button", { name: "Refresh authorized view" }),
  ).toBeDisabled();
  await expect(app.locator("#bridge")).toContainText("Ask the conversation");
  await notify(page, "ui/notifications/tool-cancelled", {});
  await expect(app.locator("#content")).toBeHidden();
  await notify(page, "ui/notifications/tool-result", fixtures.research.result);
  await expect(app.locator("#content")).toBeHidden();
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
  await notify(page, "ui/notifications/tool-input", {
    arguments: fixtures.research.args,
  });
  await notify(page, "ui/notifications/tool-result", fixtures.research.result);
  await expect(app.locator("#status")).toHaveText("View closed.");
});

test("research next-page call preserves the complete immutable selection", async ({
  page,
}) => {
  await mount(page, "research");
  const result = structuredClone(fixtures.research.result);
  // This host-only cursor is deliberately not real entitlement evidence. The
  // signed PostgreSQL page tests verify actual cursor creation and authorization.
  result.structuredContent.data.next_cursor = "synthetic-host-next";
  result.structuredContent.data.total = 2;
  await notify(page, "ui/notifications/tool-result", result);
  await page
    .frameLocator("iframe")
    .getByRole("button", { name: "Next page", exact: true })
    .click();
  await expect.poll(async () => (await calls(page)).length).toBe(1);
  expect((await calls(page))[0].params).toEqual({
    name: "get_research_summary",
    arguments: {
      ...fixtures.research.args,
      entity_id: null,
      event_kind: null,
      review_state: "all",
      limit: 25,
      cursor: "synthetic-host-next",
    },
  });
});

test("research compares offset instants without discarding microseconds", async ({
  page,
}) => {
  await mount(page, "research");
  const app = page.frameLocator("iframe");
  const result = structuredClone(fixtures.research.result);
  result.structuredContent.data.source_cutoff_at =
    "2026-09-15T19:41:00.123456Z";
  for (const item of result.structuredContent.data.items)
    item.source_cutoff_at = "2026-09-15T19:41:00.123456Z";
  const args = {
    ...fixtures.research.args,
    source_cutoff_at: "2026-09-15T22:41:00.123456+03:00",
  };
  await notify(page, "ui/notifications/tool-input", { arguments: args });
  await notify(page, "ui/notifications/tool-result", result);
  await expect(app.locator("#status")).toContainText(
    "Authorized result loaded",
  );
  for (const cutoff of [
    "2026-09-15T22:41:00.123457+03:00",
    "2026-02-30T19:41:00.123456Z",
    "2026-09-15T19:41:00+24:00",
  ]) {
    await notify(page, "ui/notifications/tool-input", {
      arguments: { ...args, source_cutoff_at: cutoff },
    });
    await notify(page, "ui/notifications/tool-result", result);
    await expect(app.locator("#content")).toBeHidden();
  }
});
