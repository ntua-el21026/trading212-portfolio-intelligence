import { beforeEach, describe, expect, it, vi } from "vitest";
import { ReportApiError } from "@trading212/api-contracts";
import { submitPremiumReportCommand } from "../lib/premium-report-actions";
const mocks = vi.hoisted(() => ({
  clients: vi.fn(),
  run: vi.fn(),
  create: vi.fn(),
  refresh: vi.fn(),
}));
vi.mock("../lib/report-adapter", () => ({
  reportClients: mocks.clients,
  reportData: (value: { data: unknown }) => value.data,
}));
vi.mock("../lib/risk-adapter", () => ({
  riskData: (value: { data: unknown }) => value.data,
}));
vi.mock("next/cache", () => ({ revalidatePath: mocks.refresh }));
const account = "20000000-0000-4000-8000-000000000001";
const runId = "20000000-0000-4000-8000-000000000002";
const snapshot = "20000000-0000-4000-8000-000000000003";
const job = "20000000-0000-4000-8000-000000000004";
const command = {
  account_id: account,
  risk_run_id: runId,
  expected_result_digest: "a".repeat(64),
  idempotency_key: "same-risk-copy",
  formats: ["pdf", "csv", "json", "xlsx"],
  ttl_days: 7,
};
const run = {
  id: runId,
  account_id: account,
  portfolio_snapshot_id: snapshot,
  state: "succeeded",
  result_availability: "available",
  result: {
    content_digest: command.expected_result_digest,
    definition: { name: "Saved risk" },
    historical_context: {
      window: {
        start_date: "2026-08-01",
        end_date: "2026-08-31",
        source_cutoff_at: "2026-09-01T12:34:56Z",
        reporting_currency: "GBP",
      },
    },
  },
};
beforeEach(() => {
  vi.resetAllMocks();
  mocks.clients.mockResolvedValue({
    risk: { get_risk_run: mocks.run },
    premiumReports: { generate_premium_portfolio_report: mocks.create },
  });
  mocks.run.mockResolvedValue({ data: run });
  mocks.create.mockResolvedValue({
    data: { account_id: account, job_id: job, state: "queued" },
  });
});
describe("saved risk report server action", () => {
  it("authenticates and checks origin before inspecting input", async () => {
    mocks.clients.mockRejectedValue(new Error("Session required"));
    const toJSON = vi.fn();
    await expect(submitPremiumReportCommand({ toJSON })).rejects.toThrow(
      "Session required",
    );
    expect(toJSON).not.toHaveBeenCalled();
    expect(mocks.run).not.toHaveBeenCalled();
    expect(mocks.clients).toHaveBeenCalledWith(true);
  });
  it("derives every immutable pin on the server and supports all four formats", async () => {
    expect(await submitPremiumReportCommand(command)).toMatchObject({
      ok: true,
      job: { job_id: job },
    });
    expect(mocks.run).toHaveBeenCalledWith(runId);
    expect(mocks.create).toHaveBeenCalledWith(
      {
        account_id: account,
        risk_run_id: runId,
        snapshot_id: snapshot,
        ...run.result.historical_context.window,
        report_type: "portfolio_summary",
        sections: ["overview", "allocation", "quality", "risk"],
        formats: command.formats,
        ttl_days: 7,
      },
      { idempotencyKey: command.idempotency_key },
    );
    expect(mocks.refresh).toHaveBeenCalledWith("/reports/premium");
  });
  it("rechecks the retained source and preserves idempotency on retry", async () => {
    mocks.create.mockRejectedValueOnce(
      new ReportApiError(
        "JOB_DISPATCH_UNAVAILABLE",
        503,
        "Retry the same request.",
      ),
    );
    expect(await submitPremiumReportCommand(command)).toMatchObject({
      ok: false,
      code: "JOB_DISPATCH_UNAVAILABLE",
    });
    await submitPremiumReportCommand(command);
    expect(mocks.clients).toHaveBeenCalledTimes(2);
    expect(mocks.run).toHaveBeenCalledTimes(2);
    expect(mocks.create.mock.calls[0]).toEqual(mocks.create.mock.calls[1]);
  });
  it.each([
    { ...run, account_id: snapshot },
    { ...run, id: snapshot },
    { ...run, state: "running", result: null },
    { ...run, result_availability: "expired", result: null },
    { ...run, result_availability: "unavailable", result: null },
  ])("rejects foreign, incomplete or expired results", async (value) => {
    mocks.run.mockResolvedValue({ data: value });
    expect(await submitPremiumReportCommand(command)).toMatchObject({
      ok: false,
      code: "SOURCE_UNAVAILABLE",
    });
    expect(mocks.create).not.toHaveBeenCalled();
  });
  it("requires the displayed canonical result digest to remain unchanged", async () => {
    mocks.run.mockResolvedValue({
      data: {
        ...run,
        result: { ...run.result, content_digest: "b".repeat(64) },
      },
    });
    expect(await submitPremiumReportCommand(command)).toMatchObject({
      ok: false,
      code: "SOURCE_CHANGED",
    });
    expect(mocks.create).not.toHaveBeenCalled();
  });
  it.each([
    { ...command, snapshot_id: snapshot },
    { ...command, return_values: [0.1] },
    { ...command, formats: ["pdf", "pdf"] },
    { ...command, ttl_days: 31 },
    { ...command, url: "https://private-canary.invalid" },
  ])(
    "rejects caller-supplied inputs beyond the closed selection",
    async (input) => {
      expect(await submitPremiumReportCommand(input)).toMatchObject({
        ok: false,
        code: "VALIDATION_FAILED",
      });
      expect(mocks.run).not.toHaveBeenCalled();
      expect(mocks.create).not.toHaveBeenCalled();
    },
  );
  it("bounds input and masks unexpected private errors", async () => {
    const oversized = await submitPremiumReportCommand({
      ...command,
      description: "private-canary".repeat(6000),
    });
    expect(oversized).toMatchObject({ ok: false, code: "REQUEST_TOO_LARGE" });
    expect(mocks.run).not.toHaveBeenCalled();
    mocks.run.mockRejectedValue(new Error("private-canary"));
    const failed = await submitPremiumReportCommand(command);
    expect(failed).toMatchObject({ ok: false, code: "REPORT_UNAVAILABLE" });
    expect(JSON.stringify([oversized, failed])).not.toContain("private-canary");
  });
});
