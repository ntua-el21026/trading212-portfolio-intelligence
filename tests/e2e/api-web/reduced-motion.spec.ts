import { expect, test } from "@playwright/test";
import { accountSummarySchema } from "@trading212/api-contracts";

import { keyboardClearance } from "./accessibility";

const api = "http://127.0.0.1:18000/api/v1";
const account = "f0f5c66e-b128-59b2-a620-83bc8faa4a57";

test("reduced motion applies real CSS without changing API values or snapshot access", async ({
  page,
  request,
}) => {
  test.setTimeout(120_000);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.goto("/sign-in");
  await page.getByRole("button", { name: "Start local session" }).click();
  await expect(page).toHaveURL("http://127.0.0.1:3001/");
  expect((await request.post(api + "/auth/local-session")).status()).toBe(201);
  const response = await request.get(api + "/accounts/" + account + "/summary");
  expect(response.status()).toBe(200);
  const summary = accountSummarySchema.parse(await response.json());
  expect(summary.total_value.value).toBe("248431.27");
  const canonical = page
    .locator(".metric-card--primary [data-canonical-value]")
    .first();
  await expect(canonical).toHaveAttribute(
    "data-canonical-value",
    summary.total_value.value!,
  );
  expect(
    await page.evaluate(
      () => matchMedia("(prefers-reduced-motion: reduce)").matches,
    ),
  ).toBe(false);
  await expect(page.locator("html")).toHaveCSS("scroll-behavior", "auto");

  await page.emulateMedia({ reducedMotion: "reduce" });
  await expect
    .poll(() =>
      page.evaluate(
        () => matchMedia("(prefers-reduced-motion: reduce)").matches,
      ),
    )
    .toBe(true);
  await expect(page.locator("html")).toHaveCSS("scroll-behavior", "auto");
  await expect(canonical).toHaveAttribute(
    "data-canonical-value",
    summary.total_value.value!,
  );

  // This navigation renders the real API snapshot collection and real Recharts.
  await page.goto("/snapshots?account=" + account);
  await expect(
    page.getByRole("heading", { name: "Snapshots", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("combobox", { name: "Portfolio account", exact: true }),
  ).toHaveValue(account);
  const plot = page.getByRole("img", {
    name: "Portfolio value by immutable snapshot",
  });
  await expect(plot.locator("svg.recharts-surface")).toBeVisible();
  await page.getByText(/^Exact snapshot values and sources/).click();
  await expect(
    page.getByRole("table", {
      name: "Snapshot chart: exact server values in original page order",
    }),
  ).toBeVisible();
  await expect(page.locator("html")).toHaveCSS("scroll-behavior", "auto");

  const motion = await page.locator("main").evaluate((main) => {
    const nodes = [main, ...main.querySelectorAll<HTMLElement>("*")];
    const violations: string[] = [];
    for (const node of nodes) {
      for (const pseudo of [null, "::before", "::after"]) {
        const style = getComputedStyle(node, pseudo);
        const tooLong = (value: string) =>
          value
            .split(",")
            .some((duration) => Number.parseFloat(duration) > 0.000011);
        if (
          style.scrollBehavior !== "auto" ||
          tooLong(style.animationDuration) ||
          tooLong(style.transitionDuration) ||
          (style.animationName !== "none" &&
            style.animationIterationCount
              .split(",")
              .some(
                (count) => count.trim() === "infinite" || Number(count) > 1,
              ))
        ) {
          violations.push(
            node.tagName + (pseudo ?? "") + ":" + style.animationName,
          );
        }
      }
    }
    return { inspected: nodes.length, violations };
  });
  expect(motion.inspected).toBeGreaterThan(1);
  expect(motion.violations).toEqual([]);
  await keyboardClearance(page);
  expect(errors).toEqual([]);
});
