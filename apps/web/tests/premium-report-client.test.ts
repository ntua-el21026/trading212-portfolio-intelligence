// @vitest-environment node
import { createHash } from "node:crypto";
import { describe, expect, it, vi } from "vitest";
import {
  PremiumReportApiClient,
  ReportApiClient,
  ReportArtifactMetadataSchema,
  type GeneratePremiumReportRequest,
  type ReportArtifactMetadata,
} from "@trading212/api-contracts";
import { ReportTransport } from "../../../packages/api-contracts/src/report-transport";

const account = "00000000-0000-4000-8000-000000000001";
const report = "00000000-0000-4000-8000-000000000002";
const artifact = "00000000-0000-4000-8000-000000000003";
const token = "private-premium-grant-" + "a".repeat(32);
const content = new TextEncoder().encode('{"exact":"-0.000000000000000001"}');
const metadata: ReportArtifactMetadata = {
  artifact_id: artifact,
  format: "json",
  mime_type: "application/json",
  byte_length: content.length,
  content_digest: createHash("sha256").update(content).digest("hex"),
  expires_at: "2026-09-30T00:00:00Z",
};
const privateHeaders = {
  "cache-control": "private, no-store",
  "x-content-type-options": "nosniff",
};
function response(
  bytes: Uint8Array<ArrayBuffer> = content,
  change: HeadersInit = {},
) {
  return new Response(bytes, {
    headers: {
      ...privateHeaders,
      "content-type": metadata.mime_type,
      "content-length": String(metadata.byte_length),
      "x-artifact-sha256": metadata.content_digest,
      "content-disposition": `attachment; filename="portfolio-artifact-${artifact}.json"`,
      ...change,
    },
  });
}
const body: GeneratePremiumReportRequest = {
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

describe("versioned premium report client", () => {
  it("uses only the fixed V2 binary route while V1 keeps its original route", async () => {
    const fetchImpl = vi.fn<typeof fetch>(async () => response());
    const options = { baseUrl: "https://portfolio.example", fetchImpl };
    const premium = new PremiumReportApiClient(options);
    const value = await premium.download_premium_report_artifact(
      report,
      artifact,
      { account_id: account },
      { grantToken: token, metadata },
    );
    expect(value.content).toEqual(content);
    const [input, init] = fetchImpl.mock.calls[0];
    const url = new URL(String(input));
    expect(url.pathname).toBe(
      `/api/v2/reports/${report}/artifacts/${artifact}/content`,
    );
    expect([...url.searchParams]).toEqual([["account_id", account]]);
    expect(url.href).not.toContain(token);
    expect(new Headers(init?.headers).get("x-artifact-grant")).toBe(token);
    expect(init).toMatchObject({
      method: "GET",
      cache: "no-store",
      redirect: "error",
    });
    expect("download_export_artifact" in premium).toBe(false);
    await new ReportApiClient(options).download_report_artifact(
      report,
      artifact,
      { account_id: account },
      { grantToken: token, metadata },
    );
    expect(new URL(String(fetchImpl.mock.calls[1][0])).pathname).toBe(
      `/api/v1/reports/${report}/artifacts/${artifact}/content`,
    );
  });

  it("cannot use the V2 transport to invent an export download", async () => {
    const fetchImpl = vi.fn<typeof fetch>(async () => response());
    const transport = new ReportTransport(
      { baseUrl: "https://portfolio.example", fetchImpl },
      2,
    );
    await expect(
      transport.download(
        "exports",
        report,
        artifact,
        { account_id: account },
        { grantToken: token, metadata },
        ReportArtifactMetadataSchema,
      ),
    ).rejects.toMatchObject({ code: "VALIDATION_FAILED" });
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it.each([
    ["cache-control", "public, max-age=60"],
    ["x-content-type-options", ""],
    ["content-type", "text/html"],
    ["x-artifact-sha256", "f".repeat(64)],
    ["location", "https://foreign.example"],
  ])(
    "rejects an invalid %s without exposing a private body",
    async (key, value) => {
      const client = new PremiumReportApiClient({
        baseUrl: "https://portfolio.example",
        fetchImpl: async () => response(content, { [key]: value }),
      });
      await expect(
        client.download_premium_report_artifact(
          report,
          artifact,
          { account_id: account },
          { grantToken: token, metadata },
        ),
      ).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
    },
  );

  it("verifies actual content against the current artifact metadata", async () => {
    const changed = new Uint8Array(content);
    changed[0] = 91;
    const client = new PremiumReportApiClient({
      baseUrl: "https://portfolio.example",
      fetchImpl: async () => response(changed),
    });
    await expect(
      client.download_premium_report_artifact(
        report,
        artifact,
        { account_id: account },
        { grantToken: token, metadata },
      ),
    ).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
  });

  it("sends a typed risk pin to V2 creation and sanitizes unknown input before dispatch", async () => {
    const fetchImpl = vi.fn<typeof fetch>(async () =>
      Response.json(
        { error: { code: "REPORT_UNAVAILABLE", message: token } },
        { status: 503, headers: privateHeaders },
      ),
    );
    const client = new PremiumReportApiClient({
      baseUrl: "https://portfolio.example",
      fetchImpl,
    });
    await expect(
      client.generate_premium_portfolio_report(body, {
        idempotencyKey: "premium:one",
      }),
    ).rejects.toMatchObject({ code: "REPORT_UNAVAILABLE" });
    const [input, init] = fetchImpl.mock.calls[0];
    expect(new URL(String(input)).pathname).toBe("/api/v2/report-jobs");
    expect(JSON.parse(String(init?.body)).risk_run_id).toBe(report);
    const failure: unknown = await client
      .generate_premium_portfolio_report(
        {
          ...body,
          "private-key-canary": token,
        } as GeneratePremiumReportRequest,
        { idempotencyKey: "premium:two" },
      )
      .catch((error: unknown) => error);
    expect(failure).toMatchObject({ code: "VALIDATION_FAILED" });
    expect(String(failure)).not.toContain(token);
    expect(String(failure)).not.toContain("private-key-canary");
    expect(fetchImpl).toHaveBeenCalledOnce();
  });
});
