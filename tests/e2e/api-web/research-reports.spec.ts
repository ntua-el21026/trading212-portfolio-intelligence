import { execFile } from "node:child_process";
import { createHash } from "node:crypto";
import { chmod, mkdir, readFile, writeFile } from "node:fs/promises";
import { delimiter, join, resolve, sep } from "node:path";
import { promisify } from "node:util";
import {
  expect,
  test,
  type APIRequestContext,
  type Page,
  type TestInfo,
} from "@playwright/test";
import { z } from "zod";
import {
  PremiumReportDocumentHeaderV3Schema,
  PremiumReportJobStatusV3Schema,
  PremiumReportManifestV3Schema,
  ResearchItemViewSchema,
  ReportRowSchema,
  type ReportArtifactMetadata,
} from "@trading212/api-contracts";
import { keyboardClearance } from "./accessibility";

const host = "http://127.0.0.1:18000";
const profile = "report_sections_v3";
const baseline = "f0f5c66e-b128-59b2-a620-83bc8faa4a57";
const markers = [
  "A2_PRIVATE_SOURCE_PROSE",
  "A2_PRIVATE_OWNER_PROSE",
  "A2_FOREIGN_ACCOUNT_NOTE_PROSE",
];
const fixtureSchema = z.strictObject({
  account_id: z.string().uuid(),
  item_id: z.string().uuid(),
  absent_item_id: z.string().uuid(),
  note_revision_ids: z.array(z.string().uuid()).length(64),
  missing_note_revision_id: z.string().uuid(),
  foreign_note_id: z.string().uuid(),
  review_id: z.string().uuid(),
  submissions: z
    .array(
      z.strictObject({
        status: z.number().int(),
        key_digest: z.string().length(64),
      }),
    )
    .max(128),
});
const documentSchema = z.strictObject({
  schema: z.literal("report_document_json_v1"),
  manifest: PremiumReportManifestV3Schema,
  header: PremiumReportDocumentHeaderV3Schema,
  tables: z.array(
    z.strictObject({ table: z.string(), rows: z.array(ReportRowSchema) }),
  ),
});
type Fixture = z.infer<typeof fixtureSchema>;
type Document = z.infer<typeof documentSchema>;
const researchTables = [
  "research_basis_v1",
  "research_event_v1",
  "research_portfolio_v1",
  "research_notes_v1",
  "research_review_v1",
  "research_citations_v1",
  "research_sources_v1",
  "research_source_licenses_v1",
  "research_source_grants_v1",
  "research_portfolio_members_v1",
  "research_warnings_v1",
  "research_note_citations_v1",
  "research_xray_pin_v1",
];

