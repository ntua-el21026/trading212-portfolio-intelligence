import { expect, test, type Locator, type Page } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.goto("/sign-in");
  await page.getByRole("button", { name: "Start local session" }).click();
  await expect(page).toHaveURL("http://127.0.0.1:3001/");
});

async function rowText(table: Locator): Promise<string[]> {
  return table
    .locator("tbody tr")
    .allTextContents()
    .then((rows) => rows.map((row) => row.replace(/\s+/gu, " ").trim()));
}

async function assertAccessibleDocument(page: Page): Promise<void> {
  const violations = await page.evaluate(() => {
    const issues: string[] = [];
    const ids = Array.from(document.querySelectorAll<HTMLElement>("[id]"))
      .map((element) => element.id)
      .filter(Boolean);
    if (new Set(ids).size !== ids.length) issues.push("duplicate ids");
    for (const image of document.querySelectorAll("img")) {
      if (!image.hasAttribute("alt")) issues.push("image without alt");
    }
    for (const table of document.querySelectorAll("table")) {
      if (!table.querySelector("caption")) issues.push("table without caption");
    }
    for (const control of document.querySelectorAll("input, select")) {
      if (!control.closest("label") && !control.getAttribute("aria-label")) {
        issues.push("form control without label");
      }
    }
    return issues;
  });
  expect(violations).toEqual([]);
}

test("a newer inserted activity does not duplicate or skip the active cursor traversal", async ({
  page,
  request,
}) => {
  const consoleErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => consoleErrors.push(error.message));
  const reset = await request.post(
    "http://127.0.0.1:18000/__e2e__/reset-newer-activity",
  );
  expect(reset.ok()).toBe(true);
  await page.goto("/activity");
  const firstTable = page.getByRole("table", {
    name: "Canonical portfolio activity",
  });
  await expect(firstTable.locator("tbody tr")).toHaveCount(50);
  const firstPageRows = await rowText(firstTable);
  await expect(
    page.getByText(
      "Showing 50 records on this page out of 65 matching records.",
    ),
  ).toBeVisible();

  const inserted = await request.post(
    "http://127.0.0.1:18000/__e2e__/insert-newer-activity",
  );
  expect(inserted.ok()).toBe(true);

  const nextPage = page.getByRole("link", { name: "Next page" });
  await nextPage.focus();
  await expect(nextPage).toBeFocused();
  await nextPage.click();
  await expect(page).toHaveURL(/\?[^#]*cursor=/u);
  const secondTable = page.getByRole("table", {
    name: "Canonical portfolio activity",
  });
  await expect(secondTable.locator("tbody tr")).toHaveCount(15);
  const secondPageRows = await rowText(secondTable);
  expect(new Set([...firstPageRows, ...secondPageRows]).size).toBe(65);
  expect(secondPageRows.some((row) => row.includes("Interest activity"))).toBe(
    false,
  );
  await expect(page.getByText("End of collection")).toBeVisible();

  await page.goBack();
  await expect(page).toHaveURL("http://127.0.0.1:3001/activity");
  const restoredTable = page.getByRole("table", {
    name: "Canonical portfolio activity",
  });
  await expect(restoredTable.locator("tbody tr")).toHaveCount(50);
  expect(await rowText(restoredTable)).toEqual(firstPageRows);
  await expect(
    page.getByText(
      "Showing 50 records on this page out of 65 matching records.",
    ),
  ).toBeVisible();

  await page.reload();
  await expect(
    page.getByText(
      "Showing 50 records on this page out of 66 matching records.",
    ),
  ).toBeVisible();
  const freshTable = page.getByRole("table", {
    name: "Canonical portfolio activity",
  });
  await expect(freshTable.locator("tbody tr").first()).toContainText(
    "Interest activity",
  );

  await assertAccessibleDocument(page);
  const overflow = await page.evaluate(
    () =>
      document.documentElement.scrollWidth -
      document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(1);
  expect(consoleErrors).toEqual([]);
});
