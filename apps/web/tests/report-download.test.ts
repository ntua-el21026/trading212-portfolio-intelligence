// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ReportApiError } from "@trading212/api-contracts";
import { serveReportArtifact } from "../lib/report-download";
const mocks = vi.hoisted(() => ({
  clients: vi.fn(),
  status: vi.fn(),
  exportStatus: vi.fn(),
  grant: vi.fn(),
  exportGrant: vi.fn(),
  download: vi.fn(),
  exportDownload: vi.fn(),
}));
vi.mock("server-only", () => ({}));
vi.mock("../lib/report-adapter", () => ({
  reportClients: mocks.clients,
  reportData: (value: { data: unknown }) => value.data,
}));
const account = "10000000-0000-4000-8000-000000000001",
  parent = "10000000-0000-4000-8000-000000000002",
  artifact = "10000000-0000-4000-8000-000000000003";
const token = "private-header-grant-canary";
const metadata = {
  artifact_id: artifact,
  format: "json",
  mime_type: "application/json",
  byte_length: 2,
  content_digest: "a".repeat(64),
  expires_at: "2026-09-14T12:00:00Z",
};
function request(body = `account_id=${account}`) {
  return new Request("https://portfolio.example/api/reports/download", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });
}

describe("private browser download bridge", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    mocks.clients.mockResolvedValue({
      reports: {
        get_report_status: mocks.status,
        get_export_status: mocks.exportStatus,
        create_report_download_grant: mocks.grant,
        create_export_download_grant: mocks.exportGrant,
        download_report_artifact: mocks.download,
        download_export_artifact: mocks.exportDownload,
      },
    });
    for (const method of [mocks.status, mocks.exportStatus])
      method.mockResolvedValue({
        data: { state: "succeeded", artifacts: [metadata] },
      });
    for (const method of [mocks.grant, mocks.exportGrant])
      method.mockResolvedValue({
        data: {
          artifact_id: artifact,
          token,
          expires_at: "2026-09-07T12:05:00Z",
        },
      });
    for (const method of [mocks.download, mocks.exportDownload])
      method.mockResolvedValue({
        content: new TextEncoder().encode("{}"),
        metadata,
        filename: `portfolio-artifact-${artifact}.json`,
      });
  });
  it("preserves grant throttling status and safe retry timing without a download", async () => {
    mocks.grant.mockRejectedValueOnce(
      new ReportApiError(
        "RATE_LIMITED",
        429,
        "The private report request rate limit was reached.",
      ),
    );
    const response = await serveReportArtifact(
      request(),
      "reports",
      parent,
      artifact,
    );
    expect(response.status).toBe(429);
    expect(response.headers.get("retry-after")).toBe("300");
    expect(await response.json()).toMatchObject({
      error: { code: "RATE_LIMITED", retryable: true },
    });
    expect(mocks.download).not.toHaveBeenCalled();
  });
  it.each(["reports", "exports"] as const)(
    "keeps %s grants on the server and streams only verified content",
    async (family) => {
      const reply = await serveReportArtifact(
        request(),
        family,
        parent,
        artifact,
      );
      expect(reply.status).toBe(200);
      expect(await reply.text()).toBe("{}");
      expect([...reply.headers].join(" ")).not.toContain(token);
      expect(reply.headers.get("cache-control")).toBe("private, no-store");
      expect(reply.headers.get("x-content-type-options")).toBe("nosniff");
      expect(reply.headers.get("content-length")).toBe("2");
      const grant = family === "reports" ? mocks.grant : mocks.exportGrant;
      const download =
        family === "reports" ? mocks.download : mocks.exportDownload;
      expect(grant).toHaveBeenCalledWith(
        parent,
        artifact,
        { account_id: account },
        {},
      );
      expect(download).toHaveBeenCalledWith(
        parent,
        artifact,
        { account_id: account },
        { grantToken: token, metadata },
      );
      expect(mocks.clients).toHaveBeenCalledWith(true);
    },
  );
  it("authorizes before reading or parsing form data", async () => {
    mocks.clients.mockRejectedValueOnce(new Error("Authentication required"));
    const malicious = request();
    const read = vi.spyOn(malicious, "body", "get").mockImplementation(() => {
      throw new Error("Input was read");
    });
    await expect(
      serveReportArtifact(malicious, "reports", "bad", "bad"),
    ).rejects.toThrow("Authentication required");
    expect(read).not.toHaveBeenCalled();
    expect(mocks.status).not.toHaveBeenCalled();
  });
  it.each([
    `account_id=${account}&token=${token}`,
    `account_id=${account}&account_id=${account}`,
    "x".repeat(1025),
  ])("rejects extra, duplicated and oversized browser fields", async (body) => {
    const reply = await serveReportArtifact(
      request(body),
      "reports",
      parent,
      artifact,
    );
    expect([413, 422]).toContain(reply.status);
    expect(await reply.text()).not.toContain(token);
    expect(mocks.status).not.toHaveBeenCalled();
    expect(mocks.grant).not.toHaveBeenCalled();
  });
  it.each(["queued", "running", "failed", "cancelled", "expired"])(
    "denies %s artifacts before minting a grant",
    async (state) => {
      mocks.status.mockResolvedValueOnce({
        data: { state, artifacts: [metadata] },
      });
      const response = await serveReportArtifact(
        request(),
        "reports",
        parent,
        artifact,
      );
      expect(response.status).toBe(state === "expired" ? 410 : 404);
      expect(mocks.grant).not.toHaveBeenCalled();
      expect(mocks.download).not.toHaveBeenCalled();
    },
  );
  it("rejects a grant for a different artifact", async () => {
    mocks.grant.mockResolvedValueOnce({ data: { artifact_id: parent, token } });
    const response = await serveReportArtifact(
      request(),
      "reports",
      parent,
      artifact,
    );
    expect(response.status).toBe(502);
    expect(await response.text()).not.toContain(token);
    expect(mocks.download).not.toHaveBeenCalled();
  });
});
