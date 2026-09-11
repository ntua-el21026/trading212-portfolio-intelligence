import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import {
  expect,
  test,
  type APIRequestContext,
  type Page,
} from "@playwright/test";
import {
  AlertEventDetailSchema,
  AlertEventPageSchema,
  AlertRuleDetailSchema,
  AlertRulePageSchema,
  AlertSummarySchema,
  ExportJobStatusSchema,
  ReportManifestSchema,
  ReportRowSchema,
  snapshotDetailSchema,
} from "@trading212/api-contracts";

const api = "http://127.0.0.1:18000/api/v1";
const account = "f0f5c66e-b128-59b2-a620-83bc8faa4a57";

async function storedRule(request: APIRequestContext, ruleId: string) {
  const response = await request.get(`${api}/alert-rules/${ruleId}`);
  expect(response.status()).toBe(200);
  return AlertRuleDetailSchema.parse(await response.json());
}
async function namedRule(request: APIRequestContext, name: string) {
  const response = await request.get(`${api}/alert-rules`, {
    params: { account_id: account, state: "all", limit: 100 },
  });
  expect(response.status()).toBe(200);
  const page = AlertRulePageSchema.parse(await response.json());
  const rule = page.items.find(
    (item) => item.latest_version.definition.name === name,
  );
  expect(rule, `Actual seeded rule ${name}`).toBeDefined();
  return rule!;
}
async function presentation(page: Page) {
  await expect(page.getByRole("main")).toHaveCount(1);
  await expect(
    page.getByRole("heading", { level: 1, name: "Alerts" }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () =>
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
    ),
  ).toBeLessThanOrEqual(1);
  expect(await page.content()).not.toMatch(
    /Bearer |X-CSRF-Token|comparison_basis|secret_reference/,
  );
  expect(
    await page
      .getByRole("main")
      .locator(
        'input:not([type="checkbox"]):not([type="hidden"]), select, textarea',
      )
      .evaluateAll((controls) =>
        controls
          .filter((control) => control.getBoundingClientRect().height < 44)
          .map((control) => control.tagName),
      ),
  ).toEqual([]);
  expect(
    await page
      .getByRole("main")
      .locator(".ui-surface")
      .evaluateAll((surfaces) =>
        surfaces.every((surface) => {
          const style = getComputedStyle(surface);
          return (
            Number.parseFloat(style.paddingLeft) >= 16 &&
            Number.parseFloat(style.paddingRight) >= 16
          );
        }),
      ),
  ).toBe(true);
}
async function capture(page: Page, path: string) {
  await page.evaluate(() => window.scrollTo(0, 0));
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(0);
  await page.screenshot({ path, fullPage: true });
}

async function hydrated(page: Page) {
  await expect
    .poll(() =>
      page.evaluate(
        () =>
          (window as Window & { __alertHistoryReady?: boolean })
            .__alertHistoryReady === true,
      ),
    )
    .toBe(true);
}

test.beforeEach(async ({ page, request }) => {
  await page.addInitScript(() => {
    const push = window.history.pushState;
    const replace = window.history.replaceState;
    Object.defineProperty(window, "__alertHistoryReady", {
      get: () =>
        window.history.pushState !== push &&
        window.history.replaceState !== replace,
    });
  });
  await page.goto("/sign-in");
  await page.getByRole("button", { name: "Start local session" }).click();
  await expect(page).toHaveURL("http://127.0.0.1:3001/");
  expect((await request.post(`${api}/auth/local-session`)).status()).toBe(201);
});

