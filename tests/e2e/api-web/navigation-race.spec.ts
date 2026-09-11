import { randomUUID } from "node:crypto";
import { expect, test } from "@playwright/test";
import {
  TargetPageResponse_VirtualPortfolioResponse_Schema,
  VirtualPortfolioResponseSchema,
} from "@trading212/api-contracts";

const origin = "http://127.0.0.1:3001";
const api = "http://127.0.0.1:18000/api/v1";
const account = "f0f5c66e-b128-59b2-a620-83bc8faa4a57";

test("late saved Pie result cannot replace newer same-account Holdings intent", async ({
  page,
  request,
}, info) => {
  test.setTimeout(120_000);
  page.setDefaultTimeout(20_000);
  await page.goto("/sign-in");
  await page
    .getByRole("button", { name: "Start local session", exact: true })
    .click();
  await expect(page).toHaveURL(origin + "/");
  expect((await request.post(api + "/auth/local-session")).status()).toBe(201);
  await page.goto("/pies?account=" + account);
  await expect(
    page.getByRole("heading", { name: "Pies", exact: true }),
  ).toBeVisible();
  const name = "H2 same-account " + randomUUID();
  const fieldset = page.getByRole("group", {
    name: "New Pie details",
    exact: true,
  });
  await fieldset.getByRole("textbox", { name: "Name", exact: true }).fill(name);
  await expect(
    fieldset.getByRole("combobox", { name: "Account", exact: true }),
  ).toHaveValue(account);
  const oldForm = await fieldset.elementHandle();
  expect(oldForm).not.toBeNull();
  if (!oldForm) throw new Error("Create Pie fieldset was not mounted");

  let releaseAction = () => {};
  let releaseNavigation = () => {};
  const actionGate = new Promise<void>((resolve) => {
    releaseAction = resolve;
  });
  const navigationGate = new Promise<void>((resolve) => {
    releaseNavigation = resolve;
  });
  const events: string[] = [];
  const routeErrors: string[] = [];
  const staleRequests: string[] = [];
  const staleCommits: string[] = [];
  let actionFetched = false;
  let actionDelivered = false;
  let navigationIntent = false;
  let navigationFetched = false;
  let navigationDelivered = false;
  let pieId: string | undefined;
  const onRequest = (incoming: import("@playwright/test").Request) => {
    if (pieId && new URL(incoming.url()).pathname === "/pies/" + pieId) {
      staleRequests.push("/pies/" + pieId);
    }
  };
  const onNavigation = (frame: import("@playwright/test").Frame) => {
    if (
      frame === page.mainFrame() &&
      pieId &&
      new URL(frame.url()).pathname === "/pies/" + pieId
    ) {
      staleCommits.push("/pies/" + pieId);
    }
  };
  page.on("request", onRequest);
  page.on("framenavigated", onNavigation);
  try {
    await page.route(
      (url) =>
        url.origin === origin && ["/pies", "/holdings"].includes(url.pathname),
      async (route) => {
        const incoming = route.request();
        const url = new URL(incoming.url());
        const headers = incoming.headers();
        const action =
          url.pathname === "/pies" &&
          incoming.method() === "POST" &&
          Boolean(headers["next-action"]);
        const navigation =
          url.pathname === "/holdings" &&
          incoming.method() === "GET" &&
          headers.rsc === "1" &&
          url.searchParams.get("account") === account;
        if (!action && !navigation) return route.continue();
        try {
          if (
            navigation &&
            (!navigationIntent || headers["next-router-prefetch"] === "1")
          )
            throw new Error(
              "Holdings request did not follow explicit navigation intent",
            );
          // Fetch and preserve the real Next response, including its Flight body.
          // Neither a successful action DTO nor a navigation response is invented.
          const response = await route.fetch({
            timeout: 20_000,
            maxRedirects: 0,
          });
          await response.body();
          if (
            response.status() !== 200 ||
            !response.headers()["content-type"]?.startsWith("text/x-component")
          )
            throw new Error(
              "Expected an actual successful Next Flight response",
            );
          events.push(
            action ? "action-response-held" : "holdings-response-held",
          );
          if (action) actionFetched = true;
          else navigationFetched = true;
          await (action ? actionGate : navigationGate);
          await route.fulfill({ response });
          events.push(
            action
              ? "action-response-delivered"
              : "holdings-response-delivered",
          );
          if (action) actionDelivered = true;
          else navigationDelivered = true;
        } catch {
          // Do not put Playwright request diagnostics/headers in the attachment.
          routeErrors.push(
            action ? "action route failed" : "Holdings route failed",
          );
          await route.abort("failed").catch(() => {});
        }
      },
    );
    await fieldset
      .getByRole("button", { name: "Create Pie", exact: true })
      .click({ noWaitAfter: true });
    await expect
      .poll(() => actionFetched || routeErrors.length > 0, {
        message:
          "Precondition: actual saved action response must be fetched and held",
        timeout: 25_000,
      })
      .toBe(true);
    expect(routeErrors).toEqual([]);
    const collectionResponse = await request.get(api + "/virtual-portfolios", {
      params: {
        account_id: account,
        search: name,
        state: "all",
        sort: "name_asc",
        limit: 5,
      },
    });
    expect(collectionResponse.status()).toBe(200);
    const collection = TargetPageResponse_VirtualPortfolioResponse_Schema.parse(
      await collectionResponse.json(),
    );
    expect(collection.total).toBe(1);
    expect(collection.items).toHaveLength(1);
    const saved = collection.items[0]!;
    expect(saved.name).toBe(name);
    expect(saved.account_id).toBe(account);
    pieId = saved.id;
    const savedResponse = await request.get(
      api + "/virtual-portfolios/" + pieId,
    );
    expect(savedResponse.status()).toBe(200);
    expect(
      VirtualPortfolioResponseSchema.parse(await savedResponse.json()),
    ).toEqual(saved);
    events.push("saved-object-confirmed-by-api");
    expect(actionDelivered).toBe(false);
    const holdings = page
      .locator("a:visible")
      .filter({ hasText: /^Holdings$/ })
      .first();
    await expect(holdings).toHaveAttribute(
      "href",
      "/holdings?account=" + account,
    );
    navigationIntent = true;
    events.push("holdings-intent");
    // SPA clicks must not wait for the deliberately withheld response.
    await holdings.click({ noWaitAfter: true });
    await expect
      .poll(() => navigationFetched || routeErrors.length > 0, {
        message:
          "Precondition: actual Holdings RSC must arrive while action remains held",
        timeout: 25_000,
      })
      .toBe(true);
    expect(routeErrors).toEqual([]);
    expect(actionDelivered).toBe(false);
    expect(navigationDelivered).toBe(false);
    expect(await oldForm.evaluate((node) => node.isConnected)).toBe(true);
    await expect(
      fieldset.getByRole("button", { name: "Creating…", exact: true }),
    ).toBeDisabled();
    events.push("old-form-connected-before-action-delivery");
    releaseAction();
    await expect
      .poll(() => actionDelivered || routeErrors.length > 0)
      .toBe(true);
    expect(routeErrors).toEqual([]);
    // Observe the actual caller settling while Holdings is still held. A stale
    // detail request is also a completion signal, but remains a failing outcome.
    await expect
      .poll(
        async () =>
          staleRequests.length > 0 ||
          (await oldForm.evaluate(
            (node) => node.isConnected && !node.hasAttribute("disabled"),
          )),
        {
          message:
            "Precondition: client action must settle before held navigation returns",
          timeout: 20_000,
        },
      )
      .toBe(true);
    events.push("client-completion-observed");
    expect(navigationDelivered).toBe(false);
    releaseNavigation();
    await expect
      .poll(() => navigationDelivered || routeErrors.length > 0)
      .toBe(true);
    await expect(page).toHaveURL(origin + "/holdings?account=" + account);
    await expect(
      page.getByRole("heading", { name: "Holdings", exact: true }),
    ).toBeVisible();
    expect(await oldForm.evaluate((node) => node.isConnected)).toBe(false);
    expect(
      staleRequests,
      "Late Create Pie continuation must not navigate to its saved detail",
    ).toEqual([]);
    expect(staleCommits).toEqual([]);
    expect(routeErrors).toEqual([]);
  } finally {
    // Always drain both real responses and remove interception, even on a failed
    // race precondition; never leave Next blocked behind a test-owned gate.
    releaseAction();
    releaseNavigation();
    try {
      await page.unrouteAll({ behavior: "wait" });
    } finally {
      page.off("request", onRequest);
      page.off("framenavigated", onNavigation);
      await info.attach("navigation-race-order", {
        body: JSON.stringify(
          {
            events,
            actionFetched,
            actionDelivered,
            navigationIntent,
            navigationFetched,
            navigationDelivered,
            staleRequests,
            staleCommits,
            routeErrors,
          },
          null,
          2,
        ),
        contentType: "application/json",
      });
    }
  }
});
