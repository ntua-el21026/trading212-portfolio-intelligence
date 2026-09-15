import { beforeEach, describe, expect, it, vi } from "vitest";
import { ReportApiError } from "@trading212/api-contracts";
import { submitPremiumReportV3Command } from "../lib/premium-report-actions";
import { id, scenarioRun } from "./premium-report-profile-fixtures";
const mocks = vi.hoisted(() => ({
  clients: vi.fn(),
  scenario: vi.fn(),
  risk: vi.fn(),
  create: vi.fn(),
  oldCreate: vi.fn(),
  refresh: vi.fn(),
}));
vi.mock("../lib/report-adapter", () => ({
  reportClients: mocks.clients,
  reportData: (value: { data: unknown }) => value.data,
}));
vi.mock("../lib/scenario-adapter", () => ({
  scenarioData: (value: { data: unknown }) => value.data,
}));
vi.mock("../lib/risk-adapter", () => ({
  riskData: (value: { data: unknown }) => value.data,
}));
vi.mock("next/cache", () => ({ revalidatePath: mocks.refresh }));
const run = scenarioRun();
const command = {
  profile_version: "report_sections_v3",
  account_id: id,
  premium_run: { family: "scenario", run_id: run.id },
  expected_result_digest: "b".repeat(64),
  idempotency_key: "scenario-report:one",
  formats: ["pdf", "csv", "json", "xlsx"],
  ttl_days: 7,
};
beforeEach(() => {
  vi.resetAllMocks();
  mocks.clients.mockResolvedValue({
    scenarios: { get_scenario_run: mocks.scenario },
    risk: { get_risk_run: mocks.risk },
    premiumReports: { generate_premium_portfolio_report: mocks.oldCreate },
    premiumReportsV3: { generate_premium_portfolio_report: mocks.create },
  });
  mocks.scenario.mockResolvedValue({ data: run });
  mocks.create.mockResolvedValue({
    data: {
      profile_version: "report_sections_v3",
      account_id: id,
      job_id: run.id,
      state: "queued",
    },
  });
});
describe("profile-three report server action", () => {
  it("uses saved replay dates while preserving the separate holdings cutoff", async () => {
    if (!run.result) throw new Error("synthetic source missing");
    // The action consumes only saved context pins; the typed API client owns
    // validation of the complete historical proof surrounding this mock.
    mocks.scenario.mockResolvedValueOnce({
      data: {
        ...run,
        result: {
          ...run.result,
          context: {
            ...run.result.context,
            replay: {
              selection: {
                start_date: "2025-01-01",
                end_date: "2025-12-31",
                market_knowledge_cutoff_at: "2026-01-02T12:00:00Z",
              },
            },
          },
        },
      },
    });
    expect(await submitPremiumReportV3Command(command)).toMatchObject({
      ok: true,
    });
    expect(mocks.create.mock.calls[0][0]).toMatchObject({
      start_date: "2025-01-01",
      end_date: "2025-12-31",
      source_cutoff_at: "2026-09-07T12:00:00.123456Z",
    });
  });
  it("also selects an actual retained risk run through the explicit V3 client", async () => {
    mocks.risk.mockResolvedValueOnce({
      data: {
        id: run.id,
        account_id: id,
        portfolio_snapshot_id: id,
        state: "succeeded",
        result_availability: "available",
        result: {
          content_digest: command.expected_result_digest,
          definition: { name: "Saved risk" },
          historical_context: {
            window: {
              start_date: "2026-08-01",
              end_date: "2026-08-31",
              reporting_currency: "GBP",
              source_cutoff_at: "2026-09-01T00:00:00Z",
            },
          },
        },
      },
    });
    expect(
      await submitPremiumReportV3Command({
        ...command,
        premium_run: { family: "risk", run_id: run.id },
      }),
    ).toMatchObject({ ok: true });
    expect(mocks.risk).toHaveBeenCalledWith(run.id);
    expect(mocks.scenario).not.toHaveBeenCalled();
    expect(mocks.create.mock.calls[0][0]).toMatchObject({
      profile_version: "report_sections_v3",
      premium_run: { family: "risk", run_id: run.id },
      reporting_currency: "GBP",
      sections: ["overview", "allocation", "quality", "risk"],
    });
    expect(mocks.create.mock.calls[0][0]).not.toHaveProperty("risk_run_id");
    expect(mocks.oldCreate).not.toHaveBeenCalled();
  });

  it("authenticates before inspecting input", async () => {
    mocks.clients.mockRejectedValueOnce(new Error("Session required"));
    const toJSON = vi.fn();
    await expect(submitPremiumReportV3Command({ toJSON })).rejects.toThrow(
      "Session required",
    );
    expect(toJSON).not.toHaveBeenCalled();
    expect(mocks.scenario).not.toHaveBeenCalled();
  });
  it("rereads the saved run and derives all report basis fields without financial arrays", async () => {
    expect(await submitPremiumReportV3Command(command)).toMatchObject({
      ok: true,
    });
    expect(mocks.clients).toHaveBeenCalledWith(true);
    expect(mocks.scenario).toHaveBeenCalledWith(run.id, { component_limit: 1 });
    expect(mocks.create).toHaveBeenCalledWith(
      {
        profile_version: "report_sections_v3",
        premium_run: command.premium_run,
        account_id: id,
        snapshot_id: run.portfolio_snapshot_id,
        start_date: "2026-09-07",
        end_date: "2026-09-07",
        reporting_currency: "EUR",
        source_cutoff_at: "2026-09-07T12:00:00.123456Z",
        report_type: "portfolio_summary",
        sections: ["overview", "allocation", "quality", "scenario"],
        formats: command.formats,
        ttl_days: 7,
      },
      { idempotencyKey: command.idempotency_key },
    );
    expect(mocks.risk).not.toHaveBeenCalled();
    expect(mocks.oldCreate).not.toHaveBeenCalled();
  });
  it("preserves the exact idempotency identity while rechecking each retry", async () => {
    mocks.create.mockRejectedValueOnce(
      new ReportApiError("JOB_DISPATCH_UNAVAILABLE", 503, "Retry."),
    );
    expect(await submitPremiumReportV3Command(command)).toMatchObject({
      ok: false,
    });
    await submitPremiumReportV3Command(command);
    expect(mocks.scenario).toHaveBeenCalledTimes(2);
    expect(mocks.create.mock.calls[0]).toEqual(mocks.create.mock.calls[1]);
  });
  it.each([
    { ...command, profile_version: "report_sections_v2" },
    { ...command, premium_run: { family: "projection", run_id: run.id } },
    { ...command, risk_run_id: run.id },
    { ...command, snapshot_id: id },
    { ...command, source_cutoff_at: "2026-09-01T00:00:00Z" },
    { ...command, values: ["0"] },
  ])(
    "rejects unsupported families and caller-invented basis fields",
    async (value) => {
      expect(await submitPremiumReportV3Command(value)).toMatchObject({
        ok: false,
        code: "VALIDATION_FAILED",
      });
      expect(mocks.scenario).not.toHaveBeenCalled();
      expect(mocks.create).not.toHaveBeenCalled();
    },
  );
  it("rejects another account and the presentation digest before creation", async () => {
    expect(
      await submitPremiumReportV3Command({ ...command, account_id: run.id }),
    ).toMatchObject({ ok: false, code: "SOURCE_UNAVAILABLE" });
    expect(
      await submitPremiumReportV3Command({
        ...command,
        expected_result_digest: run.result?.content_digest,
      }),
    ).toMatchObject({ ok: false, code: "SOURCE_CHANGED" });
    expect(mocks.create).not.toHaveBeenCalled();
  });
  it("masks unexpected errors and rejects a downgraded create response", async () => {
    mocks.scenario.mockRejectedValueOnce(new Error("private-canary"));
    const failed = await submitPremiumReportV3Command(command);
    expect(failed).toMatchObject({ ok: false, code: "REPORT_UNAVAILABLE" });
    expect(JSON.stringify(failed)).not.toContain("private-canary");
    mocks.create.mockResolvedValueOnce({
      data: { account_id: id, job_id: id },
    });
    expect(await submitPremiumReportV3Command(command)).toMatchObject({
      ok: false,
      code: "INVALID_RESPONSE",
    });
  });
});
