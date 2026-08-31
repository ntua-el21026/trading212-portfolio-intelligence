import { expect, test } from "@playwright/test";

test("renders the Phase 1 read-only shell", async ({ page }) => {
  await page.goto("/");

  await expect(
    page.getByRole("heading", { name: "Trading 212 Portfolio Intelligence" }),
  ).toBeVisible();
  await expect(
    page.getByText(/strictly read-only broker boundary/i),
  ).toBeVisible();
});
