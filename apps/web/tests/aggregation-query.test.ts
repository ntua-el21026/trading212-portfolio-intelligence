import { describe, expect, it } from "vitest";
import {
  readAggregationQuery,
  aggregationHref,
} from "../lib/aggregation-query";
import { accountSwitchHref } from "../lib/account-selection";
const id = "00000000-0000-4000-8000-000000000001";
const other = "00000000-0000-4000-8000-000000000002";
describe("bounded aggregate navigation", () => {
  it("round trips exact result identity and opaque page while clearing owned pins on account switch", () => {
    const query = {
      account: other,
      view: "result" as const,
      selection: id,
      run: other,
      table: "components" as const,
      cursor: "opaque_page-01",
    };
    const url = new URL(aggregationHref(query), "https://local.test");
    expect(readAggregationQuery(Object.fromEntries(url.searchParams))).toEqual(
      query,
    );
    expect(accountSwitchHref(url.pathname, url.searchParams, id)).toBe(
      `/aggregation?account=${id}`,
    );
    const tab = new URL(
      aggregationHref({ ...query, table: "holdings", cursor: undefined }),
      url,
    );
    expect(tab.searchParams.has("cursor")).toBe(false);
    expect(tab.searchParams.get("run")).toBe(other);
  });
  it.each([
    { account: [id, other] },
    { view: "runs" },
    { view: "result", selection: id },
    { view: "selections", selection: id },
    { view: "new", selection: id },
    { view: "new", cursor: "old" },
    { run: id },
    { table: "transfers" },
    { cursor: "x".repeat(2049) },
    { cursor: "https://invalid.test" },
    { url: "https://invalid.test" },
    { arbitrary: "value" },
  ])("rejects ambiguous or unsupported page state %o", (input) => {
    expect(() => readAggregationQuery(input)).toThrow();
  });
  it("does not silently select the first saved resource", () => {
    expect(readAggregationQuery({})).toEqual({
      view: "selections",
      table: "holdings",
    });
    expect(aggregationHref({ view: "new" })).toBe("/aggregation?view=new");
  });
});
