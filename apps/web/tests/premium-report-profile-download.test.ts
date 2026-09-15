// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ReportApiError } from "@trading212/api-contracts";
import { serveReportArtifact } from "../lib/report-download";
const mocks = vi.hoisted(() => ({
  clients: vi.fn(),
  status: vi.fn(),
  grant: vi.fn(),
  download: vi.fn(),
  oldStatus: vi.fn(),
  oldGrant: vi.fn(),
  oldDownload: vi.fn(),
}));
vi.mock("server-only", () => ({}));
vi.mock("../lib/report-adapter", () => ({
  reportClients: mocks.clients,
  reportData: (value: { data: unknown }) => value.data,
}));
const id = "d778f930-9d2e-4f47-b24f-5b1fa99c6eee";
const metadata = {
  artifact_id: id,
  format: "json",
  mime_type: "application/json",
  byte_length: 2,
  content_digest: "a".repeat(64),
  expires_at: "2026-09-30T12:00:00Z",
};
function request(body = `account_id=${id}&profile=report_sections_v3`) {
  return new Request("https://portfolio.example/api/premium-reports/download", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });
}
beforeEach(() => {
  vi.resetAllMocks();
  mocks.clients.mockResolvedValue({
    reports: {},
    premiumReports: {
      get_premium_report_status: mocks.oldStatus,
      create_premium_report_download_grant: mocks.oldGrant,
      download_premium_report_artifact: mocks.oldDownload,
    },
    premiumReportsV3: {
      get_premium_report_status: mocks.status,
      create_premium_report_download_grant: mocks.grant,
      download_premium_report_artifact: mocks.download,
    },
  });
  mocks.status.mockResolvedValue({
    data: {
      profile_version: "report_sections_v3",
      account_id: id,
      state: "succeeded",
      artifacts: [metadata],
    },
  });
  mocks.oldStatus.mockResolvedValue({
    data: { account_id: id, state: "succeeded", artifacts: [metadata] },
  });
  for (const call of [mocks.grant, mocks.oldGrant])
    call.mockResolvedValue({
      data: { artifact_id: id, token: "private-grant-canary" },
    });
  for (const call of [mocks.download, mocks.oldDownload])
    call.mockResolvedValue({
      content: new TextEncoder().encode("{}"),
      metadata,
      filename: "portfolio.json",
    });
});
describe("profile-pinned browser download bridge", () => {
  it("keeps one explicit V3 client across authorization, grant and verified content", async () => {
    const reply = await serveReportArtifact(
      request(),
      "premium-reports",
      id,
      id,
    );
    expect(reply.status).toBe(200);
    expect(await reply.text()).toBe("{}");
    expect(mocks.status).toHaveBeenCalledWith(id, { account_id: id });
    expect(mocks.grant).toHaveBeenCalledWith(id, id, { account_id: id }, {});
    expect(mocks.download).toHaveBeenCalledWith(
      id,
      id,
      { account_id: id },
      { grantToken: "private-grant-canary", metadata },
    );
    expect(mocks.oldStatus).not.toHaveBeenCalled();
    expect([...reply.headers].join(" ")).not.toContain("private-grant-canary");
  });
  it("preserves default-two requests without an added profile field", async () => {
    const reply = await serveReportArtifact(
      request(`account_id=${id}`),
      "premium-reports",
      id,
      id,
    );
    expect(reply.status).toBe(200);
    expect(mocks.oldStatus).toHaveBeenCalledWith(id, { account_id: id });
    expect(mocks.oldDownload).toHaveBeenCalled();
    expect(mocks.status).not.toHaveBeenCalled();
  });
  it.each([
    `account_id=${id}&profile=unknown`,
    `account_id=${id}&profile=report_sections_v3&profile=report_sections_v3`,
    `account_id=${id}&profile=report_sections_v3&account_id=${id}`,
    `account_id=${id}&profile=report_sections_v3&token=private-canary`,
  ])(
    "rejects ambiguous selectors before status or grant requests",
    async (body) => {
      const reply = await serveReportArtifact(
        request(body),
        "premium-reports",
        id,
        id,
      );
      expect(reply.status).toBe(422);
      expect(await reply.text()).not.toContain("private-canary");
      expect(mocks.status).not.toHaveBeenCalled();
      expect(mocks.oldStatus).not.toHaveBeenCalled();
    },
  );
  it.each(["reports", "exports"] as const)(
    "cannot use a V3 selector on legacy %s",
    async (family) => {
      const reply = await serveReportArtifact(request(), family, id, id);
      expect(reply.status).toBe(422);
      expect(mocks.status).not.toHaveBeenCalled();
    },
  );
  it("rejects wrong-profile or revoked source responses before minting a grant", async () => {
    mocks.status.mockResolvedValueOnce({
      data: { account_id: id, state: "succeeded", artifacts: [metadata] },
    });
    expect(
      (await serveReportArtifact(request(), "premium-reports", id, id)).status,
    ).toBe(502);
    mocks.status.mockRejectedValueOnce(
      new ReportApiError("NOT_FOUND", 404, "Report unavailable."),
    );
    expect(
      (await serveReportArtifact(request(), "premium-reports", id, id)).status,
    ).toBe(404);
    expect(mocks.grant).not.toHaveBeenCalled();
    expect(mocks.download).not.toHaveBeenCalled();
  });
  it("authenticates before form parsing", async () => {
    mocks.clients.mockRejectedValueOnce(new Error("Session required"));
    const input = request();
    const body = vi.spyOn(input, "body", "get");
    await expect(
      serveReportArtifact(input, "premium-reports", id, id),
    ).rejects.toThrow("Session required");
    expect(body).not.toHaveBeenCalled();
  });
});
