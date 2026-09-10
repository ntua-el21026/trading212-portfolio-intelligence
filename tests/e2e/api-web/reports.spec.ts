import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import {
  expect,
  test,
  type APIRequestContext,
  type Page,
} from "@playwright/test";
import {
  ReportJobStatusSchema,
  ExportJobStatusSchema,
  ReportManifestSchema,
  snapshotDetailSchema,
  type ReportArtifactMetadata,
} from "@trading212/api-contracts";

const api = "http://127.0.0.1:18000/api/v1";
const account = "f0f5c66e-b128-59b2-a620-83bc8faa4a57";
async function selectedSnapshot(request: APIRequestContext) {
  const response = await request.get(
    `${api}/accounts/${account}/snapshots/latest`,
  );
  expect(response.status()).toBe(200);
  return snapshotDetailSchema.parse(await response.json());
}
async function presentation(page: Page) {
  expect(
    await page.evaluate(
      () =>
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
    ),
  ).toBeLessThanOrEqual(1);
  await expect(page.getByRole("main")).toHaveCount(1);
  await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
  expect(
    await page
      .locator("table")
      .evaluateAll((tables) =>
        tables.every(
          (table) =>
            table.getAttribute("aria-label") || table.querySelector("caption"),
        ),
      ),
  ).toBe(true);
  for (const forbidden of [
    "X-Artifact-Grant",
    "download_link",
    ["EXPORT", "URL", "CANARY"].join("_"),
  ])
    expect(await page.content()).not.toContain(forbidden);
}
async function download(page: Page, metadata: ReportArtifactMetadata) {
  const event = page.waitForEvent("download");
  await page
    .getByRole("button", {
      name: `Download ${metadata.format.toUpperCase()}`,
      exact: true,
    })
    .click();
  const file = await event;
  expect(file.suggestedFilename()).toBe(
    `portfolio-artifact-${metadata.artifact_id}.${metadata.format}`,
  );
  const path = await file.path();
  expect(path).not.toBeNull();
  try {
    const bytes = await readFile(path!);
    expect(bytes.length).toBe(metadata.byte_length);
    expect(createHash("sha256").update(bytes).digest("hex")).toBe(
      metadata.content_digest,
    );
    return bytes;
  } finally {
    await file.delete();
  }
}

test.beforeEach(async ({ page, request }) => {
  page.setDefaultTimeout(30_000);
  await page.goto("/sign-in");
  await page.getByRole("button", { name: "Start local session" }).click();
  await expect(page).toHaveURL("http://127.0.0.1:3001/");
  expect((await request.post(`${api}/auth/local-session`)).status()).toBe(201);
});

async function reportsLink(page: Page) {
  const desktop = page.getByRole("navigation", {
    name: "Portfolio",
    exact: true,
  });
  if (await desktop.isVisible()) {
    await desktop.getByRole("link", { name: "Reports", exact: true }).click();
  } else {
    await page.getByText("All sections", { exact: true }).click();
    await page
      .getByRole("navigation", { name: "All portfolio sections", exact: true })
      .getByRole("link", { name: "Reports", exact: true })
      .click();
  }
}

async function captureSelectionControls(
  page: Page,
  project: string,
  kind: "report" | "export",
) {
  const control = page.getByRole("combobox", {
    name: kind === "report" ? "Report type" : "Dataset",
    exact: true,
  });
  await control.evaluate((element) =>
    element.scrollIntoView({ block: "center" }),
  );
  await control.click({ trial: true });
  await page.screenshot({
    path: `/tmp/t212-p2-06-${project}-${kind}-controls.png`,
    fullPage: false,
  });
}

