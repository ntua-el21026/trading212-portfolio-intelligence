import { execFile } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdtemp, readFile, rm, stat, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { delimiter, dirname, join, resolve } from "node:path";
import { promisify } from "node:util";
import { expect, test, type Page } from "@playwright/test";
import { z } from "zod";
import {
  PremiumReportDocumentHeaderV3Schema,
  PremiumReportJobStatusV3Schema,
  PremiumReportManifestV3Schema,
  PremiumReportPageSchema,
  PremiumReportPageV3Schema,
  ReportPageSchema,
  ReportRowSchema,
  ScenarioRunResponseSchema,
  ScenarioVersionResponseSchema,
  XrayExposuresResponseSchema,
  snapshotDetailSchema,
  type ReportArtifactMetadata,
  type ReportCell,
  type ReportRow,
  type ScenarioMoneyView,
  type ScenarioRunResponse,
} from "@trading212/api-contracts";
import { keyboardClearance } from "./accessibility";

const host = "http://127.0.0.1:18000";
const account = "86ecdc4c-6c42-5593-84ed-de7bde3a6c4c";
const baseline = "f0f5c66e-b128-59b2-a620-83bc8faa4a57";
const alpha = "4a058969-a055-548a-9083-74eb9a4dfec8";
const cutoff = "2026-08-31T12:00:00Z";
const profile = "report_sections_v3";
const name = "Browser scenario report";
const shock = "-0.123456789012345678";
const documentSchema = z.strictObject({
  schema: z.literal("report_document_json_v1"),
  manifest: PremiumReportManifestV3Schema,
  header: PremiumReportDocumentHeaderV3Schema,
  tables: z.array(
    z.strictObject({ table: z.string(), rows: z.array(ReportRowSchema) }),
  ),
});
type Document = z.infer<typeof documentSchema>;

// Independently fixed ADR-0026 inventory, including zero-row proof descriptors.
const scenarioTables = [
  "scenario_basis_v1",
  "scenario_definition_v1",
  "scenario_shocks_v1",
  "scenario_exclusions_v1",
  "scenario_summary_v1",
  "scenario_components_v1",
  "scenario_channels_v1",
  "scenario_applied_sensitivities_v1",
  "scenario_diagnostics_v1",
  "scenario_replay_changes_v1",
  "scenario_subjects_v1",
  "scenario_classifications_v1",
  "scenario_currencies_v1",
  "scenario_members_v1",
  "scenario_sensitivity_versions_v1",
  "scenario_drivers_v1",
  "scenario_sensitivity_observations_v1",
  "scenario_sensitivity_memberships_v1",
  "scenario_sensitivity_evidence_v1",
  "scenario_source_licenses_v1",
  "scenario_replay_basis_v1",
  "scenario_replay_bindings_v1",
  "scenario_replay_methods_v1",
  "scenario_replay_coverage_v1",
  "scenario_replay_warnings_v1",
  "scenario_xray_paths_v1",
  "scenario_source_headers_v1",
];

