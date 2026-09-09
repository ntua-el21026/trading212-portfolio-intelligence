import { describe, expect, it } from "vitest";
import {
  readXrayQuery,
  xrayHref,
  xrayRunQuery,
  XrayQueryError,
} from "../lib/xray-query";

const first = "00000000-0000-4000-8000-000000000001";
const second = "00000000-0000-4000-8000-000000000002";
const defaults = {
  now: new Date("2026-09-07T12:00:00Z"),
  currency: "EUR",
  snapshot: first,
};

describe("X-ray URL identity", () => {
  it("keeps economic pins and microsecond cutoff while changing projection", () => {
    const query = readXrayQuery(
      {
        account: first,
        run: second,
        cutoff: "2026-09-07T10:00:00.123456Z",
        cursor: "opaque",
      },
      defaults,
    );
    const url = new URL(
      xrayHref(query, { dimension: "sector", normalized: true }),
      "https://portfolio.example",
    );
    expect(url.searchParams.get("run")).toBe(second);
    expect(url.searchParams.get("cutoff")).toBe("2026-09-07T10:00:00.123456Z");
    expect(url.searchParams.has("cursor")).toBe(false);
    const changed = new URL(xrayHref(query, { currency: "USD" }), url);
    expect(changed.searchParams.has("run")).toBe(false);
    expect(changed.searchParams.has("cursor")).toBe(false);
    expect(xrayRunQuery(query).snapshot_id).toBe(first);
  });
  it("preserves repeated selected funds through discovery pagination", () => {
    const query = readXrayQuery(
      { view: "held_funds", fund_ids: [first, second] },
      defaults,
    );
    const url = new URL(
      xrayHref(query, { cursor: "next" }),
      "https://portfolio.example",
    );
    expect(url.searchParams.getAll("fund_ids")).toEqual([first, second]);
  });
  it.each([
    { dimension: ["company", "sector"] },
    { private_key: "canary" },
    { normalized: "yes" },
    { fund_ids: [first, first] },
    { view: "pairs", fund_ids: first },
    { view: "paths" },
    {
      view: "common_entities",
      run: second,
      fund_ids: [first, second],
      left: first,
      right: first,
    },
    { cutoff: "2026-02-30T12:00:00Z" },
    { cutoff: "2026-09-07T12:00:00.1234567Z" },
    { limit: "1.0" },
    { limit: "101" },
  ])(
    "rejects invalid or ambiguous selectors without reflecting values",
    (search) => {
      expect(() => readXrayQuery(search, defaults)).toThrow(XrayQueryError);
      try {
        readXrayQuery(search, defaults);
      } catch (error) {
        expect(String(error)).not.toContain("canary");
      }
    },
  );
});
