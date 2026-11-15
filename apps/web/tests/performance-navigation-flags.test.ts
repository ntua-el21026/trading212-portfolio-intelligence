import { describe, expect, it } from "vitest";
import { navigationFlags } from "../../../tests/e2e/api-web/performance-navigation-flags";

const selection =
  "http://127.0.0.1:3001/research?account=private_account_canary&xray=private_pin_canary&cutoff=2026-11-15T12%3A00%3A00.123400%2B00%3A00&event_kind=news";
const next = `${selection}&cursor=private_cursor_canary`;

describe("private performance navigation diagnostics", () => {
  it("retains only booleans and never serializes selector or cursor canaries", () => {
    const flags = navigationFlags(next, selection, next);
    expect(flags).toEqual({
      sameOrigin: true,
      routeMatches: true,
      cursorPresent: true,
      cursorSyntaxValid: true,
      selectionMatchesExpected: true,
      cursorMatchesExpectedNext: true,
    });
    expect(
      Object.values(flags).every((value) => typeof value === "boolean"),
    ).toBe(true);
    expect(JSON.stringify(flags)).not.toMatch(/private_|http|research|2026/);
  });
  it("distinguishes stale filter state, a foreign destination and an invalid cursor", () => {
    expect(
      navigationFlags(
        next.replace("event_kind=news", "event_kind=all"),
        selection,
        next,
      ).selectionMatchesExpected,
    ).toBe(false);
    const foreign = navigationFlags(
      next.replace("127.0.0.1:3001", "other.invalid"),
      selection,
      next,
    );
    expect(foreign.sameOrigin).toBe(false);
    expect(foreign.selectionMatchesExpected).toBe(false);
    expect(foreign.cursorMatchesExpectedNext).toBe(false);
    expect(
      navigationFlags(
        next.replace("private_cursor_canary", "invalid%2Fcursor"),
        selection,
        next,
      ).cursorSyntaxValid,
    ).toBe(false);
  });
  it("normalizes equivalent UTC spelling without collapsing microsecond differences", () => {
    expect(
      navigationFlags(
        next.replace(".123400%2B00%3A00", ".1234Z"),
        selection,
        next,
      ).selectionMatchesExpected,
    ).toBe(true);
    expect(
      navigationFlags(next.replace(".123400", ".123401"), selection, next)
        .selectionMatchesExpected,
    ).toBe(false);
  });
  it("fails closed on malformed input without retaining the rejected value", () => {
    const flags = navigationFlags("http://[private_bad_url", selection, next);
    expect(Object.values(flags).every((value) => value === false)).toBe(true);
    expect(JSON.stringify(flags)).not.toContain("private_bad_url");
  });
});
