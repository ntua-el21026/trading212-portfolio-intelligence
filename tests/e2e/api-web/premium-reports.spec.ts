import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { expect, test, type Page } from "@playwright/test";
import { z } from "zod";
import {
  PremiumReportDocumentHeaderSchema,
  PremiumReportJobStatusSchema,
  PremiumReportManifestSchema,
  PremiumReportPageSchema,
  ReportPageSchema,
  ReportRowSchema,
  RiskRunResponseSchema,
  type ReportArtifactMetadata,
} from "@trading212/api-contracts";
import { keyboardClearance } from "./accessibility";

const host = "http://127.0.0.1:18000";
const account = "9a85cdf8-eac9-57c7-be38-e500e4b9edb4";
const baseline = "f0f5c66e-b128-59b2-a620-83bc8faa4a57";
// The seeded complete annual source also covers this real, bounded one-month window.
const window = {
  account,
  start: "2025-01-01",
  end: "2025-01-31",
  cutoff: "2026-09-07T12:00:00.123456Z",
  currency: "EUR",
};
const documentSchema = z.strictObject({
  schema: z.literal("report_document_json_v1"),
  manifest: PremiumReportManifestSchema,
  header: PremiumReportDocumentHeaderSchema,
  tables: z.array(
    z.strictObject({ table: z.string(), rows: z.array(ReportRowSchema) }),
  ),
});

async function presentation(page: Page) {
  await keyboardClearance(page);
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
    "PRIVATE_PREMIUM_CANARY",
  ])
    expect(await page.content()).not.toContain(forbidden);
}
async function download(page: Page, artifact: ReportArtifactMetadata) {
  const event = page.waitForEvent("download");
  await page
    .getByRole("button", {
      name: `Download ${artifact.format.toUpperCase()}`,
      exact: true,
    })
    .click();
  const saved = await event;
  expect(saved.suggestedFilename()).toBe(
    `portfolio-artifact-${artifact.artifact_id}.${artifact.format}`,
  );
  const path = await saved.path();
  expect(path).not.toBeNull();
  try {
    const bytes = await readFile(path!);
    expect(bytes.byteLength).toBe(artifact.byte_length);
    expect(createHash("sha256").update(bytes).digest("hex")).toBe(
      artifact.content_digest,
    );
    return bytes;
  } finally {
    await saved.delete();
  }
}

async function capture(page: Page, path: string) {
  // Keyboard assertions finish before resetting incidental scroll/focus for the image.
  await page.evaluate(() => {
    if (document.activeElement instanceof HTMLElement)
      document.activeElement.blur();
    window.scrollTo({ top: 0, left: 0, behavior: "instant" });
  });
  await expect
    .poll(() =>
      page.evaluate(() => ({
        scrollY,
        headerTop: document
          .querySelector("header.topbar")
          ?.getBoundingClientRect().top,
        skipFocused: document.activeElement?.matches(".skip-link") ?? false,
      })),
    )
    .toEqual({ scrollY: 0, headerTop: 0, skipFocused: false });
  await page.screenshot({ path, fullPage: true });
}

