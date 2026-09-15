// @vitest-environment node
import { createHash } from "node:crypto";
import { describe, expect, expectTypeOf, it, vi } from "vitest";
import {
  PremiumReportApiClient,
  type GeneratePremiumReportRequest,
  type GeneratePremiumReportRequestV3,
  type PremiumReportJobStatus,
  type PremiumReportJobStatusV3,
  type PremiumReportManifest,
  type ReportApiResponse,
  type ReportArtifactMetadata,
} from "@trading212/api-contracts";

const account = "00000000-0000-4000-8000-000000000001";
const report = "00000000-0000-4000-8000-000000000002";
const artifact = "00000000-0000-4000-8000-000000000003";
const privateHeaders = {
  "cache-control": "private, no-store",
  "x-content-type-options": "nosniff",
};
const token = "private-premium-grant-" + "a".repeat(32);
const body2: GeneratePremiumReportRequest = {
  account_id: account,
  snapshot_id: account,
  risk_run_id: report,
  start_date: "2026-09-01",
  end_date: "2026-09-07",
  source_cutoff_at: "2026-09-07T12:00:00Z",
  reporting_currency: "EUR",
  report_type: "portfolio_summary",
  sections: ["overview", "allocation", "quality", "risk"],
  formats: ["json"],
};
const body3: GeneratePremiumReportRequestV3 = {
  account_id: account,
  snapshot_id: account,
  start_date: "2026-09-01",
  end_date: "2026-09-07",
  source_cutoff_at: "2026-09-07T12:00:00Z",
  reporting_currency: "EUR",
  report_type: "portfolio_summary",
  sections: ["overview", "allocation", "quality", "scenario"],
  formats: ["json"],
  premium_run: { family: "scenario", run_id: report },
  profile_version: "report_sections_v3",
};
const status2: PremiumReportJobStatus = {
  account_id: account,
  context: null,
  job_id: report,
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
const status3: PremiumReportJobStatusV3 = {
  ...status2,
  context: null,
  profile_version: "report_sections_v3",
};
const manifest2: PremiumReportManifest = {
  document: {
    selection: body2,
    owner_id: account,
    valuation_at: "2026-09-07T12:00:00Z",
    context_digest: "a".repeat(64),
    tables: [
      {
        table: "risk_observed_v1",
        schema_digest: "b".repeat(64),
        row_count: 1,
        content_digest: "c".repeat(64),
        section: "risk",
        dataset: null,
        state: "available",
        reason_key: null,
      },
    ],
    document_digest: "d".repeat(64),
    document_schema_version: "2.0.0",
  },
  renderer_profile: {
    renderer_versions: [{ format: "json", name: "json", version: "1.0.0" }],
    fonts: [],
    profile_version: "report_render_v1",
    template_version: "report_template_v1",
    locale: "en-GB",
    timezone: "UTC",
    chart_order_version: "report_chart_order_v1",
    accessibility_profile_version: "report_visual_accessibility_v1",
  },
  bindings: [],
  contexts: [],
  source_references: [],
  source_memberships: [],
  note_memberships: [],
  license_references: [],
  coverage: [],
  bounds: [],
  notes: [],
  proof_relations: [],
  reconciliation: [],
  method: "report_manifest_v1",
  method_version: "1.0.0",
  escaping_version: "report_csv_text_v1",
};
const content = new TextEncoder().encode('{"amount":"-0.000000000000000001"}');
const metadata: ReportArtifactMetadata = {
  artifact_id: artifact,
  format: "json",
  mime_type: "application/json",
  byte_length: content.length,
  content_digest: createHash("sha256").update(content).digest("hex"),
  expires_at: "2026-09-30T00:00:00Z",
};
function json(value: unknown) {
  return Response.json(value, { headers: privateHeaders });
}
function binary() {
  return new Response(content, {
    headers: {
      ...privateHeaders,
      "content-type": metadata.mime_type,
      "content-length": String(metadata.byte_length),
      "x-artifact-sha256": metadata.content_digest,
      "content-disposition": `attachment; filename="portfolio-artifact-${artifact}.json"`,
    },
  });
}

// Compile-time checks: the existing constructor retains V2 inference; explicit V3 narrows outputs.
function clientTypes() {
  const previous = new PremiumReportApiClient({
    baseUrl: "https://portfolio.example",
  });
  const current = new PremiumReportApiClient({
    baseUrl: "https://portfolio.example",
    profile: "report_sections_v3",
  });
  expectTypeOf(previous.get_premium_report_status).returns.toEqualTypeOf<
    Promise<ReportApiResponse<PremiumReportJobStatus>>
  >();
  expectTypeOf(current.get_premium_report_status).returns.toEqualTypeOf<
    Promise<ReportApiResponse<PremiumReportJobStatusV3>>
  >();
}
void clientTypes;

describe("explicit premium report profile client", () => {
  it("pins profile three across all six fixed routes including ephemeral grant and binary content", async () => {
    const fetchImpl = vi.fn<typeof fetch>(async (input) => {
      const path = new URL(String(input)).pathname;
      if (path.endsWith("/content")) return binary();
      if (path.endsWith("/grants"))
        return json({
          artifact_id: artifact,
          token,
          expires_at: "2026-09-30T00:00:00Z",
        });
      if (path === "/api/v2/reports")
        return json({
          profile_version: "report_sections_v3",
          items: [status3],
          next_cursor: null,
          limit: 25,
          total: 1,
        });
      if (path === `/api/v2/reports/${report}`)
        return Response.json(
          { error: { code: "REPORT_UNAVAILABLE" } },
          { status: 503, headers: privateHeaders },
        );
      return json(status3);
    });
    const client = new PremiumReportApiClient({
      baseUrl: "https://portfolio.example",
      profile: "report_sections_v3",
      fetchImpl,
    });
    await client.generate_premium_portfolio_report(body3, {
      idempotencyKey: "profile3:create",
    });
    await client.get_premium_report_status(report, { account_id: account });
    await client.list_premium_reports({ account_id: account });
    await expect(
      client.get_premium_report_manifest(report, { account_id: account }),
    ).rejects.toMatchObject({ code: "REPORT_UNAVAILABLE" });
    await client.create_premium_report_download_grant(
      report,
      artifact,
      { account_id: account },
      {},
    );
    expect(
      (
        await client.download_premium_report_artifact(
          report,
          artifact,
          { account_id: account },
          { grantToken: token, metadata },
        )
      ).content,
    ).toEqual(content);
    expect(fetchImpl).toHaveBeenCalledTimes(6);
    for (const [input] of fetchImpl.mock.calls) {
      const url = new URL(String(input));
      expect(url.searchParams.getAll("profile")).toEqual([
        "report_sections_v3",
      ]);
      expect(url.pathname).toMatch(/^\/api\/v2\//);
      expect(url.href).not.toContain(token);
    }
    expect(
      new Headers(fetchImpl.mock.calls[5][1]?.headers).get("x-artifact-grant"),
    ).toBe(token);
  });

  it("keeps default profile-two creation signature, body and query omission", async () => {
    const fetchImpl = vi.fn<typeof fetch>(async () => json(status2));
    const client = new PremiumReportApiClient({
      baseUrl: "https://portfolio.example",
      fetchImpl,
    });
    await client.generate_premium_portfolio_report(body2, {
      idempotencyKey: "profile2:create",
    });
    const [input, init] = fetchImpl.mock.calls[0];
    expect(new URL(String(input)).search).toBe("");
    expect(JSON.parse(String(init?.body))).toEqual(body2);
    expect(init?.body).not.toContain("profile_version");
  });

  it("rejects mismatched query/body or unimplemented variants before dispatch without reflecting inputs", async () => {
    const fetchImpl = vi.fn<typeof fetch>();
    const client = new PremiumReportApiClient({
      baseUrl: "https://portfolio.example",
      profile: "report_sections_v3",
      fetchImpl,
    });
    await expect(
      client.get_premium_report_status(report, {
        account_id: account,
        profile: "report_sections_v2",
      } as never),
    ).rejects.toMatchObject({ code: "VALIDATION_FAILED" });
    await expect(
      client.generate_premium_portfolio_report(body2 as never, {
        idempotencyKey: "profile3:bad",
      }),
    ).rejects.toMatchObject({ code: "VALIDATION_FAILED" });
    await expect(
      client.generate_premium_portfolio_report(
        {
          ...body3,
          sections: ["overview", "allocation", "quality", "projection"],
        },
        { idempotencyKey: "profile3:unsupported" },
      ),
    ).rejects.toMatchObject({ code: "VALIDATION_FAILED" });
    const error: unknown = await client
      .generate_premium_portfolio_report(
        { ...body3, "private-field-canary": token } as never,
        { idempotencyKey: "profile3:canary" },
      )
      .catch((value: unknown) => value);
    expect(error).toMatchObject({ code: "VALIDATION_FAILED" });
    expect(String(error)).not.toContain("private-field-canary");
    expect(String(error)).not.toContain(token);
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("validates expired status and empty pages against the explicitly selected profile", async () => {
    const fetchImpl = vi.fn<typeof fetch>(async (input) =>
      json(
        new URL(String(input)).pathname === "/api/v2/reports"
          ? { items: [], next_cursor: null, limit: 25, total: 0 }
          : status2,
      ),
    );
    const client = new PremiumReportApiClient({
      baseUrl: "https://portfolio.example",
      profile: "report_sections_v3",
      fetchImpl,
    });
    await expect(
      client.get_premium_report_status(report, { account_id: account }),
    ).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
    await expect(
      client.list_premium_reports({ account_id: account }),
    ).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
  });

  it("accepts a V2 manifest only through the default client, without union fallback on V3", async () => {
    const options = {
      baseUrl: "https://portfolio.example",
      fetchImpl: async () => json(manifest2),
    };
    const previous = new PremiumReportApiClient(options);
    expect(
      (
        await previous.get_premium_report_manifest(report, {
          account_id: account,
        })
      ).notModified,
    ).toBe(false);
    const current = new PremiumReportApiClient({
      ...options,
      profile: "report_sections_v3",
    });
    await expect(
      current.get_premium_report_manifest(report, { account_id: account }),
    ).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
  });
});
