import { describe, expect, it } from "vitest";
import { readResearchQuery, researchHref } from "../lib/research-query";
import { accountSwitchHref } from "../lib/account-selection";
import { account, id, other, at } from "./research-ui-fixtures";
const query = () =>
  readResearchQuery(
    { account, xray: id, cutoff: at, cursor: "saved_cursor" },
    new Date(at),
  );
describe("research immutable selection", () => {
  it("preserves microsecond cutoffs and clears every cursor when filters change", () => {
    const current = query();
    expect(current.cutoff).toBe(at);
    const page = new URL(
      researchHref(current, { cursor: "page_two" }),
      "https://local.test",
    );
    expect(page.searchParams.get("cursor")).toBe("page_two");
    const changed = new URL(
      researchHref(current, { review_state: "unreviewed" }),
      "https://local.test",
    );
    expect(changed.searchParams.has("cursor")).toBe(false);
    expect(changed.searchParams.get("cutoff")).toBe(at);
  });
  it.each([
    { xray: [id, other] },
    { cutoff: "2026-13-01" },
    { cutoff: "2026-09-15T12:00:00.1234567Z" },
    { unknown: "value" },
    { cursor: "x".repeat(2049) },
    { view: "item" },
    { versions_cursor: "orphan" },
  ])("rejects invalid or ambiguous selectors %o", (extra) => {
    expect(() =>
      readResearchQuery({ account, ...extra }, new Date(at)),
    ).toThrow();
  });
  it("drops owned pins and all cursors on an account change", () => {
    expect(
      accountSwitchHref(
        "/research",
        new URLSearchParams({
          account,
          xray: id,
          item: id,
          note: id,
          entity: id,
          cursor: "one",
          cutoff: at,
          start_date: "2026-09-01",
          view: "item",
        }),
        other,
      ),
    ).toBe(`/research?account=${other}`);
  });
});