test("saved monthly risk creates all four private formats with canonical values and isolated collections", async ({
  page,
  request,
}, testInfo) => {
  test.setTimeout(300_000);
  page.setDefaultTimeout(30_000);
  const width = testInfo.project.name.includes("mobile")
    ? 360
    : testInfo.project.name.includes("tablet")
      ? 768
      : 1440;
  await page.setViewportSize({ width, height: 900 });
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

  await page.goto(
    `/risk?${new URLSearchParams({ ...window, view: "definitions" })}`,
  );
  await page
    .getByLabel("Name", { exact: true })
    .fill("Browser monthly risk report");
  await page
    .getByLabel("Reporting calendar")
    .selectOption({ label: "synthetic-history-annual · daily-v1" });
  await page.getByLabel("Annual risk-free rate").fill("0.012345678901234567");
  await page
    .getByRole("button", { name: "Create risk definition", exact: true })
    .click();
  await expect(page).toHaveURL(/definition=[0-9a-f-]+/);
  await page.getByRole("link", { name: "New analysis", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Prepared immutable inputs" }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Create risk run", exact: true })
    .click();
  await expect(page).toHaveURL(/view=result/);
  await expect(
    page.getByRole("heading", { name: "Observed historical estimates" }),
  ).toBeVisible({ timeout: 120_000 });
  const runId = new URL(page.url()).searchParams.get("run")!;
  const riskResponse = await request.get(`${host}/api/v1/risk-runs/${runId}`);
  expect(riskResponse.status()).toBe(200);
  const risk = RiskRunResponseSchema.parse(await riskResponse.json());
  expect(risk.state).toBe("succeeded");
  expect(risk.result_availability).toBe("available");
  expect(risk.result).not.toBeNull();
  const canonical = risk.result!;
  expect(canonical.historical_context.window.start_date).toBe(window.start);
  expect(canonical.historical_context.window.end_date).toBe(window.end);
  expect(canonical.observed.volatility_annualized.value).not.toBeNull();

  await page
    .getByRole("link", {
      name: "Create a report from this risk analysis",
      exact: true,
    })
    .click();
  await expect(
    page.getByRole("heading", { name: "Risk reports", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", {
      name: "Report from Browser monthly risk report",
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    page.getByText(risk.portfolio_snapshot_id, { exact: true }).first(),
  ).toBeVisible();
  await expect(
    page.getByText(`${window.start} to ${window.end}`, { exact: true }),
  ).toBeVisible();
  for (const format of ["CSV", "JSON", "XLSX"])
    await page.getByRole("checkbox", { name: format, exact: true }).check();
  await presentation(page);
  await capture(page, testInfo.outputPath("premium-report-selection.png"));
  await page
    .getByRole("button", { name: "Create risk report", exact: true })
    .click();
  await expect(page).toHaveURL(/[?&]report=[0-9a-f-]{36}/);
  const reportId = new URL(page.url()).searchParams.get("report")!;
  const statusUrl = `${host}/api/v2/report-jobs/${reportId}`;
  const admittedResponse = await request.get(statusUrl, {
    params: { account_id: account },
  });
  expect(admittedResponse.status()).toBe(200);
  const admitted = PremiumReportJobStatusSchema.parse(
    await admittedResponse.json(),
  );
  expect(["queued", "running", "succeeded"]).toContain(admitted.state);
  expect(admitted.context?.profile_version).toBe("report_sections_v2");
  expect(admitted.context?.pins).toEqual(
    expect.arrayContaining([
      expect.objectContaining({
        family: "risk",
        role: "input",
        subject_id: runId,
        content_digest: risk.input_digest,
      }),
      expect.objectContaining({
        family: "risk",
        role: "result",
        parent_id: runId,
        content_digest: canonical.content_digest,
      }),
    ]),
  );
  await expect(page.getByText("Job succeeded", { exact: true })).toBeVisible({
    timeout: 150_000,
  });
  await expect(
    page.getByRole("heading", { name: "Manifest and provenance", exact: true }),
  ).toBeVisible();
  const completedResponse = await request.get(statusUrl, {
    params: { account_id: account },
  });
  expect(completedResponse.status()).toBe(200);
  const completed = PremiumReportJobStatusSchema.parse(
    await completedResponse.json(),
  );
  expect(completed.state).toBe("succeeded");
  expect(completed.artifacts.map((artifact) => artifact.format).sort()).toEqual(
    ["csv", "json", "pdf", "xlsx"],
  );
  const manifestResponse = await request.get(
    `${host}/api/v2/reports/${reportId}`,
    { params: { account_id: account } },
  );
  expect(manifestResponse.status()).toBe(200);
  const manifestBytes = await manifestResponse.body();
  expect(createHash("sha256").update(manifestBytes).digest("hex")).toBe(
    completed.manifest_digest,
  );
  const manifest = PremiumReportManifestSchema.parse(
    JSON.parse(manifestBytes.toString("utf8")),
  );
  expect(manifest.document.document_schema_version).toBe("2.0.0");
  expect(manifest.document.selection).toMatchObject({
    risk_run_id: runId,
    snapshot_id: risk.portfolio_snapshot_id,
    account_id: account,
    start_date: window.start,
    end_date: window.end,
    reporting_currency: canonical.historical_context.window.reporting_currency,
    source_cutoff_at: canonical.historical_context.window.source_cutoff_at,
  });
  for (const artifact of completed.artifacts) {
    const bytes = await download(page, artifact);
    if (artifact.format === "json") {
      const document = documentSchema.parse(JSON.parse(bytes.toString("utf8")));
      expect(document.manifest).toEqual(manifest);
      const observed = document.tables.find(
        (table) => table.table === "risk_observed_v1",
      )!.rows[0];
      // These independently named schema positions bind exact published values; no browser arithmetic.
      expect(observed.cells[6].value).toBe(
        canonical.observed.volatility_annualized.value,
      );
      expect(observed.cells[7].value).toBe(
        canonical.observed.downside_annualized.value,
      );
      expect(observed.cells[11].value).toBe(canonical.maximum_drawdown.value);
      expect(observed.cells[8].value).toBe(canonical.observed.beta.value);
      expect(observed.cells[8].state).toBe("unavailable");
      expect(
        document.manifest.notes.find(
          (note) => note.key === observed.cells[8].reason_key,
        )?.code,
      ).toBe(canonical.observed.beta.reason);
      const basis = document.tables.find(
        (table) => table.table === "risk_basis_v1",
      )!.rows[0];
      expect(basis.cells[0].value).toBe(runId);
      expect(basis.cells[2].value).toBe(canonical.content_digest);
      expect(
        document.tables.find((table) => table.table === "risk_intervals_v1")!
          .rows.length,
      ).toBe(canonical.observed.requested_observations);
      expect(
        document.tables.find(
          (table) => table.table === "historical_use_consumers",
        )!.rows.length,
      ).toBeGreaterThan(0);
    } else if (artifact.format === "pdf")
      expect(bytes.subarray(0, 5).toString()).toBe("%PDF-");
    else if (artifact.format === "xlsx")
      expect(bytes.subarray(0, 2).toString()).toBe("PK");
    else
      expect(bytes.toString("utf8").split("\r\n")[0]).toContain('"column_key"');
  }
  const legacy = ReportPageSchema.parse(
    await (
      await request.get(`${host}/api/v1/reports`, {
        params: { account_id: account },
      })
    ).json(),
  );
  expect(legacy.items.some((item) => item.job_id === reportId)).toBe(false);
  const premium = PremiumReportPageSchema.parse(
    await (
      await request.get(`${host}/api/v2/reports`, {
        params: { account_id: account },
      })
    ).json(),
  );
  expect(premium.items.some((item) => item.job_id === reportId)).toBe(true);
  expect(
    (
      await request.get(`${host}/api/v1/report-jobs/${reportId}`, {
        params: { account_id: account },
      })
    ).status(),
  ).toBe(404);
  await page.reload();
  await expect(page.getByText("Job succeeded", { exact: true })).toBeVisible();
  await presentation(page);
  await capture(page, testInfo.outputPath("premium-report-completed.png"));
  await page
    .getByRole("combobox", { name: "Portfolio account", exact: true })
    .selectOption(baseline);
  await expect(page).toHaveURL(`/reports/premium?account=${baseline}`);
  await expect(
    page.getByRole("heading", { name: "Private artifacts", exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("heading", {
      name: "Report from Browser monthly risk report",
      exact: true,
    }),
  ).toHaveCount(0);
  await page.goBack();
  await expect(page.getByText("Job succeeded", { exact: true })).toBeVisible();
  await page.goto(
    `/reports/premium?${new URLSearchParams({ account: baseline, report: reportId })}`,
  );
  await expect(
    page.getByText("Selected report unavailable", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Private artifacts", exact: true }),
  ).toHaveCount(0);
  expect(errors).toEqual([]);
});
