import { execFile } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdtemp, readFile, rm, stat, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { delimiter, dirname, join, resolve } from "node:path";
import { promisify } from "node:util";
import {
  expect,
  test,
  type APIRequestContext,
  type Page,
} from "@playwright/test";
import { z } from "zod";
import {
  AssumptionVersionResponseSchema,
  GoalVersionResponseSchema,
  PremiumReportDocumentHeaderV4Schema,
  PremiumReportJobStatusV4Schema,
  PremiumReportManifestV4Schema,
  PremiumReportPageSchema,
  PremiumReportPageV3Schema,
  PremiumReportPageV4Schema,
  ProjectionRunResponseSchema,
  ReportPageSchema,
  ReportRowSchema,
  snapshotDetailSchema,
  type AssumptionVersionResponse,
  type GoalVersionResponse,
  type ProjectionPointRow,
  type ProjectionRunResponse,
  type ReportArtifactMetadata,
  type ReportRow,
} from "@trading212/api-contracts";
import { keyboardClearance } from "./accessibility";

const host = "http://127.0.0.1:18000";
const api = `${host}/api/v1`;
const account = "86ecdc4c-6c42-5593-84ed-de7bde3a6c4c";
const baseline = "f0f5c66e-b128-59b2-a620-83bc8faa4a57";
const profile = "report_sections_v4";
const anchor = "2026-09-15";
const terminal = "2026-12-15";
const moneyFields = [
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
] as const;
// Independent fixed inventory: empty proof tables must remain present as well.
const projectionTables = [
  "projection_basis_v1",
  "projection_definitions_v1",
  "projection_assumptions_v1",
  "projection_assets_v1",
  "projection_correlations_v1",
  "projection_calendar_v1",
  "projection_schedule_v1",
  "projection_sensitivity_v1",
  "projection_variants_v1",
  "projection_paths_v1",
  "projection_points_v1",
  "projection_point_assets_v1",
  "projection_distributions_v1",
  "projection_quantiles_v1",
  "projection_histograms_v1",
  "projection_histogram_bins_v1",
  "projection_goal_state_v1",
  "projection_goal_definition_v1",
  "projection_goal_results_v1",
  "projection_members_v1",
  "projection_source_headers_v1",
  "projection_source_nodes_v1",
  "projection_source_members_v1",
  "projection_source_scalars_v1",
];
const documentSchema = z.strictObject({
  schema: z.literal("report_document_json_v1"),
  manifest: PremiumReportManifestV4Schema,
  header: PremiumReportDocumentHeaderV4Schema,
  tables: z.array(
    z.strictObject({ table: z.string(), rows: z.array(ReportRowSchema) }),
  ),
});
type Document = z.infer<typeof documentSchema>;
type Expected =
  string | number | boolean | null | { amount: string; currency: string };

