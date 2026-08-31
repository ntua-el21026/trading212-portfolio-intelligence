import { expect, test } from "@playwright/test";

test("responsive shell remains keyboard accessible without horizontal overflow", async ({
  page,
}) => {
  await page.goto("/sign-in");
  await page.keyboard.press("Tab");
  await expect(
    page.getByRole("link", { name: "Portfolio Intelligence" }),
  ).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(
    page.getByRole("button", { name: "Enter demo portfolio" }),
  ).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();

  const viewport = page.viewportSize();
  if (viewport && viewport.width <= 736) {
    await expect(
      page.getByRole("navigation", { name: "Primary" }),
    ).toBeVisible();
    await expect(
      page.getByRole("navigation", { name: "Portfolio" }),
    ).toBeHidden();
  } else {
    await expect(
      page.getByRole("navigation", { name: "Portfolio" }),
    ).toBeVisible();
  }

  const overflow = await page.evaluate(
    () =>
      document.documentElement.scrollWidth -
      document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(1);
});
