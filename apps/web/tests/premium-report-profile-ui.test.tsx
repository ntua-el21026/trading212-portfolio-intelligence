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
import { ScenarioResults } from "../components/scenario-results";
import {
  premiumScenarioReportSource,
  premiumReportSourceHref,
} from "../lib/premium-report-query";
import { readScenarioQuery } from "../lib/scenario-query";
import type { PremiumReportV3ActionResult } from "../lib/premium-report-actions";
import { id, scenarioRun } from "./premium-report-profile-fixtures";
const mocks = vi.hoisted(() => ({
  submit: vi.fn(),
  old: vi.fn(),
  push: vi.fn(),
  navigation: { current: 0 },
}));
vi.mock("../lib/premium-report-actions", () => ({
  submitPremiumReportCommand: mocks.old,
  submitPremiumReportV3Command: mocks.submit,
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: mocks.push }) }));
vi.mock("../components/navigation-intent", () => ({
  useNavigationVersionRef: () => mocks.navigation,
  default: ({
    prefetch: _prefetch,
    ...props
  }: import("react").ComponentProps<"a"> & { prefetch?: boolean }) => {
    void _prefetch;
    return <a {...props} />;
  },
}));
const run = scenarioRun();
const source = premiumScenarioReportSource(run, id);
if (!source) throw new Error("synthetic source missing");
const selected = source;
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
describe("explicit scenario report presentation", () => {
  it("sends the actual scenario pin and preserves retry identity without legacy risk fields", async () => {
    render(<PremiumReportSelection source={selected} canCreate />);
    expect(screen.getByText("Scenario run")).toBeVisible();
    fireEvent.click(
      screen.getByRole("button", { name: "Create scenario report" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "REPORT_UNAVAILABLE",
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Create scenario report" }),
    );
    await waitFor(() => expect(mocks.submit).toHaveBeenCalledTimes(2));
    expect(mocks.submit.mock.calls[0]).toEqual(mocks.submit.mock.calls[1]);
    expect(mocks.submit.mock.calls[0][0]).toMatchObject({
      profile_version: "report_sections_v3",
      premium_run: { family: "scenario", run_id: run.id },
      expected_result_digest: selected.resultDigest,
    });
    expect(mocks.submit.mock.calls[0][0]).not.toHaveProperty("risk_run_id");
    expect(mocks.old).not.toHaveBeenCalled();
  });
  it("rejects an unmarked response rather than downgrading report navigation", async () => {
    mocks.submit.mockResolvedValue({
      ok: true,
      job: { account_id: id, job_id: id },
    });
    render(<PremiumReportSelection source={selected} canCreate />);
    fireEvent.click(
      screen.getByRole("button", { name: "Create scenario report" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "could not be verified",
    );
    expect(mocks.push).not.toHaveBeenCalled();
  });
  it("keeps profile and exact canonical hints when opening a newly created report", async () => {
    mocks.submit.mockResolvedValue({
      ok: true,
      job: {
        profile_version: "report_sections_v3",
        account_id: id,
        job_id: id,
      },
    });
    render(<PremiumReportSelection source={selected} canCreate />);
    fireEvent.click(
      screen.getByRole("button", { name: "Create scenario report" }),
    );
    await waitFor(() =>
      expect(mocks.push).toHaveBeenCalledWith(
        premiumReportSourceHref(selected, id),
      ),
    );
  });
  it("discards a late command result when account or profile navigation advances", async () => {
    let finish!: (value: PremiumReportV3ActionResult) => void;
    mocks.submit.mockImplementation(
      () =>
        new Promise<PremiumReportV3ActionResult>((resolve) => {
          finish = resolve;
        }),
    );
    render(<PremiumReportSelection source={selected} canCreate />);
    fireEvent.click(
      screen.getByRole("button", { name: "Create scenario report" }),
    );
    mocks.navigation.current += 1;
    await act(async () =>
      finish({ ok: false, code: "OLD_ACCOUNT", message: "Old result" }),
    );
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(mocks.push).not.toHaveBeenCalled();
  });
  it("links an available scenario to its complete report basis without changing component rows", () => {
    const query = readScenarioQuery(
      { account: id, view: "result", run: run.id },
      { now: new Date("2026-09-07T12:00:00Z"), currency: "EUR" },
    );
    const view = render(<ScenarioResults run={run} query={query} />);
    expect(
      screen.getByRole("link", {
        name: "Create a report from this saved scenario",
      }),
    ).toHaveAttribute("href", premiumReportSourceHref(selected));
    expect(
      screen.getByRole("table", { name: "Saved scenario terminal components" }),
    ).toBeInTheDocument();
    view.rerender(
      <ScenarioResults run={run} query={{ ...query, account: run.id }} />,
    );
    expect(
      screen.queryByRole("link", {
        name: "Create a report from this saved scenario",
      }),
    ).not.toBeInTheDocument();
  });
  it("pins downloads to profile three and abandons late bytes after a profile change", async () => {
    let finish!: (response: Response) => void;
    const fetcher = vi.fn<
      (url: string, options: RequestInit) => Promise<Response>
    >(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    vi.stubGlobal("fetch", fetcher);
    class ArtifactURL extends URL {
      static createObjectURL = vi.fn();
      static revokeObjectURL = vi.fn();
    }
    vi.stubGlobal("URL", ArtifactURL);
    const artifact = {
      artifact_id: id,
      format: "json" as const,
      mime_type: "application/json" as const,
      byte_length: 2,
      content_digest: "a".repeat(64),
      expires_at: "2026-09-30T00:00:00Z",
    };
    const view = render(
      <ReportDownloadButton
        accountId={id}
        parentId={run.id}
        family="premium-reports"
        profile="report_sections_v3"
        artifact={artifact}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Download JSON" }));
    const options = fetcher.mock.calls[0][1];
    expect(options.body?.toString()).toBe(
      `account_id=${id}&profile=report_sections_v3`,
    );
    view.rerender(
      <ReportDownloadButton
        accountId={id}
        parentId={run.id}
        family="premium-reports"
        artifact={artifact}
      />,
    );
    expect(options.signal?.aborted).toBe(true);
    await act(async () => finish(new Response("{}")));
    expect(ArtifactURL.createObjectURL).not.toHaveBeenCalled();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
