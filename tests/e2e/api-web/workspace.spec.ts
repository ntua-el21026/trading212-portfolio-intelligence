import { keyboardClearance } from "./accessibility";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  expect,
  test,
  type APIRequestContext,
  type Page,
} from "@playwright/test";
import {
  accountSchema,
  accountSummarySchema,
  reconciliationSchema,
  type Account,
} from "@trading212/api-contracts";
import { z } from "zod";

const api = "http://127.0.0.1:18000/api/v1";
const primary = "f0f5c66e-b128-59b2-a620-83bc8faa4a57";

async function accounts(request: APIRequestContext): Promise<Account[]> {
  const response = await request.get(`${api}/accounts`);
  expect(response.status()).toBe(200);
  return z.array(accountSchema).parse(await response.json());
}
async function summary(request: APIRequestContext, account: string) {
  const response = await request.get(`${api}/accounts/${account}/summary`);
  expect(response.status()).toBe(200);
  return accountSummarySchema.parse(await response.json());
}
// SSR intentionally disables selection until hydration and responsive styles settle.
async function accountControl(page: Page) {
  const control = page.getByRole("combobox", {
    name: "Portfolio account",
    exact: true,
  });
  await expect(control).toHaveCount(1);
  await expect(control).toBeEnabled();
  return control;
}
async function selectAccount(page: Page, account: string) {
  await (await accountControl(page)).selectOption(account);
  await expect(page).toHaveURL(new RegExp(`[?&]account=${account}(?:&|$)`));
  await expect(
    page.locator("[data-portfolio-account]").first(),
  ).toHaveAttribute("data-portfolio-account", account);
}
async function assertAccount(
  page: Page,
  request: APIRequestContext,
  account: string,
) {
  const data = await summary(request, account);
  await expect(await accountControl(page)).toHaveValue(account);
  await expect(
    page.locator(".metric-card--primary [data-canonical-value]").first(),
  ).toHaveAttribute("data-canonical-value", data.total_value.value!);
  await expect(
    page.locator("[data-portfolio-account]").first(),
  ).toHaveAttribute("data-portfolio-account", account);
}

test.beforeEach(async ({ page, request }) => {
  page.setDefaultTimeout(15_000);
  await page.goto("/sign-in");
  await page.getByRole("button", { name: "Start local session" }).click();
  await expect(page).toHaveURL("http://127.0.0.1:3001/");
  expect((await request.post(`${api}/auth/local-session`)).status()).toBe(201);
  await accountControl(page);
});

test("account identity survives real API navigation, reload and browser history", async ({
  page,
  request,
}) => {
  test.setTimeout(120_000);
  const second = (await accounts(request)).find((row) => row.id !== primary)!;
  expect(second).toBeDefined();
  await assertAccount(page, request, primary);
  await selectAccount(page, second.id);
  await assertAccount(page, request, second.id);
  await page.reload();
  await assertAccount(page, request, second.id);
  await selectAccount(page, primary);
  await assertAccount(page, request, primary);
  await page.goBack();
  await assertAccount(page, request, second.id);
  await page.goForward();
  await assertAccount(page, request, primary);
  const nav = page.getByRole("navigation", { name: "Primary", exact: true });
  const desktop = page.getByRole("navigation", {
    name: "Portfolio",
    exact: true,
  });
  await ((await nav.isVisible()) ? nav : desktop)
    .getByRole("link", { name: "Holdings", exact: true })
    .click();
  await expect(page).toHaveURL(new RegExp(`/holdings\\?account=${primary}$`));
});

test("invalid, duplicate and foreign account selections never reveal the configured account", async ({
  page,
}) => {
  for (const query of [
    "account=invalid",
    `account=${primary}&account=${primary}`,
    "account=f791a374-cc3e-4e73-9168-a120c0d54cec",
  ]) {
    await page.goto(`/?${query}`);
    await expect(
      page.getByText("Account unavailable", { exact: true }).last(),
    ).toBeVisible();
    await expect(page.locator(".metric-card")).toHaveCount(0);
    await expect(page.locator("[data-portfolio-account]")).toHaveCount(0);
  }
});

