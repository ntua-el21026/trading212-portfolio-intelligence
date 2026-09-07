import { describe, expect, it } from "vitest";
import {
  HistoricalQueryError,
  historicalHref,
  readHistoricalQuery,
  type HistoricalSearch,
} from "../lib/historical-query";

const account = "d778f930-9d2e-4f47-b24f-5b1fa99c6eee";
const capture = "2f34c23a-3798-4d4a-9133-9cd47639dd37";
const options = {
  now: new Date("2026-09-07T12:00:00.123Z"),
  currency: "EUR",
  pathname: "/performance" as const,
};

function read(search: HistoricalSearch = {}) {
  return readHistoricalQuery(search, options);
}

describe("historical URL selection", () => {
  it("defaults to the previous complete calendar year and explicit current cutoff", () => {
    expect(read()).toMatchObject({
      start: "2025-01-01",
      end: "2025-12-31",
      cutoff: "2026-09-07T12:00:00.123Z",
      currency: "EUR",
      method: "twr",
      frequency: "monthly",
      knowledge: "as_of_cutoff",
      coverage: "require_complete",
      view: "summary",
      limit: 25,
      top: 25,
    });
  });
  it.each([
    ["2026-08-31T15:34:56.123456+03:00", "2026-08-31T12:34:56.123456Z"],
    ["2026-08-31T23:45:00.000001-02:00", "2026-09-01T01:45:00.000001Z"],
    ["2026-08-31T12:34:56.654321", "2026-08-31T12:34:56.654321Z"],
    ["2026-08-31T12:34", "2026-08-31T12:34:00Z"],
  ])("preserves six-digit source precision for %s", (cutoff, expected) => {
    expect(read({ cutoff }).cutoff).toBe(expected);
  });
  it.each([
    { "private-query-canary": "private-value-canary" },
    { account: [account, account] },
    { start: "2025-02-30" },
    { start: "2025-01-02", end: "2025-01-01" },
    { start: "2000-01-01", end: "2025-01-01" },
    { cutoff: "2026-08-31T12:00:00.1234567Z" },
    { cutoff: "2026-09-08T00:00:00Z" },
    { cutoff: "2026-09-07T12:00:00.123001Z" },
    { cutoff: "2026-08-31T24:00:00Z" },
    { end: "2026-09-07" },
    { currency: "eur" },
    { method: "formula" },
    { top: "51" },
    { top: "1e1" },
    { limit: "101" },
    { limit: "1.0" },
    { capture: "../private" },
    { cursor: " x " },
    { grouping_policy: "historical_assignment" },
    { view: "attribution", method: "mwr" },
    { view: "cash_flows" },
  ])(
    "rejects malformed or future selection %j with a fixed safe error",
    (search) => {
      let failure: unknown;
      try {
        read(search);
      } catch (error) {
        failure = error;
      }
      expect(failure).toBeInstanceOf(HistoricalQueryError);
      expect(String(failure)).not.toContain("canary");
    },
  );
  it("enforces income-only grouping and view families", () => {
    expect(() =>
      readHistoricalQuery(
        { grouping: "sector" },
        { ...options, pathname: "/income" },
      ),
    ).toThrow(HistoricalQueryError);
    expect(() =>
      readHistoricalQuery(
        { view: "benchmark" },
        { ...options, pathname: "/income" },
      ),
    ).toThrow(HistoricalQueryError);
    expect(
      readHistoricalQuery(
        { view: "cash_flows", kind: "dividend" },
        { ...options, pathname: "/income" },
      ),
    ).toMatchObject({ view: "cash_flows", kind: "dividend" });
  });
  it("keeps exact capture and selectors when continuing its signed page", () => {
    const query = read({
      account,
      capture,
      view: "series",
      cutoff: "2026-08-31T12:00:00.123456Z",
    });
    const url = new URL(
      historicalHref("/performance", query, { cursor: "signed_cursor" }),
      "https://portfolio.example",
    );
    expect(url.searchParams.get("capture")).toBe(capture);
    expect(url.searchParams.get("cursor")).toBe("signed_cursor");
    expect(url.searchParams.get("cutoff")).toBe(query.cutoff);
  });
  it.each([
    { method: "mwr" as const },
    { knowledge: "point_in_time" as const },
    { currency: "USD" },
    { start: "2025-02-01" },
    { benchmark: account },
  ])(
    "drops capture and cursor when changing input-affecting selection %j",
    (changes) => {
      const url = new URL(
        historicalHref(
          "/performance",
          read({ capture, cursor: "previous_cursor" }),
          changes,
        ),
        "https://portfolio.example",
      );
      expect(url.searchParams.has("capture")).toBe(false);
      expect(url.searchParams.has("cursor")).toBe(false);
    },
  );
  it("resets a page cursor when changing its bound while preserving compatible input capture", () => {
    const url = new URL(
      historicalHref(
        "/performance",
        read({ capture, cursor: "previous_cursor", view: "series" }),
        { limit: 50 },
      ),
      "https://portfolio.example",
    );
    expect(url.searchParams.has("cursor")).toBe(false);
    expect(url.searchParams.get("capture")).toBe(capture);
  });
  it("keeps the financial capture while toggling a display overlay or benchmark-choice page", () => {
    const original = read({ capture, cursor: "previous_cursor" });
    for (const changes of [
      { flows: "hide" as const },
      { benchmarks_cursor: "catalog_cursor" },
    ]) {
      const url = new URL(
        historicalHref("/performance", original, changes),
        "https://portfolio.example",
      );
      expect(url.searchParams.get("capture")).toBe(capture);
      expect(url.searchParams.get("cursor")).toBe("previous_cursor");
    }
  });
});
