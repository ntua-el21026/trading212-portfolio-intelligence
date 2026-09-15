import { describe, expect, it } from "vitest";
import {
  readProjectionQuery,
  projectionHref,
  projectionSelectionHref,
} from "../lib/projection-query";
import { accountSwitchHref } from "../lib/account-selection";
import { account, id, other } from "./projection-fixtures";
describe("saved projection URL state", () => {
  it("round-trips absolute saved selections and a signed point cursor", () => {
    const query = readProjectionQuery({
      account,
      run: id,
      view: "result",
      point_cursor: "abc_123-DEF",
    });
    expect(
      readProjectionQuery(
        Object.fromEntries(
          new URL(projectionHref(query), "https://local.test").searchParams,
        ),
      ),
    ).toEqual(query);
    expect(
      projectionSelectionHref(query, { view: "new", version: other }),
    ).not.toContain("point_cursor");
    expect(
      projectionSelectionHref(query, { view: "new", version: other }),
    ).not.toContain("run=");
    expect(projectionHref(query, { point_cursor: "next" })).toContain(
      `run=${id}`,
    );
  });
  it.each([
    { view: "result" },
    { view: "goal" },
    { run: id, point_cursor: ["a", "b"] },
    { account: [account, other] },
    { seed: "123" },
    { modeled_value: "1" },
    { cutoff: "2026-09-15T12:00:00.123456Z" },
    { run: id, point_cursor: "x".repeat(2049) },
    { run: id, point_cursor: "../secret" },
  ])("rejects invalid or invented selection fields %j", (search) => {
    expect(() => readProjectionQuery(search)).toThrow();
  });
  it("clears every saved pin, result and cursor on account switch", () => {
    const query = readProjectionQuery({
      account,
      set: id,
      version: id,
      goal: id,
      goal_version: id,
      snapshot: id,
      run: id,
      point_cursor: "cursor",
      view: "result",
    });
    const params = new URL(projectionHref(query), "https://local.test")
      .searchParams;
    params.set("start_date", "2026-09-15");
    params.set("end_date", "2027-09-15");
    expect(accountSwitchHref("/projections", params, other)).toBe(
      `/projections?account=${other}`,
    );
  });
});
