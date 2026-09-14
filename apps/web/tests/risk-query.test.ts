import { describe, expect, it } from "vitest";
import {
  readRiskQuery,
  riskHref,
  riskWindow,
  RiskQueryError,
} from "../lib/risk-query";
import { accountSwitchHref } from "../lib/account-selection";
const id = "d778f930-9d2e-4f47-b24f-5b1fa99c6eee";
const options = { now: new Date("2026-09-14T12:00:00Z"), currency: "EUR" };
describe("risk URL contract", () => {
  it("keeps explicit microsecond cutoff, policies and owned selections through pagination", () => {
    const query = readRiskQuery(
      {
        account: id,
        version: id,
        snapshot: id,
        capture: id,
        xray: id,
        view: "new",
        cutoff: "2026-09-07T12:00:00.123456Z",
        knowledge: "point_in_time",
        coverage: "allow_degraded",
      },
      options,
    );
    const url = new URL(
      riskHref(query, { sources_cursor: "signed_cursor" }),
      "https://portfolio.example",
    );
    expect(
      readRiskQuery(Object.fromEntries(url.searchParams), options),
    ).toEqual({ ...query, sources_cursor: "signed_cursor" });
    expect(riskWindow(query)).toEqual({
      start_date: "2025-01-01",
      end_date: "2025-12-31",
      source_cutoff_at: "2026-09-07T12:00:00.123456Z",
      reporting_currency: "EUR",
      knowledge_policy: "point_in_time",
      coverage_policy: "allow_degraded",
    });
  });
  it.each([
    { account: [id, id] },
    { version: "private-canary" },
    { view: "result" },
    { run: "../private-canary" },
    { url: "https://private-canary" },
    { currency: "usd" },
    { sources_cursor: "a/b" },
    { xray_mode: "automatic" },
    { start: "2025-02-30" },
    { end: "2026-09-15" },
  ])(
    "rejects ambiguous or unsafe selection without echoing it: %j",
    (search) => {
      expect(() => readRiskQuery(search, options)).toThrow(RiskQueryError);
      try {
        readRiskQuery(search, options);
      } catch (error) {
        expect(String(error)).not.toContain("private-canary");
      }
    },
  );
  it("switches accounts without carrying any owner-bound input or result", () => {
    const query = readRiskQuery(
      {
        account: id,
        run: id,
        definition: id,
        version: id,
        snapshot: id,
        capture: id,
        benchmark: id,
        xray: id,
        runs_cursor: "signed_cursor",
      },
      options,
    );
    const params = new URL(riskHref(query), "https://portfolio.example")
      .searchParams;
    expect(
      accountSwitchHref(
        "/risk",
        params,
        "2f34c23a-3798-4d4a-9133-9cd47639dd37",
      ),
    ).toBe(
      "/risk?account=2f34c23a-3798-4d4a-9133-9cd47639dd37&start=2025-01-01&end=2025-12-31",
    );
  });
});