test("report navigation restores edited defaults through the sidebar and browser history", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/reports");
  await expect(
    page.getByRole("heading", { level: 1, name: "Reports" }),
  ).toBeVisible();
  const accountBefore = await page
    .getByRole("combobox", { name: "Account", exact: true })
    .inputValue();
  const snapshotBefore = await page
    .getByRole("combobox", { name: "Valuation snapshot", exact: true })
    .inputValue();
  const startBefore = await page
    .getByLabel("Start date", { exact: true })
    .inputValue();
  await page.evaluate(() => {
    document.documentElement.dataset.reportNavigation = "same-document";
  });
  await page
    .getByRole("combobox", { name: "Output", exact: true })
    .selectOption("export");
  await page
    .getByRole("combobox", { name: "Dataset", exact: true })
    .selectOption("dividends");
  await page
    .getByRole("combobox", { name: "Format", exact: true })
    .selectOption("xlsx");
  await page
    .getByRole("combobox", { name: "Columns", exact: true })
    .selectOption("audit");
  const cutoff = page.getByLabel("Source cutoff (UTC)", { exact: true });
  const typed = "2026-09-07T12:00:00.123456789+00:00";
  expect(typed.length).toBeGreaterThan(32);
  await cutoff.fill("");
  await cutoff.pressSequentially(typed);
  await expect(cutoff).toBeFocused();
  await expect(cutoff).toHaveValue(typed);
  const edited = page.url();
  await reportsLink(page);
  await expect(page).toHaveURL("http://127.0.0.1:3001/reports");
  await expect(
    page.getByRole("combobox", { name: "Account", exact: true }),
  ).toHaveValue(accountBefore);
  await expect(
    page.getByRole("combobox", { name: "Valuation snapshot", exact: true }),
  ).toHaveValue(snapshotBefore);
  await expect(
    page.getByRole("combobox", { name: "Output", exact: true }),
  ).toHaveValue("report");
  await expect(
    page.getByRole("combobox", { name: "Report type", exact: true }),
  ).toHaveValue("portfolio_summary");
  await expect(page.getByLabel("Start date", { exact: true })).toHaveValue(
    startBefore,
  );
  await expect(
    page.getByRole("checkbox", { name: "PDF", exact: true }),
  ).toBeChecked();
  expect(
    await page.evaluate(
      () => document.documentElement.dataset.reportNavigation,
    ),
  ).toBe("same-document");
  await page.goBack();
  await expect(page).toHaveURL(edited);
  await expect(
    page.getByRole("combobox", { name: "Output", exact: true }),
  ).toHaveValue("export");
  await expect(
    page.getByRole("combobox", { name: "Dataset", exact: true }),
  ).toHaveValue("dividends");
  await expect(
    page.getByRole("combobox", { name: "Format", exact: true }),
  ).toHaveValue("xlsx");
  await expect(
    page.getByRole("combobox", { name: "Columns", exact: true }),
  ).toHaveValue("audit");
  await expect(cutoff).toHaveValue(typed);
  await page.goForward();
  await expect(page).toHaveURL("http://127.0.0.1:3001/reports");
  await expect(
    page.getByRole("combobox", { name: "Output", exact: true }),
  ).toHaveValue("report");
  await presentation(page);
  expect(errors).toEqual([]);
});

