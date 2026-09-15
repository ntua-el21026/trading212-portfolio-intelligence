import { expect, test, type Page, type TestInfo } from "@playwright/test";
import {
  ResearchItemViewSchema,
  ResearchNotePageSchema,
  ResearchNoteRevisionSchema,
  ResearchSummarySchema,
  XrayExposuresResponseSchema,
  snapshotDetailSchema,
} from "@trading212/api-contracts";
import { keyboardClearance } from "./accessibility";
const api = "http://127.0.0.1:18000/api/v1";
const account = "86ecdc4c-6c42-5593-84ed-de7bde3a6c4c";
const otherAccount = "f0f5c66e-b128-59b2-a620-83bc8faa4a57";
const href = (fields: Record<string, string> = {}) =>
  `/research?${new URLSearchParams({ account, ...fields })}`;
async function capture(page: Page, info: TestInfo, name: string) {
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth - window.innerWidth,
    ),
  ).toBeLessThanOrEqual(1);
  await expect(page.getByRole("main")).toHaveCount(1);
  await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
  await keyboardClearance(page);
  await page.evaluate(() => {
    if (document.activeElement instanceof HTMLElement)
      document.activeElement.blur();
    window.scrollTo(0, 0);
  });
  await page.screenshot({
    path: info.outputPath(`research-${name}.png`),
    fullPage: true,
  });
}

