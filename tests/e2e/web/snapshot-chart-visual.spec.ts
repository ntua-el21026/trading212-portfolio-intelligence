import { expect, test } from "@playwright/test";

// Existing demo-data.ts uses fixed UTC timestamps and exact decimal strings.
// The normal demo Playwright server enables its 65-record collection fixture.
// No API, React, Recharts, financial text or chart geometry is intercepted.
test("actual snapshot SVG preserves UTC spacing and exact fixture values in reviewed visuals", async ({
  page,
}, info) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  await page.goto("/sign-in");
  await page.getByRole("button", { name: "Enter demo portfolio" }).click();
  await expect(
    page.getByRole("heading", { name: "Overview", exact: true }),
  ).toBeVisible();
  await page.goto("/snapshots");
  await expect(
    page.getByRole("heading", { name: "Snapshots", exact: true }),
  ).toBeVisible();
  const plot = page.getByRole("img", {
    name: "Portfolio value by immutable snapshot",
  });
  const figure = plot.locator("..");
  await expect(figure.locator("figcaption")).toHaveText(
    "Snapshot observations · EUR · UTC",
  );
  await expect(figure).toContainText("No daily observations are inferred.");
  await expect(
    page.getByText(
      "Showing 50 records on this page out of 65 matching records.",
      { exact: true },
    ),
  ).toBeVisible();
  await expect(plot.locator("svg.recharts-surface")).toBeVisible();
  const dots = plot.locator("circle.recharts-line-dot");
  await expect(dots).toHaveCount(50);
  const coordinates = await dots.evaluateAll((nodes) =>
    nodes.map((node) => ({
      x: Number(node.getAttribute("cx")),
      y: Number(node.getAttribute("cy")),
    })),
  );
  for (const [index, point] of coordinates.entries()) {
    expect(Number.isFinite(point.x) && Number.isFinite(point.y)).toBe(true);
    if (index > 0) expect(point.x).toBeGreaterThan(coordinates[index - 1].x);
  }
  // The last three observations are Jun 30, Jul 31 and Aug 31. Their irregular
  // elapsed UTC intervals must control x positions; record index spacing fails.
  const [june, july, august] = coordinates.slice(-3);
  const expectedRatio =
    (Date.parse("2026-08-31T09:30:00Z") - Date.parse("2026-07-31T16:30:00Z")) /
    (Date.parse("2026-07-31T16:30:00Z") - Date.parse("2026-06-30T16:30:00Z"));
  expect((august.x - july.x) / (july.x - june.x)).toBeCloseTo(expectedRatio, 5);
  const curve = plot.locator("path.recharts-line-curve");
  await expect(curve).toHaveCount(1);
  const path = await curve.getAttribute("d");
  expect(path).not.toBeNull();
  expect(path!.match(/[Mm]/gu)).toHaveLength(1);
  await expect(
    plot
      .locator(
        ".recharts-yAxis-tick-labels .recharts-cartesian-axis-tick-value",
      )
      .filter({ hasText: /^0$/u }),
  ).toHaveCount(1);
  await page.evaluate(() => document.fonts.ready.then(() => undefined));
  await page.mouse.move(0, 0);

  // Project/platform-specific Playwright filenames are intentional. No masks,
  // injected styles, clock rewriting, animation suppression or seeded images.
  await expect(figure).toHaveScreenshot("snapshot-observations.png", {
    animations: "allow",
    maxDiffPixels: 0,
  });
  await dots.last().hover();
  const tooltip = plot.locator(".recharts-tooltip-wrapper");
  await expect(
    tooltip.getByText("248431.27 EUR", { exact: true }),
  ).toBeVisible();
  await expect(
    tooltip.getByText("2026-08-31T09:30:00Z", { exact: true }),
  ).toBeVisible();
  await expect(
    tooltip.getByText("Source cutoff: 2026-08-31T09:28:00Z", {
      exact: true,
    }),
  ).toBeVisible();
  await expect(figure).toHaveScreenshot("snapshot-observations-tooltip.png", {
    animations: "allow",
    maxDiffPixels: 0,
  });

  const summary = figure.locator("summary").first();
  await summary.click();
  const table = figure.getByRole("table", {
    name: "Snapshot chart: exact server values in original page order",
  });
  await expect(table.locator("tbody tr")).toHaveCount(50);
  const latest = table.locator("tbody tr").first();
  await expect(latest).toContainText("Snapshot: snapshot-2026-08-31");
  await expect(latest).toContainText("248431.27 EUR");
  await expect(latest).toContainText("2026-08-31T09:28:00Z");
  await expect(table.locator("tbody tr").nth(1)).toContainText("241220.18 EUR");
  await expect(latest).toContainText("Fresh");
  await latest.getByText("Method and provenance", { exact: true }).click();
  await expect(latest).toContainText("phase1-core-accounting/1.0.0");
  await expect(latest).toContainText("synthetic_canonical_fixture");
  expect(
    await page.evaluate(
      () =>
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
    ),
  ).toBeLessThanOrEqual(1);
  await info.attach("snapshot-geometry", {
    body: JSON.stringify({
      fixture: "existing deterministic demo collection; first 50 of 65",
      viewport: page.viewportSize(),
      coordinates,
      expectedUtcIntervalRatio: expectedRatio,
      observedUtcIntervalRatio: (august.x - july.x) / (july.x - june.x),
      source:
        "actual rendered SVG; synthetic demo data, not runtime acceptance",
    }),
    contentType: "application/json",
  });
  expect(errors).toEqual([]);
});
