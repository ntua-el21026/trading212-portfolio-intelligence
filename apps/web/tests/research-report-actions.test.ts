import { beforeEach, describe, expect, it, vi } from "vitest";
import { ReportApiError } from "@trading212/api-contracts";
import { submitResearchReportCommand } from "../lib/research-report-actions";
import { account, id, item, other } from "./research-ui-fixtures";

const mocks = vi.hoisted(() => ({
  clients: vi.fn(),
  item: vi.fn(),
  create: vi.fn(),
  refresh: vi.fn(),
}));
vi.mock("../lib/report-adapter", () => ({
  reportClients: mocks.clients,
  reportData: (value: { data: unknown }) => value.data,
}));
vi.mock("../lib/research-adapter", () => ({
  researchData: (value: { data: unknown }) => value.data,
}));
vi.mock("next/cache", () => ({ revalidatePath: mocks.refresh }));
vi.mock("@trading212/api-contracts", async (original) => ({
  ...(await original<typeof import("@trading212/api-contracts")>()),
  ResearchApiClient: class {
    get_research_item = mocks.item;
  },
}));
const oldRevision = "00000000-0000-4000-8000-000000000009";
const command = {
  account_id: account,
  premium_run: {
    family: "research",
    item_id: id,
    note_revision_ids: [oldRevision],
  },
  expected_event_digest: "d".repeat(64),
  expected_xray_result_digest: "b".repeat(64),
  idempotency_key: "research-report:exact",
  formats: ["pdf", "csv", "json", "xlsx"],
  ttl_days: 7,
};
beforeEach(() => {
  vi.resetAllMocks();
  mocks.clients.mockResolvedValue({
    options: { baseUrl: "https://portfolio.example" },
    access: {
      principal: {
        scopes: [
          "portfolio:read",
          "analytics:read",
          "reports:write",
          "research:read",
        ],
      },
    },
    premiumReportsV3: { generate_premium_portfolio_report: mocks.create },
  });
  mocks.item.mockResolvedValue({ data: item });
  mocks.create.mockResolvedValue({
    data: {
      account_id: account,
      job_id: other,
      profile_version: "report_sections_v3",
      state: "queued",
    },
  });
});
describe("research report server command", () => {
  it("uses exact selected historical versions and derives basis without current-head substitution", async () => {
    expect(await submitResearchReportCommand(command)).toMatchObject({
      ok: true,
    });
    expect(mocks.clients).toHaveBeenCalledWith(true);
    expect(mocks.item).toHaveBeenCalledWith(id);
    expect(mocks.create).toHaveBeenCalledWith(
      {
        profile_version: "report_sections_v3",
        premium_run: command.premium_run,
        account_id: account,
        snapshot_id: item.portfolio.pin.snapshot_id,
        start_date: "2026-08-31",
        end_date: "2026-08-31",
        source_cutoff_at: item.source_cutoff_at,
        reporting_currency: "EUR",
        report_type: "portfolio_summary",
        sections: ["overview", "allocation", "quality", "research"],
        formats: command.formats,
        ttl_days: 7,
      },
      { idempotencyKey: command.idempotency_key },
    );
    expect(
      mocks.create.mock.calls[0][0].premium_run.note_revision_ids,
    ).not.toContain(item.owner_revisions[0].revision_id);
    expect(mocks.create.mock.calls[0][0].premium_run).not.toHaveProperty(
      "run_id",
    );
  });
  it("preserves explicit empty notes and optional exact review identity", async () => {
    await submitResearchReportCommand({
      ...command,
      premium_run: {
        family: "research",
        item_id: id,
        note_revision_ids: [],
        review_acknowledgment_id: other,
      },
    });
    expect(mocks.create.mock.calls[0][0].premium_run).toEqual({
      family: "research",
      item_id: id,
      note_revision_ids: [],
      review_acknowledgment_id: other,
    });
    await submitResearchReportCommand({
      ...command,
      premium_run: { family: "research", item_id: id, note_revision_ids: [] },
    });
    expect(mocks.create.mock.calls[1][0].premium_run).not.toHaveProperty(
      "review_acknowledgment_id",
    );
  });
  it("authenticates before serializing input or reading private research", async () => {
    mocks.clients.mockRejectedValueOnce(new Error("Session required"));
    const toJSON = vi.fn();
    await expect(submitResearchReportCommand({ toJSON })).rejects.toThrow(
      "Session required",
    );
    expect(toJSON).not.toHaveBeenCalled();
    expect(mocks.item).not.toHaveBeenCalled();
  });
  it("requires research scope before caller serialization and source reads", async () => {
    mocks.clients.mockResolvedValueOnce({
      access: { principal: { scopes: [] } },
    });
    const toJSON = vi.fn();
    expect(await submitResearchReportCommand({ toJSON })).toMatchObject({
      ok: false,
      code: "ACCESS_DENIED",
    });
    expect(toJSON).not.toHaveBeenCalled();
    expect(mocks.item).not.toHaveBeenCalled();
  });
  it.each([
    {
      ...command,
      premium_run: {
        family: "research",
        item_id: id,
        note_revision_ids: [id, id],
      },
    },
    {
      ...command,
      premium_run: {
        family: "research",
        item_id: id,
        note_revision_ids: [],
        run_id: other,
      },
    },
    { ...command, premium_run: { family: "research", item_id: id } },
    { ...command, snapshot_id: other },
    { ...command, source_cutoff_at: item.source_cutoff_at },
    { ...command, values: ["999"] },
  ])(
    "rejects malformed pins and caller-provided financial bases",
    async (value) => {
      expect(await submitResearchReportCommand(value)).toMatchObject({
        ok: false,
        code: "VALIDATION_FAILED",
      });
      expect(mocks.item).not.toHaveBeenCalled();
      expect(mocks.create).not.toHaveBeenCalled();
    },
  );
  it("retains retry semantics and rechecks current item authority each time", async () => {
    mocks.create.mockRejectedValueOnce(
      new ReportApiError("REPORT_UNAVAILABLE", 503, "Retry."),
    );
    expect(await submitResearchReportCommand(command)).toMatchObject({
      ok: false,
    });
    await submitResearchReportCommand(command);
    expect(mocks.item).toHaveBeenCalledTimes(2);
    expect(mocks.create.mock.calls[0]).toEqual(mocks.create.mock.calls[1]);
  });
  it("denies account/basis changes and masks unexpected failures", async () => {
    expect(
      await submitResearchReportCommand({ ...command, account_id: other }),
    ).toMatchObject({ ok: false, code: "SOURCE_UNAVAILABLE" });
    expect(
      await submitResearchReportCommand({
        ...command,
        expected_event_digest: "0".repeat(64),
      }),
    ).toMatchObject({ ok: false, code: "SOURCE_CHANGED" });
    expect(mocks.create).not.toHaveBeenCalled();
    mocks.item.mockRejectedValueOnce(new Error("private-source-canary"));
    expect(
      JSON.stringify(await submitResearchReportCommand(command)),
    ).not.toContain("private-source-canary");
  });
});