test("a delayed account response cannot replace the account currently selected in history", async ({
  page,
  request,
}) => {
  test.setTimeout(120_000);
  const second = (await accounts(request)).find((row) => row.id !== primary)!;
  let release: () => void = () => {};
  let requested = false;
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route(
    (url) =>
      url.pathname === "/" &&
      url.searchParams.get("account") === second.id &&
      url.searchParams.has("_rsc"),
    async (route) => {
      const response = await route.fetch();
      requested = true;
      await held;
      await route.fulfill({ response });
    },
  );
  try {
    await page
      .getByRole("combobox", { name: "Portfolio account", exact: true })
      .selectOption(second.id);
    await expect.poll(() => requested, { timeout: 20_000 }).toBe(true);
    // A second actual account choice supersedes the outstanding B response.
    await page
      .getByRole("combobox", { name: "Portfolio account", exact: true })
      .selectOption(primary);
  } finally {
    release();
    await page.unrouteAll({ behavior: "wait" });
  }
  await assertAccount(page, request, primary);
  await expect(
    page.locator(`[data-portfolio-account="${second.id}"]`),
  ).toHaveCount(0);
});

test("Back during a pending account navigation restores the earlier account before the response arrives", async ({
  page,
  request,
}, testInfo) => {
  test.setTimeout(120_000);
  const second = (await accounts(request)).find((row) => row.id !== primary)!;
  async function recordHistory(phase: string) {
    const session = await page.context().newCDPSession(page);
    try {
      const history = await session.send("Page.getNavigationHistory");
      testInfo.annotations.push({
        type: "account-history-diagnostic",
        description: JSON.stringify({
          phase,
          current_index: history.currentIndex,
          entries: history.entries.map((entry) => {
            const url = new URL(entry.url);
            return {
              id: entry.id,
              pathname: url.pathname,
              account: url.searchParams.get("account"),
            };
          }),
        }),
      });
    } finally {
      await session.detach();
    }
  }
  async function navigate(label: string) {
    const primaryNav = page.getByRole("navigation", {
      name: "Primary",
      exact: true,
    });
    const desktopNav = page.getByRole("navigation", {
      name: "Portfolio",
      exact: true,
    });
    await ((await primaryNav.isVisible()) ? primaryNav : desktopNav)
      .getByRole("link", { name: label, exact: true })
      .click();
  }
  await navigate("Holdings");
  await expect(page).toHaveURL(
    (url) =>
      url.pathname === "/holdings" &&
      url.searchParams.get("account") === primary,
  );
  await recordHistory("holdings");
  await navigate("Overview");
  await expect(page).toHaveURL(
    (url) =>
      url.pathname === "/" && url.searchParams.get("account") === primary,
  );
  await expect(
    page.getByRole("heading", { name: "Overview", exact: true }),
  ).toBeVisible();
  await assertAccount(page, request, primary);
  await recordHistory("overview");
  let release: () => void = () => {};
  let requested = false;
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route(
    (url) =>
      url.pathname === "/" &&
      url.searchParams.get("account") === second.id &&
      url.searchParams.has("_rsc"),
    async (route) => {
      const response = await route.fetch();
      requested = true;
      await held;
      await route.fulfill({ response });
    },
  );
  try {
    await page
      .getByRole("combobox", { name: "Portfolio account", exact: true })
      .selectOption(second.id);
    await expect.poll(() => requested, { timeout: 20_000 }).toBe(true);
    // Record the actual browser entries while the account response remains held.
    await expect(page).toHaveURL(
      (url) =>
        url.pathname === "/" && url.searchParams.get("account") === primary,
    );
    await recordHistory("held-account-response");
    testInfo.annotations.push({
      type: "before-back-history",
      description: JSON.stringify(
        await page.evaluate(() => ({
          pathname: location.pathname,
          account: new URL(location.href).searchParams.get("account"),
          history_length: history.length,
        })),
      ),
    });
    await page.goBack();
    await expect(page).toHaveURL(
      (url) =>
        url.pathname === "/holdings" &&
        url.searchParams.get("account") === primary,
    );
    await expect(
      page.getByRole("combobox", { name: "Portfolio account", exact: true }),
    ).toHaveValue(primary);
    await expect
      .poll(() =>
        page
          .locator("[data-portfolio-account]")
          .evaluateAll((views) => [
            ...new Set(
              views.map((view) => view.getAttribute("data-portfolio-account")),
            ),
          ]),
      )
      .toEqual([primary]);
  } finally {
    release();
    await page.unrouteAll({ behavior: "wait" });
  }
  await expect(page).toHaveURL(
    (url) =>
      url.pathname === "/holdings" &&
      url.searchParams.get("account") === primary,
  );
  await expect
    .poll(() =>
      page
        .locator("[data-portfolio-account]")
        .evaluateAll((views) => [
          ...new Set(
            views.map((view) => view.getAttribute("data-portfolio-account")),
          ),
        ]),
    )
    .toEqual([primary]);
});

