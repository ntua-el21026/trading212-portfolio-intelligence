import { describe, expect, it } from "vitest";
import {
  parsePremiumReportQuery,
  premiumReportHref,
} from "../lib/premium-report-query";
import { accountSwitchHref } from "../lib/account-selection";
const account = "20000000-0000-4000-8000-000000000001";
const run = "20000000-0000-4000-8000-000000000002";
const report = "20000000-0000-4000-8000-000000000003";
describe("risk report selection routes", () => {
  it("uses a separate owned collection and independently bounded cursors", () => {
    const query = {
      account,
      run,
      report,
      cursor: "reports_page",
      runs_cursor: "runs_page",
    };
    const href = premiumReportHref(query);
    const url = new URL(href, "https://portfolio.example");
    expect(url.pathname).toBe("/reports/premium");
    expect(
      parsePremiumReportQuery(Object.fromEntries(url.searchParams)),
    ).toEqual(query);
  });
  it("clears all source, job and collection pins on account switch", () => {
    const query = new URLSearchParams({
      account,
      run,
      report,
      cursor: "reports_page",
      runs_cursor: "runs_page",
    });
    expect(accountSwitchHref("/reports/premium", query, report)).toBe(
      `/reports/premium?account=${report}`,
    );
  });
  it.each([
    { account: [account, run] },
    { account, run: "bad" },
    { account, export: report },
    { account, cursor: "a".repeat(2049) },
    { account, destination: "https://private.invalid" },
  ])("rejects ambiguous or unrelated inputs", (query) => {
    expect(() => parsePremiumReportQuery(query)).toThrow();
  });
});
