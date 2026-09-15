import { webcrypto } from "node:crypto";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ProjectionReportSelection } from "../components/projection-report-selection";
import {
  projectionReportSource,
  projectionReportSourceHref,
} from "../lib/projection-report-query";
import type { ProjectionReportActionResult } from "../lib/projection-report-actions";
import {
  account,
  id,
  other,
  saved,
  snapshot,
} from "./projection-report-fixtures";
const mocks = vi.hoisted(() => ({
  submit: vi.fn(),
  push: vi.fn(),
  navigation: { current: 0 },
}));
vi.mock("../lib/projection-report-actions", () => ({
  submitProjectionReportCommand: mocks.submit,
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: mocks.push }) }));
vi.mock("../components/navigation-intent", () => ({
  useNavigationVersionRef: () => mocks.navigation,
}));
const selected = projectionReportSource(saved, account, snapshot);
if (!selected) throw new Error("synthetic source missing");
const source = selected;
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
describe("projection report selection", () => {
  it("keeps model dates and absent source clocks distinct from report snapshot clocks", () => {
    render(<ProjectionReportSelection source={source} canCreate />);
    expect(
      screen.getByText("No observed valuation; modeled starting value"),
    ).toBeVisible();
    expect(
      screen.getByText("Not supplied by every original source"),
    ).toBeVisible();
    expect(screen.getByText("2026-09-15 to 2027-09-15")).toBeVisible();
    expect(screen.getByText(/No goal is pinned/)).toBeVisible();
    expect(
      screen.queryByRole("checkbox", {
        name: "Include the pinned goal section",
      }),
    ).not.toBeInTheDocument();
  });
  it("submits all four formats and the exact saved identities, preserving retries", async () => {
    render(<ProjectionReportSelection source={source} canCreate />);
    for (const format of ["CSV", "JSON", "XLSX"])
      fireEvent.click(screen.getByRole("checkbox", { name: format }));
    fireEvent.click(
      screen.getByRole("button", { name: "Create projection report" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "REPORT_UNAVAILABLE",
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Create projection report" }),
    );
    await waitFor(() => expect(mocks.submit).toHaveBeenCalledTimes(2));
    expect(mocks.submit.mock.calls[0]).toEqual(mocks.submit.mock.calls[1]);
    expect(mocks.submit.mock.calls[0][0]).toMatchObject({
      profile_version: "report_sections_v4",
      premium_run: { family: "projection", run_id: id },
      snapshot_id: other,
      expected_result_digest: source.resultDigest,
      expected_capture_digest: source.captureDigest,
      formats: ["pdf", "csv", "json", "xlsx"],
      include_goal: false,
    });
    expect(mocks.submit.mock.calls[0][0]).not.toHaveProperty("risk_run_id");
  });
  it("uses a new idempotency identity only when the submitted selection changes", async () => {
    render(
      <ProjectionReportSelection
        source={{ ...source, goalVersionId: other }}
        canCreate
      />,
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Create projection report" }),
    );
    await screen.findByRole("alert");
    fireEvent.click(
      screen.getByRole("checkbox", { name: "Include the pinned goal section" }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Create projection report" }),
    );
    await waitFor(() => expect(mocks.submit).toHaveBeenCalledTimes(2));
    expect(mocks.submit.mock.calls[0][0].idempotency_key).not.toBe(
      mocks.submit.mock.calls[1][0].idempotency_key,
    );
    expect(mocks.submit.mock.calls[0][0].include_goal).toBe(true);
    expect(mocks.submit.mock.calls[1][0].include_goal).toBe(false);
  });
  it("discards late replies after account or profile navigation", async () => {
    let finish!: (value: ProjectionReportActionResult) => void;
    mocks.submit.mockImplementation(
      () =>
        new Promise<ProjectionReportActionResult>((resolve) => {
          finish = resolve;
        }),
    );
    render(<ProjectionReportSelection source={source} canCreate />);
    fireEvent.click(
      screen.getByRole("button", { name: "Create projection report" }),
    );
    mocks.navigation.current += 1;
    await act(async () =>
      finish({ ok: false, code: "OLD_ACCOUNT", message: "Old response" }),
    );
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(mocks.push).not.toHaveBeenCalled();
  });
  it("navigates with the actual profile, account and immutable basis hints", async () => {
    mocks.submit.mockResolvedValueOnce({
      ok: true,
      job: {
        profile_version: "report_sections_v4",
        account_id: account,
        job_id: id,
      },
    });
    render(<ProjectionReportSelection source={source} canCreate />);
    fireEvent.click(
      screen.getByRole("button", { name: "Create projection report" }),
    );
    await waitFor(() =>
      expect(mocks.push).toHaveBeenCalledWith(
        projectionReportSourceHref(source, id),
      ),
    );
  });
  it("keeps read-only access and an empty format selection non-submittable", () => {
    const view = render(
      <ProjectionReportSelection source={source} canCreate={false} />,
    );
    expect(
      screen.getByRole("button", { name: "Create projection report" }),
    ).toBeDisabled();
    view.rerender(<ProjectionReportSelection source={source} canCreate />);
    fireEvent.click(screen.getByRole("checkbox", { name: "PDF" }));
    expect(
      screen.getByRole("button", { name: "Create projection report" }),
    ).toBeDisabled();
    expect(mocks.submit).not.toHaveBeenCalled();
  });
});
