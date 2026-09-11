import { describe, expect, it } from "vitest";
import { getDemoPortfolio } from "../lib/demo-data";
import {
  accountParameter,
  accountSwitchHref,
  resolveAccountSelection,
} from "../lib/account-selection";

const first = getDemoPortfolio().summary.account;
const second = {
  ...first,
  id: "ab402b97-943c-4b95-94c6-b5eb6f2e6dc1",
  display_name: "Second portfolio",
};
const foreign = "f791a374-cc3e-4e73-9168-a120c0d54cec";

describe("authorized account selection", () => {
  it("prefers an explicit owned account to a configured preference", () => {
    expect(
      resolveAccountSelection([first, second], second.id, first.id).account?.id,
    ).toBe(second.id);
  });

  it.each([
    "",
    "invalid",
    foreign,
    ` ${first.id}`,
    [first.id],
    [first.id, first.id],
    [first.id, second.id],
  ])(
    "does not fall back from invalid or duplicated explicit selection %j",
    (requested) => {
      expect(
        resolveAccountSelection([first, second], requested, first.id),
      ).toEqual({ kind: "invalid", account: null });
    },
  );

  it("uses an authorized configured preference and otherwise requires an unambiguous account", () => {
    expect(
      resolveAccountSelection([first, second], undefined, second.id).account
        ?.id,
    ).toBe(second.id);
    expect(
      resolveAccountSelection([first], undefined, foreign).account?.id,
    ).toBe(first.id);
    expect(
      resolveAccountSelection([first, second], undefined, foreign).kind,
    ).toBe("choose");
    expect(resolveAccountSelection([], undefined, first.id).kind).toBe("empty");
  });

  it("keeps duplicate URL parameters distinguishable from an absent parameter", () => {
    expect(accountParameter(new URLSearchParams())).toBeUndefined();
    expect(accountParameter(new URLSearchParams({ account: first.id }))).toBe(
      first.id,
    );
    expect(
      accountParameter(
        new URLSearchParams(`account=${first.id}&account=${first.id}`),
      ),
    ).toEqual([first.id, first.id]);
  });

  it.each([
    "/holdings/position",
    "/pies/pie",
    "/planner/plan",
    "/sources/benchmarks/definition",
    "/xray/sources/snapshot",
  ])(
    "drops the prior account's resource path, pins and cursors when switching from %s",
    (path) => {
      const query = new URLSearchParams({
        account: first.id,
        snapshot: "old",
        pie: "old",
        run: "old",
        version: "old",
        cursor: "old",
        rule: "old",
        event: "old",
        report: "old",
        edit: "1",
        start_date: "2026-01-01",
        end_date: "2026-03-01",
        currency: "EUR",
      });
      const next = new URL(
        accountSwitchHref(path, query, second.id),
        "https://portfolio.invalid",
      );
      expect(next.pathname).toBe(`/${path.split("/")[1]}`);
      expect(Object.fromEntries(next.searchParams)).toEqual({
        account: second.id,
        start_date: "2026-01-01",
        end_date: "2026-03-01",
      });
    },
  );

  it("does not carry malformed or duplicated date state to another account", () => {
    const query = new URLSearchParams(
      "start_date=2026-02-30&end_date=2026-03-01&end_date=2026-03-01",
    );
    expect(accountSwitchHref("/income", query, second.id)).toBe(
      `/income?account=${second.id}`,
    );
  });
});
