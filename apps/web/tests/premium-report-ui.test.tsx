import { webcrypto } from "node:crypto";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PremiumReportSelection } from "../components/premium-report-selection";
import { ReportDownloadButton } from "../components/report-download";
import { job } from "./report-fixtures";
import type { PremiumReportActionResult } from "../lib/premium-report-actions";
import type { PremiumReportSource } from "../lib/premium-report-query";
const mocks = vi.hoisted(() => ({
  submit: vi.fn(),
  push: vi.fn(),
  navigation: { current: 0 },
}));
vi.mock("../lib/premium-report-actions", () => ({
  submitPremiumReportCommand: mocks.submit,
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: mocks.push }) }));
vi.mock("../components/navigation-intent", () => ({
  useNavigationVersionRef: () => mocks.navigation,
}));
const source: PremiumReportSource = {
  accountId: "20000000-0000-4000-8000-000000000001",
  runId: "20000000-0000-4000-8000-000000000002",
  snapshotId: "20000000-0000-4000-8000-000000000003",
  startDate: "2026-08-01",
  endDate: "2026-08-31",
  sourceCutoff: "2026-09-01T12:34:56Z",
  currency: "GBP",
  resultDigest: "a".repeat(64),
  name: "Saved analysis",
};
beforeEach(() => {
  vi.resetAllMocks();
  mocks.navigation.current = 0;
  vi.stubGlobal("crypto", webcrypto);
  mocks.submit.mockResolvedValue({
    ok: false,
    code: "REPORT_UNAVAILABLE",
    message: "Retry the same selection.",
  });
});
afterEach(() => vi.unstubAllGlobals());
describe("risk report creation", () => {
  it("shows canonical pins and preserves formats plus retry identity across failures", async () => {
    render(<PremiumReportSelection source={source} canCreate />);
    expect(screen.getByText(source.snapshotId)).toBeVisible();
    expect(screen.getByText("GBP")).toBeVisible();
    for (const format of ["CSV", "JSON", "XLSX"])
      fireEvent.click(screen.getByRole("checkbox", { name: format }));
    fireEvent.click(screen.getByRole("button", { name: "Create risk report" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "REPORT_UNAVAILABLE",
    );
    fireEvent.click(screen.getByRole("button", { name: "Create risk report" }));
    await waitFor(() => expect(mocks.submit).toHaveBeenCalledTimes(2));
    expect(mocks.submit.mock.calls[0]).toEqual(mocks.submit.mock.calls[1]);
    expect(mocks.submit.mock.calls[0][0]).toMatchObject({
      risk_run_id: source.runId,
      expected_result_digest: source.resultDigest,
      formats: ["pdf", "csv", "json", "xlsx"],
      ttl_days: 7,
    });
    expect(mocks.submit.mock.calls[0][0]).not.toHaveProperty("snapshot_id");
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Create risk report" }),
      ).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole("checkbox", { name: "XLSX" }));
    fireEvent.click(screen.getByRole("button", { name: "Create risk report" }));
    await waitFor(() => expect(mocks.submit).toHaveBeenCalledTimes(3));
    expect(mocks.submit.mock.calls[2][0].idempotency_key).not.toBe(
      mocks.submit.mock.calls[0][0].idempotency_key,
    );
  });
  it.each(["navigation", "unmount"])(
    "discards responses after %s",
    async (change) => {
      let resolve!: (reply: PremiumReportActionResult) => void;
      mocks.submit.mockImplementation(
        () =>
          new Promise<PremiumReportActionResult>((done) => {
            resolve = done;
          }),
      );
      const view = render(<PremiumReportSelection source={source} canCreate />);
      fireEvent.click(
        screen.getByRole("button", { name: "Create risk report" }),
      );
      if (change === "navigation") mocks.navigation.current += 1;
      else view.unmount();
      await act(async () =>
        resolve({
          ok: false,
          code: "OLD_ACCOUNT",
          message: "Old account error",
        }),
      );
      expect(screen.queryByText(/OLD_ACCOUNT/)).not.toBeInTheDocument();
      expect(mocks.push).not.toHaveBeenCalled();
    },
  );
  it("disables unavailable creation and rejects an empty format selection", () => {
    const view = render(
      <PremiumReportSelection source={source} canCreate={false} />,
    );
    expect(
      screen.getByRole("button", { name: "Create risk report" }),
    ).toBeDisabled();
    view.rerender(<PremiumReportSelection source={source} canCreate />);
    fireEvent.click(screen.getByRole("checkbox", { name: "PDF" }));
    expect(
      screen.getByRole("button", { name: "Create risk report" }),
    ).toBeDisabled();
    expect(mocks.submit).not.toHaveBeenCalled();
  });
});

describe("premium artifact navigation safety", () => {
  it.each(["navigation", "unmount"])(
    "discards old download bytes after %s and releases its busy state",
    async (change) => {
      let finish!: (response: Response) => void;
      const fetcher = vi.fn<
        (url: string, options: RequestInit) => Promise<Response>
      >(
        () =>
          new Promise<Response>((resolve) => {
            finish = resolve;
          }),
      );
      vi.stubGlobal("fetch", fetcher);
      class ArtifactURL extends URL {
        static createObjectURL = vi.fn(() => "blob:private-test");
        static revokeObjectURL = vi.fn();
      }
      vi.stubGlobal("URL", ArtifactURL);
      const artifact = {
        artifact_id: source.snapshotId,
        format: "json" as const,
        mime_type: "application/json" as const,
        byte_length: 2,
        content_digest: "a".repeat(64),
        expires_at: "2026-09-30T00:00:00Z",
      };
      const view = render(
        <ReportDownloadButton
          accountId={source.accountId}
          parentId={source.runId}
          family="premium-reports"
          artifact={artifact}
        />,
      );
      fireEvent.click(screen.getByRole("button", { name: "Download JSON" }));
      expect(fetcher.mock.calls[0][0]).toBe(
        `/api/premium-reports/${source.runId}/artifacts/${source.snapshotId}/download`,
      );
      const options = fetcher.mock.calls[0][1];
      expect(options.body?.toString()).toBe(`account_id=${source.accountId}`);
      mocks.navigation.current += 1;
      if (change === "unmount") {
        view.unmount();
        expect(options.signal?.aborted).toBe(true);
      }
      await act(async () => finish(new Response("{}")));
      expect(ArtifactURL.createObjectURL).not.toHaveBeenCalled();
      if (change === "navigation") {
        expect(
          screen.getByRole("button", { name: "Download JSON" }),
        ).toBeEnabled();
        expect(screen.queryByRole("alert")).not.toBeInTheDocument();
      }
    },
  );
  it("opens only the selected account's premium report after creation", async () => {
    mocks.submit.mockResolvedValue({
      ok: true,
      job: { ...job, account_id: source.accountId, context: null },
    });
    render(<PremiumReportSelection source={source} canCreate />);
    fireEvent.click(screen.getByRole("button", { name: "Create risk report" }));
    await waitFor(() =>
      expect(mocks.push).toHaveBeenCalledWith(
        `/reports/premium?account=${source.accountId}&run=${source.runId}&report=${job.job_id}`,
      ),
    );
  });
});