test("invalid client navigation displays a bounded selection error and restores safely", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/reports");
  for (const query of [
    "kind=unsafe-selector",
    "__proto__=unsafe-selector",
    "kind=report&kind=export",
    "start_date=2026-09-08&end_date=2026-09-07",
  ]) {
    await page.evaluate(
      (search) => window.history.pushState(null, "", `/reports?${search}`),
      query,
    );
    await expect(
      page.getByText("Invalid report selection", { exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Generate report", exact: true }),
    ).toHaveCount(0);
    expect(await page.getByRole("main").innerText()).not.toContain(
      "unsafe-selector",
    );
    await page
      .getByRole("link", { name: "Reset the report selection", exact: true })
      .click();
    await expect(page).toHaveURL("http://127.0.0.1:3001/reports");
    await expect(
      page.getByRole("button", { name: "Generate report", exact: true }),
    ).toBeEnabled();
  }
  await presentation(page);
  expect(errors).toEqual([]);
});

test("report generation retains snapshot and manifest provenance across all four authenticated downloads", async ({
  page,
  request,
}, testInfo) => {
  test.setTimeout(150_000);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const snapshot = await selectedSnapshot(request);
  const selected = new URLSearchParams({
    account,
    snapshot: snapshot.id,
    source_cutoff_at: snapshot.source_cutoff_at,
    reporting_currency: "EUR",
    start_date: `${snapshot.valuation_at.slice(0, 7)}-01`,
    end_date: snapshot.valuation_at.slice(0, 10),
  });
  await page.goto(`/reports?${selected}`);
  await expect(
    page.getByRole("heading", { level: 1, name: "Reports" }),
  ).toBeVisible();
  await expect(
    page.getByRole("combobox", { name: "Report type", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("combobox", { name: "Dataset", exact: true }),
  ).toBeHidden();
  await page.getByRole("checkbox", { name: "CSV", exact: true }).check();
  await page.getByRole("checkbox", { name: "JSON", exact: true }).check();
  await page.getByRole("checkbox", { name: "XLSX", exact: true }).check();
  await captureSelectionControls(page, testInfo.project.name, "report");
  await page
    .getByRole("button", { name: "Generate report", exact: true })
    .click();
  await expect(page).toHaveURL(/[?&]report=[0-9a-f-]{36}/);
  await expect(page.getByText("Job succeeded", { exact: true })).toBeVisible({
    timeout: 90_000,
  });
  const id = new URL(page.url()).searchParams.get("report")!;
  const response = await request.get(`${api}/report-jobs/${id}`, {
    params: { account_id: account },
  });
  expect(response.status()).toBe(200);
  const status = ReportJobStatusSchema.parse(await response.json());
  expect(status.context?.snapshot_id).toBe(snapshot.id);
  expect(status.artifacts.map((artifact) => artifact.format).sort()).toEqual([
    "csv",
    "json",
    "pdf",
    "xlsx",
  ]);
  expect(status.artifacts.every((artifact) => artifact.byte_length > 0)).toBe(
    true,
  );
  const proof = await request.get(`${api}/reports/${id}`, {
    params: { account_id: account },
  });
  expect(proof.status()).toBe(200);
  const proofBytes = await proof.body();
  expect(createHash("sha256").update(proofBytes).digest("hex")).toBe(
    status.manifest_digest,
  );
  const manifest = ReportManifestSchema.parse(
    JSON.parse(proofBytes.toString("utf8")),
  );
  expect(manifest.document.selection.snapshot_id).toBe(snapshot.id);
  expect(
    manifest.bindings.some(
      (pin) => pin.subject_id === snapshot.id && pin.role === "snapshot",
    ),
  ).toBe(true);
  await page.getByText("Captured inputs and quality", { exact: true }).click();
  await expect(
    page.getByText(
      `Snapshot ${snapshot.id} · input ${status.context!.input_digest}`,
      { exact: true },
    ),
  ).toBeVisible();
  await page.getByText(/Sources \(\d+\) and immutable inputs/).click();
  await expect(
    page.getByRole("heading", { name: "Manifest and provenance", exact: true }),
  ).toBeVisible();
  for (const artifact of status.artifacts) {
    const bytes = await download(page, artifact);
    if (artifact.format === "json") {
      const data = JSON.parse(bytes.toString("utf8"));
      expect(data.schema).toBe("report_document_json_v1");
      expect(ReportManifestSchema.parse(data.manifest)).toEqual(manifest);
      expect(data.header.selection.snapshot_id).toBe(snapshot.id);
      expect(
        data.tables.some(
          (table: { table: string; rows: unknown[] }) =>
            table.table === "snapshot_totals" && table.rows.length > 0,
        ),
      ).toBe(true);
    } else if (artifact.format === "pdf")
      expect(bytes.subarray(0, 5).toString()).toBe("%PDF-");
    else if (artifact.format === "xlsx")
      expect(bytes.subarray(0, 2).toString()).toBe("PK");
    else
      expect(bytes.toString("utf8").split("\r\n")[0]).toContain('"column_key"');
  }
  await page.reload();
  await expect(page.getByText("Job succeeded", { exact: true })).toBeVisible();
  expect(new URL(page.url()).searchParams.get("snapshot")).toBe(snapshot.id);
  await presentation(page);
  await page.evaluate(() => window.scrollTo(0, 0));
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(0);
  await page.screenshot({
    path: `/tmp/t212-p2-06-${testInfo.project.name}-report.png`,
    fullPage: true,
  });
  const after = await selectedSnapshot(request);
  expect(after.total_value).toEqual(snapshot.total_value);
  expect(errors).toEqual([]);
});

test("audit export preserves selection after validation failure and offers a verified private spreadsheet", async ({
  page,
  request,
}, testInfo) => {
  test.setTimeout(150_000);
  const snapshot = await selectedSnapshot(request);
  await page.goto(
    `/reports?${new URLSearchParams({ account, snapshot: snapshot.id, kind: "export" })}`,
  );
  await expect(
    page.getByRole("combobox", { name: "Report type", exact: true }),
  ).toBeHidden();
  await page
    .getByRole("combobox", { name: "Format", exact: true })
    .selectOption("xlsx");
  await page
    .getByRole("combobox", { name: "Columns", exact: true })
    .selectOption("audit");
  await page
    .getByLabel("Source cutoff (UTC)", { exact: true })
    .fill("invalid-utc-value");
  await page
    .getByRole("button", { name: "Create export", exact: true })
    .click();
  await expect(
    page.getByText("Request not completed", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("combobox", { name: "Columns", exact: true }),
  ).toHaveValue("audit");
  await page
    .getByLabel("Source cutoff (UTC)", { exact: true })
    .fill(snapshot.source_cutoff_at);
  await captureSelectionControls(page, testInfo.project.name, "export");
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
  expect(status.dataset).toBe("positions");
  expect(status.field_set).toBe("audit");
  expect(status.format).toBe("xlsx");
  expect(status.context?.snapshot_id).toBe(snapshot.id);
  const bytes = await download(page, status.artifacts[0]);
  expect(bytes.subarray(0, 2).toString()).toBe("PK");
  await presentation(page);
  await page.evaluate(() => window.scrollTo(0, 0));
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(0);
  await page.screenshot({
    path: `/tmp/t212-p2-06-${testInfo.project.name}-export.png`,
    fullPage: true,
  });
});
