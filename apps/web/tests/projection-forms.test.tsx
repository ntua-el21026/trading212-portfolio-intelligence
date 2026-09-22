import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ProjectionAssumptionEditor } from "../components/projection-assumption-editor";
import { ProjectionGoalEditor } from "../components/projection-goal-editor";
import { ProjectionRunForm } from "../components/projection-run-form";
import { ProjectionJobControls } from "../components/projection-job-controls";
import { readProjectionQuery } from "../lib/projection-query";
import {
  account,
  id,
  other,
  assumption,
  definition,
  goal,
  run,
  schedule,
} from "./projection-fixtures";
const mocks = vi.hoisted(() => ({
  submit: vi.fn(),
  push: vi.fn(),
  refresh: vi.fn(),
  navigation: { current: 0 },
}));
vi.mock("../lib/projection-actions", () => ({
  submitProjectionCommand: mocks.submit,
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mocks.push, refresh: mocks.refresh }),
}));
vi.mock("../components/navigation-intent", () => ({
  useNavigationVersionRef: () => mocks.navigation,
}));
const query = readProjectionQuery({ account, view: "new", version: id });
beforeEach(() => {
  vi.clearAllMocks();
  mocks.navigation.current = 0;
  mocks.submit.mockResolvedValue({
    ok: false,
    code: "PROJECTION_UNAVAILABLE",
    message: "Retry later",
  });
});
describe("immutable projection editors and asynchronous job controls", () => {
  it("preserves exact log return, current revision and retry identity until editing", async () => {
    render(
      <ProjectionAssumptionEditor
        accountId={account}
        currency="EUR"
        query={query}
        definition={definition}
        version={assumption}
        canWrite
      />,
    );
    expect(screen.getByLabelText("Annual mean log return")).toHaveValue(
      "-0.000000000000000001",
    );
    fireEvent.submit(screen.getByRole("form"));
    await screen.findByRole("alert");
    await waitFor(() =>
      expect(screen.getByLabelText("Annual mean log return")).toBeEnabled(),
    );
    const first = mocks.submit.mock.calls[0][0];
    expect(first).toMatchObject({
      kind: "create_assumption_version",
      set_id: id,
      if_match: `"${id}:2"`,
      body: { content: assumption.content },
    });
    fireEvent.submit(screen.getByRole("form"));
    await waitFor(() => expect(mocks.submit).toHaveBeenCalledTimes(2));
    await screen.findByRole("alert");
    await waitFor(() =>
      expect(screen.getByLabelText("Annual mean log return")).toBeEnabled(),
    );
    expect(mocks.submit.mock.calls[1][0].idempotency_key).toBe(
      first.idempotency_key,
    );
    fireEvent.change(screen.getByLabelText("Annual mean log return"), {
      target: { value: "0.123456789012345678" },
    });
    fireEvent.submit(screen.getByRole("form"));
    await waitFor(() => expect(mocks.submit).toHaveBeenCalledTimes(3));
    expect(mocks.submit.mock.calls[2][0].idempotency_key).not.toBe(
      first.idempotency_key,
    );
    expect(
      mocks.submit.mock.calls[2][0].body.content.assets[0]
        .annual_mean_log_return,
    ).toBe("0.123456789012345678");
    expect(assumption.content.assets[0].annual_mean_log_return).toBe(
      "-0.000000000000000001",
    );
  });
  it("updates both correlation cells while preserving saved source pins", async () => {
    render(
      <ProjectionAssumptionEditor
        accountId={account}
        currency="EUR"
        query={query}
        canWrite
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Add asset group" }));
    fireEvent.change(screen.getByLabelText("Correlation asset 1 and 2"), {
      target: { value: "-0.25" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Add calibration pin" }),
    );
    fireEvent.change(screen.getByLabelText("Calibration subject ID"), {
      target: { value: other },
    });
    fireEvent.change(screen.getByLabelText("Calibration content digest"), {
      target: { value: "d".repeat(64) },
    });
    fireEvent.submit(screen.getByRole("form"));
    await screen.findByRole("alert");
    expect(mocks.submit.mock.calls[0][0].body.content).toMatchObject({
      correlation: [
        ["1", "-0.25"],
        ["-0.25", "1"],
      ],
      calibration_pins: [{ subject_id: other, content_digest: "d".repeat(64) }],
    });
  });
  it("revises a goal with its precise target, withdrawal and version precondition", async () => {
    render(
      <ProjectionGoalEditor
        accountId={account}
        query={query}
        assumption={assumption}
        goal={{ ...definition, id: other }}
        version={goal}
        canWrite
      />,
    );
    fireEvent.submit(screen.getByRole("form"));
    await screen.findByRole("alert");
    expect(mocks.submit.mock.calls[0][0]).toMatchObject({
      kind: "create_goal_version",
      goal_id: other,
      if_match: `"${other}:2"`,
      body: { content: goal.content },
    });
    expect(screen.getByLabelText("Entry amount")).toHaveValue(
      "0.123456789012345678",
    );
  });
  it("pins goal schedule/horizon and submits explicit modeled initial money without recomputing", async () => {
    render(
      <ProjectionRunForm
        accountId={account}
        query={query}
        assumption={assumption}
        goal={goal}
        defaultAnchor="2026-09-15"
        canWrite
      />,
    );
    expect(screen.getByLabelText("Projection horizon (months)")).toBeDisabled();
    expect(screen.getByLabelText("Base monthly contribution")).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Modeled initial value (EUR)"), {
      target: { value: "123.123456789012345678" },
    });
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.change(
      screen.getByLabelText("Monthly contribution delta (EUR)"),
      { target: { value: "0.000000000000000001" } },
    );
    fireEvent.submit(screen.getByRole("form"));
    await screen.findByRole("alert");
    expect(mocks.submit.mock.calls[0][0]).toMatchObject({
      kind: "create_run",
      body: {
        assumption_version_id: id,
        goal_version_id: other,
        schedule,
        months: 12,
        initial_basis: {
          kind: "modeled_value",
          modeled_value: { amount: "123.123456789012345678", currency: "EUR" },
          modeled_anchor_date: "2026-09-15",
          snapshot_id: null,
        },
        sensitivity: {
          contribution_delta: {
            amount: "0.000000000000000001",
            currency: "EUR",
          },
          annual_mean_log_delta: "0",
        },
      },
    });
  });
  it("suppresses a late successful action after an account navigation", async () => {
    let finish!: (value: unknown) => void;
    mocks.submit.mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    render(
      <ProjectionRunForm
        accountId={account}
        query={query}
        assumption={assumption}
        defaultAnchor="2026-09-15"
        canWrite
      />,
    );
    fireEvent.submit(screen.getByRole("form"));
    await waitFor(() => expect(mocks.submit).toHaveBeenCalledOnce());
    mocks.navigation.current++;
    await act(async () => finish({ ok: true, kind: "run", value: run }));
    expect(mocks.push).not.toHaveBeenCalled();
  });
  it("disables edits and omits cancellation without the current write scope", () => {
    render(
      <>
        <ProjectionRunForm
          accountId={account}
          query={query}
          assumption={assumption}
          defaultAnchor="2026-09-15"
          canWrite={false}
        />
        <ProjectionJobControls run={run} canWrite={false} />
      </>,
    );
    expect(
      screen.getByRole("button", { name: "Create projection run" }),
    ).toBeDisabled();
    expect(
      screen.queryByRole("button", { name: "Cancel projection run" }),
    ).not.toBeInTheDocument();
  });
  it("bounds polling, pauses while hidden and ignores obsolete navigation", async () => {
    vi.useFakeTimers();
    try {
      render(<ProjectionJobControls run={run} canWrite />);
      const visible = vi
        .spyOn(document, "visibilityState", "get")
        .mockReturnValue("hidden");
      await act(async () => vi.advanceTimersByTime(20000));
      expect(mocks.refresh).not.toHaveBeenCalled();
      visible.mockReturnValue("visible");
      await act(async () => vi.advanceTimersByTime(250000));
      expect(mocks.refresh).toHaveBeenCalledTimes(48);
      expect(screen.getByText(/Automatic refresh paused/)).toBeInTheDocument();
      fireEvent.click(
        screen.getByRole("button", { name: "Refresh projection status" }),
      );
      mocks.navigation.current++;
      await act(async () => vi.advanceTimersByTime(20000));
      expect(mocks.refresh).toHaveBeenCalledTimes(49);
      visible.mockRestore();
    } finally {
      vi.useRealTimers();
    }
  });
});
