import { keyboardClearance } from "./accessibility";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expect, test, type Page } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  page.setDefaultTimeout(15_000);
  await page.goto("/sign-in");
  await page.getByRole("button", { name: "Start local session" }).click();
  await expect(page).toHaveURL("http://127.0.0.1:3001/");
});

async function assertAccessibleTargetPage(page: Page): Promise<void> {
  await keyboardClearance(page);
  const issues = await page.evaluate(() => {
    const violations: string[] = [];
    const ids = [...document.querySelectorAll<HTMLElement>("[id]")]
      .map((node) => node.id)
      .filter(Boolean);
    if (new Set(ids).size !== ids.length) violations.push("duplicate ids");
    for (const control of document.querySelectorAll("input,select,textarea")) {
      if (
        control.getAttribute("type") !== "hidden" &&
        !control.closest("label") &&
        !control.getAttribute("aria-label")
      ) {
        violations.push("control without accessible label");
      }
    }
    for (const table of document.querySelectorAll("table")) {
      if (!table.querySelector("caption") && !table.getAttribute("aria-label"))
        violations.push("table without accessible name");
    }
    for (const image of document.querySelectorAll("img"))
      if (!image.hasAttribute("alt")) violations.push("image without alt");
    if (document.querySelectorAll("main").length !== 1)
      violations.push("missing or duplicate main landmark");
    if (document.querySelectorAll("h1").length !== 1)
      violations.push("missing or duplicate page heading");
    return violations;
  });
  expect(issues).toEqual([]);
  expect(
    await page.evaluate(
      () =>
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
    ),
  ).toBeLessThanOrEqual(1);
  await expect(page.locator("nextjs-portal").getByText(/error/i)).toHaveCount(
    0,
  );
  const content = await page.content();
  for (const forbidden of [
    "downloadLink",
    "download_link",
    ["EXPORT", "URL", "CANARY"].join("_"),
    ["signed", "example", "invalid"].join("."),
  ]) {
    expect(content).not.toContain(forbidden);
  }
}

