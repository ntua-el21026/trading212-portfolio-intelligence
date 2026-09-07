import { tmpdir } from "node:os";
import { join } from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { BenchmarkDefinitionDetailSchema } from "@trading212/api-contracts";

const api = "http://127.0.0.1:18000/api/v1";
const account = "f0f5c66e-b128-59b2-a620-83bc8faa4a57";

test.beforeEach(async ({ page, request }) => {
  page.setDefaultTimeout(15_000);
  await page.goto("/sign-in");
  await page.getByRole("button", { name: "Start local session" }).click();
  await expect(page).toHaveURL("http://127.0.0.1:3001/");
  expect((await request.post(`${api}/auth/local-session`)).status()).toBe(201);
});

async function presentation(page: Page) {
  expect(
    await page.evaluate(
      () =>
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
    ),
  ).toBeLessThanOrEqual(1);
  expect(
    await page.evaluate(() => {
      const failures: string[] = [];
      for (const table of document.querySelectorAll("table"))
        if (
          !table.querySelector("caption") &&
          !table.getAttribute("aria-label")
        )
          failures.push("unnamed table");
      for (const control of document.querySelectorAll("input,select,textarea"))
        if (
          control.getAttribute("type") !== "hidden" &&
          !control.closest("label") &&
          !control.getAttribute("aria-label")
        )
          failures.push("unlabelled control");
      if (
        document.querySelectorAll("main").length !== 1 ||
        document.querySelectorAll("h1").length !== 1
      )
        failures.push("landmark count");
      return failures;
    }),
  ).toEqual([]);
}

