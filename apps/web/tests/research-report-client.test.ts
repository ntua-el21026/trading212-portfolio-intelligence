// @vitest-environment node
import { describe, expect, it, vi } from "vitest";
import { PremiumReportApiClient } from "@trading212/api-contracts";

const account = "00000000-0000-4000-8000-000000000001";
const item = "00000000-0000-4000-8000-000000000002";
const note = "00000000-0000-4000-8000-000000000003";
const body = {
  account_id: account,
  snapshot_id: account,
  start_date: "2026-11-01",
  end_date: "2026-11-01",
  source_cutoff_at: "2026-11-14T12:00:00.120000Z",
  reporting_currency: "EUR",
  report_type: "portfolio_summary" as const,
  sections: ["overview", "allocation", "quality", "research"] as const,
  formats: ["json"] as const,
  profile_version: "report_sections_v3" as const,
  premium_run: {
    family: "research" as const,
    item_id: item,
    note_revision_ids: [note],
  },
};
const status = {
  account_id: account,
  context: null,
  job_id: item,
  report_id: null,
  state: "expired",
  requested_at: "2026-11-01T00:00:00Z",
  completed_at: null,
  expires_at: "2026-11-08T00:00:00Z",
  failure_code: null,
  report_type: "portfolio_summary",
  formats: ["json"],
  manifest_digest: null,
  artifacts: [],
  profile_version: "report_sections_v3",
};

describe("research selection through the existing premium client", () => {
  it("uses the same operation with exact item/version IDs and omitted absent review", async () => {
    const fetchImpl = vi.fn<typeof fetch>(async () =>
      Response.json(status, {
        headers: {
          "cache-control": "private, no-store",
          "x-content-type-options": "nosniff",
        },
      }),
    );
    const client = new PremiumReportApiClient({
      baseUrl: "https://portfolio.example",
      profile: "report_sections_v3",
      fetchImpl,
    });
    await client.generate_premium_portfolio_report(
      { ...body, sections: [...body.sections], formats: [...body.formats] },
      { idempotencyKey: "research:exact" },
    );
    const [url, options] = fetchImpl.mock.calls[0];
    expect(String(url)).toBe(
      "https://portfolio.example/api/v2/report-jobs?profile=report_sections_v3",
    );
    const sent = JSON.parse(String(options?.body));
    expect(sent.premium_run).toEqual(body.premium_run);
    expect(sent.premium_run).not.toHaveProperty("run_id");
    expect(sent.premium_run).not.toHaveProperty("review_acknowledgment_id");
  });
  it.each([
    { ...body.premium_run, note_revision_ids: [note, note] },
    {
      ...body.premium_run,
      note_revision_ids: [
        "00000000-0000-4000-8000-00000000abcd",
        "00000000-0000-4000-8000-00000000ABCD",
      ],
    },
    { ...body.premium_run, run_id: item },
    { ...body.premium_run, review_acknowledgment_id: null },
    { family: "research", item_id: item },
    { ...body.premium_run, item_id: "latest" },
  ])(
    "rejects duplicate, partial and invented selectors before dispatch",
    async (pin) => {
      const fetchImpl = vi.fn<typeof fetch>();
      const client = new PremiumReportApiClient({
        baseUrl: "https://portfolio.example",
        profile: "report_sections_v3",
        fetchImpl,
      });
      await expect(
        client.generate_premium_portfolio_report(
          { ...body, premium_run: pin } as never,
          { idempotencyKey: "research:invalid" },
        ),
      ).rejects.toMatchObject({ code: "VALIDATION_FAILED" });
      expect(fetchImpl).not.toHaveBeenCalled();
    },
  );
});
