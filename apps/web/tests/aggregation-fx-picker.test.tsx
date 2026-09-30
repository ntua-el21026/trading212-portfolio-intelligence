import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AggregateFxBinding } from "@trading212/api-contracts";
import { AggregateFxPicker } from "../components/aggregation-fx-picker";
import {
  account,
  at,
  id,
  other,
  selection,
  snapshot,
} from "./aggregation-ui-fixtures";
const mocks = vi.hoisted(() => ({
  load: vi.fn(),
  remove: vi.fn(),
  navigation: { current: 0 },
}));
vi.mock("../lib/aggregation-fx-actions", () => ({
  loadAggregateFxChoices: mocks.load,
}));
vi.mock("../components/navigation-intent", () => ({
  useNavigationVersionRef: () => mocks.navigation,
}));
const sources = {
  ok: true,
  kind: "snapshots",
  account_id: id,
  base: "USD",
  quote: "EUR",
  next_cursor: null,
  items: [
    {
      snapshot_id: other,
      provider: "Synthetic FX",
      first_observed_at: at,
      effective_at: at,
      available_count: 31,
      availability: "available",
    },
  ],
};
const observed = {
  ok: true,
  kind: "observations",
  page: {
    account_id: id,
    snapshot_id: other,
    base: "USD",
    quote: "EUR",
    source_cutoff_at: at,
    effective_at_lte: at,
    first_observed_at: at,
    expires_at: "2026-09-15T00:00:00Z",
    next_cursor: "older-page",
    limit: 25,
    content_digest: "a".repeat(64),
    items: [
      {
        observation_id: snapshot,
        session_date: "2026-09-01",
        effective_at: at,
        rate: "0.900000000000000001",
        state: "available",
      },
      {
        observation_id: id,
        session_date: "2026-08-31",
        effective_at: at,
        rate: null,
        state: "missing",
      },
    ],
  },
};
function Editor({ revision = 7 }: { revision?: number }) {
  const [value, setValue] = useState<AggregateFxBinding>({
    account_id: id,
    currency: "USD",
    fx_observation_id: "",
  });
  return (
    <>
      <AggregateFxPicker
        index={0}
        value={value}
        selection={{ ...selection, revision }}
        accounts={[account]}
        change={setValue}
        remove={mocks.remove}
      />
      <output aria-label="Submitted observation">
        {value.fx_observation_id}
      </output>
    </>
  );
}
beforeEach(() => {
  vi.resetAllMocks();
  mocks.navigation.current = 0;
  mocks.load.mockImplementation((request: { kind: string }) =>
    Promise.resolve(request.kind === "snapshots" ? sources : observed),
  );
});
describe("explicit saved FX picker", () => {
  it("requires explicit source and observation choices and forwards the exact persisted ID", async () => {
    render(<Editor />);
    expect(mocks.load).not.toHaveBeenCalled();
    fireEvent.click(
      screen.getByRole("button", { name: "Load saved FX sources 1" }),
    );
    const source = await screen.findByRole("combobox", {
      name: "Saved FX source 1",
    });
    await waitFor(() => expect(source).toBeEnabled());
    expect(source).toHaveValue("");
    expect(
      screen.getByLabelText("Submitted observation"),
    ).toBeEmptyDOMElement();
    fireEvent.change(source, { target: { value: other } });
    const choice = await screen.findByRole("combobox", {
      name: "Saved FX observation 1",
    });
    await waitFor(() => expect(choice).toBeEnabled());
    expect(choice).toHaveValue("");
    expect(
      screen.getByRole("option", { name: /0\.900000000000000001/ }),
    ).toBeEnabled();
    expect(
      screen.getByRole("option", { name: /unavailable.*missing/ }),
    ).toBeDisabled();
    fireEvent.change(choice, { target: { value: snapshot } });
    expect(screen.getByLabelText("Submitted observation")).toHaveTextContent(
      snapshot,
    );
    expect(mocks.load.mock.calls).toEqual([
      [
        {
          kind: "snapshots",
          selection_id: id,
          revision: 7,
          account_id: id,
          currency: "USD",
          direction: "direct",
          cursor: null,
        },
      ],
      [
        {
          kind: "observations",
          snapshot_id: other,
          selection_id: id,
          revision: 7,
          account_id: id,
          currency: "USD",
          direction: "direct",
          cursor: null,
        },
      ],
    ]);
    fireEvent.change(screen.getByRole("combobox", { name: "FX direction 1" }), {
      target: { value: "inverse" },
    });
    expect(
      screen.getByLabelText("Submitted observation"),
    ).toBeEmptyDOMElement();
    expect(
      screen.queryByRole("combobox", { name: "Saved FX observation 1" }),
    ).not.toBeInTheDocument();
    expect(mocks.load).toHaveBeenCalledTimes(2);
  });
  it("requests one next page without accumulating or automatically fetching the remainder", async () => {
    render(<Editor />);
    fireEvent.click(
      screen.getByRole("button", { name: "Load saved FX sources 1" }),
    );
    const source = await screen.findByRole("combobox", {
      name: "Saved FX source 1",
    });
    await waitFor(() => expect(source).toBeEnabled());
    fireEvent.change(source, { target: { value: other } });
    const next = await screen.findByRole("button", {
      name: "Older FX observations 1",
    });
    await waitFor(() => expect(next).toBeEnabled());
    fireEvent.change(
      screen.getByRole("combobox", { name: "Saved FX observation 1" }),
      { target: { value: snapshot } },
    );
    mocks.load.mockResolvedValue({
      ...observed,
      page: { ...observed.page, items: [], next_cursor: null },
    });
    fireEvent.click(next);
    await screen.findByText("No retained observations on this page.");
    expect(
      screen.getByLabelText("Submitted observation"),
    ).toBeEmptyDOMElement();
    expect(
      screen.queryByRole("option", { name: /0\.900000000000000001/ }),
    ).not.toBeInTheDocument();
    expect(mocks.load).toHaveBeenCalledTimes(3);
    expect(mocks.load.mock.calls[2][0]).toMatchObject({
      cursor: "older-page",
      snapshot_id: other,
    });
  });
  it.each(["navigation", "unmount", "revision"])(
    "discards a source response after %s changes",
    async (reason) => {
      let finish!: (value: unknown) => void;
      mocks.load.mockImplementation(
        () =>
          new Promise((resolve) => {
            finish = resolve;
          }),
      );
      const view = render(<Editor />);
      fireEvent.click(
        screen.getByRole("button", { name: "Load saved FX sources 1" }),
      );
      await waitFor(() => expect(mocks.load).toHaveBeenCalledOnce());
      if (reason === "unmount") view.unmount();
      else if (reason === "navigation") mocks.navigation.current += 1;
      else view.rerender(<Editor revision={8} />);
      await act(async () => finish(sources));
      expect(
        screen.queryByRole("combobox", { name: "Saved FX source 1" }),
      ).not.toBeInTheDocument();
    },
  );
});
