// @vitest-environment node
import { createHash } from "node:crypto";
import { describe, expect, expectTypeOf, it, vi } from "vitest";
import {
  PremiumReportApiClient,
  type GeneratePremiumReportRequestV4,
  type PremiumReportJobStatus,
  type PremiumReportJobStatusV3,
  type PremiumReportJobStatusV4,
  type ReportApiResponse,
  type ReportArtifactMetadata,
} from "@trading212/api-contracts";
const account = "10000000-0000-4000-8000-000000000001";
const id = "10000000-0000-4000-8000-000000000002";
const privateHeaders = {
  "cache-control": "private, no-store",
  "x-content-type-options": "nosniff",
};
const body: GeneratePremiumReportRequestV4 = {
  profile_version: "report_sections_v4",
  account_id: account,
  snapshot_id: id,
  start_date: "2026-09-14",
  end_date: "2026-09-14",
  source_cutoff_at: "2026-09-14T11:00:00.123456Z",
  reporting_currency: "EUR",
  report_type: "portfolio_summary",
  sections: ["overview", "allocation", "quality", "projection"],
  formats: ["json"],
  premium_run: { family: "projection", run_id: id },
};
const expired: PremiumReportJobStatusV4 = {
  profile_version: "report_sections_v4",
  account_id: account,
  context: null,
  job_id: id,
  report_id: null,
  state: "expired",
  requested_at: "2026-09-01T00:00:00Z",
  completed_at: null,
  expires_at: "2026-09-08T00:00:00Z",
  failure_code: null,
  report_type: "portfolio_summary",
  formats: ["json"],
  manifest_digest: null,
  artifacts: [],
};
const bytes = new TextEncoder().encode(
  '{"value":"-0.000000000000000001","source_cutoff_at":null}',
);
const metadata: ReportArtifactMetadata = {
  artifact_id: id,
  format: "json",
  mime_type: "application/json",
  byte_length: bytes.length,
  content_digest: createHash("sha256").update(bytes).digest("hex"),
  expires_at: "2026-09-30T00:00:00Z",
};
function clientTypes() {
  const previous = new PremiumReportApiClient({
    baseUrl: "https://portfolio.example",
  });
  const third = new PremiumReportApiClient({
    baseUrl: "https://portfolio.example",
    profile: "report_sections_v3",
  });
  const fourth = new PremiumReportApiClient({
    baseUrl: "https://portfolio.example",
    profile: "report_sections_v4",
  });
  expectTypeOf(previous.get_premium_report_status).returns.toEqualTypeOf<
    Promise<ReportApiResponse<PremiumReportJobStatus>>
  >();
  expectTypeOf(third.get_premium_report_status).returns.toEqualTypeOf<
    Promise<ReportApiResponse<PremiumReportJobStatusV3>>
  >();
  expectTypeOf(fourth.get_premium_report_status).returns.toEqualTypeOf<
    Promise<ReportApiResponse<PremiumReportJobStatusV4>>
  >();
}
void clientTypes;
describe("explicit profile-four premium client", () => {
  it("pins all six fixed operations, grants and exact binary bytes to profile four", async () => {
    const fetchImpl = vi.fn<typeof fetch>(async (input) => {
      const path = new URL(String(input)).pathname;
      if (path.endsWith("/content"))
        return new Response(bytes, {
          headers: {
            ...privateHeaders,
            "content-type": "application/json",
            "content-length": String(bytes.length),
            "x-artifact-sha256": metadata.content_digest,
            "content-disposition": `attachment; filename="portfolio-artifact-${id}.json"`,
          },
        });
      if (path.endsWith("/grants"))
        return Response.json(
          {
            artifact_id: id,
            token: "private-grant-" + "a".repeat(32),
            expires_at: metadata.expires_at,
          },
          { headers: privateHeaders },
        );
      if (path === "/api/v2/reports")
        return Response.json(
          {
            profile_version: "report_sections_v4",
            items: [],
            next_cursor: null,
            limit: 25,
            total: 0,
          },
          { headers: privateHeaders },
        );
      if (path === `/api/v2/reports/${id}`)
        return Response.json(
          { error: { code: "REPORT_UNAVAILABLE" } },
          { status: 503, headers: privateHeaders },
        );
      return Response.json(expired, { headers: privateHeaders });
    });
    const client = new PremiumReportApiClient({
      baseUrl: "https://portfolio.example",
      profile: "report_sections_v4",
      fetchImpl,
    });
    await client.generate_premium_portfolio_report(body, {
      idempotencyKey: "projection-report:one",
    });
    await client.get_premium_report_status(id, { account_id: account });
    await client.list_premium_reports({ account_id: account });
    await expect(
      client.get_premium_report_manifest(id, { account_id: account }),
    ).rejects.toThrow();
    const grant = await client.create_premium_report_download_grant(
      id,
      id,
      { account_id: account },
      {},
    );
    if (!grant.data) throw new Error("grant missing");
    const artifact = await client.download_premium_report_artifact(
      id,
      id,
      { account_id: account },
      { grantToken: grant.data.token, metadata },
    );
    expect(artifact.content).toEqual(bytes);
    expect(fetchImpl).toHaveBeenCalledTimes(6);
    for (const [url] of fetchImpl.mock.calls)
      expect(new URL(String(url)).searchParams.get("profile")).toBe(
        "report_sections_v4",
      );
  });
  it.each(["report_sections_v2", "report_sections_v3", undefined])(
    "rejects a %s empty page response",
    async (profile) => {
      const fetchImpl = vi.fn<typeof fetch>(async () =>
        Response.json(
          {
            items: [],
            next_cursor: null,
            limit: 25,
            total: 0,
            ...(profile ? { profile_version: profile } : {}),
          },
          { headers: privateHeaders },
        ),
      );
      const client = new PremiumReportApiClient({
        baseUrl: "https://portfolio.example",
        profile: "report_sections_v4",
        fetchImpl,
      });
      await expect(
        client.list_premium_reports({ account_id: account }),
      ).rejects.toThrow();
    },
  );
  it("rejects foreign run families and cross-profile query values before fetch", async () => {
    const fetchImpl = vi.fn<typeof fetch>();
    const client = new PremiumReportApiClient({
      baseUrl: "https://portfolio.example",
      profile: "report_sections_v4",
      fetchImpl,
    });
    // Deliberate JavaScript callers bypass compile-time literals.
    await expect(
      client.generate_premium_portfolio_report(
        {
          ...body,
          premium_run: { family: "scenario", run_id: id },
        } as unknown as GeneratePremiumReportRequestV4,
        { idempotencyKey: "projection-report:one" },
      ),
    ).rejects.toThrow();
    await expect(
      client.list_premium_reports({
        account_id: account,
        profile: "report_sections_v3",
      } as never),
    ).rejects.toThrow();
    expect(fetchImpl).not.toHaveBeenCalled();
  });
});
