import { expect, test, type Locator, type Page } from "@playwright/test";

async function rowText(table: Locator): Promise<string[]> {
  return table
    .locator("tbody tr")
    .allTextContents()
    .then((rows) => rows.map((row) => row.replace(/\s+/gu, " ").trim()));
}

test.beforeEach(async ({ page }) => {
  await page.goto("/sign-in");
  await page.getByRole("button", { name: "Enter demo portfolio" }).click();
});

test("quality discrepancies remain bounded and cursor-paginated", async ({
  page,
}: {
  page: Page;
}) => {
  const consoleErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => consoleErrors.push(error.message));
  await page.goto("/quality?state=unreconciled");
  const firstTable = page.getByRole("table", {
    name: "Reconciliation discrepancy records",
  });
  await expect(firstTable.locator("tbody tr")).toHaveCount(50);
  const firstRows = await rowText(firstTable);
  await expect(
    page.getByText(
      "Showing 50 records on this page out of 61 matching records.",
    ),
  ).toBeVisible();

  await page.getByRole("link", { name: "Next page" }).click();
  await expect(page).toHaveURL(/state=unreconciled&cursor=/u);
  const secondTable = page.getByRole("table", {
    name: "Reconciliation discrepancy records",
  });
  await expect(secondTable.locator("tbody tr")).toHaveCount(11);
  const secondRows = await rowText(secondTable);
  expect(new Set([...firstRows, ...secondRows]).size).toBe(61);
  await expect(page.getByText("End of collection")).toBeVisible();

  await page.goBack();
  await expect(page).toHaveURL(/\/quality\?state=unreconciled$/u);
  const restoredTable = page.getByRole("table", {
    name: "Reconciliation discrepancy records",
  });
  await expect(restoredTable.locator("tbody tr")).toHaveCount(50);
  expect(await rowText(restoredTable)).toEqual(firstRows);

  const overflow = await page.evaluate(
    () =>
      document.documentElement.scrollWidth -
      document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(1);
  expect(consoleErrors).toEqual([]);
});
