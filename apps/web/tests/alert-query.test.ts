import { describe, expect, it } from "vitest";
import { alertHref, parseAlertQuery, parseAlertUrl } from "../lib/alert-query";

describe("strict alert navigation", () => {
  it("preserves all history filters and evaluation cursors", () => {
    const selected = parseAlertQuery({
      view: "events",
      severity: "critical",
      event_state: "resolved",
      start_date: "2026-09-01",
      end_date: "2026-09-10",
      cursor: "first",
      limit: "50",
      evaluation_cursor: "proof",
      evaluation_limit: "10",
    });
    expect(
      parseAlertQuery(
        Object.fromEntries(
          new URL(alertHref(selected), "https://test.invalid").searchParams,
        ),
      ),
    ).toEqual(selected);
  });
  it.each([
    { token: "private" },
    Object.fromEntries([["__proto__", "x"]]),
    { state: "open" },
    { rule_state: ["active", "paused"] },
    { start_date: "2026-09-01" },
    { start_date: "2026-09-10", end_date: "2026-09-01" },
    { limit: "101" },
    { limit: "1.5" },
  ])("rejects ambiguous or unsupported query %j", (query) => {
    expect(() => parseAlertQuery(query)).toThrow();
  });
  it("accepts unselected optional GET form inputs without dropping unknown keys", () => {
    expect(
      parseAlertQuery({ start_date: "", end_date: "", rule: "" }).view,
    ).toBe("rules");
    expect(() => parseAlertQuery({ unknown: "" })).toThrow();
  });
  it.each(["__proto__=x", "unknown=x", "rule_state=active&rule_state=paused"])(
    "rejects the actual browser URL without losing raw keys: %s",
    (query) => {
      expect(() => parseAlertUrl(new URLSearchParams(query))).toThrow();
    },
  );
});
