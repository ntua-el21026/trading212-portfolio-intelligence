import { describe, expect, it } from "vitest";
import { accountSwitchHref } from "../lib/account-selection";
import { parsePremiumReportQuery } from "../lib/premium-report-query";
import {
  projectionReportSource,
  projectionReportSourceHref,
  projectionReportSourceMatches,
} from "../lib/projection-report-query";
import {
  account,
  id,
  other,
  saved,
  snapshot,
} from "./projection-report-fixtures";

describe("saved projection report basis", () => {
  it("keeps modeled clocks absent and the ordinary snapshot basis distinct", () => {
    const source = projectionReportSource(saved, account, snapshot);
    expect(source).toMatchObject({
      resultDigest: "c".repeat(64),
      currency: "EUR",
      initialKind: "modeled_value",
      anchorDate: "2026-09-15",
      terminalDate: "2027-09-15",
      originalValuation: null,
      originalCutoff: null,
      snapshotId: other,
      snapshotValuation: snapshot.valuation_at,
      sourceCutoff: snapshot.source_cutoff_at,
      startDate: "2026-09-14",
      endDate: "2026-09-14",
    });
    if (!source) throw new Error("fixture source missing");
    const url = new URL(
      projectionReportSourceHref(source),
      "https://local.test",
    );
    const query = parsePremiumReportQuery(Object.fromEntries(url.searchParams));
    expect(projectionReportSourceMatches(source, query)).toBe(true);
    expect(
      projectionReportSourceMatches(source, {
        ...query,
        result_digest: "d".repeat(64),
      }),
    ).toBe(false);
    expect(
      projectionReportSourceMatches(source, { ...query, snapshot: id }),
    ).toBe(false);
  });
  it("retains each actual currency without implicitly converting snapshot money", () => {
    expect(
      projectionReportSource(saved, account, {
        ...snapshot,
        reporting_currency: "USD",
      }),
    ).toMatchObject({ currency: "EUR", snapshotCurrency: "USD" });
  });
  it.each(["queued", "running", "failed", "cancelled", "expired"] as const)(
    "never offers a %s result",
    (state) => {
      expect(
        projectionReportSource({ ...saved, state }, account, snapshot),
      ).toBeNull();
    },
  );
  it("rejects foreign accounts and inconsistent saved capture pins", () => {
    expect(projectionReportSource(saved, other, snapshot)).toBeNull();
    expect(
      projectionReportSource(
        { ...saved, capture_digest: "f".repeat(64) },
        account,
        snapshot,
      ),
    ).toBeNull();
    expect(
      projectionReportSource({ ...saved, result: null }, account, snapshot),
    ).toBeNull();
  });
  it("preserves only collection identity across an account change", () => {
    const query = new URLSearchParams({
      profile: "report_sections_v4",
      family: "projection",
      account,
      run: id,
      snapshot: other,
      result_digest: "c".repeat(64),
      cursor: "saved",
      snapshots_cursor: "owned",
    });
    expect(accountSwitchHref("/reports/premium", query, other)).toBe(
      `/reports/premium?account=${other}&profile=report_sections_v4&family=projection`,
    );
  });
  it.each([
    { profile: "report_sections_v3", family: "projection" },
    { profile: "report_sections_v4", family: "risk" },
    { profile: "report_sections_v4", family: "projection", snapshot: other },
    {
      profile: "report_sections_v4",
      family: "projection",
      account,
      run: id,
      snapshot: other,
      currency: "EUR",
    },
    { profile: ["report_sections_v4", "report_sections_v4"] },
    { snapshots_cursor: "owned" },
  ])("rejects partial or cross-profile selections", (query) => {
    expect(() => parsePremiumReportQuery(query)).toThrow();
  });
});
