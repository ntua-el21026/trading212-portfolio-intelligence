import { expect, test, type Locator, type Page } from "@playwright/test";

async function signIn(page: Page): Promise<void> {
  await page.goto("/sign-in");
  await page.getByRole("button", { name: "Enter demo portfolio" }).click();
  await expect(page).toHaveURL(/\/$/u);
}

async function assertNoDocumentOverflow(page: Page): Promise<void> {
  const overflow = await page.evaluate(
    () =>
      document.documentElement.scrollWidth -
      document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(1);
}

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
      if (!table.hidden && !table.querySelector("caption")) {
        issues.push("visible table without caption");
      }
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

function collectConsoleErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  page.on("pageerror", (error) => errors.push(error.message));
  return errors;
}

test.beforeEach(async ({ page }) => {
  await signIn(page);
});

test("overview labels its bounded preview and orders it by market value", async ({
  page,
}) => {
  const consoleErrors = collectConsoleErrors(page);
  await expect(
    page.getByText(
      "Showing 5 of 65 direct positions, ordered by market value.",
    ),
  ).toBeVisible();
  const preview = page.getByRole("table", { name: "Largest direct holdings" });
  await expect(preview.locator("tbody tr")).toHaveCount(5);
  await expect(preview.locator("tbody tr").first()).toContainText("VWCE");
  await expect(page.getByRole("link", { name: "View all" })).toHaveAttribute(
    "href",
    "/holdings",
  );
  await expect(
    page.getByText(
      "Showing 6 of 66 canonical rows, including cash when available.",
    ),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Explore allocation" }),
  ).toHaveAttribute("href", "/allocation");
  await assertAccessibleDocument(page);
  await assertNoDocumentOverflow(page);
  expect(consoleErrors).toEqual([]);
});

test("allocation exposes exact bounded coverage instead of implying completeness", async ({
  page,
}) => {
  const consoleErrors = collectConsoleErrors(page);
  await page.goto("/allocation");
  await expect(
    page.getByText(
      "Showing 51 of 66 direct allocation rows. This bounded Phase 1 view is partial; no omitted row is included in the chart or table.",
    ),
  ).toBeVisible();
  await expect(
    page
      .getByRole("table", { name: "Direct allocation details" })
      .locator("tbody tr"),
  ).toHaveCount(51);
  await assertAccessibleDocument(page);
  await assertNoDocumentOverflow(page);
  expect(consoleErrors).toEqual([]);
});

for (const collection of [
  {
    caption: "Direct portfolio holdings",
    path: "/holdings",
    total: 65,
  },
  {
    caption: "Canonical portfolio activity",
    path: "/activity",
    total: 63,
  },
  {
    caption: "Canonical dividend records",
    path: "/dividends",
    total: 61,
  },
  {
    caption: "Immutable portfolio snapshots",
    path: "/snapshots",
    total: 65,
  },
] as const) {
  test(`${collection.path} reaches every row through URL cursor pagination and browser back`, async ({
    page,
  }) => {
    const consoleErrors = collectConsoleErrors(page);
    await page.goto(collection.path);
    const firstTable = page.getByRole("table", { name: collection.caption });
    await expect(firstTable.locator("tbody tr")).toHaveCount(50);
    const firstPageRows = await rowText(firstTable);
    expect(new Set(firstPageRows).size).toBe(firstPageRows.length);
    await expect(
      page.getByText(
        `Showing 50 records on this page out of ${collection.total} matching records.`,
      ),
    ).toBeVisible();

    const next = page.getByRole("link", { name: "Next page" });
    await next.focus();
    await expect(next).toBeFocused();
    await next.click();
    await expect(page).toHaveURL(/\?[^#]*cursor=/u);

    const secondTable = page.getByRole("table", { name: collection.caption });
    await expect(secondTable.locator("tbody tr")).toHaveCount(
      collection.total - 50,
    );
    const secondPageRows = await rowText(secondTable);
    expect(new Set([...firstPageRows, ...secondPageRows]).size).toBe(
      collection.total,
    );
    await expect(page.getByText("End of collection")).toBeVisible();
    await assertAccessibleDocument(page);
    await assertNoDocumentOverflow(page);

    await page.goBack();
    await expect(page).toHaveURL(new RegExp(`${collection.path}$`, "u"));
    const restoredTable = page.getByRole("table", { name: collection.caption });
    await expect(restoredTable.locator("tbody tr")).toHaveCount(50);
    const restoredRows = await rowText(restoredTable);
    expect(restoredRows).toEqual(firstPageRows);
    expect(consoleErrors).toEqual([]);
  });
}

test("collection filters submit bounded URL state and reset pagination", async ({
  page,
}) => {
  const consoleErrors = collectConsoleErrors(page);
  await page.goto("/holdings");
  await page.getByLabel("Search ticker or name").fill("fixture holding 060");
  await page.getByLabel("Sort").selectOption("ticker_asc");
  await page.getByRole("button", { name: "Apply" }).click();
  await expect(page).toHaveURL(
    /\/holdings\?search=fixture\+holding\+060&sort=ticker_asc$/u,
  );
  await expect(
    page.getByRole("table", { name: "Direct portfolio holdings" }),
  ).toContainText("FX060");
  await expect(
    page.getByText("Showing 1 record on this page out of 1 matching record."),
  ).toBeVisible();

  await page.goto("/activity");
  await page.getByLabel("From").fill("2026-06-01");
  await page.getByLabel("To").fill("2026-06-30");
  await page.getByLabel("Activity type").selectOption("buy");
  await page.getByRole("button", { name: "Apply" }).click();
  await expect(page).toHaveURL(
    /start_date=2026-06-01&end_date=2026-06-30&activity_type=buy/u,
  );
  await expect(
    page.getByText(
      "Showing 15 records on this page out of 15 matching records.",
    ),
  ).toBeVisible();
  await expect(
    page
      .getByRole("table", { name: "Canonical portfolio activity" })
      .locator("tbody tr"),
  ).toHaveCount(15);
  await assertAccessibleDocument(page);
  await assertNoDocumentOverflow(page);
  expect(consoleErrors).toEqual([]);
});