function rows(document: Document, table: string) {
  const selected = document.tables.find((item) => item.table === table);
  expect(selected, `Canonical table ${table}`).toBeDefined();
  return selected!.rows;
}
function metricQuality(document: Document, row: ReportRow, cell: ReportCell) {
  const context = document.manifest.contexts.find(
    (item) => item.key === (cell.context_key ?? row.context_key),
  );
  expect(context, "Metric context is retained in the manifest").toBeDefined();
  return cell.quality ?? context!.quality;
}
function money(
  document: Document,
  row: ReportRow,
  column: string,
  index: number,
  metric: ScenarioMoneyView,
) {
  const cell = row.cells[index];
  expect(cell).toMatchObject({
    kind: "decimal",
    decimal_role: "money",
    currency: "EUR",
    value: metric.value?.amount ?? null,
    state: metric.value === null ? "unavailable" : "available",
    origin: "derived_deterministic",
  });
  expect(metricQuality(document, row, cell)).toBe(metric.quality);
  expect(cell.confidence ?? null).toBe(metric.confidence);
  expect(
    document.manifest.notes.find((note) => note.key === cell.reason_key)
      ?.code ?? null,
  ).toBe(metric.reason);
  expect(
    document.manifest.bounds.find((bound) => bound.key === cell.bound_key)
      ?.kind,
  ).toBe(metric.value === null ? "unavailable" : "exact");
  // A bounded API preview must not truncate the corresponding report memberships.
  const members = rows(document, "scenario_members_v1")
    .filter(
      (item) =>
        item.cells[0].value === "metric" &&
        item.cells[1].value === `${row.key}.${column}` &&
        item.cells[2].value === "source_reference_ids",
    )
    .sort(
      (left, right) =>
        Number(left.cells[3].value) - Number(right.cells[3].value),
    );
  expect(members).toHaveLength(
    metric.source_reference_ids.items.length +
      metric.source_reference_ids.omitted_count,
  );
  expect(
    members
      .slice(0, metric.source_reference_ids.items.length)
      .map((item) => item.cells[4].value),
  ).toEqual(metric.source_reference_ids.items);
}
function ratio(
  document: Document,
  row: ReportRow,
  index: number,
  metric: { value: string | null; quality: string },
) {
  const cell = row.cells[index];
  expect(cell).toMatchObject({
    kind: "decimal",
    decimal_role: "ratio",
    value: metric.value,
    state: metric.value === null ? "unavailable" : "available",
  });
  expect(metricQuality(document, row, cell)).toBe(metric.quality);
}
function canonicalRows(document: Document, run: ScenarioRunResponse) {
  expect(run.result).not.toBeNull();
  const result = run.result!;
  const context = result.context;
  expect(document.header).toEqual(document.manifest.document);
  expect(
    document.tables
      .filter((table) => table.table.startsWith("scenario_"))
      .map((table) => table.table)
      .sort(),
  ).toEqual([...scenarioTables].sort());
  expect(document.tables.some((table) => table.table.startsWith("risk_"))).toBe(
    false,
  );
  expect(
    document.manifest.bindings.some((binding) => binding.family === "risk"),
  ).toBe(false);
  const basis = rows(document, "scenario_basis_v1");
  expect(basis).toHaveLength(1);
  for (const [index, value] of [
    [0, run.id],
    [1, context.result_id],
    [2, context.saved_result_digest],
    [3, run.input_digest],
    [7, run.scenario_version_id],
    [8, context.pins.scenario_version_digest],
    [10, run.portfolio_snapshot_id],
    [11, context.pins.portfolio_snapshot_digest],
    [12, context.pins.xray_run_id],
    [13, context.pins.xray_input_id],
    [14, context.pins.xray_input_digest],
    [15, context.pins.xray_result_digest],
    [16, "EUR"],
    [17, context.pins.source_cutoff_at],
    [18, context.valuation_at],
    [22, "scenario"],
    [24, context.method_version],
    [26, context.numerical_profile],
    [27, 0],
    [28, false],
  ] as const)
    expect(basis[0].cells[index].value).toBe(value);
  const shocks = rows(document, "scenario_shocks_v1");
  expect(shocks).toHaveLength(1);
  expect(shocks[0].cells[2].value).toBe("price");
  expect(shocks[0].cells[3].value).toBe(shock);
  expect(shocks[0].cells[6].value).toBe(alpha);
  const summary = rows(document, "scenario_summary_v1");
  expect(summary).toHaveLength(1);
  for (const [column, index, metric] of [
    ["terminal_pre_value", 0, context.summary.terminal_pre_value],
    ["covered_pre_value", 1, context.summary.covered_pre_value],
    ["uncovered_pre_value", 2, context.summary.uncovered_pre_value],
    ["excluded_pre_value", 3, context.summary.excluded_pre_value],
    ["covered_post_value", 9, context.summary.covered_post_value],
    ["excluded_post_value", 10, context.summary.excluded_post_value],
    [
      "provably_unchanged_uncovered_value",
      11,
      context.summary.provably_unchanged_uncovered_value,
    ],
    ["post_value", 12, context.summary.post_value],
    ["impact", 13, context.summary.impact],
    ["rounding_residual", 14, context.summary.rounding_residual],
    ["component_sum_residual", 15, context.summary.component_sum_residual],
    ["upstream_portfolio_value", 16, context.upstream_portfolio_value],
    [
      "upstream_partition_difference",
      17,
      context.upstream_partition_difference,
    ],
  ] as const)
    money(document, summary[0], column, index, metric);
  const components = rows(document, "scenario_components_v1");
  expect(components).toHaveLength(result.components.total);
  expect(components.length).toBeGreaterThan(1);
  expect(result.components.items).toHaveLength(result.components.total);
  for (const component of result.components.items) {
    const actual = components.find(
      (row) => row.cells[1].value === component.exposure.path_key,
    );
    expect(actual).toBeDefined();
    expect(actual!.cells[8].value).toBe(component.partition);
    money(document, actual!, "pre_value", 10, component.exposure.pre_value);
    money(document, actual!, "post_value", 11, component.post_value);
    money(document, actual!, "impact", 12, component.impact);
    money(
      document,
      actual!,
      "rounding_residual",
      13,
      component.rounding_residual,
    );
    expect(actual!.cells[14].value).toBe(component.money_basis);
  }
  const channels = rows(document, "scenario_channels_v1");
  expect(channels).toHaveLength(4 * (components.length + 1));
  const effects = [
    { scope: "summary", path: null, value: context.summary.effects },
    ...result.components.items.map((item) => ({
      scope: "component",
      path: item.exposure.path_key,
      value: item.effects,
    })),
  ];
  for (const effect of effects) {
    for (const [channel, change, metric] of [
      ["price", effect.value.price_ratio, effect.value.price],
      ["factor", effect.value.factor_ratio, effect.value.factor],
      ["fx", effect.value.fx_ratio, effect.value.fx],
      ["interaction", null, effect.value.interaction],
    ] as const) {
      const actual = channels.find(
        (row) =>
          row.cells[0].value === effect.scope &&
          row.cells[1].value === effect.path &&
          row.cells[2].value === channel,
      );
      expect(actual).toBeDefined();
      if (change) ratio(document, actual!, 3, change);
      else expect(actual!.cells[3].state).toBe("not_applicable");
      money(document, actual!, "effect", 4, metric);
    }
  }
  for (const table of [
    "scenario_applied_sensitivities_v1",
    "scenario_replay_changes_v1",
    "scenario_sensitivity_versions_v1",
    "scenario_drivers_v1",
    "scenario_sensitivity_observations_v1",
    "scenario_sensitivity_memberships_v1",
    "scenario_sensitivity_evidence_v1",
    "scenario_source_licenses_v1",
    "scenario_source_headers_v1",
    "scenario_replay_basis_v1",
    "scenario_replay_bindings_v1",
    "scenario_replay_methods_v1",
    "scenario_replay_coverage_v1",
    "scenario_replay_warnings_v1",
  ])
    expect(rows(document, table)).toHaveLength(0);
  expect(rows(document, "scenario_xray_paths_v1").length).toBeGreaterThan(0);
  expect(document.manifest.source_references.length).toBeGreaterThan(0);
  expect(document.manifest.license_references.length).toBeGreaterThan(0);
}

