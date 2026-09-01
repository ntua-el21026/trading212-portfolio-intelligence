import { expect, test } from "@playwright/test";

async function signIn(page: import("@playwright/test").Page) {
  await page.goto("/sign-in");
  await page.getByRole("button", { name: "Enter demo portfolio" }).click();
  await expect(page).toHaveURL(/\/$/);
}

test("authenticated Phase 1 routes expose canonical views", async ({
  page,
}) => {
  await signIn(page);
  const routes = [
    ["/holdings", "Holdings"],
    ["/allocation", "Allocation"],
    ["/activity", "Activity"],
    ["/dividends", "Dividends"],
    ["/snapshots", "Snapshots"],
    ["/synchronization", "Synchronization"],
    ["/quality", "Quality & reconciliation"],
    ["/settings", "Connection & settings"],
  ] as const;

  for (const [route, heading] of routes) {
    await page.goto(route);
    await expect(
      page.getByRole("heading", { name: heading, exact: true }),
    ).toBeVisible();
    await expect(page.getByText(/read-only/i).first()).toBeVisible();
  }

  await page.goto("/holdings/vwce");
  await expect(
    page.getByRole("heading", { name: "Vanguard FTSE All-World UCITS ETF" }),
  ).toBeVisible();
  await expect(page.getByText("104,000.00").first()).toBeVisible();

  await page.goto("/settings");
  await expect(page.getByText("Connected Read Only")).toBeVisible();
  await expect(page.getByText("Not Configured")).toBeVisible();
  await expect(
    page.getByText("Last successful refresh", { exact: true }).locator(".."),
  ).toContainText("31 Aug 2026, 09:30 UTC");
  await expect(page.locator("body")).not.toContainText(/credential_reference/u);
});

test("read-only synchronization returns an explicit synthetic result", async ({
  page,
}) => {
  await signIn(page);
  await page.goto("/synchronization");
  await page.getByRole("button", { name: "Run demo synchronization" }).click();
  await expect(page.getByText("Synchronization completed")).toBeVisible();
  await expect(
    page.getByText(/no external broker request was made/i),
  ).toBeVisible();
});
