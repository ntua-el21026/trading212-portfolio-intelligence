import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.goto("/sign-in");
  await page.getByRole("button", { name: "Enter demo portfolio" }).click();
});

test("stale, partial, empty, unavailable, and unreconciled states are explicit", async ({
  page,
}) => {
  await page.goto("/?state=stale");
  await expect(page.getByText("Stale portfolio data")).toBeVisible();

  await page.goto("/quality?state=partial");
  await expect(page.getByText("Partial portfolio data")).toBeVisible();
  await expect(page.getByText(/historical_dividends/i).first()).toBeVisible();
  await expect(page.getByText("Unavailable", { exact: true })).toBeVisible();

  await page.goto("/holdings?state=empty");
  await expect(
    page.getByRole("heading", { name: "No holdings available" }),
  ).toBeVisible();

  await page.goto("/quality?state=unreconciled");
  await expect(page.getByText("Unreconciled portfolio data")).toBeVisible();
  await expect(page.getByText(/observed cash differs/i)).toBeVisible();
});

test("API failures render a safe recovery state", async ({ page }) => {
  await page.goto("/?state=error");
  await expect(
    page.getByRole("heading", { name: "Portfolio data unavailable" }),
  ).toBeVisible();
  await expect(page.getByText(/your data was not changed/i)).toBeVisible();
});