test("retained research facts, exact exposure, owner revisions and review remain private across navigation", async ({
  page,
  request,
}, info) => {
  test.setTimeout(300_000);
  page.setDefaultTimeout(30_000);
  const width = info.project.name.includes("mobile")
    ? 360
    : info.project.name.includes("tablet")
      ? 768
      : 1440;
  await page.setViewportSize({ width, height: 900 });
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/sign-in");
  await page.getByRole("button", { name: "Start local session" }).click();
  await expect(page).toHaveURL("http://127.0.0.1:3001/");
  expect((await request.post(`${api}/auth/local-session`)).status()).toBe(201);
  const snapshotResponse = await request.get(
    `${api}/accounts/${account}/snapshots/latest`,
  );
  expect(snapshotResponse.status()).toBe(200);
  const snapshot = snapshotDetailSchema.parse(await snapshotResponse.json());
  const xrayResponse = await request.get(
    `${api}/accounts/${account}/effective-exposure`,
    {
      params: {
        snapshot_id: snapshot.id,
        source_cutoff_at: snapshot.source_cutoff_at,
        reporting_currency: "EUR",
        limit: 25,
      },
    },
  );
  expect(xrayResponse.status()).toBe(200);
  const xray = XrayExposuresResponseSchema.parse(await xrayResponse.json());
  await page.goto(
    `/xray?${new URLSearchParams({
      account,
      snapshot: snapshot.id,
      run: xray.context.run_id,
      currency: xray.context.reporting_currency,
      cutoff: xray.context.source_cutoff_at,
    })}`,
  );
  await page
    .getByRole("link", { name: "Research with this saved X-ray" })
    .click();
  await expect(
    page.getByRole("heading", { name: "Exposure-ranked research" }),
  ).toBeVisible();
  const cutoff = await page
    .getByLabel("Research source cutoff (ISO timestamp)")
    .inputValue();
  const summaryResponse = await request.get(
    `${api}/accounts/${account}/research`,
    {
      params: {
        xray_run_id: xray.context.run_id,
        source_cutoff_at: cutoff,
        limit: 25,
      },
    },
  );
  expect(summaryResponse.status()).toBe(200);
  expect(summaryResponse.headers()["cache-control"]).toContain("no-store");
  const summary = ResearchSummarySchema.parse(await summaryResponse.json());
  expect(summary.total).toBe(29);
  expect(summary.unknown_exposure_total).toBe(1);
  expect(summary.items).toHaveLength(25);
  expect(summary.next_cursor).not.toBeNull();
  expect(summary.pin.input_digest).toBe(xray.context.input_digest);
  expect(summary.pin.result_digest).toBe(xray.context.content_digest);
  const articles = page.getByTestId("research-item");
  await expect(articles).toHaveCount(summary.items.length);
  for (const [index, item] of summary.items.entries()) {
    const exposure = item.portfolio.effective_exposure;
    expect(exposure).not.toBeNull();
    await expect(
      articles.nth(index).getByTestId("research-portfolio-facts"),
    ).toContainText(`${exposure!.amount} ${exposure!.currency}`);
    expect(item.portfolio.effective_exposure).toEqual({
      amount: "560",
      currency: "EUR",
    });
    expect(item.portfolio.pin.result_digest).toBe(summary.pin.result_digest);
  }
  expect(
    await page.evaluate(() => Object.hasOwn(window, "researchInjected")),
  ).toBe(false);
  await capture(page, info, "summary");
  await page.getByRole("link", { name: "Next research items" }).click();
  await expect(page.getByTestId("research-item")).toHaveCount(4);
  const missing = page.getByTestId("research-item").filter({
    has: page.getByRole("heading", {
      name: "Synthetic entity absent from capture",
    }),
  });
  await expect(missing.getByTestId("research-portfolio-facts")).toContainText(
    "Unavailable · entity_absent_from_capture",
  );
  await expect(
    missing.getByTestId("research-portfolio-facts"),
  ).not.toContainText("0 EUR");
  await capture(page, info, "unavailable");
  await page.getByRole("link", { name: "First research items" }).click();
  await expect(page.getByTestId("research-item")).toHaveCount(25);
  await page.getByRole("link", { name: "Open research item" }).first().click();
  await expect
    .poll(() => new URL(page.url()).searchParams.get("item"))
    .not.toBeNull();
  const itemId = new URL(page.url()).searchParams.get("item");
  expect(itemId).not.toBeNull();
  const itemResponse = await request.get(`${api}/research/items/${itemId}`);
  expect(itemResponse.status()).toBe(200);
  const item = ResearchItemViewSchema.parse(await itemResponse.json());
  await expect(page.getByTestId("research-portfolio-facts")).toContainText(
    "560 EUR",
  );
  await page
    .getByText("Original source citations and permissions", { exact: true })
    .click();
  const citations = page.locator("details").filter({
    has: page.locator("summary", {
      hasText: "Original source citations and permissions",
    }),
  });
  for (const citation of item.source.citations) {
    await expect(citations).toContainText(citation.citation_id);
    await expect(citations).toContainText(citation.source.content_digest);
    await expect(citations).toContainText(citation.source.first_known_at);
    await expect(citations).toContainText(citation.source.license.attribution);
  }
  await expect(
    page.getByText("Optional synthesis: unavailable · disabled"),
  ).toBeVisible();
  await capture(page, info, "item");
  await page
    .getByRole("button", { name: "Mark this revision reviewed" })
    .click();
  await expect(page.getByText(/^Reviewed /)).toBeVisible();
  const reviewed = ResearchItemViewSchema.parse(
    await (await request.get(`${api}/research/items/${itemId}`)).json(),
  );
  expect(reviewed.review?.revision_id).toBe(item.source.revision_id);
  expect(reviewed.review?.revision_digest).toBe(item.source.content_digest);
  expect(reviewed.portfolio).toEqual(item.portfolio);
  const form = page.getByRole("form", { name: "Create owner note" });
  await expect(form.getByLabel("Note", { exact: true })).toHaveValue("");
  await form.getByLabel("Title", { exact: true }).fill("Browser owner thesis");
  await form
    .getByLabel("Thesis", { exact: true })
    .fill("My own assessment <script>inert owner prose</script>");
  await form
    .getByLabel("Risks", { exact: true })
    .fill("The stated premise may fail.");
  await form
    .getByLabel("Catalysts", { exact: true })
    .fill("Review the next public filing.");
  await form
    .getByLabel("Break conditions", { exact: true })
    .fill("The premise is contradicted by evidence.");
  await form.getByRole("checkbox").first().check();
  await form.getByRole("button", { name: "Save owner note" }).click();
  await expect
    .poll(() => new URL(page.url()).searchParams.get("note"))
    .not.toBeNull();
  const noteId = new URL(page.url()).searchParams.get("note")!;
  const note = ResearchNoteRevisionSchema.parse(
    await (await request.get(`${api}/research/notes/${noteId}`)).json(),
  );
  expect(note.revision).toBe(1);
  expect(note.content.thesis).toBe(
    "My own assessment <script>inert owner prose</script>",
  );
  expect(note.content.citations?.[0]?.citation_id).toBe(
    item.source.citations[0].citation_id,
  );
  expect(
    await page
      .locator("script")
      .evaluateAll((scripts) =>
        scripts.some(
          (script) =>
            script.textContent?.includes("inert owner prose") &&
            !script.textContent?.includes("self.__next_f"),
        ),
      ),
  ).toBe(false);
  const editor = page.getByRole("form", { name: "Append owner note revision" });
  const risks = editor.getByRole("textbox", { name: "Risks", exact: true });
  await expect(risks).toHaveValue("The stated premise may fail.");
  await risks.fill("Updated owner risk after review.");
  await editor.getByRole("button", { name: "Save new revision" }).click();
  await expect(
    editor.getByText("Append revision after 2", { exact: true }),
  ).toBeVisible();
  const history = ResearchNotePageSchema.parse(
    await (
      await request.get(`${api}/research/notes/${noteId}/versions`, {
        params: { limit: 25 },
      })
    ).json(),
  );
  expect(history.items.map((entry) => entry.revision).sort()).toEqual([1, 2]);
  expect(
    history.items.find((entry) => entry.revision === 1)?.content.risks,
  ).toBe("The stated premise may fail.");
  expect(
    history.items.find((entry) => entry.revision === 2)?.content.risks,
  ).toBe("Updated owner risk after review.");
  await capture(page, info, "owner-history");
  await page.goto(
    href({ xray: summary.pin.run_id, cutoff, event_kind: "company_overview" }),
  );
  await expect(page.getByTestId("research-item")).toHaveCount(1);
  await expect(
    page.getByRole("heading", { name: "Synthetic Beta overview" }),
  ).toBeVisible();
  await expect(
    page.getByText("Published: Unavailable · provider_publication_unavailable"),
  ).toBeVisible();
  await expect(page.getByTestId("research-portfolio-facts")).toContainText(
    "390 EUR",
  );
  await capture(page, info, "overview");
  await page.goto(
    href({ xray: summary.pin.run_id, cutoff, review_state: "reviewed" }),
  );
  await expect(page.getByTestId("research-item")).toHaveCount(1);
  const afterNotes = ResearchItemViewSchema.parse(
    await (await request.get(`${api}/research/items/${itemId}`)).json(),
  );
  expect(afterNotes.portfolio).toEqual(item.portfolio);
  expect(
    afterNotes.owner_revisions.some(
      (revision) => revision.note_id === noteId && revision.revision === 2,
    ),
  ).toBe(true);
  const currentXray = XrayExposuresResponseSchema.parse(
    await (
      await request.get(`${api}/accounts/${account}/effective-exposure`, {
        params: {
          run_id: summary.pin.run_id,
          snapshot_id: snapshot.id,
          source_cutoff_at: xray.context.source_cutoff_at,
          reporting_currency: "EUR",
          limit: 25,
        },
      })
    ).json(),
  );
  expect(currentXray.context.content_digest).toBe(xray.context.content_digest);
  expect(currentXray.exposures).toEqual(xray.exposures);
  await page
    .getByRole("combobox", { name: "Portfolio account", exact: true })
    .selectOption(otherAccount);
  await expect
    .poll(() => new URL(page.url()).searchParams.get("account"))
    .toBe(otherAccount);
  expect([...new URL(page.url()).searchParams.keys()]).toEqual(["account"]);
  await expect(page.getByTestId("research-item")).toHaveCount(0);
  await expect(
    page.getByText("Select a saved X-ray", { exact: true }),
  ).toBeVisible();
  await page.goto(
    `/research?${new URLSearchParams({ account: otherAccount, view: "item", item: itemId! })}`,
  );
  await expect(
    page.getByText("Research unavailable", { exact: true }),
  ).toBeVisible();
  await expect(page.getByTestId("research-item")).toHaveCount(0);
  await capture(page, info, "account-denial");
  await page.goto(`/settings?account=${account}`);
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(page).toHaveURL(/\/sign-in/);
  await page.goto(href({ view: "notes", note: noteId }));
  await expect(page).toHaveURL(/\/sign-in/);
  await expect(
    page.getByText("Browser owner thesis", { exact: true }),
  ).toHaveCount(0);
  await capture(page, info, "signed-out");
  expect(errors).toEqual([]);
});
