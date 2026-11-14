import { describe, expect, it } from "vitest";
import { accountSwitchHref } from "../lib/account-selection";
import { parsePremiumReportQuery } from "../lib/premium-report-query";
import {
  researchReportHref,
  researchReportPinsSchema,
  researchReportSource,
} from "../lib/research-report-query";
import { account, id, item, other } from "./research-ui-fixtures";

describe("exact research report source and URL selection", () => {
  it("keeps the research observation cutoff separate from the saved financial cutoff", () => {
    const source = researchReportSource(item, account);
    expect(source).toMatchObject({
      itemId: id,
      eventRevisionId: item.source.revision_id,
      sourceCutoff: "2026-09-15T12:00:00.123456Z",
      xraySourceCutoff: "2026-08-31T12:00:00Z",
      valuationAt: "2026-08-31T12:00:00Z",
      currency: "EUR",
      snapshotId: other,
    });
    expect(source).not.toHaveProperty("runId");
    expect(researchReportSource(item, other)).toBeNull();
  });
  it("retains exact selected historical versions and review without a latest lookup", () => {
    const source = researchReportSource(item, account);
    if (!source) throw new Error("fixture source missing");
    const pins = researchReportPinsSchema.parse({
      family: "research",
      item_id: id,
      note_revision_ids: [other, id],
      review_acknowledgment_id: other,
    });
    const url = new URL(
      researchReportHref(source, pins, other),
      "https://portfolio.example",
    );
    const parsed = parsePremiumReportQuery(
      Object.fromEntries(url.searchParams),
    );
    expect(parsed).toMatchObject({
      profile: "report_sections_v3",
      family: "research",
      account,
      item: id,
      note_revisions: [id, other].sort().join(","),
      review: other,
      report: other,
    });
    expect(parsed).not.toHaveProperty("run");
    expect(parsed).not.toHaveProperty("snapshot");
    expect(accountSwitchHref(url.pathname, url.searchParams, other)).toBe(
      `/reports/premium?account=${other}&profile=report_sections_v3&family=research`,
    );
  });
  it("preserves an explicit empty note set and omits absent review evidence", () => {
    const pins = researchReportPinsSchema.parse({
      family: "research",
      item_id: id,
      note_revision_ids: [],
    });
    expect(pins.note_revision_ids).toEqual([]);
    expect(pins).not.toHaveProperty("review_acknowledgment_id");
    expect(() =>
      researchReportPinsSchema.parse({ family: "research", item_id: id }),
    ).toThrow();
  });
  it.each([
    { family: "research", item_id: id, note_revision_ids: [id, id] },
    { family: "research", item_id: id, note_revision_ids: [], run_id: id },
    {
      family: "research",
      item_id: id,
      note_revision_ids: [],
      review_acknowledgment_id: null,
    },
    { family: "research", item_id: "latest", note_revision_ids: [] },
    {
      family: "research",
      item_id: id,
      note_revision_ids: Array.from(
        { length: 65 },
        (_, n) => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`,
      ),
    },
  ])(
    "rejects duplicate, unbounded and invented research identities",
    (pins) => {
      expect(() => researchReportPinsSchema.parse(pins)).toThrow();
    },
  );
  it.each([
    { profile: "report_sections_v2", family: "research", account, item: id },
    {
      profile: "report_sections_v3",
      family: "research",
      account,
      item: id,
      run: other,
    },
    {
      profile: "report_sections_v3",
      family: "research",
      account,
      item: id,
      note_revisions: `${id},${id}`,
    },
    {
      profile: "report_sections_v3",
      family: "research",
      account,
      review: other,
    },
    { profile: "report_sections_v3", family: "risk", account, item: id },
  ])("rejects profile confusion and incomplete query pins", (query) => {
    expect(() => parsePremiumReportQuery(query)).toThrow();
  });
});
