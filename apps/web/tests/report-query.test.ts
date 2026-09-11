import { describe, expect, it } from "vitest";
import {
  EXPORT_DATASETS,
  REPORT_TYPES,
  REQUIRED_SECTIONS,
  parseReportQuery,
  reportHref,
  reportSelectionSearchKey,
} from "../lib/report-query";

describe("report selection URLs", () => {
  it("retains a complete retry selection and scoped history filter across a reload", () => {
    const input = {
      account: "00000000-0000-4000-8000-000000000001",
      snapshot: "00000000-0000-4000-8000-000000000002",
      kind: "report",
      report_type: "portfolio_xray",
      sections: "overview,xray,quality",
      formats: "pdf,json",
      state: "failed",
      history_type: "portfolio_xray",
      start_date: "2026-09-01",
      end_date: "2026-09-07",
      source_cutoff_at: "2026-09-07T12:00:00Z",
      reporting_currency: "EUR",
      ttl_days: "7",
      request_key: "retry:one",
      request_digest: "a".repeat(64),
      cursor: "retained_cursor",
    };
    const query = parseReportQuery(input);
    const url = new URL(reportHref(query), "https://portfolio.example");
    expect(parseReportQuery(Object.fromEntries(url.searchParams))).toEqual(
      query,
    );
    expect(query.request_key).toBe("retry:one");
  });
  it.each([
    { account: ["one", "two"] },
    { private_token: "canary" },
    { ttl_days: "31" },
    { formats: "html" },
    { sections: "overview,arbitrary" },
    { start_date: "2026-09-08", end_date: "2026-09-07" },
    { dataset: "unknown" },
    { xray_run_id: "invalid" },
    { xray_run_id: ["00000000-0000-4000-8000-000000000001"] },
  ])("rejects unsupported selectors without reflecting them", (input) => {
    expect(() => parseReportQuery(input)).toThrow(/report/);
    try {
      parseReportQuery(input);
    } catch (error) {
      expect(String(error)).not.toContain("canary");
    }
  });
  it("retains an explicit company run without inventing one for an old selection", () => {
    const pin = "00000000-0000-4000-8000-000000000005";
    const selected = parseReportQuery({
      report_type: "target_drift",
      xray_run_id: pin,
    });
    const restored = parseReportQuery(
      Object.fromEntries(
        new URL(reportHref(selected), "https://portfolio.example").searchParams,
      ),
    );
    expect(restored.xray_run_id).toBe(pin);
    expect(Object.hasOwn(parseReportQuery({}), "xray_run_id")).toBe(false);
  });
  it("offers all report profiles and the eight implemented datasets with mandatory quality", () => {
    expect(REPORT_TYPES).toHaveLength(10);
    expect(EXPORT_DATASETS).toHaveLength(8);
    expect(EXPORT_DATASETS).toContain("alerts");
    for (const type of REPORT_TYPES)
      expect(REQUIRED_SECTIONS[type]).toContain("quality");
    expect(REQUIRED_SECTIONS.portfolio_xray).toContain("xray");
    expect(REQUIRED_SECTIONS.performance_benchmark).toContain("benchmark");
  });

  it.each([
    ["kind", "export"],
    ["report_type", "portfolio_xray"],
    ["dataset", "dividends"],
    ["start_date", "2026-01-01"],
    ["end_date", "2026-12-31"],
    ["source_cutoff_at", "2026-09-07T12:00:00Z"],
    ["reporting_currency", "USD"],
    ["target_version_id", "00000000-0000-4000-8000-000000000001"],
    ["plan_revision_id", "00000000-0000-4000-8000-000000000002"],
    ["benchmark_version_id", "00000000-0000-4000-8000-000000000003"],
    ["constituent_snapshot_id", "00000000-0000-4000-8000-000000000004"],
    ["xray_run_id", "00000000-0000-4000-8000-000000000005"],
    ["formats", "csv,json"],
    ["sections", "xray"],
    ["field_set", "audit"],
    ["ttl_days", "9"],
  ])("recognizes an externally restored %s selection", (field, value) => {
    expect(
      reportSelectionSearchKey(new URLSearchParams({ [field]: value })),
    ).not.toBe(reportSelectionSearchKey(new URLSearchParams()));
  });

  it("excludes job, history and retry metadata while normalizing declared defaults", () => {
    const query = new URLSearchParams({
      report: "00000000-0000-4000-8000-000000000001",
      export: "00000000-0000-4000-8000-000000000002",
      state: "succeeded",
      history_type: "annual",
      history_dataset: "activity",
      cursor: "next_page",
      snapshots_cursor: "next_snapshots",
      request_key: "retry-one",
      request_digest: "a".repeat(64),
      kind: "report",
      report_type: "portfolio_summary",
      dataset: "positions",
      field_set: "standard",
      ttl_days: "7",
    });
    expect(reportSelectionSearchKey(query)).toBe(
      reportSelectionSearchKey(new URLSearchParams()),
    );
  });
});
