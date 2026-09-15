import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type {
  CreateScenarioRunRequest,
  ScenarioRunResponse,
  ScenarioVersionResponse,
} from "@trading212/api-contracts";
import { ScenarioDefinitionForm } from "../components/scenario-editor";
import {
  ScenarioRunForm,
  ScenarioJobControls,
} from "../components/scenario-forms";
import { readScenarioQuery } from "../lib/scenario-query";
const mocks = vi.hoisted(() => ({
  submit: vi.fn(),
  push: vi.fn(),
  refresh: vi.fn(),
  navigation: { current: 0 },
}));
vi.mock("../lib/scenario-actions", () => ({
  submitScenarioCommand: mocks.submit,
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mocks.push, refresh: mocks.refresh }),
}));
vi.mock("../components/navigation-intent", () => ({
  useNavigationVersionRef: () => mocks.navigation,
}));
const account = "d778f930-9d2e-4f47-b24f-5b1fa99c6eee",
  id = "2f34c23a-3798-4d4a-9133-9cd47639dd37";
const query = readScenarioQuery(
  { account, view: "new" },
  { now: new Date("2026-09-15T12:00:00Z"), currency: "EUR" },
);
const definition = {
  id,
  account_id: account,
  name: "Scenario",
  revision: 2,
  current_version_id: id,
  archived: false,
  created_at: query.cutoff,
  updated_at: query.cutoff,
};
const version: ScenarioVersionResponse = {
  id,
  account_id: account,
  definition_id: id,
  version_number: 2,
  predecessor_id: null,
  created_at: query.cutoff,
  content_digest: "a".repeat(64),
  content: {
    name: "Scenario",
    mode: "compounded",
    shocks: [
      {
        kind: "price",
        selector: { kind: "instrument", instrument_id: id },
        size: "-0.000000000000000001",
      },
    ],
  },
};
const prepared: CreateScenarioRunRequest = {
  scenario_version_id: id,
  portfolio_snapshot_id: id,
  xray_run_id: id,
  reporting_currency: "EUR",
  source_cutoff_at: "2026-09-07T12:00:00.123456Z",
  replay: null,
};
const run: ScenarioRunResponse = {
  id,
  account_id: account,
  scenario_version_id: id,
  portfolio_snapshot_id: id,
  xray_run_id: id,
  job_id: id,
  input_digest: "a".repeat(64),
  created_at: query.cutoff,
  expires_at: "2026-10-01T00:00:00Z",
  completed_at: null,
  failure_code: null,
  state: "queued",
  result: null,
  result_availability: "pending",
};
beforeEach(() => {
  vi.clearAllMocks();
  mocks.navigation.current = 0;
  mocks.submit.mockResolvedValue({
    ok: false,
    code: "SCENARIO_UNAVAILABLE",
    message: "Retry later",
  });
});
describe("scenario immutable editor and jobs", () => {
  it("preserves tiny exact shocks and predecessor revision across retries, with a new identity after edits", async () => {
    render(
      <ScenarioDefinitionForm
        accountId={account}
        query={query}
        definition={definition}
        version={version}
        canWrite
      />,
    );
    expect(screen.getByLabelText("Simple return shock")).toHaveValue(
      "-0.000000000000000001",
    );
    fireEvent.submit(screen.getByRole("form"));
    await screen.findByRole("alert");
    const first = mocks.submit.mock.calls[0][0];
    expect(first).toMatchObject({
      kind: "create_version",
      definition_id: id,
      if_match: `"${id}:2"`,
      body: { content: version.content },
    });
    fireEvent.submit(screen.getByRole("form"));
    await waitFor(() => expect(mocks.submit).toHaveBeenCalledTimes(2));
    await screen.findByRole("alert");
    expect(mocks.submit.mock.calls[1][0].idempotency_key).toBe(
      first.idempotency_key,
    );
    fireEvent.change(screen.getByLabelText("Simple return shock"), {
      target: { value: "0.123456789012345678" },
    });
    fireEvent.submit(screen.getByRole("form"));
    await waitFor(() => expect(mocks.submit).toHaveBeenCalledTimes(3));
    expect(mocks.submit.mock.calls[2][0].idempotency_key).not.toBe(
      first.idempotency_key,
    );
    expect(mocks.submit.mock.calls[2][0].body.content.shocks[0].size).toBe(
      "0.123456789012345678",
    );
    expect(version.content.shocks?.[0].size).toBe("-0.000000000000000001");
  });
  it("edits rate and factor source pins without accepting a coefficient field", async () => {
    render(
      <ScenarioDefinitionForm accountId={account} query={query} canWrite />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Add shock" }));
    fireEvent.change(screen.getByLabelText("Shock channel"), {
      target: { value: "rate" },
    });
    fireEvent.change(screen.getByLabelText("Sensitivity version ID"), {
      target: { value: id },
    });
    fireEvent.change(screen.getByLabelText("Sensitivity content digest"), {
      target: { value: "a".repeat(64) },
    });
    fireEvent.change(screen.getByLabelText("Driver ID"), {
      target: { value: account },
    });
    fireEvent.change(screen.getByLabelText("Driver definition version ID"), {
      target: { value: id },
    });
    fireEvent.change(screen.getByLabelText("Absolute rate change"), {
      target: { value: "0.001" },
    });
    expect(
      screen.queryByRole("textbox", { name: "Coefficient" }),
    ).not.toBeInTheDocument();
    fireEvent.submit(screen.getByRole("form"));
    await screen.findByRole("alert");
    expect(mocks.submit.mock.calls[0][0].body.content.shocks).toEqual([
      {
        kind: "rate",
        size: "0.001",
        source: {
          version_id: id,
          content_digest: "a".repeat(64),
          driver_id: account,
          driver_definition_version_id: id,
        },
      },
    ]);
    fireEvent.click(screen.getByRole("button", { name: "Remove shock 1" }));
    expect(
      screen.queryByLabelText("Sensitivity version ID"),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Add exclusion" }));
    fireEvent.change(screen.getByLabelText("Match by"), {
      target: { value: "economic_currency" },
    });
    expect(screen.getByLabelText("Economic currency")).toHaveValue("EUR");
  });
  it("discards a late completed submission after navigation intent", async () => {
    let finish!: (value: unknown) => void;
    mocks.submit.mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    render(
      <ScenarioRunForm
        accountId={account}
        query={query}
        prepared={prepared}
        canWrite
      />,
    );
    fireEvent.submit(screen.getByRole("form"));
    await waitFor(() => expect(mocks.submit).toHaveBeenCalledOnce());
    mocks.navigation.current++;
    await act(async () => finish({ ok: true, kind: "run", value: run }));
    expect(mocks.push).not.toHaveBeenCalled();
  });
  it("submits only the exact prepared saved pins", async () => {
    render(
      <ScenarioRunForm
        accountId={account}
        query={query}
        prepared={prepared}
        canWrite
      />,
    );
    fireEvent.submit(screen.getByRole("form"));
    await screen.findByRole("alert");
    expect(mocks.submit.mock.calls[0][0]).toMatchObject({
      kind: "create_run",
      account_id: account,
      body: prepared,
    });
    expect(mocks.submit.mock.calls[0][0].body).not.toHaveProperty(
      "coefficients",
    );
  });
  it("disables run creation and cancellation without write access", () => {
    render(
      <>
        <ScenarioRunForm
          accountId={account}
          query={query}
          prepared={prepared}
          canWrite={false}
        />
        <ScenarioJobControls run={run} canWrite={false} />
      </>,
    );
    expect(
      screen.getByRole("button", { name: "Create scenario run" }),
    ).toBeDisabled();
    expect(
      screen.queryByRole("button", { name: "Cancel scenario run" }),
    ).not.toBeInTheDocument();
  });
  it("bounds polling and requires an explicit refresh to resume", async () => {
    vi.useFakeTimers();
    try {
      render(<ScenarioJobControls run={run} canWrite />);
      await act(async () => vi.advanceTimersByTime(250000));
      expect(mocks.refresh).toHaveBeenCalledTimes(48);
      expect(screen.getByText(/Automatic refresh paused/)).toBeInTheDocument();
      await act(async () => vi.advanceTimersByTime(100000));
      expect(mocks.refresh).toHaveBeenCalledTimes(48);
      fireEvent.click(
        screen.getByRole("button", { name: "Refresh scenario status" }),
      );
      await act(async () => vi.advanceTimersByTime(5000));
      expect(mocks.refresh).toHaveBeenCalledTimes(50);
    } finally {
      vi.useRealTimers();
    }
  });
  it("does not refresh a stale account route after navigation intent", async () => {
    vi.useFakeTimers();
    try {
      render(<ScenarioJobControls run={run} canWrite />);
      mocks.navigation.current++;
      await act(async () => vi.advanceTimersByTime(20000));
      expect(mocks.refresh).not.toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
  });
});
