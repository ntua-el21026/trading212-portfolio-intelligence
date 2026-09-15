import { beforeEach, describe, expect, it, vi } from "vitest";
import { ReportApiError } from "@trading212/api-contracts";
import { submitProjectionReportCommand } from "../lib/projection-report-actions";
import {
  account,
  id,
  other,
  saved,
  snapshot,
  command,
} from "./projection-report-fixtures";
const mocks = vi.hoisted(() => ({
  clients: vi.fn(),
  run: vi.fn(),
  snapshot: vi.fn(),
  create: vi.fn(),
  previous: vi.fn(),
  refresh: vi.fn(),
}));
vi.mock("../lib/report-adapter", () => ({
  reportClients: mocks.clients,
  reportData: (value: { data: unknown }) => value.data,
}));
vi.mock("../lib/projection-adapter", () => ({
  projectionData: (value: { data: unknown }) => value.data,
}));
vi.mock("next/cache", () => ({ revalidatePath: mocks.refresh }));
beforeEach(() => {
  vi.resetAllMocks();
  mocks.clients.mockResolvedValue({
    projections: { get_projection_run: mocks.run },
    portfolio: { getSnapshot: mocks.snapshot },
    premiumReports: { generate_premium_portfolio_report: mocks.previous },
    premiumReportsV3: { generate_premium_portfolio_report: mocks.previous },
    premiumReportsV4: { generate_premium_portfolio_report: mocks.create },
  });
  mocks.run.mockResolvedValue({ data: saved });
  mocks.snapshot.mockResolvedValue(snapshot);
  mocks.create.mockResolvedValue({
    data: {
      profile_version: "report_sections_v4",
      account_id: account,
      job_id: id,
      state: "queued",
      context: { snapshot_id: other, reporting_currency: "EUR" },
    },
  });
});
describe("projection report admission action", () => {
  it("authenticates before parsing or reading caller input", async () => {
    mocks.clients.mockRejectedValueOnce(new Error("Session required"));
    const toJSON = vi.fn();
    await expect(submitProjectionReportCommand({ toJSON })).rejects.toThrow(
      "Session required",
    );
    expect(toJSON).not.toHaveBeenCalled();
    expect(mocks.run).not.toHaveBeenCalled();
  });
  it("rereads the exact owned snapshot and canonical run without copying a sampled view into the request", async () => {
    expect(await submitProjectionReportCommand(command)).toMatchObject({
      ok: true,
    });
    expect(mocks.clients).toHaveBeenCalledWith(true);
    expect(mocks.run).toHaveBeenCalledWith(id, { point_limit: 1 });
    expect(mocks.snapshot).toHaveBeenCalledWith(account, other);
    expect(mocks.create).toHaveBeenCalledWith(
      {
        profile_version: "report_sections_v4",
        premium_run: command.premium_run,
        account_id: account,
        snapshot_id: other,
        reporting_currency: "EUR",
        start_date: "2026-09-14",
        end_date: "2026-09-14",
        source_cutoff_at: snapshot.source_cutoff_at,
        report_type: "portfolio_summary",
        sections: ["overview", "allocation", "quality", "projection"],
        formats: command.formats,
        ttl_days: 7,
      },
      { idempotencyKey: command.idempotency_key },
    );
    expect(mocks.previous).not.toHaveBeenCalled();
  });
  it("preserves the retry identity while reauthorizing both immutable resources", async () => {
    mocks.create.mockRejectedValueOnce(
      new ReportApiError("JOB_DISPATCH_UNAVAILABLE", 503, "Retry."),
    );
    expect(await submitProjectionReportCommand(command)).toMatchObject({
      ok: false,
    });
    expect(await submitProjectionReportCommand(command)).toMatchObject({
      ok: true,
    });
    expect(mocks.run).toHaveBeenCalledTimes(2);
    expect(mocks.snapshot).toHaveBeenCalledTimes(2);
    expect(mocks.create.mock.calls[0]).toEqual(mocks.create.mock.calls[1]);
  });
  it.each([
    { ...command, premium_run: { family: "scenario", run_id: id } },
    { ...command, profile_version: "report_sections_v3" },
    { ...command, source_cutoff_at: snapshot.source_cutoff_at },
    { ...command, coefficients: ["0"] },
    { ...command, formats: ["json", "json"] },
    { ...command, ttl_days: 31 },
  ])(
    "rejects fabricated fields and ambiguous selectors before private reads",
    async (value) => {
      expect(await submitProjectionReportCommand(value)).toMatchObject({
        ok: false,
        code: "VALIDATION_FAILED",
      });
      expect(mocks.run).not.toHaveBeenCalled();
      expect(mocks.snapshot).not.toHaveBeenCalled();
      expect(mocks.create).not.toHaveBeenCalled();
    },
  );
  it.each([
    { ...command, expected_result_digest: "d".repeat(64) },
    { ...command, expected_capture_digest: "f".repeat(64) },
    { ...command, expected_snapshot_cutoff: "2026-09-01T00:00:00Z" },
  ])(
    "rejects changed identities instead of substituting latest values",
    async (value) => {
      expect(await submitProjectionReportCommand(value)).toMatchObject({
        ok: false,
        code: "SOURCE_CHANGED",
      });
      expect(mocks.create).not.toHaveBeenCalled();
    },
  );
  it("never invents an unpinned goal or treats a foreign account as the current selection", async () => {
    expect(
      await submitProjectionReportCommand({ ...command, include_goal: true }),
    ).toMatchObject({ ok: false, code: "SOURCE_UNAVAILABLE" });
    expect(
      await submitProjectionReportCommand({ ...command, account_id: other }),
    ).toMatchObject({ ok: false, code: "SOURCE_UNAVAILABLE" });
    expect(mocks.create).not.toHaveBeenCalled();
  });
  it("rejects missing or downgraded response context and sanitizes unexpected read errors", async () => {
    mocks.create.mockResolvedValueOnce({
      data: {
        account_id: account,
        profile_version: "report_sections_v3",
        context: null,
      },
    });
    expect(await submitProjectionReportCommand(command)).toMatchObject({
      ok: false,
      code: "INVALID_RESPONSE",
    });
    mocks.run.mockRejectedValueOnce(new Error("private-canary"));
    const failed = await submitProjectionReportCommand(command);
    expect(failed).toMatchObject({ ok: false, code: "REPORT_UNAVAILABLE" });
    expect(JSON.stringify(failed)).not.toContain("private-canary");
  });
});