function selection(
  fixture: Fixture,
  notes: string[] = [],
  review?: string,
  item = fixture.item_id,
) {
  return `/reports/premium?${new URLSearchParams({
    profile,
    family: "research",
    account: fixture.account_id,
    item,
    ...(notes.length ? { note_revisions: notes.join(",") } : {}),
    ...(review ? { review } : {}),
  })}`;
}
function rows(document: Document, table: string) {
  const found = document.tables.find((value) => value.table === table);
  expect(found, `Complete canonical ${table}`).toBeDefined();
  return found!.rows;
}
async function control(request: APIRequestContext, action: string) {
  const response = await request.post(
    `${host}/__e2e__/research-reports/${action}`,
  );
  expect(response.status()).toBe(200);
  expect(await response.json()).toEqual({ action });
}
async function presentation(page: Page, info: TestInfo, name: string) {
  await keyboardClearance(page);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth - window.innerWidth,
    ),
  ).toBeLessThanOrEqual(1);
  await expect(page.getByRole("main")).toHaveCount(1);
  await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
  for (const table of await page.getByRole("table").all())
    await expect(table).toHaveAccessibleName(/\S/);
  await page.evaluate(() => {
    if (document.activeElement instanceof HTMLElement)
      document.activeElement.blur();
    window.scrollTo(0, 0);
  });
  await page.screenshot({
    path: info.outputPath(`research-reports-${name}.png`),
    fullPage: true,
  });
}
async function download(
  page: Page,
  artifact: ReportArtifactMetadata,
  directory?: string,
) {
  const event = page.waitForEvent("download");
  await page
    .getByRole("button", {
      name: `Download ${artifact.format.toUpperCase()}`,
      exact: true,
    })
    .click();
  const saved = await event;
  try {
    const path = await saved.path();
    expect(path).not.toBeNull();
    const bytes = await readFile(path!);
    // Persist the actual bytes before parity assertions so a failed check retains its input.
    if (directory)
      await writeFile(join(directory, `report.${artifact.format}`), bytes, {
        mode: 0o600,
        flag: "wx",
      });
    expect(saved.suggestedFilename()).toBe(
      `portfolio-artifact-${artifact.artifact_id}.${artifact.format}`,
    );
    expect(bytes.length).toBe(artifact.byte_length);
    expect(createHash("sha256").update(bytes).digest("hex")).toBe(
      artifact.content_digest,
    );
    return bytes;
  } finally {
    await saved.delete();
  }
}
async function complete(
  page: Page,
  request: APIRequestContext,
  fixture: Fixture,
) {
  const action = page.waitForResponse(
    (value) =>
      value.request().method() === "POST" &&
      new URL(value.url()).pathname === "/reports/premium",
  );
  await page
    .getByRole("button", { name: "Create research report", exact: true })
    .click();
  expect((await action).status()).toBe(200);
  await expect(page).toHaveURL(/[?&]report=[0-9a-f-]{36}/, { timeout: 30_000 });
  const id = new URL(page.url()).searchParams.get("report")!;
  const params = { profile, account_id: fixture.account_id };
  const admitted = await request.get(`${host}/api/v2/report-jobs/${id}`, {
    params,
  });
  expect(admitted.status()).toBe(200);
  expect(["queued", "running", "succeeded"]).toContain(
    PremiumReportJobStatusV3Schema.parse(await admitted.json()).state,
  );
  await expect(page.getByText("Job succeeded", { exact: true })).toBeVisible({
    timeout: 150_000,
  });
  const statusResponse = await request.get(`${host}/api/v2/report-jobs/${id}`, {
    params,
  });
  expect(statusResponse.status()).toBe(200);
  const job = PremiumReportJobStatusV3Schema.parse(await statusResponse.json());
  expect(job.state).toBe("succeeded");
  const response = await request.get(`${host}/api/v2/reports/${id}`, {
    params,
  });
  expect(response.status()).toBe(200);
  expect(response.headers()["cache-control"]).toContain("private");
  expect(response.headers()["cache-control"]).toContain("no-store");
  const bytes = await response.body();
  expect(createHash("sha256").update(bytes).digest("hex")).toBe(
    job.manifest_digest,
  );
  return {
    id,
    job,
    bytes,
    manifest: PremiumReportManifestV3Schema.parse(
      JSON.parse(bytes.toString("utf8")),
    ),
  };
}
async function jsonOnly(page: Page) {
  await page.getByRole("checkbox", { name: "PDF", exact: true }).uncheck();
  await page.getByRole("checkbox", { name: "JSON", exact: true }).check();
}