test("all portfolio sections remain accessible at the configured viewport", async ({
  page,
  request,
}, info) => {
  test.setTimeout(360_000);
  const paths = [
    "/performance",
    "/",
    "/holdings",
    "/allocation",
    "/activity",
    "/dividends",
    "/snapshots",
    "/synchronization",
    "/quality",
    "/settings",
    "/pies",
    "/drift",
    "/planner",
    "/sources",
    "/income",
    "/xray",
    "/reports",
    "/alerts",
  ];
  for (const path of paths) {
    await page.goto(`${path}?account=${primary}`);
    await expect(page.getByRole("main")).toHaveCount(1);
    await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
    await expect(
      page.getByRole("combobox", { name: "Portfolio account", exact: true }),
    ).toHaveValue(primary);
    const overflow = await page.evaluate(() => ({
      width:
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
      nodes: [...document.querySelectorAll<HTMLElement>("main *")]
        .filter((node) => node.getBoundingClientRect().right > innerWidth + 1)
        .slice(0, 12)
        .map((node) => ({
          tag: node.tagName,
          class: node.getAttribute("class"),
          right: node.getBoundingClientRect().right,
          parent: node.parentElement?.getAttribute("class"),
          parentRight: node.parentElement?.getBoundingClientRect().right,
          parentOverflow:
            node.parentElement &&
            getComputedStyle(node.parentElement).overflowX,
        })),
    }));
    expect(
      overflow.width,
      path + " " + JSON.stringify(overflow),
    ).toBeLessThanOrEqual(1);
    if (path === "/") {
      const response = await request.get(
        api + "/accounts/" + primary + "/reconciliation",
      );
      expect(response.status()).toBe(200);
      const reconciliation = reconciliationSchema.parse(await response.json());
      expect(reconciliation.status).toBe("unreconciled");
      expect(reconciliation.issues).toEqual([]);
      const discrepancyText =
        reconciliation.discrepancy_count === 1
          ? "1 discrepancy record."
          : reconciliation.discrepancy_count + " discrepancy records.";
      const mobileTrust = page.locator(".mobile-trust-summary");
      const desktopTrust = page.locator(".trust-rail");
      for (const panel of [mobileTrust, desktopTrust]) {
        await expect(panel).toContainText("Unreconciled");
        await expect(panel).toContainText(discrepancyText);
      }
      await expect(
        info.project.use.isMobile ? mobileTrust : desktopTrust,
      ).toBeVisible();
      await expect(
        page.getByText("Open discrepancies are present.", { exact: true }),
      ).toHaveCount(0);
    }
    await keyboardClearance(page);
    if (
      ["/", "/snapshots", "/quality", "/synchronization", "/settings"].includes(
        path,
      )
    ) {
      // Screenshot capture is separate from the unaided keyboard checks above.
      await page.evaluate(() => window.scrollTo(0, 0));
      await page.screenshot({
        path: join(
          tmpdir(),
          `t212-p2-08-workspace-${path === "/" ? "overview" : path.slice(1)}-${info.project.name}.png`,
        ),
        fullPage: false,
      });
    }
  }
});