async function presentation(page: Page) {
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
  expect(
    await page
      .locator("table")
      .evaluateAll((tables) =>
        tables.every(
          (table) =>
            !table.querySelector("tr") ||
            table.getAttribute("aria-label") ||
            table.querySelector("caption"),
        ),
      ),
  ).toBe(true);
  for (const forbidden of [
    "X-Artifact-Grant",
    "download_link",
    "PRIVATE_PREMIUM_CANARY",
  ])
    expect(await page.content()).not.toContain(forbidden);
}
async function capture(page: Page, path: string) {
  // Reset incidental focus/scroll only after the actual layout and keyboard checks.
  await page.evaluate(() => {
    if (document.activeElement instanceof HTMLElement)
      document.activeElement.blur();
    window.scrollTo({ top: 0, left: 0, behavior: "instant" });
    for (const element of document.querySelectorAll<HTMLElement>("main *")) {
      if (element.scrollWidth > element.clientWidth) element.scrollLeft = 0;
      if (element.scrollHeight > element.clientHeight) element.scrollTop = 0;
    }
  });
  await expect
    .poll(() =>
      page.evaluate(() => ({
        y: scrollY,
        top: document.querySelector("header.topbar")?.getBoundingClientRect()
          .top,
        skip: document.activeElement?.matches(".skip-link") ?? false,
      })),
    )
    .toEqual({ y: 0, top: 0, skip: false });
  await page.screenshot({ path, fullPage: true });
}
async function download(
  page: Page,
  artifact: ReportArtifactMetadata,
  directory: string,
) {
  expect(artifact.byte_length).toBeLessThanOrEqual(10 * 1024 * 1024);
  const event = page.waitForEvent("download");
  await page
    .getByRole("button", {
      name: `Download ${artifact.format.toUpperCase()}`,
      exact: true,
    })
    .click();
  const saved = await event;
  try {
    expect(saved.suggestedFilename()).toBe(
      `portfolio-artifact-${artifact.artifact_id}.${artifact.format}`,
    );
    const path = await saved.path();
    expect(path).not.toBeNull();
    expect((await stat(path!)).size).toBeLessThanOrEqual(10 * 1024 * 1024);
    const bytes = await readFile(path!);
    expect(bytes.byteLength).toBe(artifact.byte_length);
    expect(createHash("sha256").update(bytes).digest("hex")).toBe(
      artifact.content_digest,
    );
    await writeFile(join(directory, `report.${artifact.format}`), bytes, {
      mode: 0o600,
      flag: "wx",
    });
  } finally {
    await saved.delete();
  }
}
function cleared(
  page: Page,
  selectedAccount: string,
  selectedProfile?: string,
  family?: string,
) {
  expect(Object.fromEntries(new URL(page.url()).searchParams)).toEqual({
    account: selectedAccount,
    ...(selectedProfile ? { profile: selectedProfile, family } : {}),
  });
}

