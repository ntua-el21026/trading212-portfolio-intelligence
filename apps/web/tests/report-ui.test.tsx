import { webcrypto } from "node:crypto";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ReportSelectionForm } from "../components/report-selection";
import { ReportJobStatusCard } from "../components/report-job-status";
import { ReportHistory } from "../components/report-history";
import { ReportArtifacts } from "../components/report-manifest";
import { parseReportQuery } from "../lib/report-query";
import { accountId, job, snapshot } from "./report-fixtures";
const mocks = vi.hoisted(() => ({
  command: vi.fn(),
  push: vi.fn(),
  refresh: vi.fn(),
}));
vi.mock("../lib/report-actions", () => ({
  submitReportCommand: mocks.command,
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mocks.push, refresh: mocks.refresh }),
  useSearchParams: () => new URLSearchParams(window.location.search),
}));
const choices = { targets: [], plans: [], benchmarks: [], warnings: [] };

describe("report selection and retained status", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.stubGlobal("crypto", webcrypto);
    window.history.replaceState({}, "", "/reports");
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });
  it("preserves an explicit request and reuses its identity after a failed attempt and reload", async () => {
    const user = userEvent.setup();
    mocks.command.mockResolvedValue({
      ok: false,
      code: "REPORT_UNAVAILABLE",
      message: "Retry the same request.",
    });
    const renderForm = (initial = parseReportQuery({})) => (
      <ReportSelectionForm
        accountId={accountId}
        snapshot={snapshot}
        initial={initial}
        choices={choices}
        canCreate
      />
    );
    const first = render(renderForm());
    await user.click(screen.getByRole("checkbox", { name: "JSON" }));
    await user.click(screen.getByRole("button", { name: "Generate report" }));
    expect(await screen.findByText(/REPORT_UNAVAILABLE/)).toBeVisible();
    const initial = parseReportQuery(
      Object.fromEntries(new URL(window.location.href).searchParams),
    );
    expect(initial.formats).toBe("pdf,json");
    expect(initial.source_cutoff_at).toBe(snapshot.source_cutoff_at);
    first.unmount();
    render(renderForm(initial));
    await user.click(screen.getByRole("button", { name: "Generate report" }));
    expect(await screen.findByText(/REPORT_UNAVAILABLE/)).toBeVisible();
    expect(mocks.command).toHaveBeenCalledTimes(2);
    expect(mocks.command.mock.calls[0]).toEqual(mocks.command.mock.calls[1]);
    expect(mocks.command.mock.calls[0][0].body.sections).toEqual([
      "overview",
      "allocation",
      "quality",
    ]);
    expect(screen.getByLabelText("Reporting currency")).toHaveValue("EUR");
  });
  it("supports saved references beyond the bounded suggestion list and honest export formats", async () => {
    const user = userEvent.setup();
    render(
      <ReportSelectionForm
        accountId={accountId}
        snapshot={snapshot}
        initial={parseReportQuery({})}
        choices={choices}
        canCreate
      />,
    );
    await user.selectOptions(
      screen.getByLabelText("Report type"),
      "target_drift",
    );
    const target = screen.getByLabelText("Published target");
    await user.type(target, accountId);
    expect(target).toHaveValue(accountId);
    await user.selectOptions(screen.getByLabelText("Output"), "export");
    expect(
      screen.getByLabelText("Dataset").querySelectorAll("option"),
    ).toHaveLength(8);
    expect(
      screen.getByLabelText("Format").querySelectorAll("option"),
    ).toHaveLength(3);
    await user.selectOptions(screen.getByLabelText("Dataset"), "alerts");
    expect(screen.getByLabelText("Dataset")).toHaveValue("alerts");
    expect(screen.getByLabelText("Format")).not.toHaveTextContent("PDF");
  });
  it("shows partial quality and warning counts while preventing expired downloads", async () => {
    const user = userEvent.setup();
    const view = render(<ReportJobStatusCard job={job} />);
    await user.click(screen.getByText("Captured inputs and quality"));
    expect(
      screen.getByText("Quality: partial · availability: partial"),
    ).toBeVisible();
    expect(
      screen.getByText("Synthetic source coverage is partial."),
    ).toBeVisible();
    expect(screen.getByText(/2 additional warning/)).toBeVisible();
    const expired = { ...job, state: "expired" as const, context: null };
    view.rerender(
      <>
        <ReportJobStatusCard job={expired} />
        <ReportArtifacts job={expired} />
      </>,
    );
    expect(
      screen.getByText(/licensed input detail is no longer retained/),
    ).toBeVisible();
    expect(
      screen.queryByRole("button", { name: /Download/ }),
    ).not.toBeInTheDocument();
  });
  it("keeps type, state and account filters in history paging and selected jobs", () => {
    render(
      <ReportHistory
        history={{
          items: [job],
          next_cursor: "next_page",
          limit: 25,
          total: 2,
        }}
        accountId={accountId}
        query={parseReportQuery({
          state: "queued",
          history_type: "portfolio_summary",
          account: accountId,
          cursor: "page_one",
        })}
      />,
    );
    const next = screen.getByRole("link", { name: /Next page/ });
    const url = new URL(
      next.getAttribute("href")!,
      "https://portfolio.example",
    );
    expect(url.searchParams.get("state")).toBe("queued");
    expect(url.searchParams.get("history_type")).toBe("portfolio_summary");
    expect(url.searchParams.get("account")).toBe(accountId);
    expect(
      screen.getByRole("table", { name: "Private report history" }),
    ).toBeVisible();
  });
  it("stops background polling when a terminal state arrives", async () => {
    vi.useFakeTimers();
    const view = render(<ReportJobStatusCard job={job} />);
    await act(() => vi.advanceTimersByTimeAsync(5000));
    expect(mocks.refresh).toHaveBeenCalledTimes(1);
    view.rerender(
      <ReportJobStatusCard
        job={{ ...job, state: "failed", failure_code: "render_failed" }}
      />,
    );
    await act(() => vi.advanceTimersByTimeAsync(30000));
    expect(mocks.refresh).toHaveBeenCalledTimes(1);
    expect(screen.getByText("Reason: Render Failed")).toBeVisible();
  });
});
