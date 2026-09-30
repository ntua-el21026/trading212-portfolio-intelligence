import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ComponentProps } from "react";
import {
  AggregateRunForm,
  AggregateSelectionForm,
} from "../components/aggregation-forms";
import {
  account,
  at,
  id,
  other,
  receipt,
  selection,
  snapshot,
} from "./aggregation-ui-fixtures";
const mocks = vi.hoisted(() => ({
  submit: vi.fn(),
  snapshots: vi.fn(),
  fx: vi.fn(),
  push: vi.fn(),
  refresh: vi.fn(),
  navigation: { current: 0 },
}));
vi.mock("../lib/aggregation-actions", () => ({
  submitAggregationCommand: mocks.submit,
  loadAggregateSnapshotChoices: mocks.snapshots,
}));
vi.mock("../lib/aggregation-fx-actions", () => ({
  loadAggregateFxChoices: mocks.fx,
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mocks.push, refresh: mocks.refresh }),
}));
vi.mock("../components/navigation-intent", () => ({
  useNavigationVersionRef: () => mocks.navigation,
  default: ({
    prefetch: _prefetch,
    ...props
  }: ComponentProps<"a"> & { prefetch?: boolean }) => {
    void _prefetch;
    return <a {...props} />;
  },
}));
beforeEach(() => {
  vi.clearAllMocks();
  mocks.navigation.current = 0;
  mocks.submit.mockResolvedValue({
    ok: false,
    code: "SOURCE_UNAVAILABLE",
    message: "Retry later",
  });
  mocks.snapshots.mockResolvedValue({
    ok: true,
    account_id: id,
    items: [
      {
        id: snapshot,
        valuation_at: at,
        source_cutoff_at: at,
        reporting_currency: "EUR",
      },
    ],
    next_cursor: null,
  });
});
describe("aggregate editor safety", () => {
  it("keeps command identity across retries, changing it only when inputs change", async () => {
    render(
      <AggregateRunForm
        selection={selection}
        accounts={[account]}
        canReadActivity
      />,
    );
    const submit = screen.getByRole("button", { name: "Calculate aggregate" });
    fireEvent.click(submit);
    await screen.findByText("Retry later");
    await waitFor(() => expect(submit).toBeEnabled());
    fireEvent.click(submit);
    await waitFor(() => expect(mocks.submit).toHaveBeenCalledTimes(2));
    expect(mocks.submit.mock.calls[0][0].idempotency_key).toBe(
      mocks.submit.mock.calls[1][0].idempotency_key,
    );
    await waitFor(() => expect(submit).toBeEnabled());
    fireEvent.click(screen.getByLabelText("Include transfer evidence"));
    fireEvent.change(screen.getByLabelText("Activity start (ISO timestamp)"), {
      target: { value: "2026-08-01T00:00:00Z" },
    });
    fireEvent.change(screen.getByLabelText("Activity end (ISO timestamp)"), {
      target: { value: at },
    });
    fireEvent.click(submit);
    await waitFor(() => expect(mocks.submit).toHaveBeenCalledTimes(3));
    expect(mocks.submit.mock.calls[2][0].idempotency_key).not.toBe(
      mocks.submit.mock.calls[0][0].idempotency_key,
    );
    expect(mocks.submit.mock.calls[2][0]).toMatchObject({
      selection_id: id,
      revision: 7,
      body: {
        activity_window: { start_at: "2026-08-01T00:00:00Z", end_at: at },
      },
    });
  });
  it.each(["navigation", "unmount"])(
    "ignores late success after %s",
    async (change) => {
      let finish!: (value: unknown) => void;
      mocks.submit.mockImplementation(
        () =>
          new Promise((resolve) => {
            finish = resolve;
          }),
      );
      const view = render(
        <AggregateRunForm
          selection={selection}
          accounts={[account]}
          canReadActivity={false}
        />,
      );
      fireEvent.click(
        screen.getByRole("button", { name: "Calculate aggregate" }),
      );
      await waitFor(() => expect(mocks.submit).toHaveBeenCalledOnce());
      if (change === "unmount") view.unmount();
      else mocks.navigation.current += 1;
      await act(async () => finish({ ok: true, kind: "run", value: receipt }));
      expect(mocks.push).not.toHaveBeenCalled();
    },
  );
  it("preserves edited fields when reloading the current revision after a conflict", async () => {
    mocks.submit.mockResolvedValue({
      ok: false,
      code: "REVISION_MISMATCH",
      message: "Reload revision",
    });
    const view = render(
      <AggregateRunForm
        selection={selection}
        accounts={[account]}
        canReadActivity
      />,
    );
    fireEvent.click(screen.getByLabelText("Include transfer evidence"));
    fireEvent.change(screen.getByLabelText("Activity start (ISO timestamp)"), {
      target: { value: "2026-08-01T00:00:00Z" },
    });
    fireEvent.change(screen.getByLabelText("Activity end (ISO timestamp)"), {
      target: { value: at },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Calculate aggregate" }),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Reload current revision" }),
    );
    expect(mocks.refresh).toHaveBeenCalledOnce();
    view.rerender(
      <AggregateRunForm
        selection={{ ...selection, revision: 8 }}
        accounts={[account]}
        canReadActivity
      />,
    );
    expect(screen.getByLabelText("Activity start (ISO timestamp)")).toHaveValue(
      "2026-08-01T00:00:00Z",
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Calculate aggregate" }),
    );
    await waitFor(() => expect(mocks.submit).toHaveBeenCalledTimes(2));
    expect(mocks.submit.mock.calls[1][0].revision).toBe(8);
    expect(mocks.submit.mock.calls[1][0].idempotency_key).not.toBe(
      mocks.submit.mock.calls[0][0].idempotency_key,
    );
  });
  it("loads only the explicitly chosen account and saves the exact selected snapshot", async () => {
    render(
      <AggregateSelectionForm
        accounts={[account, { ...account, id: other }]}
        cutoff={at}
      />,
    );
    expect(mocks.snapshots).not.toHaveBeenCalled();
    fireEvent.change(
      screen.getByRole("combobox", { name: "Included account 1" }),
      { target: { value: id } },
    );
    await waitFor(() =>
      expect(
        screen.getByRole("combobox", { name: "Saved snapshot 1" }),
      ).toBeEnabled(),
    );
    expect(mocks.snapshots).toHaveBeenCalledWith({
      account_id: id,
      cursor: null,
    });
    fireEvent.change(
      screen.getByRole("combobox", { name: "Saved snapshot 1" }),
      { target: { value: snapshot } },
    );
    fireEvent.change(screen.getByLabelText("Aggregate name"), {
      target: { value: "Exact sources" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Save aggregate selection" }),
    );
    await waitFor(() => expect(mocks.submit).toHaveBeenCalledOnce());
    expect(mocks.submit.mock.calls[0][0]).toMatchObject({
      kind: "selection",
      body: {
        content: {
          members: [{ account_id: id, portfolio_snapshot_id: snapshot }],
          source_cutoff_at: at,
        },
      },
    });
  });
  it("ignores snapshot choices from an earlier navigation even while the editor remains mounted", async () => {
    let finish!: (value: unknown) => void;
    mocks.snapshots.mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    render(<AggregateSelectionForm accounts={[account]} cutoff={at} />);
    fireEvent.change(
      screen.getByRole("combobox", { name: "Included account 1" }),
      { target: { value: id } },
    );
    await waitFor(() => expect(mocks.snapshots).toHaveBeenCalledOnce());
    mocks.navigation.current += 1;
    await act(async () =>
      finish({
        ok: true,
        account_id: id,
        items: [
          {
            id: snapshot,
            valuation_at: at,
            source_cutoff_at: at,
            reporting_currency: "EUR",
          },
        ],
        next_cursor: null,
      }),
    );
    expect(
      screen.getByRole("combobox", { name: "Saved snapshot 1" }),
    ).toBeDisabled();
    expect(
      screen.queryByRole("option", { name: /known/ }),
    ).not.toBeInTheDocument();
  });
  it("omits transfer controls without activity access", () => {
    render(
      <AggregateRunForm
        selection={selection}
        accounts={[account]}
        canReadActivity={false}
      />,
    );
    expect(
      screen.queryByLabelText("Include transfer evidence"),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText(
        "Activity access is required to include transfer evidence.",
      ),
    ).toBeVisible();
  });
});
