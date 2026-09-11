import { describe, expect, it } from "vitest";
import { readPlanningCompanyQuery } from "../lib/planning-company-query";

const run = "ab402b97-943c-4b95-94c6-b5eb6f2e6dc1";
describe("explicit company source selection", () => {
  it("leaves direct planning without an implicit company source", () => {
    expect(readPlanningCompanyQuery({})).toEqual({
      included: false,
      runId: undefined,
    });
  });
  it("distinguishes first source selection from replay of one retained run", () => {
    expect(readPlanningCompanyQuery({ company: "include" })).toEqual({
      included: true,
      runId: undefined,
    });
    expect(
      readPlanningCompanyQuery({ company: "include", xray_run: run }),
    ).toEqual({ included: true, runId: run });
  });
  it.each([
    { company: ["include", "include"] },
    { company: "unknown" },
    { company: "include", xray_run: [run, run] },
    { company: "include", xray_run: "invalid" },
    { xray_run: run },
  ])("rejects ambiguous or orphaned pins", (query) => {
    expect(() => readPlanningCompanyQuery(query)).toThrow();
  });
});
