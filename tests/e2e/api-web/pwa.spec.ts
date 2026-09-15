import { expect, test } from "@playwright/test";
import { assertAccessible } from "./axe";

test("public offline shell never retains account pages or successful private responses", async ({
  page,
  context,
}, info) => {
  test.setTimeout(180_000);
  const width = info.project.name.includes("mobile")
    ? 360
    : info.project.name.includes("tablet")
      ? 768
      : 1440;
  await page.setViewportSize({
    width,
    height: width === 360 ? 800 : width === 768 ? 1024 : 900,
  });
  await page.goto("/sign-in");
  await page.getByRole("button", { name: "Start local session" }).click();
  await expect(page).toHaveURL("http://127.0.0.1:3001/");
  await page.evaluate(async () => {
    await navigator.serviceWorker.ready;
  });
  await expect
    .poll(() =>
      page.evaluate(() => navigator.serviceWorker.controller?.scriptURL),
    )
    .toBe("http://127.0.0.1:3001/sw.js");
  const manifest = await (
    await page.request.get("/manifest.webmanifest")
  ).json();
  expect(manifest).toMatchObject({
    id: "/",
    start_url: "/",
    scope: "/",
    display: "standalone",
  });
  expect(manifest.icons).toHaveLength(3);
  expect(
    manifest.icons.map((icon: { sizes: string; purpose: string }) => [
      icon.sizes,
      icon.purpose,
    ]),
  ).toEqual([
    ["192x192", "any"],
    ["512x512", "any"],
    ["512x512", "maskable"],
  ]);
  for (const icon of manifest.icons as { src: string; sizes: string }[]) {
    const dimensions = await page.evaluate(async (src) => {
      const image = new Image();
      image.src = src;
      await image.decode();
      return `${image.naturalWidth}x${image.naturalHeight}`;
    }, icon.src);
    expect(dimensions).toBe(icon.sizes);
  }
  expect(
    (await page.request.get("/sw.js")).headers()["cache-control"],
  ).toContain("no-store");
  await page.goto("/settings?account=86ecdc4c-6c42-5593-84ed-de7bde3a6c4c");
  await expect(
    page.getByRole("heading", {
      name: "Install & offline access",
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    page.getByText("The public offline shell is ready.", { exact: false }),
  ).toBeVisible();
  await expect(
    page.getByText(
      "Push notifications are unavailable because delivery is not configured.",
      { exact: false },
    ),
  ).toBeVisible();
  const paletteButton = page.getByRole("button", {
    name: "Open command palette",
    exact: true,
  });
  await paletteButton.focus();
  await page.keyboard.press("Control+k");
  const palette = page.getByRole("dialog", { name: "Go to a workspace" });
  const search = palette.getByRole("combobox", { name: "Search pages" });
  await expect(search).toBeFocused();
  await search.fill("https://private.invalid/execute");
  await expect(palette.getByRole("status")).toHaveText(
    "No matching workspace.",
  );
  await search.press("Enter");
  await expect(page).toHaveURL(/\/settings\?account=/);
  await search.fill("risk");
  const result = palette.getByRole("option");
  await expect(result).toHaveCount(1);
  await expect(result).toHaveAttribute(
    "href",
    "/risk?account=86ecdc4c-6c42-5593-84ed-de7bde3a6c4c",
  );
  await assertAccessible(page);
  await page.screenshot({
    path: info.outputPath("pwa-command-palette.png"),
    fullPage: true,
  });
  await search.press("Escape");
  await expect(palette).not.toBeVisible();
  await expect(paletteButton).toBeFocused();
  await paletteButton.click();
  await search.fill("hold");
  await search.press("ArrowDown");
  await search.press("Enter");
  await expect(page).toHaveURL(
    /\/holdings\?account=86ecdc4c-6c42-5593-84ed-de7bde3a6c4c$/,
  );
  await expect(palette).not.toBeVisible();
  await page.goto("/settings?account=f0f5c66e-b128-59b2-a620-83bc8faa4a57");
  await paletteButton.click();
  await search.fill("risk");
  await expect(
    palette.getByRole("option", { name: "Risk", exact: true }),
  ).toHaveAttribute(
    "href",
    "/risk?account=f0f5c66e-b128-59b2-a620-83bc8faa4a57",
  );
  await search.press("Escape");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await expect(
    page.getByRole("heading", {
      name: "Install & offline access",
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    page.getByText("The public offline shell is ready.", { exact: false }),
  ).toBeVisible();
  await assertAccessible(page);
  await page.screenshot({
    path: info.outputPath("pwa-install-settings.png"),
    fullPage: true,
  });
  const account = new URL(page.url()).searchParams.get("account");
  // Real authenticated HTML passes through the controlled browser, but is not stored.
  const body = await page.evaluate(async () =>
    (await fetch("/holdings")).text(),
  );
  expect(body).toContain("Holdings");
  const cacheState = async () =>
    page.evaluate(async () => {
      const names = (await caches.keys()).filter((name) =>
        name.startsWith("t212pi-public-shell-"),
      );
      const entries = [] as {
        name: string;
        path: string;
        text: string | null;
      }[];
      for (const name of names) {
        const cache = await caches.open(name);
        for (const request of await cache.keys()) {
          const response = (await cache.match(request))!;
          entries.push({
            name,
            path: new URL(request.url).pathname,
            text: response.headers.get("content-type")?.startsWith("text/html")
              ? await response.text()
              : null,
          });
        }
      }
      return entries;
    });
  const before = await cacheState();
  expect(before.map((item) => item.path).sort()).toEqual(
    [
      "/pwa/icon-192-v1.png",
      "/pwa/icon-512-v1.png",
      "/pwa/maskable-512-v1.png",
      "/pwa/offline-v1.css",
      "/pwa/offline-v1.html",
    ].sort(),
  );
  expect(JSON.stringify(before)).not.toMatch(
    /Synthetic EUR Portfolio|t212pi_session|t212pi_csrf/,
  );
  await context.setOffline(true);
  try {
    await page.goto(
      `/holdings?${new URLSearchParams({ account: account ?? "f0f5c66e-b128-59b2-a620-83bc8faa4a57" })}`,
    );
    await expect(
      page.getByRole("heading", { name: "You are offline", exact: true }),
    ).toBeVisible();
    await expect(
      page.getByText("Synthetic EUR Portfolio", { exact: true }),
    ).toHaveCount(0);
    const failure = await page.evaluate(async () => {
      try {
        await fetch("/api/private-canary");
        return false;
      } catch {
        return true;
      }
    });
    expect(failure).toBe(true);
    await page.getByRole("link", { name: "Try again", exact: true }).focus();
    const focused = await page
      .getByRole("link", { name: "Try again", exact: true })
      .boundingBox();
    expect(focused).not.toBeNull();
    expect(focused!.x).toBeGreaterThanOrEqual(0);
    expect(focused!.x + focused!.width).toBeLessThanOrEqual(width);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await assertAccessible(page);
    await page.screenshot({
      path: info.outputPath("pwa-public-offline.png"),
      fullPage: true,
    });
    expect(await cacheState()).toEqual(before);
  } finally {
    await context.setOffline(false);
  }
  await page.goto("/settings");
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(page).toHaveURL(/\/sign-in$/);
  expect(await cacheState()).toEqual(before);
  await expect(
    page.getByText("Synthetic EUR Portfolio", { exact: true }),
  ).toHaveCount(0);
});
