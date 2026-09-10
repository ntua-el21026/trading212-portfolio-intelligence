import { beforeEach, describe, expect, it, vi } from "vitest";
import { ReportApiError } from "@trading212/api-contracts";
import { submitReportCommand } from "../lib/report-actions";
const mocks = vi.hoisted(() => ({
  clients: vi.fn(),
  report: vi.fn(),
  export: vi.fn(),
  revalidate: vi.fn(),
}));
vi.mock("../lib/report-adapter", () => ({
  reportClients: mocks.clients,
  reportData: (value: { data: unknown }) => value.data,
}));
vi.mock("next/cache", () => ({ revalidatePath: mocks.revalidate }));
const id = "20000000-0000-4000-8000-000000000001";
const body = {
  account_id: id,
  snapshot_id: id,
  start_date: "2026-09-01",
  end_date: "2026-09-07",
  source_cutoff_at: "2026-09-07T12:00:00Z",
  reporting_currency: "EUR",
  report_type: "portfolio_summary",
  formats: ["pdf", "json"],
  sections: ["overview", "allocation", "quality"],
};

describe("private report server actions", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.clients.mockResolvedValue({
      reports: {
        generate_portfolio_report: mocks.report,
        create_portfolio_export: mocks.export,
      },
    });
  });
  it("authorizes before reading command input", async () => {
    mocks.clients.mockRejectedValueOnce(new Error("Authentication required"));
    const toJSON = vi.fn();
    await expect(submitReportCommand({ toJSON })).rejects.toThrow(
      "Authentication required",
    );
    expect(toJSON).not.toHaveBeenCalled();
    expect(mocks.report).not.toHaveBeenCalled();
    expect(mocks.clients).toHaveBeenCalledWith(true);
  });
  it("preserves exact selection and retry identity across recoverable failures", async () => {
    const command = { kind: "report", idempotency_key: "retry:one", body };
    mocks.report.mockRejectedValueOnce(
      new ReportApiError(
        "JOB_DISPATCH_UNAVAILABLE",
        503,
        "Retry the same request.",
      ),
    );
    expect(await submitReportCommand(command)).toMatchObject({
      ok: false,
      code: "JOB_DISPATCH_UNAVAILABLE",
    });
    expect(mocks.revalidate).not.toHaveBeenCalled();
    mocks.report.mockResolvedValueOnce({
      data: { job_id: id, state: "queued" },
    });
    expect(await submitReportCommand(command)).toMatchObject({
      ok: true,
      kind: "report",
      job: { job_id: id },
    });
    expect(mocks.report.mock.calls[0]).toEqual(mocks.report.mock.calls[1]);
    expect(mocks.report).toHaveBeenLastCalledWith(body, {
      idempotencyKey: "retry:one",
    });
    expect(mocks.revalidate).toHaveBeenCalledWith("/reports");
  });
  it("bounds caller-controlled data and hides untrusted exceptions", async () => {
    for (const input of [
      {
        kind: "report",
        idempotency_key: "one",
        body: { ...body, destination: "private-canary" },
      },
      { value: "a".repeat(65537) },
    ]) {
      const reply = await submitReportCommand(input);
      expect(reply.ok).toBe(false);
      expect(JSON.stringify(reply)).not.toContain("private-canary");
    }
    expect(mocks.report).not.toHaveBeenCalled();
    mocks.report.mockRejectedValueOnce(new Error("private-canary"));
    const reply = await submitReportCommand({
      kind: "report",
      idempotency_key: "one",
      body,
    });
    expect(reply).toMatchObject({ ok: false, code: "REPORT_UNAVAILABLE" });
    expect(JSON.stringify(reply)).not.toContain("private-canary");
  });
});