test("creates immutable versions and explicitly activates, pauses and archives through the UI", async ({
  page,
  request,
}, info) => {
  await page.goto(`/alerts?account=${account}`);
  await hydrated(page);
  const editor = page.getByRole("form", { name: "Alert rule editor" });
  await editor
    .getByLabel("Rule name", { exact: true })
    .fill(`Browser cash ${info.project.name}`);
  await editor
    .getByRole("combobox", { name: "Rule family", exact: true })
    .selectOption("cash_threshold");
  await editor
    .getByRole("combobox", { name: "Metric", exact: true })
    .selectOption("cash_weight");
  await expect(editor.getByLabel("Threshold", { exact: true })).toBeVisible();
  await editor
    .getByLabel("Threshold", { exact: true })
    .fill("0.100000000000000001");
  await editor
    .getByRole("button", { name: "Create rule", exact: true })
    .click();
  await expect(page).toHaveURL(/rule=[0-9a-f-]{36}/);
  const ruleId = new URL(page.url()).searchParams.get("rule")!;
  const first = await storedRule(request, ruleId);
  expect(first.lifecycle).toBe("draft");
  expect(first.active_version).toBeNull();
  expect(first.latest_version.definition.predicate).toMatchObject({
    metric: "cash_weight",
    threshold: "0.100000000000000001",
  });
  await page
    .getByRole("form", { name: "Alert rule editor" })
    .getByLabel("Rule name", { exact: true })
    .fill(`Browser revision ${info.project.name}`);
  await page
    .getByRole("button", { name: "Save new version", exact: true })
    .click();
  await expect
    .poll(
      async () =>
        (await storedRule(request, ruleId)).latest_version.version_number,
    )
    .toBe(2);
  const second = await storedRule(request, ruleId);
  expect(second.active_version).toBeNull();
  expect(second.version_page.items.map((item) => item.id)).toContain(
    first.latest_version.id,
  );
  await expect(
    page.getByRole("heading", {
      name: "Immutable version history",
      exact: true,
    }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Activate version 2", exact: true })
    .click();
  await expect
    .poll(async () => (await storedRule(request, ruleId)).active_version?.id)
    .toBe(second.latest_version.id);
  await page.getByRole("button", { name: "Pause rule", exact: true }).click();
  await expect
    .poll(async () => (await storedRule(request, ruleId)).lifecycle)
    .toBe("paused");
  await page.getByText(/Saved version 1 ·/).click();
  await page
    .getByRole("button", { name: "Activate saved version 1", exact: true })
    .click();
  await expect
    .poll(async () => (await storedRule(request, ruleId)).active_version?.id)
    .toBe(first.latest_version.id);
  await page.getByRole("button", { name: "Archive rule", exact: true }).click();
  await expect
    .poll(async () => (await storedRule(request, ruleId)).lifecycle)
    .toBe("archived");
  await expect(
    page.getByRole("button", { name: "Save new version", exact: true }),
  ).toBeDisabled();
  await presentation(page);
  await capture(page, `/tmp/trading212-alerts-rules-${info.project.name}.png`);
  const name = page
    .getByRole("form", { name: "Alert rule editor" })
    .getByLabel("Rule name", { exact: true });
  await name.evaluate((control) =>
    control.scrollIntoView({ block: "center", behavior: "instant" }),
  );
  await expect
    .poll(() =>
      name.evaluate((control) => {
        const box = control.getBoundingClientRect();
        return box.top >= 80 && box.bottom <= window.innerHeight - 100;
      }),
    )
    .toBe(true);
  await page.screenshot({
    path: `/tmp/trading212-alerts-controls-${info.project.name}.png`,
  });
});

test("inspects an actual captured event and separately acknowledges and resolves it", async ({
  page,
  request,
}, info) => {
  const rule = await namedRule(request, "Synthetic cash monitor");
  const response = await request.get(`${api}/alert-events`, {
    params: { account_id: account, rule_id: rule.id, state: "open", limit: 25 },
  });
  expect(response.status()).toBe(200);
  const events = AlertEventPageSchema.parse(await response.json());
  expect(events.items.length).toBeGreaterThan(0);
  const event = events.items[0];
  expect(event.evaluation.result?.outcome).toBe("matched");
  expect(event.evaluation.result?.observation?.value).not.toBeNull();
  await page.goto(
    `/alerts?account=${account}&view=events&rule=${rule.id}&event=${event.id}`,
  );
  await hydrated(page);
  await expect(
    page.getByRole("heading", { name: "Alert event · Warning", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText(event.evaluation.input_digest, { exact: false }).first(),
  ).toBeVisible();
  await page
    .getByLabel("Review note (optional)")
    .fill("Reviewed the recorded synthetic cash observation.");
  await page
    .getByRole("button", { name: "Acknowledge event", exact: true })
    .click();
  await expect
    .poll(async () => {
      const result = await request.get(`${api}/alert-events/${event.id}`);
      return AlertEventDetailSchema.parse(await result.json()).acknowledgment
        ?.note;
    })
    .toBe("Reviewed the recorded synthetic cash observation.");
  let stored = AlertEventDetailSchema.parse(
    await (await request.get(`${api}/alert-events/${event.id}`)).json(),
  );
  expect(stored.episode_state).toBe("open");
  await page
    .getByRole("button", { name: "Resolve event", exact: true })
    .click();
  await expect
    .poll(
      async () =>
        AlertEventDetailSchema.parse(
          await (await request.get(`${api}/alert-events/${event.id}`)).json(),
        ).episode_state,
    )
    .toBe("resolved");
  stored = AlertEventDetailSchema.parse(
    await (await request.get(`${api}/alert-events/${event.id}`)).json(),
  );
  expect(stored.resolution_reason).toBe("manual");
  expect(stored.acknowledgment).not.toBeNull();
  expect(stored.evaluation.input_digest).toBe(event.evaluation.input_digest);
  expect(stored.evaluation.result_digest).toBe(event.evaluation.result_digest);
  await expect(
    page.getByRole("button", { name: "Resolve event", exact: true }),
  ).toBeDisabled();
  const summary = AlertSummarySchema.parse(
    await (
      await request.get(`${api}/accounts/${account}/alert-summary`, {
        params: { state: "all", severity: "all", top_n: 5 },
      })
    ).json(),
  );
  expect(summary.counts.acknowledged_count).toBeGreaterThanOrEqual(1);
  expect(summary.counts.open_count + summary.counts.resolved_count).toBe(
    summary.counts.total_count,
  );
  await presentation(page);
  await capture(
    page,
    `/tmp/trading212-alerts-history-${info.project.name}.png`,
  );
});

test("quality gaps remain evaluations rather than invented notifications", async ({
  page,
  request,
}) => {
  const rule = await namedRule(request, "Synthetic quality monitor");
  const detail = await storedRule(request, rule.id);
  expect(
    detail.evaluation_page.items.some(
      (item) =>
        item.outcome === "suppressed" &&
        item.result?.reason === "material_quality",
    ),
  ).toBe(true);
  const response = await request.get(`${api}/alert-events`, {
    params: { account_id: account, rule_id: rule.id, state: "all" },
  });
  expect(AlertEventPageSchema.parse(await response.json()).total).toBe(0);
  await page.goto(
    `/alerts?account=${account}&rule=${rule.id}&evaluation_limit=1&version_limit=1`,
  );
  await expect(
    page.getByRole("heading", { name: /Suppressed ·/ }).first(),
  ).toBeVisible();
  await expect(
    page.getByText("No conclusive decision", { exact: true }),
  ).toBeVisible();
  await page
    .getByText(/Method, coverage, warnings and source context/)
    .first()
    .click();
  await expect(page.getByText(/Outcome reason:/).first()).toBeVisible();
  await presentation(page);
});

test("keeps alerts reachable by pointer and rejects invalid filters explicitly", async ({
  page,
}, info) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.name));
  await page.goto("/");
  if (info.project.name.includes("mobile")) {
    await page.getByText("All sections", { exact: true }).click();
    await page
      .getByRole("navigation", { name: "All portfolio sections", exact: true })
      .getByRole("link", { name: "Alerts", exact: true })
      .click();
  } else
    await page
      .getByRole("navigation", { name: "Portfolio", exact: true })
      .getByRole("link", { name: "Alerts", exact: true })
      .click();
  await expect(
    page.getByRole("heading", { level: 1, name: "Alerts" }),
  ).toBeVisible();
  for (const query of [
    "unknown=x",
    "__proto__=x",
    "rule_state=active&rule_state=paused",
    "view=commands",
  ]) {
    await test.step(query, async () => {
      await page.goto(`/alerts?${query}`);
      await expect(
        page.getByText("Invalid alert selection", { exact: true }),
      ).toBeVisible();
      expect(errors).toEqual([]);
    });
  }
});

test("exports actual alert history through the authorized private download flow", async ({
  page,
  request,
}) => {
  test.setTimeout(150_000);
  const rule = await namedRule(request, "Synthetic cash monitor");
  const detail = await storedRule(request, rule.id);
  const evaluation = detail.latest_evaluation!;
  expect(evaluation.result?.observation).not.toBeNull();
  const snapshotResponse = await request.get(
    `${api}/accounts/${account}/snapshots/latest`,
  );
  expect(snapshotResponse.status()).toBe(200);
  const snapshot = snapshotDetailSchema.parse(await snapshotResponse.json());
  const cutoff = new Date().toISOString();
  await page.goto(
    `/reports?${new URLSearchParams({
      account,
      snapshot: snapshot.id,
      kind: "export",
      dataset: "alerts",
      formats: "json",
      field_set: "audit",
      start_date: evaluation.scheduled_for.slice(0, 10),
      end_date: evaluation.scheduled_for.slice(0, 10),
      source_cutoff_at: cutoff,
    })}`,
  );
  await hydrated(page);
  await expect(
    page.getByRole("combobox", { name: "Dataset", exact: true }),
  ).toHaveValue("alerts");
  await expect(
    page.getByRole("combobox", { name: "Report type", exact: true }),
  ).toBeHidden();
  await page
    .getByRole("button", { name: "Create export", exact: true })
    .click();
  await expect(page).toHaveURL(/[?&]export=[0-9a-f-]{36}/);
  await expect(page.getByText("Job succeeded", { exact: true })).toBeVisible({
    timeout: 90_000,
  });
  const id = new URL(page.url()).searchParams.get("export")!;
  const response = await request.get(`${api}/exports/${id}`, {
    params: { account_id: account },
  });
  expect(response.status()).toBe(200);
  const status = ExportJobStatusSchema.parse(await response.json());
  expect(status.dataset).toBe("alerts");
  expect(status.format).toBe("json");
  const metadata = status.artifacts[0];
  const event = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "Download JSON", exact: true })
    .click();
  const file = await event;
  try {
    const path = await file.path();
    expect(path).not.toBeNull();
    const bytes = await readFile(path!);
    expect(bytes.length).toBe(metadata.byte_length);
    expect(createHash("sha256").update(bytes).digest("hex")).toBe(
      metadata.content_digest,
    );
    const document = JSON.parse(bytes.toString("utf8")) as {
      manifest: unknown;
      tables: Array<{ table: string; rows: unknown[] }>;
    };
    const manifest = ReportManifestSchema.parse(document.manifest);
    expect(
      manifest.bindings.some(
        (pin) =>
          pin.family === "alerts" &&
          pin.subject_id === evaluation.id &&
          pin.content_digest === evaluation.result_digest,
      ),
    ).toBe(true);
    const table = document.tables.find(
      (item) => item.table === "alert_observations",
    );
    expect(table).toBeDefined();
    const observed = table!.rows
      .map((row) => ReportRowSchema.parse(row))
      .find((row) => row.cells[0].value === evaluation.id);
    expect(observed?.cells[6].value).toBe(
      evaluation.result?.observation?.value,
    );
    expect(observed?.cells[7].value).toBe(
      evaluation.result?.observation?.currency,
    );
    expect(bytes.toString("utf8")).not.toContain("comparison_basis");
  } finally {
    await file.delete();
  }
  expect(page.url()).not.toMatch(/grant|token/);
  expect(await page.content()).not.toContain("X-Artifact-Grant");
});