// All three configured projects run serially against one reused PostgreSQL service.
test("saved scenario creates a profile3 report with exact four-format values and isolated selections", async ({
  page,
  request,
}, testInfo) => {
  test.setTimeout(300_000);
  expect(testInfo.config.configFile).toBeDefined();
  const root = resolve(dirname(testInfo.config.configFile!), "../..");
  page.setDefaultTimeout(30_000);
  await page.setViewportSize({
    width: testInfo.project.name.includes("mobile")
      ? 360
      : testInfo.project.name.includes("tablet")
        ? 768
        : 1440,
    height: 900,
  });
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (["error", "warning"].includes(message.type()))
      errors.push(message.text());
  });
  await page.goto("/sign-in");
  await page
    .getByRole("button", { name: "Start local session", exact: true })
    .click();
  await expect(page).toHaveURL("http://127.0.0.1:3001/");
  expect(
    (await request.post(`${host}/api/v1/auth/local-session`)).status(),
  ).toBe(201);
  const snapshotResponse = await request.get(
    `${host}/api/v1/accounts/${account}/snapshots/latest`,
  );
  expect(snapshotResponse.status()).toBe(200);
  const snapshot = snapshotDetailSchema.parse(await snapshotResponse.json());
  const xrayResponse = await request.get(
    `${host}/api/v1/accounts/${account}/effective-exposure`,
    {
      params: {
        snapshot_id: snapshot.id,
        source_cutoff_at: cutoff,
        reporting_currency: "EUR",
      },
    },
  );
  expect(xrayResponse.status()).toBe(200);
  const xray = XrayExposuresResponseSchema.parse(await xrayResponse.json());
  expect(xray.summary.total.value).toEqual({ amount: "1000", currency: "EUR" });

  await page.goto(
    `/scenarios?${new URLSearchParams({ account, cutoff, currency: "EUR", view: "definitions" })}`,
  );
  await page.getByLabel("Name", { exact: true }).fill(name);
  await page.getByLabel("Calculation mode").selectOption("compounded");
  await page.getByRole("button", { name: "Add shock", exact: true }).click();
  await page.getByLabel("Shock channel").selectOption("price");
  await page.getByLabel("Match by").selectOption("entity");
  await page.getByLabel("Economic entity ID").fill(alpha);
  await page.getByLabel("Simple return shock").fill(shock);
  await page
    .getByRole("button", { name: "Create scenario", exact: true })
    .click();
  await expect(page).toHaveURL(/version=[0-9a-f-]{36}/);
  const versionId = new URL(page.url()).searchParams.get("version")!;
  const versionResponse = await request.get(
    `${host}/api/v1/scenario-versions/${versionId}`,
  );
  expect(versionResponse.status()).toBe(200);
  const version = ScenarioVersionResponseSchema.parse(
    await versionResponse.json(),
  );
  expect(version.content.shocks).toEqual([
    {
      kind: "price",
      size: shock,
      selector: { kind: "entity", entity_id: alpha },
    },
  ]);
  await page
    .getByRole("link", {
      name: "Use selected version in a new run",
      exact: true,
    })
    .click();
  await page
    .getByRole("combobox", { name: "Portfolio snapshot", exact: true })
    .selectOption(snapshot.id);
  await page
    .getByLabel("Saved X-ray run ID", { exact: true })
    .fill(xray.context.run_id);
  await page.getByLabel("Reporting currency", { exact: true }).fill("EUR");
  await page
    .getByLabel("X-ray knowledge cutoff (ISO timestamp)", { exact: true })
    .fill(cutoff);
  await page
    .getByRole("combobox", { name: "Run basis", exact: true })
    .selectOption("none");
  await page
    .getByRole("button", { name: "Verify saved input pins", exact: true })
    .click();
  await expect(
    page.getByRole("heading", {
      name: "Verified saved X-ray selection",
      exact: true,
    }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Create scenario run", exact: true })
    .click();
  await expect(page).toHaveURL(/view=result/);
  await expect(
    page.getByRole("heading", { name: "Scenario summary", exact: true }),
  ).toBeVisible({ timeout: 120_000 });
  const runId = new URL(page.url()).searchParams.get("run")!;
  const response = await request.get(`${host}/api/v1/scenario-runs/${runId}`);
  expect(response.status()).toBe(200);
  const run = ScenarioRunResponseSchema.parse(await response.json());
  expect(run).toMatchObject({
    account_id: account,
    state: "succeeded",
    result_availability: "available",
    portfolio_snapshot_id: snapshot.id,
    scenario_version_id: versionId,
    xray_run_id: xray.context.run_id,
  });
  expect(run.result).not.toBeNull();
  const context = run.result!.context;
  const oneResponse = await request.get(
    `${host}/api/v1/scenario-runs/${runId}`,
    { params: { component_limit: 1 } },
  );
  expect(oneResponse.status()).toBe(200);
  const one = ScenarioRunResponseSchema.parse(await oneResponse.json());
  expect(one.result?.components.items).toHaveLength(1);
  expect(one.result?.components.next_cursor).not.toBeNull();
  expect(one.result?.context.saved_result_digest).toBe(
    context.saved_result_digest,
  );
  expect(one.result?.content_digest).not.toBe(context.saved_result_digest);
  const table = page.getByRole("table", {
    name: "Saved scenario terminal components",
    exact: true,
  });
  await expect(table.locator(":scope > tbody > tr")).toHaveCount(
    run.result!.components.total,
  );
  expect(
    await table
      .locator("tbody > tr > th")
      .first()
      .evaluate((cell) => cell.getBoundingClientRect().width),
  ).toBeLessThanOrEqual(320);
  const summary = page.getByRole("table", {
    name: "Scenario summary values",
    exact: true,
  });
  expect(
    await summary.evaluate(
      (element) => element.scrollWidth - element.parentElement!.clientWidth,
    ),
  ).toBeLessThanOrEqual(1);
  await presentation(page);
  await capture(page, testInfo.outputPath("scenario-report-source.png"));

  await page
    .getByRole("link", {
      name: "Create a report from this saved scenario",
      exact: true,
    })
    .click();
  await expect(
    page.getByRole("heading", {
      name: "Scenario and risk reports",
      exact: true,
    }),
  ).toBeVisible();
  expect(Object.fromEntries(new URL(page.url()).searchParams)).toEqual({
    account,
    run: runId,
    profile,
    family: "scenario",
    snapshot: snapshot.id,
    currency: "EUR",
    cutoff: context.pins.source_cutoff_at,
    result_digest: context.saved_result_digest,
  });
  await expect(
    page.getByRole("heading", { name: `Report from ${name}`, exact: true }),
  ).toBeVisible();
  for (const format of ["CSV", "JSON", "XLSX"])
    await page.getByRole("checkbox", { name: format, exact: true }).check();
  await presentation(page);
  await capture(page, testInfo.outputPath("scenario-report-selection.png"));
  const admissionStarted = Date.now();
  const admissionResponse = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      new URL(response.url()).pathname === "/reports/premium",
    { timeout: 30_000 },
  );
  await page
    .getByRole("button", { name: "Create scenario report", exact: true })
    .click();
  const admittedAction = await admissionResponse;
  expect(admittedAction.status()).toBe(200);
  // Next streams the action response; completed navigation is the user-visible boundary.
  await expect(page).toHaveURL(/[?&]report=[0-9a-f-]{36}/, {
    timeout: 30_000,
  });
  testInfo.annotations.push({
    type: "report-create-navigation-ms",
    description: String(Date.now() - admissionStarted),
  });
  const reportId = new URL(page.url()).searchParams.get("report")!;
  const params = { account_id: account, profile };
  const admittedResponse = await request.get(
    `${host}/api/v2/report-jobs/${reportId}`,
    { params },
  );
  expect(admittedResponse.status()).toBe(200);
  const admitted = PremiumReportJobStatusV3Schema.parse(
    await admittedResponse.json(),
  );
  expect(admitted.profile_version).toBe(profile);
  expect(admitted.context?.profile_version).toBe(profile);
  expect(["queued", "running", "succeeded"]).toContain(admitted.state);
  await expect(page.getByText("Job succeeded", { exact: true })).toBeVisible({
    timeout: 150_000,
  });
  await expect(
    page.getByRole("heading", { name: "Manifest and provenance", exact: true }),
  ).toBeVisible();
  const completeResponse = await request.get(
    `${host}/api/v2/report-jobs/${reportId}`,
    { params },
  );
  expect(completeResponse.status()).toBe(200);
  const complete = PremiumReportJobStatusV3Schema.parse(
    await completeResponse.json(),
  );
  expect(complete.state).toBe("succeeded");
  expect(complete.artifacts.map((item) => item.format).sort()).toEqual([
    "csv",
    "json",
    "pdf",
    "xlsx",
  ]);
  expect(
    complete.artifacts.reduce((sum, item) => sum + item.byte_length, 0),
  ).toBeLessThanOrEqual(25 * 1024 * 1024);
  const manifestResponse = await request.get(
    `${host}/api/v2/reports/${reportId}`,
    { params },
  );
  expect(manifestResponse.status()).toBe(200);
  const manifestBytes = await manifestResponse.body();
  expect(createHash("sha256").update(manifestBytes).digest("hex")).toBe(
    complete.manifest_digest,
  );
  const manifest = PremiumReportManifestV3Schema.parse(
    JSON.parse(manifestBytes.toString("utf8")),
  );
  expect(manifest.document.selection).toMatchObject({
    profile_version: profile,
    premium_run: { family: "scenario", run_id: runId },
    snapshot_id: snapshot.id,
    account_id: account,
    reporting_currency: "EUR",
    source_cutoff_at: context.pins.source_cutoff_at,
    start_date: context.valuation_at.slice(0, 10),
    end_date: context.valuation_at.slice(0, 10),
  });
  expect(manifest.document.selection).not.toHaveProperty("risk_run_id");
  expect(manifest.document.premium_binding).toMatchObject({
    family: "scenario",
    run_id: runId,
    result_id: context.result_id,
    input_digest: context.input_digest,
    result_digest: context.saved_result_digest,
    scenario_version_id: versionId,
    scenario_version_digest: version.content_digest,
    snapshot_digest: context.pins.portfolio_snapshot_digest,
    xray: {
      run_id: run.xray_run_id,
      input_id: context.pins.xray_input_id,
      input_digest: context.pins.xray_input_digest,
      result_digest: context.pins.xray_result_digest,
    },
  });
  expect(manifest.document.premium_binding).not.toHaveProperty("historical");
  const directory = await mkdtemp(
    join(tmpdir(), "t212pi-scenario-report-browser-"),
  );
  try {
    await writeFile(join(directory, "manifest.json"), manifestBytes, {
      mode: 0o600,
      flag: "wx",
    });
    for (const artifact of complete.artifacts)
      await download(page, artifact, directory);
    const document = documentSchema.parse(
      JSON.parse(await readFile(join(directory, "report.json"), "utf8")),
    );
    expect(document.manifest).toEqual(manifest);
    canonicalRows(document, run);
    const inspected = await promisify(execFile)(
      "uv",
      [
        "run",
        "--no-sync",
        "python",
        "tests/e2e/api-web/scenario_report_artifacts.py",
        directory,
      ],
      {
        cwd: root,
        env: {
          ...process.env,
          PYTHONPATH: [root, process.env.PYTHONPATH]
            .filter(Boolean)
            .join(delimiter),
        },
        timeout: 60_000,
        maxBuffer: 65_536,
      },
    );
    expect(inspected.stderr).toBe("");
    expect(inspected.stdout.trim()).toBe(
      "Verified four formats, canonical manifests, table proofs and named scenario values.",
    );
  } finally {
    await rm(directory, { recursive: true, force: true });
  }

  for (const [versionPath, parser, selectedProfile, contains] of [
    ["v1", ReportPageSchema, undefined, false],
    ["v2", PremiumReportPageSchema, undefined, false],
    ["v2", PremiumReportPageV3Schema, profile, true],
  ] as const) {
    const response = await request.get(`${host}/api/${versionPath}/reports`, {
      params: {
        account_id: account,
        ...(selectedProfile ? { profile: selectedProfile } : {}),
      },
    });
    expect(response.status()).toBe(200);
    const collection = parser.parse(await response.json());
    expect(collection.items.some((item) => item.job_id === reportId)).toBe(
      contains,
    );
  }
  for (const versionPath of ["v1", "v2"]) {
    expect(
      (
        await request.get(
          `${host}/api/${versionPath}/report-jobs/${reportId}`,
          { params: { account_id: account } },
        )
      ).status(),
    ).toBe(404);
    expect(
      (
        await request.get(`${host}/api/${versionPath}/reports/${reportId}`, {
          params: { account_id: account },
        })
      ).status(),
    ).toBe(404);
  }
  await page.reload();
  await expect(page.getByText("Job succeeded", { exact: true })).toBeVisible();
  await presentation(page);
  await capture(page, testInfo.outputPath("scenario-report-completed.png"));
  await page
    .getByRole("navigation", { name: "Report collections", exact: true })
    .getByRole("link", { name: "Risk reports", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Risk reports", exact: true }),
  ).toBeVisible();
  cleared(page, account);
  await expect(
    page.getByRole("heading", { name: "Private artifacts", exact: true }),
  ).toHaveCount(0);
  await page.goBack();
  await expect(page.getByText("Job succeeded", { exact: true })).toBeVisible();
  await page
    .getByRole("combobox", { name: "Saved analysis family", exact: true })
    .selectOption("risk");
  await page
    .getByRole("button", { name: "Choose account", exact: true })
    .click();
  await expect(page).toHaveURL(/family=risk/);
  cleared(page, account, profile, "risk");
  await expect(
    page.getByRole("heading", { name: `Report from ${name}`, exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("heading", { name: "Private artifacts", exact: true }),
  ).toHaveCount(0);
  await page.goBack();
  await expect(page.getByText("Job succeeded", { exact: true })).toBeVisible();
  await page
    .getByRole("combobox", { name: "Portfolio account", exact: true })
    .selectOption(baseline);
  await expect(page).toHaveURL(new RegExp(`account=${baseline}`));
  cleared(page, baseline, profile, "scenario");
  await expect(
    page.getByRole("heading", { name: "Private artifacts", exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("heading", { name: `Report from ${name}`, exact: true }),
  ).toHaveCount(0);
  await page.goBack();
  await expect(page.getByText("Job succeeded", { exact: true })).toBeVisible();
  await page.goto(
    `/reports/premium?${new URLSearchParams({ account: baseline, profile, family: "scenario", report: reportId })}`,
  );
  await expect(
    page.getByText("Selected report unavailable", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Private artifacts", exact: true }),
  ).toHaveCount(0);
  expect(errors).toEqual([]);
});