test("durable target editor preserves errors and completes version lifecycle", async ({
  page,
}, testInfo) => {
  test.setTimeout(120_000);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error" || message.type() === "warning")
      errors.push(message.text());
  });
  const name = `Browser Pie ${testInfo.project.name} ${Date.now()}`;
  await page.goto("/pies");
  await expect(page).toHaveTitle(/Portfolio Intelligence/);
  await expect(
    page.getByRole("heading", { name: "Pies", exact: true }),
  ).toBeVisible();
  await page.getByLabel("Name", { exact: true }).fill(name);
  await page
    .getByRole("combobox", { name: "Account", exact: true })
    .selectOption("");
  await page
    .getByLabel("Description", { exact: true })
    .fill("Synthetic browser acceptance target");
  await page.getByRole("button", { name: "Create Pie", exact: true }).click();
  await expect(page).toHaveURL(
    (url) =>
      /^\/pies\/[0-9a-f-]{36}$/u.test(url.pathname) &&
      url.searchParams.get("account") === "template",
  );
  await expect(page.getByRole("heading", { name, exact: true })).toBeVisible();
  await page
    .getByRole("button", { name: "Create draft version", exact: true })
    .click();
  await expect(page).toHaveURL(
    (url) =>
      /^[0-9a-f-]{36}$/u.test(url.searchParams.get("version") ?? "") &&
      url.searchParams.get("account") === "template",
  );
  await page.getByRole("button", { name: "Add cash", exact: true }).click();
  const cashWeight = page.getByRole("textbox", { name: "Weight for EUR cash" });
  await cashWeight.fill("1e0");
  await page.getByRole("button", { name: "Save draft", exact: true }).click();
  await expect(
    page.getByText("Review your request", { exact: true }),
  ).toBeVisible();
  await expect(cashWeight).toHaveValue("1e0");
  await expect(
    page.getByRole("button", { name: "Validate target" }),
  ).toBeDisabled();
  await cashWeight.fill("1");
  await page.getByRole("button", { name: "Save draft", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Validate target" }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "Validate target" }).click();
  await expect(
    page.getByText("No validation issues.", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Publish version", exact: true })
    .click();
  await expect(
    page.getByText("Published target content is locked", { exact: true }),
  ).toBeVisible();
  await expect(cashWeight).toBeDisabled();
  await page.getByText("Canonical effective weights", { exact: true }).click();
  await assertAccessibleTargetPage(page);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: join(tmpdir(), `t212-p2-01-${testInfo.project.name}-published.png`),
    fullPage: false,
  });

  await page
    .locator("summary")
    .filter({ hasText: /^Create a draft version$/ })
    .click();
  await page
    .getByRole("combobox", { name: "Start from", exact: true })
    .selectOption({ label: "Selected version 1" });
  await page
    .getByRole("button", { name: "Create draft version", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Save draft", exact: true }),
  ).toBeVisible();
  await expect(cashWeight).toHaveValue("1");
  await page
    .getByRole("textbox", { name: "Name for EUR cash" })
    .fill("Cloned cash");
  await page.getByRole("button", { name: "Save draft", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Validate target" }),
  ).toBeEnabled();
  await page
    .getByRole("combobox", { name: "Earlier version", exact: true })
    .selectOption({ label: "Version 1 · active" });
  await page
    .getByRole("combobox", { name: "Later version", exact: true })
    .selectOption({ label: "Version 2 · draft" });
  await page
    .getByRole("button", { name: "Compare versions", exact: true })
    .click();
  await expect(page.locator(".target-comparison")).toContainText("Cloned cash");
  await expect(page.locator(".target-comparison")).toContainText("name");
  await page
    .getByRole("button", { name: "Archive version", exact: true })
    .click();
  await expect(
    page.getByRole("link", { name: /Version 2 archived/ }),
  ).toBeVisible();
  await page
    .locator("summary")
    .filter({ hasText: /^Pie settings$/ })
    .click();
  await page.getByRole("button", { name: "Archive Pie", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Archive Pie", exact: true }),
  ).toBeDisabled();
  await expect(
    page.getByText("No active target", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("link", { name: "View version activity", exact: true })
    .click();
  await expect(page.locator(".target-event-list")).toContainText("archived");
  await assertAccessibleTargetPage(page);
  expect(errors).toEqual([]);
});

test("target pagination retains membership while a new Pie is created", async ({
  page,
  request,
}, testInfo) => {
  test.setTimeout(120_000);
  const prefix = `Traversal ${testInfo.project.name} ${Date.now()}`;
  const session = await request.post(
    "http://127.0.0.1:18000/api/v1/auth/local-session",
  );
  expect(session.status()).toBe(201);
  const csrf = (await session.json()).csrf_token as string;
  const create = async (suffix: string) => {
    const result = await request.post(
      "http://127.0.0.1:18000/api/v1/virtual-portfolios",
      {
        headers: {
          Origin: "http://127.0.0.1:3001",
          "X-CSRF-Token": csrf,
          "X-Idempotency-Key": `${prefix.replaceAll(" ", "-")}-${suffix}`,
        },
        data: {
          name: `${prefix} ${suffix}`,
          reporting_currency: "EUR",
          account_id: null,
        },
      },
    );
    expect(result.status()).toBe(201);
  };
  for (let index = 0; index < 26; index += 1)
    await create(String(index).padStart(2, "0"));
  await page.goto(
    `/pies?account=template&search=${encodeURIComponent(prefix)}`,
  );
  const matching = page.getByRole("link", {
    name: new RegExp(`^${prefix} \\d{2}$`),
  });
  await expect(matching).toHaveCount(25);
  await assertAccessibleTargetPage(page);
  await page.screenshot({
    path: join(tmpdir(), `t212-p2-08-${testInfo.project.name}-pies.png`),
    fullPage: false,
  });
  const first = await matching.allTextContents();
  await expect(
    page.getByText(
      "Showing 25 records on this page out of 26 matching records.",
    ),
  ).toBeVisible();
  await create("99");
  const next = page.getByRole("link", { name: "Next page", exact: true });
  await next.focus();
  await expect(next).toBeFocused();
  await next.click();
  await expect(matching).toHaveCount(1);
  const second = await matching.allTextContents();
  expect(new Set([...first, ...second]).size).toBe(26);
  expect(second).not.toContain(`${prefix} 99`);
  await expect(
    page.getByText("End of collection", { exact: true }),
  ).toBeVisible();
  await page.goto(
    `/pies?account=template&search=${encodeURIComponent(prefix)}`,
  );
  await expect(
    page.getByText(
      "Showing 25 records on this page out of 27 matching records.",
    ),
  ).toBeVisible();
  await assertAccessibleTargetPage(page);
});

test("deep-linked old target remains selectable beyond the first version page", async ({
  page,
  request,
}, testInfo) => {
  test.setTimeout(120_000);
  const prefix = `Old version ${testInfo.project.name} ${Date.now()}`;
  const session = await request.post(
    "http://127.0.0.1:18000/api/v1/auth/local-session",
  );
  expect(session.status()).toBe(201);
  const csrf = (await session.json()).csrf_token as string;
  const headers = (suffix: string) => ({
    Origin: "http://127.0.0.1:3001",
    "X-CSRF-Token": csrf,
    "X-Idempotency-Key": `${prefix.replaceAll(" ", "-")}-${suffix}`,
  });
  const created = await request.post(
    "http://127.0.0.1:18000/api/v1/virtual-portfolios",
    {
      headers: headers("portfolio"),
      data: { name: prefix, reporting_currency: "EUR", account_id: null },
    },
  );
  expect(created.status()).toBe(201);
  const portfolioId = (await created.json()).id as string;
  const apiPath = `http://127.0.0.1:18000/api/v1/virtual-portfolios/${portfolioId}`;
  let etag = created.headers().etag;
  const versions: string[] = [];
  for (let number = 1; number <= 26; number += 1) {
    expect(etag).toBeTruthy();
    const version = await request.post(`${apiPath}/target-versions`, {
      headers: { ...headers(`version-${number}`), "If-Match": etag },
      data: {
        effective_at: "2026-09-07T12:00:00Z",
        content: {
          nodes:
            number === 26
              ? [
                  {
                    key: "cash",
                    kind: "cash",
                    name: "Newest version cash",
                    order: 0,
                    weight: "1",
                  },
                ]
              : [],
        },
      },
    });
    expect(version.status()).toBe(201);
    const data = await version.json();
    expect(data.version_number).toBe(number);
    versions.push(data.id as string);
    if (number < 26) {
      const portfolio = await request.get(apiPath);
      expect(portfolio.status()).toBe(200);
      etag = portfolio.headers().etag;
    }
  }
  const oldest = versions[0];
  const newest = versions[25];
  await page.goto(`/pies/${portfolioId}?version=${oldest}`);
  await expect(
    page.getByRole("heading", { name: "Target hierarchy", exact: true }),
  ).toBeVisible();
  const navigation = page.locator(".target-version-list");
  await expect(navigation.getByRole("link")).toHaveCount(25);
  await expect(
    navigation.getByRole("link", { name: /^Version 1\s/ }),
  ).toHaveCount(0);
  const earlier = page.getByRole("combobox", {
    name: "Earlier version",
    exact: true,
  });
  const later = page.getByRole("combobox", {
    name: "Later version",
    exact: true,
  });
  for (const selector of [earlier, later]) {
    await expect(selector.locator("option")).toHaveCount(26);
    await expect(
      selector.getByRole("option", { name: "Version 1 · draft", exact: true }),
    ).toHaveCount(1);
    await selector.selectOption(oldest);
    await expect(selector).toHaveValue(oldest);
  }
  await later.selectOption(newest);
  await page
    .getByRole("button", { name: "Compare versions", exact: true })
    .click();
  await expect(page).toHaveURL(
    (url) =>
      url.searchParams.get("version") === oldest &&
      url.searchParams.get("left") === oldest &&
      url.searchParams.get("right") === newest,
  );
  await expect(page.locator(".target-comparison")).toContainText(
    "Newest version cash",
  );
  await expect(page.locator(".target-comparison")).toContainText("added");
  await expect(earlier).toHaveValue(oldest);
  await expect(later).toHaveValue(newest);
  await assertAccessibleTargetPage(page);
});
