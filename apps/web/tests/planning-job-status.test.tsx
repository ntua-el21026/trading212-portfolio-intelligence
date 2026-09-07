import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ContributionPlanJob } from "@trading212/api-contracts";

import { PlanningJobStatus } from "../components/planning-job-status";

const mocks = vi.hoisted(() => ({ router: { refresh: vi.fn() } }));
vi.mock("next/navigation", () => ({ useRouter: () => mocks.router }));

const id = "10000000-0000-4000-8000-000000000001";
const job: ContributionPlanJob = {
  account_id: id,
  input_digest: "0".repeat(64),
  job_id: id,
  outcome: null,
  plan_id: id,
  request_id: id,
  request_revision: 1,
  requested_at: "2026-09-07T12:00:00Z",
  revision_etag: `"${id}:1"`,
  snapshot_id: id,
  state: "queued",
  target_version_id: id,
  virtual_portfolio_id: id,
};

describe("planning status refresh", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    mocks.router.refresh.mockReset();
  });
  afterEach(() => vi.useRealTimers());

  it("cancels pending automatic refresh and hides manual refresh while editing", async () => {
    const { rerender } = render(<PlanningJobStatus job={job} />);
    await act(() => vi.advanceTimersByTimeAsync(5_000));
    expect(mocks.router.refresh).toHaveBeenCalledTimes(1);
    rerender(<PlanningJobStatus job={job} paused />);
    await act(() => vi.advanceTimersByTimeAsync(30_000));
    expect(mocks.router.refresh).toHaveBeenCalledTimes(1);
    expect(
      screen.queryByRole("button", { name: "Check calculation status" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText(/Your original revision precondition is retained/),
    ).toBeVisible();
    rerender(<PlanningJobStatus job={job} />);
    await act(() => vi.advanceTimersByTimeAsync(5_000));
    expect(mocks.router.refresh).toHaveBeenCalledTimes(2);
  });

  it("does not poll a completed calculation", async () => {
    render(
      <PlanningJobStatus
        job={{ ...job, state: "succeeded", outcome: "optimal" }}
      />,
    );
    await act(() => vi.advanceTimersByTimeAsync(30_000));
    expect(mocks.router.refresh).not.toHaveBeenCalled();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