test("real research reports preserve exact revisions through worker completion, four downloads and private denials", async ({
  page,
  request,
  context,
}, info) => {
  test.setTimeout(600_000);
  page.setDefaultTimeout(30_000);
  await page.setViewportSize({
    width: info.project.name.includes("mobile")
      ? 360
      : info.project.name.includes("tablet")
        ? 768
        : 1440,
    height: info.project.name.includes("mobile")
      ? 800
      : info.project.name.includes("tablet")
        ? 1024
        : 900,
  });
  const errors: string[] = [],
    urls: string[] = [],
    actionKeys: string[] = [];
  const assets: Promise<string>[] = [];
  let offline = false;
  let expectedDenialUrl: string | null = null;
  let denialConsoleErrors = 0;
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    // Chromium reports the intentional denied-download fetch as a console error.
    // Only that exact URL/status/message is expected; all other errors still fail.
    if (
      message.type() === "error" &&
      message.text() ===
        "Failed to load resource: the server responded with a status of 403 (Forbidden)" &&
      message.location().url === expectedDenialUrl
    ) {
      denialConsoleErrors += 1;
      return;
    }
    if (
      ["error", "warning"].includes(message.type()) &&
      !(offline && message.text().includes("ERR_INTERNET_DISCONNECTED"))
    )
      errors.push(message.text());
  });
  page.on("request", (value) => {
    urls.push(value.url());
    if (
      value.method() === "POST" &&
      new URL(value.url()).pathname === "/reports/premium"
    ) {
      const body = value.postData() ?? "";
      for (const marker of markers) expect(body).not.toContain(marker);
      const key = body.match(/research-report:[0-9a-f-]{36}/)?.[0];
      if (key) actionKeys.push(key);
    }
  });
  page.on("response", (value) => {
    if (
      new URL(value.url()).pathname.startsWith("/_next/static/") &&
      value.ok()
    )
      assets.push(value.text());
  });
  await page.goto("/sign-in");
  await page
    .getByRole("button", { name: "Start local session", exact: true })
    .click();
  await expect(page).toHaveURL("http://127.0.0.1:3001/");
  const authentication = await request.post(
    `${host}/api/v1/auth/local-session`,
  );
  expect(authentication.status()).toBe(201);
  const session = z
    .object({ csrf_token: z.string().min(20) })
    .parse(await authentication.json());
  const fixtureResponse = await request.get(`${host}/__e2e__/research-reports`);
  expect(fixtureResponse.status()).toBe(200);
  const fixture = fixtureSchema.parse(await fixtureResponse.json());
  const itemResponse = await request.get(
    `${host}/api/v1/research/items/${fixture.item_id}`,
  );
  expect(itemResponse.status()).toBe(200);
  const item = ResearchItemViewSchema.parse(await itemResponse.json());
  const source = item.source.facts;
  expect(source.kind).toBe("news");
  expect(item.portfolio.pin.source_cutoff_at).not.toBe(item.source_cutoff_at);
  expect(
    item.owner_revisions.some(
      (value) => value.revision_id === fixture.note_revision_ids[63],
    ),
  ).toBe(true);
  const headers = {
    origin: "http://127.0.0.1:3001",
    "x-csrf-token": session.csrf_token,
    "x-idempotency-key": "browser-research-exact-retry",
  };
  const body = {
    profile_version: profile,
    account_id: fixture.account_id,
    snapshot_id: item.portfolio.pin.snapshot_id,
    reporting_currency: item.portfolio.pin.reporting_currency,
    source_cutoff_at: item.source_cutoff_at,
    start_date: item.portfolio.pin.valuation_at.slice(0, 10),
    end_date: item.portfolio.pin.valuation_at.slice(0, 10),
    report_type: "portfolio_summary",
    sections: ["overview", "allocation", "quality", "research"],
    formats: ["json"],
    ttl_days: 7,
    premium_run: {
      family: "research",
      item_id: fixture.item_id,
      note_revision_ids: [] as string[],
    },
  };
  const post = (payload: object, selectedHeaders = headers) =>
    request.post(`${host}/api/v2/report-jobs?profile=${profile}`, {
      data: payload,
      headers: selectedHeaders,
    });
  const csrfDenied = await post(body, {
    ...headers,
    "x-csrf-token": "invalid-csrf",
  });
  expect(csrfDenied.status()).toBe(401);
  const overBound = await post({
    ...body,
    premium_run: {
      ...body.premium_run,
      note_revision_ids: [
        ...fixture.note_revision_ids,
        fixture.missing_note_revision_id,
      ],
    },
  });
  expect(overBound.status()).toBe(422);
  const foreign = await post({
    ...body,
    premium_run: {
      ...body.premium_run,
      note_revision_ids: [fixture.foreign_note_id],
    },
  });
  expect(foreign.status()).toBe(403);
  for (const marker of markers)
    expect(await foreign.text()).not.toContain(marker);

  await page.goto(
    `/research?${new URLSearchParams({ account: fixture.account_id, view: "item", item: fixture.item_id })}`,
  );
  await expect(page.getByTestId("research-portfolio-facts")).toContainText(
    "560 EUR",
  );
  expect(
    await page.evaluate(() => Object.hasOwn(window, "researchReportInjected")),
  ).toBe(false);
  await page
    .getByRole("link", {
      name: "Create a report from this retained research item",
      exact: true,
    })
    .click();
  await expect(
    page.getByRole("heading", { name: "Research reports", exact: true }),
  ).toBeVisible();
  const notesInput = page.getByLabel(
    "Exact owner note revision IDs (optional)",
  );
  const reviewInput = page.getByLabel(
    "Exact review acknowledgment ID (optional)",
  );
  await expect(notesInput).toHaveValue("");
  await expect(reviewInput).toHaveValue("");
  await expect(
    page.getByLabel("Create research report", { exact: true }),
  ).toContainText(item.source_cutoff_at);
  await expect(
    page.getByLabel("Create research report", { exact: true }),
  ).toContainText(item.portfolio.pin.source_cutoff_at);
  await notesInput.fill(fixture.note_revision_ids[0]);
  await reviewInput.fill(fixture.review_id);
  for (const format of ["CSV", "JSON", "XLSX"])
    await page.getByRole("checkbox", { name: format, exact: true }).check();
  await presentation(page, info, "historical-selection");
  offline = true;
  await context.setOffline(true);
  await page
    .getByRole("button", { name: "Create research report", exact: true })
    .click();
  await expect(
    page
      .getByLabel("Create research report", { exact: true })
      .getByRole("alert"),
  ).toContainText("Your exact choices and retry identity are preserved");
  await expect(notesInput).toHaveValue(fixture.note_revision_ids[0]);
  await expect(reviewInput).toHaveValue(fixture.review_id);
  await context.setOffline(false);
  offline = false;
  const completed = await complete(page, request, fixture);
  expect(actionKeys.length).toBeGreaterThanOrEqual(2);
  expect(actionKeys.at(-1)).toBe(actionKeys.at(-2));
  expect(completed.job.artifacts.map((value) => value.format).sort()).toEqual([
    "csv",
    "json",
    "pdf",
    "xlsx",
  ]);
  expect(completed.manifest.document.selection.premium_run).toEqual({
    family: "research",
    item_id: fixture.item_id,
    note_revision_ids: [fixture.note_revision_ids[0]],
    review_acknowledgment_id: fixture.review_id,
  });
  const binding = completed.manifest.document.premium_binding;
  expect(binding.family).toBe("research");
  if (binding.family !== "research")
    throw new Error("An actual research binding is required.");
  expect(binding).toMatchObject({
    item_id: fixture.item_id,
    event_revision_id: item.source.revision_id,
    event_revision_digest: item.source.content_digest,
    source_cutoff_at: item.source_cutoff_at,
    xray_pin: item.portfolio.pin,
    note_revisions: [
      expect.objectContaining({ revision_id: fixture.note_revision_ids[0] }),
    ],
    review_acknowledgment: expect.objectContaining({
      acknowledgment_id: fixture.review_id,
    }),
  });
  expect(binding).not.toHaveProperty("run_id");
  expect(Date.parse(completed.job.expires_at)).toBeLessThanOrEqual(
    Date.parse(item.source.expires_at),
  );
  const root = resolve(process.cwd(), "../..");
  const directory = info.outputPath("downloaded-artifacts");
  expect(directory === root || directory.startsWith(root + sep)).toBe(false);
  await mkdir(directory, { recursive: true, mode: 0o700 });
  await chmod(directory, 0o700);
  let inspectionState = "not_invoked";
  let inspectionLog = "Artifact inspector was not invoked.\n";
  try {
    await writeFile(join(directory, "manifest.json"), completed.bytes, {
      mode: 0o600,
      flag: "wx",
    });
    for (const artifact of completed.job.artifacts)
      await download(page, artifact, directory);
    const document = documentSchema.parse(
      JSON.parse(await readFile(join(directory, "report.json"), "utf8")),
    );
    expect(document.manifest).toEqual(completed.manifest);
    expect(
      document.tables
        .filter((value) => value.table.startsWith("research_"))
        .map((value) => value.table)
        .sort(),
    ).toEqual([...researchTables].sort());
    expect(rows(document, "research_notes_v1")).toHaveLength(1);
    expect(JSON.stringify(rows(document, "research_notes_v1"))).toContain(
      "Original exact historical thesis.",
    );
    expect(JSON.stringify(rows(document, "research_notes_v1"))).not.toContain(
      "Later explicit owner revision 64.",
    );
    expect(rows(document, "research_review_v1")).toHaveLength(1);
    const inspected = await promisify(execFile)(
      join(root, ".venv/bin/python"),
      ["tests/e2e/api-web/research_report_artifacts.py", directory],
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
    ).then(
      (result) => {
        inspectionState = "completed";
        inspectionLog = `${result.stdout}\n${result.stderr}`;
        return result;
      },
      (error: unknown) => {
        inspectionState = "failed";
        const output = error as { stdout?: string; stderr?: string };
        inspectionLog = `${output.stdout ?? ""}\n${output.stderr ?? ""}`;
        throw error;
      },
    );
    expect(inspected.stderr).toBe("");
    expect(inspected.stdout.trim()).toBe(
      "Verified research browser four-format bytes, fixed tables and exact named values.",
    );
  } finally {
    await writeFile(join(directory, "artifact-inspection.log"), inspectionLog, {
      mode: 0o600,
      flag: "wx",
    });
    await writeFile(
      join(directory, "artifact-receipt.json"),
      JSON.stringify(
        {
          manifest_sha256: createHash("sha256")
            .update(completed.bytes)
            .digest("hex"),
          expected_artifacts: completed.job.artifacts,
          inspection_state: inspectionState,
          report_log_sha256: createHash("sha256")
            .update(inspectionLog)
            .digest("hex"),
        },
        null,
        2,
      ) + "\n",
      { mode: 0o600, flag: "wx" },
    );
  }
  await presentation(page, info, "completed-four-formats");

  await page.goto(selection(fixture));
  await jsonOnly(page);
  const empty = await complete(page, request, fixture);
  const emptyDocument = documentSchema.parse(
    JSON.parse((await download(page, empty.job.artifacts[0])).toString("utf8")),
  );
  expect(empty.manifest.document.selection.premium_run).toEqual({
    family: "research",
    item_id: fixture.item_id,
    note_revision_ids: [],
  });
  expect(rows(emptyDocument, "research_notes_v1")).toEqual([]);
  expect(rows(emptyDocument, "research_review_v1")).toEqual([]);

  await page.goto(selection(fixture, fixture.note_revision_ids));
  await expect(notesInput).toHaveValue(
    [...fixture.note_revision_ids].sort().join("\n"),
  );
  await jsonOnly(page);
  const boundary = await complete(page, request, fixture);
  const boundaryDocument = documentSchema.parse(
    JSON.parse(
      (await download(page, boundary.job.artifacts[0])).toString("utf8"),
    ),
  );
  expect(rows(boundaryDocument, "research_notes_v1")).toHaveLength(64);
  expect(boundary.manifest.document.selection.premium_run).toEqual({
    family: "research",
    item_id: fixture.item_id,
    note_revision_ids: [...fixture.note_revision_ids].sort(),
  });

  const retry = await post(body);
  expect(retry.status()).toBe(202);
  const original = PremiumReportJobStatusV3Schema.parse(await retry.json());
  const repeated = await post(body);
  expect(repeated.status()).toBe(202);
  expect(
    PremiumReportJobStatusV3Schema.parse(await repeated.json()).job_id,
  ).toBe(original.job_id);
  const conflict = await post({
    ...body,
    premium_run: {
      ...body.premium_run,
      note_revision_ids: [fixture.note_revision_ids[0]],
    },
  });
  expect(conflict.status()).toBe(409);
  await expect
    .poll(
      async () => {
        const response = await request.get(
          `${host}/api/v2/report-jobs/${original.job_id}`,
          { params: { profile, account_id: fixture.account_id } },
        );
        expect(response.status()).toBe(200);
        return PremiumReportJobStatusV3Schema.parse(await response.json())
          .state;
      },
      { timeout: 150_000 },
    )
    .toBe("succeeded");

  await page
    .getByRole("combobox", { name: "Portfolio account", exact: true })
    .selectOption(baseline);
  await expect(page).toHaveURL(
    `/reports/premium?account=${baseline}&profile=${profile}&family=research`,
  );
  await expect(
    page.getByRole("heading", { name: "Private artifacts", exact: true }),
  ).toHaveCount(0);
  for (const marker of markers)
    expect(await page.content()).not.toContain(marker);
  const foreignReport = await request.get(
    `${host}/api/v2/reports/${completed.id}`,
    { params: { profile, account_id: baseline } },
  );
  expect(foreignReport.status()).toBe(404);
  // The seed verified that this immutable revision has neither header nor
  // payload. Missing-record denial does not require an owner-erasure mutation.
  await page.goto(selection(fixture, [fixture.missing_note_revision_id]));
  await page
    .getByRole("button", { name: "Create research report", exact: true })
    .click();
  await expect(
    page
      .getByLabel("Create research report", { exact: true })
      .getByRole("alert"),
  ).toContainText("ACCESS_DENIED");
  await expect(notesInput).toHaveValue(fixture.missing_note_revision_id);
  expect(new URL(page.url()).searchParams.has("report")).toBe(false);

  await control(request, "revoke_report");
  await page.goto(
    selection(fixture, [fixture.note_revision_ids[0]], fixture.review_id),
  );
  await page
    .getByRole("button", { name: "Create research report", exact: true })
    .click();
  await expect(
    page
      .getByLabel("Create research report", { exact: true })
      .getByRole("alert"),
  ).toContainText("ACCESS_DENIED");
  await expect(notesInput).toHaveValue(fixture.note_revision_ids[0]);
  await expect(reviewInput).toHaveValue(fixture.review_id);
  const params = { profile, account_id: fixture.account_id };
  expect(
    (
      await request.get(`${host}/api/v2/reports/${completed.id}`, { params })
    ).status(),
  ).toBe(403);
  const downloadPath = `/api/premium-reports/${completed.id}/artifacts/${completed.job.artifacts[0].artifact_id}/download`;
  expectedDenialUrl = new URL(downloadPath, page.url()).href;
  const deniedDownload = await page.evaluate(
    async ({ path, account, selectedProfile }) => {
      const response = await fetch(path, {
        method: "POST",
        headers: { "content-type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({
          account_id: account,
          profile: selectedProfile,
        }),
        redirect: "error",
        cache: "no-store",
      });
      return {
        status: response.status,
        contentType: response.headers.get("content-type"),
        body: await response.text(),
      };
    },
    {
      path: downloadPath,
      account: fixture.account_id,
      selectedProfile: profile,
    },
  );
  expect(deniedDownload.status).toBe(403);
  expect(deniedDownload.contentType).toContain("application/json");
  for (const marker of markers)
    expect(deniedDownload.body).not.toContain(marker);
  await control(request, "expire");
  const expired = await request.get(
    `${host}/api/v2/report-jobs/${completed.id}`,
    { params },
  );
  expect(expired.status()).toBe(200);
  expect(PremiumReportJobStatusV3Schema.parse(await expired.json()).state).toBe(
    "expired",
  );
  expect(
    (
      await request.get(`${host}/api/v2/reports/${completed.id}`, { params })
    ).status(),
  ).toBe(410);
  await page.goto(`${selection(fixture)}&report=${completed.id}`);
  await expect(page.getByText("Job expired", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: /^Download / })).toHaveCount(0);
  await control(request, "revoke_write");
  expect((await post(body)).status()).toBe(403);
  const journal = fixtureSchema.parse(
    await (await request.get(`${host}/__e2e__/research-reports`)).json(),
  );
  const keyDigest = createHash("sha256")
    .update(headers["x-idempotency-key"])
    .digest("hex");
  expect(
    journal.submissions.filter(
      (value) => value.key_digest === keyDigest && value.status === 202,
    ),
  ).toHaveLength(2);
  for (const status of [202, 403, 409, 422])
    expect(journal.submissions.some((value) => value.status === status)).toBe(
      true,
    );
  for (const marker of markers) {
    expect(urls.join("\n")).not.toContain(marker);
    expect(errors.join("\n")).not.toContain(marker);
    for (const asset of await Promise.all(assets))
      expect(asset).not.toContain(marker);
  }
  expect(
    urls.some((value) => /grant|token|csrf/i.test(new URL(value).search)),
  ).toBe(false);
  expect(
    await page.evaluate(async () => {
      if (!("caches" in globalThis)) return [];
      const urls = [];
      for (const name of await caches.keys())
        for (const request of await (await caches.open(name)).keys())
          urls.push(new URL(request.url).pathname);
      return urls.filter(
        (path) =>
          path.startsWith("/research") ||
          path.startsWith("/reports") ||
          path.startsWith("/api/"),
      );
    }),
  ).toEqual([]);
  expect(denialConsoleErrors).toBeLessThanOrEqual(1);
  expect(errors).toEqual([]);
});