test("source catalog exposes synthetic gaps, license policy and resumable exact FX observations", async ({
  page,
  request,
}, testInfo) => {
  test.setTimeout(90_000);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto(`/sources?account=${account}&kind=market&basis=raw_close`);
  await expect(
    page.getByRole("heading", { name: "Market price series" }),
  ).toBeVisible();
  await expect(page.getByText("19 / 20", { exact: true })).toBeVisible();
  await expect(page.getByText(/External reference provider/)).toBeVisible();
  await page.getByText(/External reference provider/).click();
  await expect(
    page.getByText("None configured", { exact: false }),
  ).toBeVisible();
  await presentation(page);
  await page.screenshot({
    path: join(tmpdir(), `t212-p2-03-${testInfo.project.name}-sources.png`),
    fullPage: false,
  });
  await page.getByRole("link", { name: "SYNTHETIC_EQ_1", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Immutable observations" }),
  ).toBeVisible();
  await expect(
    page.getByRole("row").filter({ hasText: "2026-08-12" }),
  ).toContainText("Unavailable");
  await expect(
    page.getByText("Synthetic reference data; no market-data provider.", {
      exact: true,
    }),
  ).toBeVisible();
  await presentation(page);
  const response = await request.get(`${api}/accounts/${account}/fx-sources`);
  expect(response.status()).toBe(200);
  const snapshot = (await response.json()).pairs.items[0].latest_snapshot.id;
  const first = await request.get(
    `${api}/fx-snapshots/${snapshot}/observations`,
    { params: { limit: 25, account_id: account } },
  );
  expect(first.status()).toBe(200);
  const canonical = await first.json();
  expect(canonical.total).toBe(40);
  await page.goto(`/sources/snapshots/fx/${snapshot}?account=${account}`);
  await expect(
    page
      .getByRole("table", { name: "Immutable source observations" })
      .locator("tbody tr"),
  ).toHaveCount(25);
  await expect(
    page.getByRole("table").locator("tbody tr").first(),
  ).toContainText(canonical.items[0].rate);
  await page.getByRole("link", { name: "Next page" }).click();
  await expect(page).toHaveURL(/cursor=/);
  await expect(page.getByRole("table").locator("tbody tr")).toHaveCount(15);
  await presentation(page);
  expect(errors).toEqual([]);
});

test("benchmark editor validates exact weights and retains published versions after archive", async ({
  page,
  request,
}, testInfo) => {
  test.setTimeout(120_000);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto(`/sources?account=${account}&kind=definitions`);
  await page
    .getByRole("textbox", { name: "Name", exact: true })
    .fill(`Browser benchmark ${testInfo.project.name}`);
  await page.getByRole("textbox", { name: "Weight 1", exact: true }).fill("2");
  await page
    .getByRole("button", { name: "Create benchmark", exact: true })
    .click();
  await expect(
    page.getByRole("alert").filter({ hasText: "Review" }),
  ).toBeVisible();
  await expect(
    page.getByRole("textbox", { name: "Weight 1", exact: true }),
  ).toHaveValue("2");
  await page.getByRole("textbox", { name: "Weight 1", exact: true }).fill("1");
  await page
    .getByRole("button", { name: "Create benchmark", exact: true })
    .click();
  await expect(page).toHaveURL(/\/sources\/benchmarks\/[0-9a-f-]{36}/);
  await expect(
    page.getByRole("heading", { name: "Version 1 composition" }),
  ).toBeVisible();
  const id = new URL(page.url()).pathname.split("/").at(-1)!;
  const first = await request.get(`${api}/benchmark-definitions/${id}`);
  expect(first.status()).toBe(200);
  const original = (await first.json()).selected_version;
  expect(original.content.components[0].weight).toBe("1");
  await page
    .getByRole("combobox", { name: "Rebalancing convention" })
    .selectOption("daily_rebalanced");
  await page
    .getByRole("button", { name: "Publish benchmark version", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Version 2 composition" }),
  ).toBeVisible();
  await presentation(page);
  await page.screenshot({
    path: join(tmpdir(), `t212-p2-03-${testInfo.project.name}-benchmark.png`),
    fullPage: false,
  });
  const session = await request.post(`${api}/auth/local-session`);
  expect(session.status()).toBe(201);
  const csrf = (await session.json()).csrf_token as string;
  let latest = BenchmarkDefinitionDetailSchema.parse(
    await (await request.get(`${api}/benchmark-definitions/${id}`)).json(),
  );
  for (let number = 3; number <= 26; number += 1) {
    const response = await request.post(
      `${api}/benchmark-definitions/${id}/versions`,
      {
        headers: {
          Origin: "http://127.0.0.1:3001",
          "X-CSRF-Token": csrf,
          "X-Idempotency-Key": `browser-source-${testInfo.project.name}-${number}`,
          "If-Match": latest.definition.revision_etag,
        },
        data: { content: latest.selected_version!.content },
      },
    );
    expect(response.status()).toBe(201);
    latest = BenchmarkDefinitionDetailSchema.parse(await response.json());
  }
  // A plain detail URL binds no explicit selection into its collection cursor.
  await page.goto(`/sources/benchmarks/${id}?account=${account}`);
  await expect(
    page.getByRole("heading", { name: "Version 26 composition" }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Next page" }).click();
  await expect(page).toHaveURL(/cursor=/);
  expect(new URL(page.url()).searchParams.has("version")).toBe(false);
  await page.getByRole("link", { name: "Version 1", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Version 1 composition" }),
  ).toBeVisible();
  await page.getByText("Content identity", { exact: true }).click();
  await expect(
    page.getByText(original.content_digest, { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Archive benchmark", exact: true })
    .click();
  await expect(page.getByText(/History remains available/)).toBeVisible();
  const retained = await request.get(`${api}/benchmark-definitions/${id}`, {
    params: { selected_version_id: original.id },
  });
  expect(retained.status()).toBe(200);
  const detail = await retained.json();
  expect(detail.definition.state).toBe("archived");
  expect(detail.versions.total).toBe(26);
  expect(detail.selected_version).toEqual(original);
  await presentation(page);
  expect(errors).toEqual([]);
});
