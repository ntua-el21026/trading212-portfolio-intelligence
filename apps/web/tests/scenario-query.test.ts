import { describe, expect, it } from "vitest";
import { accountSwitchHref } from "../lib/account-selection";
import {
  readScenarioQuery,
  scenarioHref,
  ScenarioQueryError,
} from "../lib/scenario-query";
const id = "d778f930-9d2e-4f47-b24f-5b1fa99c6eee";
const other = "2f34c23a-3798-4d4a-9133-9cd47639dd37";
const options = { now: new Date("2026-09-15T12:00:00Z"), currency: "EUR" };
describe("saved scenario URL selections", () => {
  it("preserves ordered comparison identities, exact cutoff and component cursor", () => {
    const query = readScenarioQuery(
      {
        account: id,
        view: "compare",
        before: id,
        after: other,
        cutoff: "2026-09-07T12:00:00.123456+03:00",
        capture: id,
        xray: id,
        version: id,
        snapshot: id,
      },
      options,
    );
    const url = new URL(
      scenarioHref(query, { component_cursor: "signed_cursor" }),
      "https://portfolio.example",
    );
    expect(
      readScenarioQuery(Object.fromEntries(url.searchParams), options),
    ).toEqual({ ...query, component_cursor: "signed_cursor" });
    expect(query.cutoff).toBe("2026-09-07T12:00:00.123456+03:00");
    expect(query.before).toBe(id);
    expect(query.after).toBe(other);
  });
  it("normalizes a UTC local timestamp without losing explicit fractional digits", () => {
    expect(
      readScenarioQuery({ cutoff: "2026-09-07T12:30" }, options).cutoff,
    ).toBe("2026-09-07T12:30:00Z");
    expect(
      readScenarioQuery({ cutoff: "2026-09-07T12:30:00.123456" }, options)
        .cutoff,
    ).toBe("2026-09-07T12:30:00.123456Z");
  });
  it.each([
    { account: [id, id] },
    { before: id, after: id },
    { version: "private-canary" },
    { view: "result" },
    { run: "../private-canary" },
    { url: "https://private-canary" },
    { component_cursor: "x".repeat(2049) },
    { component_cursor: "a/b" },
    { cutoff: "2026-02-30T12:00:00Z" },
    { cutoff: "2026-09-07T24:00:00Z" },
    { start_date: "2025-02-30" },
    { start_date: "2025-12-31", end_date: "2025-01-01" },
    { start_date: "2000-01-01", end_date: "2025-01-01" },
    { currency: "usd" },
    { holdings: "automatic" },
  ])("rejects ambiguous, invalid and unbounded selections: %j", (search) => {
    expect(() => readScenarioQuery(search, options)).toThrow(
      ScenarioQueryError,
    );
    try {
      readScenarioQuery(search, options);
    } catch (error) {
      expect(String(error)).not.toContain("private-canary");
    }
  });
  it("drops every account-owned identity, cutoff, view and cursor when switching accounts", () => {
    const query = readScenarioQuery(
      {
        account: id,
        definition: id,
        version: id,
        snapshot: id,
        xray: id,
        capture: id,
        before: id,
        after: other,
        run: id,
        component_cursor: "signed",
        runs_cursor: "signed",
      },
      options,
    );
    const url = new URL(scenarioHref(query), "https://portfolio.example");
    expect(accountSwitchHref("/scenarios", url.searchParams, other)).toBe(
      `/scenarios?account=${other}&start_date=2025-01-01&end_date=2025-12-31`,
    );
  });
});
