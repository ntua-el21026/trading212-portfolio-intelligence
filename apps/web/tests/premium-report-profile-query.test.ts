import { describe, expect, it } from "vitest";
import { accountSwitchHref } from "../lib/account-selection";
import {
  parsePremiumReportQuery,
  premiumReportHref,
  premiumReportSourceHref,
  premiumScenarioReportSource,
  premiumSourceMatchesQuery,
} from "../lib/premium-report-query";
import { id, scenarioRun } from "./premium-report-profile-fixtures";

const run = scenarioRun();
const selected = () => {
  const source = premiumScenarioReportSource(run, id);
  if (!source) throw new Error("synthetic source missing");
  return source;
};
describe("explicit premium profile query and canonical scenario source", () => {
  it("keeps default-two URLs and parses no injected profile defaults", () => {
    expect(parsePremiumReportQuery({ account: id })).toEqual({ account: id });
    expect(premiumReportHref({ account: id })).toBe(
      `/reports/premium?account=${id}`,
    );
    expect(
      premiumReportHref({ account: id, profile: "report_sections_v2" }),
    ).toBe(`/reports/premium?account=${id}`);
  });
  it("uses the complete saved digest and exact monetary cutoff, never the page digest", () => {
    const source = selected();
    expect(source).toMatchObject({
      family: "scenario",
      profile: "report_sections_v3",
      accountId: id,
      runId: run.id,
      snapshotId: run.portfolio_snapshot_id,
      resultDigest: run.result?.context.saved_result_digest,
      sourceCutoff: "2026-09-07T12:00:00.123456Z",
      currency: "EUR",
      startDate: "2026-09-07",
      endDate: "2026-09-07",
    });
    expect(source.resultDigest).not.toBe(run.result?.content_digest);
    const href = new URL(
      premiumReportSourceHref(source),
      "https://portfolio.example",
    );
    const query = parsePremiumReportQuery(
      Object.fromEntries(href.searchParams),
    );
    expect(query).toMatchObject({
      account: id,
      run: run.id,
      profile: source.profile,
      family: "scenario",
      snapshot: source.snapshotId,
      cutoff: source.sourceCutoff,
      result_digest: source.resultDigest,
    });
    expect(premiumSourceMatchesQuery(source, query)).toBe(true);
    expect(
      premiumSourceMatchesQuery(source, {
        ...query,
        cutoff: "2026-09-07T12:00:00.123457Z",
      }),
    ).toBe(false);
    expect(
      premiumSourceMatchesQuery(source, { ...query, family: "risk" }),
    ).toBe(false);
  });
  it("preserves only the explicit profile and family on an account change", () => {
    const previous = new URL(
      premiumReportSourceHref(selected(), id),
      "https://portfolio.example",
    );
    previous.searchParams.set("cursor", "page2");
    previous.searchParams.set("runs_cursor", "page3");
    const target = accountSwitchHref(
      previous.pathname,
      previous.searchParams,
      run.id,
    );
    expect(target).toBe(
      `/reports/premium?account=${run.id}&profile=report_sections_v3&family=scenario`,
    );
    expect(new URL(target, previous).searchParams.has("run")).toBe(false);
  });
  it.each([
    { profile: "unknown" },
    { profile: ["report_sections_v3", "report_sections_v3"] },
    { profile: "report_sections_v3", run: id },
    { profile: "report_sections_v2", family: "scenario" },
    { profile: "report_sections_v3", family: "projection" },
    {
      profile: "report_sections_v3",
      family: "scenario",
      account: id,
      run: id,
      snapshot: id,
    },
    {
      profile: "report_sections_v3",
      family: "scenario",
      account: id,
      run: id,
      source_values: "private-canary",
    },
  ])("rejects duplicate, partial or unsupported selections", (query) => {
    expect(() => parsePremiumReportQuery(query)).toThrow();
  });
  it("fails closed for wrong account, incomplete runs and changed result identity", () => {
    expect(premiumScenarioReportSource(run, run.id)).toBeNull();
    expect(
      premiumScenarioReportSource(
        {
          ...run,
          state: "running",
          result: null,
          result_availability: "pending",
        },
        id,
      ),
    ).toBeNull();
    if (!run.result) throw new Error("synthetic source missing");
    const wrong = {
      ...run,
      result: { ...run.result, context: { ...run.result.context, run_id: id } },
    };
    expect(premiumScenarioReportSource(wrong, id)).toBeNull();
  });
});
