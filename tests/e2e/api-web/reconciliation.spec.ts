import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.goto("/sign-in");
  await page.getByRole("button", { name: "Start local session" }).click();
  await expect(page).toHaveURL("http://127.0.0.1:3001/");
});

test("persisted quantity and cash mismatches reach the API-backed web experience", async ({
  page,
}) => {
  await page.goto("/quality");

  await expect(page.getByText("Unreconciled portfolio data")).toBeVisible();
  await expect(
    page.getByRole("row", { name: /Cash Mismatch.*999\.00 EUR/ }),
  ).toBeVisible();
  await expect(
    page.getByRole("row", { name: /Quantity Mismatch.*9\.00/ }),
  ).toBeVisible();

  const documentWidth = await page.evaluate(
    () => document.documentElement.scrollWidth,
  );
  const viewportWidth = await page.evaluate(
    () => document.documentElement.clientWidth,
  );
  expect(documentWidth).toBeLessThanOrEqual(viewportWidth + 1);
});
