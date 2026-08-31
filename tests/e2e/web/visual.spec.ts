import { expect, test } from "@playwright/test";

test("overview visual smoke has healthy console and expected composition", async ({
  page,
}, testInfo) => {
  const errors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  if (testInfo.project.name === "chromium-desktop") {
    await page.setViewportSize({ height: 1024, width: 1536 });
  }
  await page.goto("/sign-in");
  await page.getByRole("button", { name: "Enter demo portfolio" }).click();
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
  await expect(
    page.getByRole("table", { name: "Largest direct holdings" }),
  ).toBeVisible();
  await expect(
    page.getByRole("img", { name: /direct allocation/i }),
  ).toBeVisible();
  await expect(page.locator(".recharts-pie-sector").first()).toBeVisible();
  await page.screenshot({
    animations: "disabled",
    path: testInfo.outputPath("overview.png"),
  });
  expect(errors).toEqual([]);
});
