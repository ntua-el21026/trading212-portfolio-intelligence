import { expect, test } from "@playwright/test";
import {
  RiskRunResponseSchema,
  RiskVersionResponseSchema,
} from "@trading212/api-contracts";
import { keyboardClearance } from "./accessibility";
const api = "http://127.0.0.1:18000/api/v1";
const account = "9a85cdf8-eac9-57c7-be38-e500e4b9edb4";
const baseline = "f0f5c66e-b128-59b2-a620-83bc8faa4a57";
const window = {
  account,
  start: "2025-01-01",
  end: "2025-12-31",
  cutoff: "2026-09-07T12:00:00.123456Z",
  currency: "EUR",
};
function href(extra: Record<string, string> = {}) {
  return `/risk?${new URLSearchParams({ ...window, ...extra })}`;
}
test("owned risk definition, immutable revision, isolated execution and canonical result", async ({
  page,
  request,
}, testInfo) => {
  test.setTimeout(240000);
  page.setDefaultTimeout(30000);
  const width = testInfo.project.name.includes("mobile")
    ? 360
    : testInfo.project.name.includes("tablet")
      ? 768
      : 1440;
  await page.setViewportSize({ width, height: 900 });

  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error" || message.type() === "warning")
      errors.push(message.text());
  });
  await page.goto("/sign-in");
  await page.getByRole("button", { name: "Start local session" }).click();
  await expect(page).toHaveURL("http://127.0.0.1:3001/");
  expect((await request.post(`${api}/auth/local-session`)).status()).toBe(201);
  await page.goto(href({ view: "definitions" }));
  await expect(
    page.getByRole("heading", { name: "Risk", exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () =>
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
    ),
  ).toBeLessThanOrEqual(1);
  await page.screenshot({
    path: testInfo.outputPath("risk-definition.png"),
    fullPage: true,
  });
  await page
    .getByLabel("Name", { exact: true })
    .fill("Browser risk assumptions");
  await page
    .getByLabel("Reporting calendar")
    .selectOption({ label: "synthetic-history-annual · daily-v1" });
  await page.getByLabel("Annual risk-free rate").fill("0.012345678901234567");
  await page
    .getByRole("button", { name: "Create risk definition", exact: true })
    .click();
  await expect(page).toHaveURL(/definition=[0-9a-f-]+/);
  const first = new URL(page.url()).searchParams;
  const firstVersion = RiskVersionResponseSchema.parse(
    await (
      await request.get(
        `${api}/risk-definition-versions/${first.get("version")}`,
      )
    ).json(),
  );
  expect(firstVersion.content.annual_risk_free).toBe("0.012345678901234567");
  await page.getByLabel("Name", { exact: true }).fill("Revised browser risk");
  await page.getByRole("button", { name: "Save new risk version" }).click();
  await expect(
    page.getByText("New immutable version, based on version 2"),
  ).toBeVisible();
  const current = new URL(page.url()).searchParams;
  expect(current.get("version")).not.toBe(first.get("version"));
  expect(
    RiskVersionResponseSchema.parse(
      await (
        await request.get(
          `${api}/risk-definition-versions/${first.get("version")}`,
        )
      ).json(),
    ),
  ).toEqual(firstVersion);
  await page.getByRole("link", { name: "New analysis", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Prepared immutable inputs" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Create risk run", exact: true }),
  ).toBeEnabled();
  expect(
    await page.evaluate(
      () =>
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
    ),
  ).toBeLessThanOrEqual(1);
  await page.screenshot({
    path: testInfo.outputPath("risk-inputs.png"),
    fullPage: true,
  });
  await page
    .getByRole("button", { name: "Create risk run", exact: true })
    .click();
  await expect(page).toHaveURL(/view=result/);
  await expect(
    page.getByRole("heading", { name: "Observed historical estimates" }),
  ).toBeVisible({ timeout: 120000 });
  const runId = new URL(page.url()).searchParams.get("run");
  const resultResponse = await request.get(`${api}/risk-runs/${runId}`);
  expect(resultResponse.status()).toBe(200);
  const run = RiskRunResponseSchema.parse(await resultResponse.json());
  expect(run.state).toBe("succeeded");
  expect(run.result).not.toBeNull();
  expect(run.definition_version_id).toBe(current.get("version"));
  const volatility = run.result!.observed.volatility_annualized;
  expect(volatility.value).not.toBeNull();
  await expect(
    page.getByTitle(volatility.value!, { exact: true }).first(),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Asset matrix" }),
  ).toBeVisible();
  await expect(page.getByText("No asset universe selected")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Cancel risk run" }),
  ).toHaveCount(0);
  await page.getByLabel("Matrix measure").selectOption("covariance_periodic");
  await expect(
    page.getByText(/No covered issuer concentration estimate is available/),
  ).toBeVisible();
  expect(
    await page
      .locator("table")
      .evaluateAll(
        (tables) =>
          tables.filter(
            (table) =>
              !table.querySelector("caption") &&
              !table.getAttribute("aria-label"),
          ).length,
      ),
  ).toBe(0);
  await keyboardClearance(page);
  expect(
    await page.evaluate(
      () =>
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
    ),
  ).toBeLessThanOrEqual(1);
  await expect(page).toHaveTitle("Portfolio Intelligence");
  await expect(
    page.locator("nextjs-portal").getByText(/Runtime Error|Build Error/),
  ).toHaveCount(0);
  await page.screenshot({
    path: testInfo.outputPath("risk-result.png"),
    fullPage: true,
  });
  await page
    .getByRole("heading", { name: "Risk", exact: true })
    .scrollIntoViewIfNeeded();
  await page.screenshot({ path: testInfo.outputPath("risk-overview.png") });
  await page
    .locator(".historical-figure")
    .screenshot({ path: testInfo.outputPath("risk-chart.png") });
  const selectedAccount = page.getByRole("combobox", {
    name: "Portfolio account",
    exact: true,
  });
  await selectedAccount.selectOption(baseline);
  await expect(page).not.toHaveURL(/run=/);
  await expect(
    page.getByRole("heading", { name: "Observed historical estimates" }),
  ).toHaveCount(0);
  await page.goBack();
  await expect(
    page.getByRole("heading", { name: "Observed historical estimates" }),
  ).toBeVisible();
  await page.goto(
    `/risk?${new URLSearchParams({ ...window, account: baseline, run: runId! })}`,
  );
  await expect(
    page.getByText(
      "This risk resource is unavailable for the selected account.",
    ),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Observed historical estimates" }),
  ).toHaveCount(0);
  await page.goto(href({ view: "result", run: "../private-canary" }));
  await expect(page.getByText("Invalid risk filters")).toBeVisible();
  await expect(page.getByText("private-canary", { exact: false })).toHaveCount(
    0,
  );
  expect(errors).toEqual([]);
});
