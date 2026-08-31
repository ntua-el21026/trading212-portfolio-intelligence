import { expect, test } from "@playwright/test";

test("local demo access is authenticated and revocable", async ({
  context,
  page,
}) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/sign-in$/);
  await expect(
    page.getByRole("heading", { name: "Private portfolio access" }),
  ).toBeVisible();

  await page.getByRole("button", { name: "Enter demo portfolio" }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
  await expect(page.getByText("Synthetic · read-only")).toBeVisible();

  const session = (await context.cookies()).find(
    (cookie) => cookie.name === "t212pi_session",
  );
  expect(session?.httpOnly).toBe(true);
  expect(session?.sameSite).toBe("Strict");

  await page.goto("/settings");
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/sign-in$/);
});