function href(fields: Record<string, string> = {}) {
  return `/projections?${new URLSearchParams({ account, ...fields })}`;
}
function pin(page: Page, key: string) {
  const value = new URL(page.url()).searchParams.get(key);
  expect(value).toMatch(/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/);
  return value!;
}
async function readRun(
  request: APIRequestContext,
  id: string,
  cursor?: string,
  pointLimit = 25,
) {
  const response = await request.get(`${api}/projection-runs/${id}`, {
    params: {
      point_limit: pointLimit,
      ...(cursor ? { point_cursor: cursor } : {}),
    },
  });
  expect(response.status()).toBe(200);
  const bytes = await response.body();
  return {
    value: ProjectionRunResponseSchema.parse(
      JSON.parse(bytes.toString("utf8")),
    ),
    bytes,
  };
}
function rows(document: Document, table: string) {
  const selected = document.tables.find((item) => item.table === table);
  expect(selected, `Retained table ${table}`).toBeDefined();
  return selected!.rows;
}
function record(
  document: Document,
  row: ReportRow,
  expected: readonly Expected[],
) {
  expect(row.cells).toHaveLength(expected.length);
  for (const [index, value] of expected.entries()) {
    const cell = row.cells[index];
    if (value !== null && typeof value === "object") {
      expect(cell).toMatchObject({
        kind: "decimal",
        decimal_role: "money",
        currency: value.currency,
        value: value.amount,
        state: "available",
      });
      const context = document.manifest.contexts.find(
        (item) => item.key === (cell.context_key ?? row.context_key),
      );
      expect(context).toBeDefined();
      expect(cell.quality ?? context!.quality).toBe("estimated");
    } else {
      const normalized =
        cell.kind === "instant" && typeof value === "string"
          ? value
              .replace(/\+00:00$/, "Z")
              .replace(/(\.\d*?[1-9])0+Z$/, "$1Z")
              .replace(/\.0+Z$/, "Z")
          : value;
      expect(cell.value).toBe(normalized);
      if (value !== null) expect(cell.state).toBe("available");
    }
  }
}
function records(
  document: Document,
  table: string,
  expected: readonly (readonly Expected[])[],
) {
  const actual = rows(document, table);
  expect(actual).toHaveLength(expected.length);
  for (const [index, value] of expected.entries())
    record(document, actual[index], value);
}
function canonicalRows(
  document: Document,
  run: ProjectionRunResponse,
  points: readonly ProjectionPointRow[],
  assumption: AssumptionVersionResponse,
  goal: GoalVersionResponse,
) {
  expect(run.result).not.toBeNull();
  const result = run.result!,
    context = result.context;
  expect(document.header).toEqual(document.manifest.document);
  expect(
    document.tables
      .filter((table) => table.table.startsWith("projection_"))
      .map((table) => table.table)
      .sort(),
  ).toEqual([...projectionTables].sort());
  expect(
    document.tables.some((table) => /^(risk|scenario)_/.test(table.table)),
  ).toBe(false);
  const binding = document.header.premium_binding;
  expect(binding).toMatchObject({
    family: "projection",
    root_id: run.id,
    run_id: run.id,
    result_id: context.result_id,
    capture_digest: context.capture_digest,
    numerical_input_digest: context.numerical_input_digest,
    result_digest: context.saved_result_digest,
    account_id: account,
    reporting_currency: "EUR",
    initial_kind: "modeled_value",
    observed: null,
    anchor_date: anchor,
    terminal_date: terminal,
    months: 3,
    path_count: 3,
    retained_point_count: 4,
    variant_count: 3,
    asset_count: context.assumptions.assets.length,
    source_count: 0,
    source_cutoff_at: null,
    assumption: {
      aggregate_id: assumption.set_id,
      version_id: assumption.id,
      content_digest: assumption.content_digest,
    },
    goal: {
      aggregate_id: goal.goal_id,
      version_id: goal.id,
      content_digest: goal.content_digest,
    },
  });
  const basis = rows(document, "projection_basis_v1");
  expect(basis).toHaveLength(1);
  record(document, basis[0], [
    binding.root_id,
    run.id,
    binding.input_id,
    context.result_id,
    context.capture_digest,
    context.numerical_input_digest,
    context.saved_result_digest,
    binding.owner_id,
    account,
    "EUR",
    binding.created_at,
    context.calculated_at,
    binding.completed_at,
    binding.expires_at,
    "modeled_value",
    context.selection.initial.modeled_value!,
    null,
    null,
    null,
    null,
    anchor,
    terminal,
    23,
    3,
    3,
    4,
    3,
    "projection_v1",
    "1.0.0",
    "premium_decimal96_q18_v1",
    "sha256_counter_polar_v1",
    "calendar_anniversary_clamped_v1",
    "1.0.0",
    binding.report_context.snapshot_id,
    binding.report_context.snapshot_digest,
    binding.report_context.valuation_at,
    binding.report_context.source_cutoff_at,
  ]);
  records(document, "projection_definitions_v1", [
    [
      "assumption",
      assumption.set_id,
      assumption.id,
      assumption.version_number,
      assumption.predecessor_id,
      assumption.metadata.name,
      assumption.metadata.description ?? "",
      assumption.content_digest,
      assumption.created_at,
    ],
    [
      "goal",
      goal.goal_id,
      goal.id,
      goal.version_number,
      goal.predecessor_id,
      goal.metadata.name,
      goal.metadata.description ?? "",
      goal.content_digest,
      goal.created_at,
    ],
  ]);
  records(document, "projection_assumptions_v1", [
    [
      context.assumptions.annual_inflation!,
      context.assumptions.annual_fee!,
      context.assumptions.annual_tax_drag ?? null,
      context.assumptions.rebalance ?? "monthly",
      "EUR",
      context.assumptions.assets.length,
      0,
    ],
  ]);
  records(
    document,
    "projection_correlations_v1",
    context.assumptions.correlation.flatMap((row, i) =>
      row.map((coefficient, j) => [
        i,
        j,
        context.assumptions.assets[i].key,
        context.assumptions.assets[j].key,
        coefficient,
      ]),
    ),
  );
  records(document, "projection_sensitivity_v1", [
    [
      context.selection.sensitivity!.contribution_delta,
      context.selection.sensitivity!.annual_mean_log_delta,
    ],
  ]);
  const scheduleRows: Expected[][] = [];
  for (const [scope, schedule] of [
    ["run", context.selection.schedule],
    ["goal", goal.content.schedule],
  ] as const) {
    scheduleRows.push([
      scope,
      "base",
      0,
      null,
      null,
      null,
      schedule.base_monthly,
      schedule.annual_growth ?? "0",
    ]);
    expect(schedule.paused_dates ?? []).toEqual([]);
    for (const [index, entry] of (schedule.entries ?? []).entries()) {
      expect(entry.on).toBe("2026-10-15");
      scheduleRows.push([
        scope,
        entry.kind,
        index,
        entry.key,
        entry.on,
        // October15 starts the second month after the September15 anchor.
        2,
        entry.value,
        null,
      ]);
    }
  }
  records(document, "projection_schedule_v1", scheduleRows);
  records(
    document,
    "projection_members_v1",
    context.numerical_zero_pivots.map((value, index) => [
      "zero_pivot",
      index,
      value,
      null,
      null,
    ]),
  );
  records(
    document,
    "projection_assets_v1",
    context.assumptions.assets.map((asset, index) => {
      const initial = context.selection.allocation.find(
        (item) => item.key === asset.key,
      )!;
      expect(initial).toBeDefined();
      return [
        index,
        asset.key,
        asset.annual_mean_log_return,
        asset.annual_volatility,
        asset.weight,
        context.selection.allocation.indexOf(initial),
        initial.weight,
      ];
    }),
  );
  const dates = [anchor, "2026-10-15", "2026-11-15", terminal];
  records(
    document,
    "projection_calendar_v1",
    dates.map((on, month) => [month, on, month]),
  );
  records(
    document,
    "projection_points_v1",
    points.map((row) => [
      row.variant,
      row.path_index,
      row.point_index,
      row.point.month,
      row.on,
      ...moneyFields.map((field) => row.point[field]),
      row.point.funding_failed,
      row.point.unpaid_positive_below_quantum,
    ]),
  );
  records(
    document,
    "projection_point_assets_v1",
    points.flatMap((row) =>
      row.point.assets.map((asset, index) => [
        row.variant,
        row.path_index,
        row.point_index,
        index,
        asset.key,
        asset.value,
      ]),
    ),
  );
  records(
    document,
    "projection_paths_v1",
    points
      .filter((row) => row.point_index === 0)
      .map((row) => [
        row.variant,
        row.path_index,
        "EUR",
        row.first_unpaid_month,
      ]),
  );
  records(
    document,
    "projection_variants_v1",
    result.variants.map((variant) => [
      variant.variant,
      3,
      variant.distributions.length,
      variant.goal !== null,
    ]),
  );
  records(
    document,
    "projection_distributions_v1",
    result.variants.flatMap((variant) =>
      variant.distributions.map((item) => [
        variant.variant,
        item.month,
        item.on,
        item.nominal_mean,
        item.real_mean,
        item.funding_failed_paths,
      ]),
    ),
  );
  const quantiles: Expected[][] = [];
  for (const variant of result.variants) {
    for (const item of variant.distributions) {
      for (const kind of ["nominal", "real"] as const)
        item[kind].values.forEach((value, index) =>
          quantiles.push([
            variant.variant,
            kind,
            item.month,
            index,
            item[kind].probabilities[index],
            value,
          ]),
        );
    }
    expect(variant.goal).not.toBeNull();
    variant.goal!.shortfalls.values.forEach((value, index) =>
      quantiles.push([
        variant.variant,
        "goal_shortfall",
        null,
        index,
        variant.goal!.shortfalls.probabilities[index],
        value,
      ]),
    );
  }
  records(document, "projection_quantiles_v1", quantiles);
  records(
    document,
    "projection_histograms_v1",
    result.variants.flatMap((variant) =>
      (["nominal", "real"] as const).map((basis) => {
        const histogram = variant[`${basis}_histogram`];
        return [
          variant.variant,
          basis,
          histogram.observed_minimum,
          histogram.observed_maximum,
          histogram.boundary_rule ?? "q18_enclosing_ceiling_v1",
        ];
      }),
    ),
  );
  records(
    document,
    "projection_histogram_bins_v1",
    result.variants.flatMap((variant) =>
      (["nominal", "real"] as const).flatMap((basis) =>
        variant[`${basis}_histogram`].bins.map((item, index) => [
          variant.variant,
          basis,
          index,
          item.lower,
          item.upper,
          item.upper_inclusive,
          item.count,
        ]),
      ),
    ),
  );
  records(document, "projection_goal_state_v1", [[true, null, goal.id, false]]);
  records(document, "projection_goal_definition_v1", [
    [
      assumption.id,
      goal.content.target,
      goal.content.target_date,
      goal.content.months,
      goal.content.basis,
      goal.content.probability_objective,
    ],
  ]);
  records(
    document,
    "projection_goal_results_v1",
    result.variants.map((variant) => {
      const estimate = variant.goal!;
      expect(estimate.automatic_goal_acceptance ?? false).toBe(false);
      return [
        variant.variant,
        estimate.goal_version_id,
        estimate.basis,
        estimate.target,
        estimate.paths,
        estimate.successes,
        estimate.probability,
        estimate.interval_low,
        estimate.interval_high,
        estimate.probability_objective,
        estimate.objective_met,
        estimate.mean_shortfall,
        estimate.funding_failed_paths,
        estimate.method ?? "goal_analysis_v1",
        estimate.interval_method ?? "wilson_95_v1",
      ];
    }),
  );
  for (const kind of ["headers", "nodes", "members", "scalars"])
    records(document, `projection_source_${kind}_v1`, []);
  const projectionContext = document.manifest.contexts.find(
    (item) => item.family === "projection",
  );
  expect(projectionContext).toMatchObject({
    valuation_at: null,
    source_cutoff_at: null,
    quality: "estimated",
  });
  expect(document.manifest.source_references.length).toBeGreaterThan(0);
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

// Each configured viewport runs serially on one reused PostgreSQL service.
// The UI and real background delivery create the source; no route/API stubs.
test("saved projection and pinned goal produce complete four-format profile4 reports", async ({
  page,
  request,
}, info) => {
  test.setTimeout(300_000);
  page.setDefaultTimeout(30_000);
  const width = info.project.name.includes("mobile")
    ? 360
    : info.project.name.includes("tablet")
      ? 768
      : 1440;
  await page.setViewportSize({ width, height: 900 });
  const root = resolve(dirname(info.config.configFile!), "../..");
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (["error", "warning"].includes(message.type()))
      errors.push(message.text());
  });
  await page.goto("/sign-in");
  await page.getByRole("button", { name: "Start local session" }).click();
  await expect(page).toHaveURL("http://127.0.0.1:3001/");
  expect((await request.post(`${api}/auth/local-session`)).status()).toBe(201);
  const snapshotResponse = await request.get(
    `${api}/accounts/${account}/snapshots/latest`,
  );
  expect(snapshotResponse.status()).toBe(200);
  const snapshot = snapshotDetailSchema.parse(await snapshotResponse.json());

  await page.goto(href({ view: "assumptions" }));
  const assumptionForm = page.getByRole("form", {
    name: "Projection assumptions",
  });
  await assumptionForm
    .getByLabel("Assumption name", { exact: true })
    .fill("Report saved assumptions");
  await assumptionForm
    .getByLabel("Annual mean log return", { exact: true })
    .fill("-0.000000000000000001");
  await assumptionForm
    .getByLabel("Annual volatility", { exact: true })
    .fill("0.2");
  await assumptionForm
    .getByLabel("Annual inflation (ratio)", { exact: true })
    .fill("0.02");
  await assumptionForm
    .getByLabel("Annual fee (ratio)", { exact: true })
    .fill("0.001");
  await assumptionForm
    .getByLabel("Annual modeled tax drag (blank means not modeled)", {
      exact: true,
    })
    .fill("0.002");
  await assumptionForm
    .getByLabel("Allocation weight", { exact: true })
    .fill("0.6");
  await assumptionForm
    .getByRole("button", { name: "Add asset group", exact: true })
    .click();
  const secondAsset = assumptionForm.getByRole("group", {
    name: "Asset 2",
    exact: true,
  });
  await secondAsset.getByLabel("Asset key", { exact: true }).fill("defensive");
  await secondAsset
    .getByLabel("Annual mean log return", { exact: true })
    .fill("0.02");
  await secondAsset
    .getByLabel("Annual volatility", { exact: true })
    .fill("0.08");
  await secondAsset
    .getByLabel("Allocation weight", { exact: true })
    .fill("0.4");
  await assumptionForm
    .getByLabel("Correlation asset 1 and 2", { exact: true })
    .fill("0.25");
  await assumptionForm
    .getByRole("button", { name: "Create assumption set", exact: true })
    .click();
  await expect
    .poll(() => new URL(page.url()).searchParams.get("version"))
    .not.toBeNull();
  const assumptionId = pin(page, "version"),
    setId = pin(page, "set");
  const assumptionResponse = await request.get(
    `${api}/assumption-versions/${assumptionId}`,
  );
  expect(assumptionResponse.status()).toBe(200);
  const assumption = AssumptionVersionResponseSchema.parse(
    await assumptionResponse.json(),
  );
  expect(
    assumption.content.assets.find((asset) => asset.key === "portfolio")
      ?.annual_mean_log_return,
  ).toBe("-0.000000000000000001");

  await page.goto(href({ view: "goals", set: setId, version: assumptionId }));
  const goalForm = page.getByRole("form", { name: "Projection goal" });
  await goalForm
    .getByLabel("Goal name", { exact: true })
    .fill("Report saved goal");
  await goalForm
    .getByLabel("Target amount (EUR)", { exact: true })
    .fill("50.123456789012345678");
  await goalForm.getByLabel("Target date", { exact: true }).fill(terminal);
  await goalForm.getByLabel("Goal horizon (months)", { exact: true }).fill("3");
  await goalForm
    .getByLabel("Base monthly contribution", { exact: true })
    .fill("10.000000000000000001");
  await goalForm
    .getByRole("button", { name: "Add dated cash flow", exact: true })
    .click();
  await goalForm
    .getByLabel("Entry key", { exact: true })
    .fill("withdrawal-one");
  await goalForm.getByLabel("Entry date", { exact: true }).fill("2026-10-15");
  await goalForm
    .getByRole("combobox", { name: "Entry type", exact: true })
    .selectOption("withdrawal");
  await goalForm
    .getByLabel("Entry amount", { exact: true })
    .fill("75.000000000000000001");
  await goalForm
    .getByRole("button", { name: "Create goal", exact: true })
    .click();
  await expect
    .poll(() => new URL(page.url()).searchParams.get("goal_version"))
    .not.toBeNull();
  const goalId = pin(page, "goal_version");
  const goalResponse = await request.get(`${api}/goal-versions/${goalId}`);
  expect(goalResponse.status()).toBe(200);
  const goal = GoalVersionResponseSchema.parse(await goalResponse.json());
  expect(goal.content.assumption_version_id).toBe(assumptionId);

  await page.goto(
    href({ view: "new", version: assumptionId, goal_version: goalId }),
  );
  const runForm = page.getByRole("form", { name: "Create projection run" });
  await runForm
    .getByLabel("Modeled initial value (EUR)", { exact: true })
    .fill("100.123456789012345678");
  await runForm.getByLabel("Modeled anchor date", { exact: true }).fill(anchor);
  await runForm.getByLabel("Saved path count", { exact: true }).fill("3");
  await runForm.getByLabel("Random seed", { exact: true }).fill("23");
  await runForm
    .getByLabel("Retained months (comma separated)", { exact: true })
    .fill("0,1,2,3");
  await runForm
    .getByLabel("Include contribution and mean-return variants", {
      exact: true,
    })
    .check();
  await runForm
    .getByLabel("Monthly contribution delta (EUR)", { exact: true })
    .fill("2");
  await runForm
    .getByLabel("Annual mean log return delta", { exact: true })
    .fill("0.005");
  await presentation(page);
  await capture(page, info.outputPath("projection-report-inputs.png"));
  await runForm
    .getByRole("button", { name: "Create projection run", exact: true })
    .click();
  await expect
    .poll(() => new URL(page.url()).searchParams.get("run"))
    .not.toBeNull();
  const runId = pin(page, "run");
  await expect
    .poll(async () => (await readRun(request, runId)).value.state, {
      timeout: 120_000,
    })
    .toBe("succeeded");
  // No next cursor in this full 36-point page: byte equality does not depend on
  // a freshly minted cursor cutoff. The separate 25-row traversal below does.
  const original = await readRun(request, runId, undefined, 100);
  const run = original.value;
  expect(run.result).not.toBeNull();
  const context = run.result!.context;
  expect(run.result!.points.total).toBe(36);
  expect(run.result!.variants).toHaveLength(3);
  expect(context.snapshot_valuation_at).toBeNull();
  expect(context.source_cutoff_at).toBeNull();
  expect(run.result!.points.next_cursor).toBeNull();
  expect(context.assumptions.assets).toHaveLength(2);
  const firstPage = (await readRun(request, runId)).value;
  expect(firstPage.result).not.toBeNull();
  expect(firstPage.result!.context).toEqual(context);
  const completePoints: ProjectionPointRow[] = [
    ...firstPage.result!.points.items,
  ];
  const cursors = new Set<string>();
  let cursor = firstPage.result!.points.next_cursor;
  while (cursor !== null) {
    expect(cursor.length).toBeLessThanOrEqual(2048);
    expect(cursors.has(cursor)).toBe(false);
    expect(cursors.size).toBeLessThan(3);
    cursors.add(cursor);
    const next = (await readRun(request, runId, cursor)).value;
    expect(next.result).not.toBeNull();
    expect(next.result!.context).toEqual(context);
    expect(next.result!.variants).toEqual(run.result!.variants);
    expect(next.result!.points.start_ordinal).toBe(completePoints.length);
    expect(next.result!.points.items.length).toBeGreaterThan(0);
    completePoints.push(...next.result!.points.items);
    cursor = next.result!.points.next_cursor;
  }
  expect(cursors.size).toBeGreaterThan(0);
  expect(completePoints).toEqual(run.result!.points.items);
  expect(completePoints.map((point) => point.ordinal)).toEqual(
    Array.from({ length: 36 }, (_, i) => i),
  );
  await page.goto(href({ view: "result", run: runId }));
  await expect(
    page.getByRole("heading", {
      name: "Complete retained point rows",
      exact: true,
    }),
  ).toBeVisible();
  await presentation(page);
  await capture(page, info.outputPath("projection-report-source.png"));

  await page.goto(
    `/reports/premium?${new URLSearchParams({ account, profile, family: "projection" })}`,
  );
  await expect(
    page.getByRole("heading", {
      name: "Projection and goal reports",
      exact: true,
    }),
  ).toBeVisible();
  await page
    .getByRole("combobox", { name: "Saved projection", exact: true })
    .selectOption(runId);
  await page
    .getByRole("combobox", { name: "Report-context snapshot", exact: true })
    .selectOption(snapshot.id);
  await page
    .getByRole("button", {
      name: "Use saved projection and snapshot",
      exact: true,
    })
    .click();
  await expect(
    page.getByRole("heading", {
      name: "Create a report from the saved projection",
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    page.getByText("No observed valuation; modeled starting value", {
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    page.getByText("Not supplied by every original source", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("checkbox", {
      name: "Include the pinned goal section",
      exact: true,
    }),
  ).toBeChecked();
  for (const format of ["CSV", "JSON", "XLSX"])
    await page.getByRole("checkbox", { name: format, exact: true }).check();
  await page
    .getByLabel("Requested retention (days)", { exact: true })
    .fill("30");
  await presentation(page);
  await capture(page, info.outputPath("projection-report-selection.png"));
  const admissionStarted = Date.now();
  const actionResponse = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      new URL(response.url()).pathname === "/reports/premium",
    { timeout: 30_000 },
  );
  await page
    .getByRole("button", { name: "Create projection report", exact: true })
    .click();
  expect((await actionResponse).status()).toBe(200);
  await expect(page).toHaveURL(/[?&]report=[0-9a-f-]{36}/, { timeout: 30_000 });
  info.annotations.push({
    type: "report-create-navigation-ms",
    description: String(Date.now() - admissionStarted),
  });
  const reportId = pin(page, "report"),
    params = { account_id: account, profile };
  const admittedResponse = await request.get(
    `${host}/api/v2/report-jobs/${reportId}`,
    { params },
  );
  expect(admittedResponse.status()).toBe(200);
  const admitted = PremiumReportJobStatusV4Schema.parse(
    await admittedResponse.json(),
  );
  expect(["queued", "running", "succeeded"]).toContain(admitted.state);
  expect(admitted.profile_version).toBe(profile);
  await expect(page.getByText("Job succeeded", { exact: true })).toBeVisible({
    timeout: 150_000,
  });
  await expect(
    page.getByRole("heading", { name: "Manifest and provenance", exact: true }),
  ).toBeVisible();
  const finishedResponse = await request.get(
    `${host}/api/v2/report-jobs/${reportId}`,
    { params },
  );
  expect(finishedResponse.status()).toBe(200);
  const finished = PremiumReportJobStatusV4Schema.parse(
    await finishedResponse.json(),
  );
  expect(finished.state).toBe("succeeded");
  expect(Date.parse(finished.expires_at)).toBeLessThanOrEqual(
    Date.parse(run.expires_at),
  );
  expect(finished.artifacts.map((item) => item.format).sort()).toEqual([
    "csv",
    "json",
    "pdf",
    "xlsx",
  ]);
  expect(
    finished.artifacts.reduce((sum, item) => sum + item.byte_length, 0),
  ).toBeLessThanOrEqual(25 * 1024 * 1024);
  const manifestResponse = await request.get(
    `${host}/api/v2/reports/${reportId}`,
    { params },
  );
  expect(manifestResponse.status()).toBe(200);
  const manifestBytes = await manifestResponse.body();
  expect(createHash("sha256").update(manifestBytes).digest("hex")).toBe(
    finished.manifest_digest,
  );
  const manifest = PremiumReportManifestV4Schema.parse(
    JSON.parse(manifestBytes.toString("utf8")),
  );
  expect(manifest.document.selection).toMatchObject({
    profile_version: profile,
    premium_run: { family: "projection", run_id: runId },
    snapshot_id: snapshot.id,
    account_id: account,
    reporting_currency: "EUR",
    source_cutoff_at: snapshot.source_cutoff_at,
    start_date: snapshot.valuation_at.slice(0, 10),
    end_date: snapshot.valuation_at.slice(0, 10),
  });
  expect(manifest.document.selection.sections).toContain("projection");
  expect(manifest.document.selection.sections).toContain("goal");
  expect(manifest.document.selection).not.toHaveProperty("risk_run_id");
  expect(manifest.document.premium_binding.report_context).toMatchObject({
    snapshot_id: snapshot.id,
    valuation_at: snapshot.valuation_at,
    source_cutoff_at: snapshot.source_cutoff_at,
  });
  expect(manifest.document.premium_binding.source_cutoff_at).toBeNull();
  expect(manifest.document.premium_binding.observed).toBeNull();
  const directory = await mkdtemp(
    join(tmpdir(), "t212pi-projection-report-browser-"),
  );
  try {
    await writeFile(join(directory, "manifest.json"), manifestBytes, {
      mode: 0o600,
      flag: "wx",
    });
    for (const artifact of finished.artifacts)
      await download(page, artifact, directory);
    const document = documentSchema.parse(
      JSON.parse(await readFile(join(directory, "report.json"), "utf8")),
    );
    expect(document.manifest).toEqual(manifest);
    canonicalRows(document, run, completePoints, assumption, goal);
    const inspected = await promisify(execFile)(
      "uv",
      [
        "run",
        "--no-sync",
        "python",
        "tests/e2e/api-web/projection_report_artifacts.py",
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
      "Verified four formats, canonical manifests, table proofs and named projection and goal values.",
    );
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
  // Report copying leaves the original saved result and its page bytes unchanged.
  const after = await readRun(request, runId, undefined, 100);
  expect(after.bytes).toEqual(original.bytes);
  expect(after.value.result!.context.saved_result_digest).toBe(
    context.saved_result_digest,
  );
  for (const [versionPath, parser, selectedProfile, contains] of [
    ["v1", ReportPageSchema, undefined, false],
    ["v2", PremiumReportPageSchema, undefined, false],
    ["v2", PremiumReportPageV3Schema, "report_sections_v3", false],
    ["v2", PremiumReportPageV4Schema, profile, true],
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
  for (const [versionPath, selectedProfile] of [
    ["v1", null],
    ["v2", null],
    ["v2", "report_sections_v3"],
  ] as const) {
    for (const resource of ["report-jobs", "reports"])
      expect(
        (
          await request.get(
            `${host}/api/${versionPath}/${resource}/${reportId}`,
            {
              params: {
                account_id: account,
                ...(selectedProfile ? { profile: selectedProfile } : {}),
              },
            },
          )
        ).status(),
      ).toBe(404);
  }
  await page.reload();
  await expect(page.getByText("Job succeeded", { exact: true })).toBeVisible();
  await presentation(page);
  await capture(page, info.outputPath("projection-report-completed.png"));
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
    .getByRole("combobox", { name: "Portfolio account", exact: true })
    .selectOption(baseline);
  await expect(page).toHaveURL(new RegExp(`account=${baseline}`));
  cleared(page, baseline, profile, "projection");
  await expect(
    page.getByRole("heading", { name: "Private artifacts", exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("heading", {
      name: "Create a report from the saved projection",
      exact: true,
    }),
  ).toHaveCount(0);
  await presentation(page);
  await capture(page, info.outputPath("projection-report-account-reset.png"));
  await page.goto(
    `/reports/premium?${new URLSearchParams({ account: baseline, profile, family: "projection", report: reportId })}`,
  );
  await expect(
    page.getByText("Report status unavailable", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Private artifacts", exact: true }),
  ).toHaveCount(0);
  expect(errors).toEqual([]);
});
