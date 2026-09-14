import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type {
  RiskRunResponse,
  RiskVersionResponse,
  SourceSeriesStatus,
} from "@trading212/api-contracts";
import {
  RiskDefinitionForm,
  RiskRunForm,
  RiskJobControls,
} from "../components/risk-forms";
import { RiskValue, RiskResults } from "../components/risk-results";
import { readRiskQuery, riskWindow } from "../lib/risk-query";
const mocks = vi.hoisted(() => ({
  submit: vi.fn(),
  push: vi.fn(),
  refresh: vi.fn(),
  navigation: { current: 0 },
}));
vi.mock("../lib/risk-actions", () => ({ submitRiskCommand: mocks.submit }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mocks.push, refresh: mocks.refresh }),
}));
vi.mock("../components/navigation-intent", () => ({
  useNavigationVersionRef: () => mocks.navigation,
}));
const account = "d778f930-9d2e-4f47-b24f-5b1fa99c6eee";
const id = "2f34c23a-3798-4d4a-9133-9cd47639dd37";
const query = readRiskQuery(
  { account, view: "new" },
  { now: new Date("2026-09-14T12:00:00Z"), currency: "EUR" },
);
const definition = {
  id,
  account_id: account,
  name: "Risk",
  revision: 2,
  current_version_id: id,
  archived: false,
  created_at: query.cutoff,
  updated_at: query.cutoff,
};
const version: RiskVersionResponse = {
  id,
  account_id: account,
  definition_id: id,
  version_number: 2,
  predecessor_id: null,
  created_at: query.cutoff,
  content_digest: "a".repeat(64),
  content: {
    name: "Risk",
    calendar_id: "synthetic",
    calendar_version: "v1",
    confidence: "0.900000000000000000",
    annual_risk_free: "0.012345678901234567",
  },
};
const prepared = {
  definition_version_id: id,
  portfolio_snapshot_id: id,
  historical_input_snapshot_id: id,
  window: riskWindow(query),
};
const run: RiskRunResponse = {
  id,
  account_id: account,
  definition_version_id: id,
  portfolio_snapshot_id: id,
  historical_input_snapshot_id: id,
  job_id: id,
  input_digest: "a".repeat(64),
  created_at: query.cutoff,
  expires_at: "2026-10-01T00:00:00Z",
  completed_at: null,
  failure_code: null,
  state: "queued",
  result: null,
  result_availability: "pending",
  xray_run_id: null,
};
function source(
  key: string,
  instrument = id,
  basis: "total_return" | "raw_close" = "total_return",
): SourceSeriesStatus {
  return {
    availability: "available",
    latest_snapshot: null,
    series: {
      id: key,
      provider_id: id,
      provider_key: key,
      instrument_id: instrument,
      kind: "security_price",
      basis,
      calendar_id: "synthetic",
      calendar_version: "v1",
      currency: "EUR",
      license_version_id: id,
      mapping_version: "v1",
    },
  };
}
beforeEach(() => {
  vi.clearAllMocks();
  mocks.navigation.current = 0;
  mocks.submit.mockResolvedValue({
    ok: false,
    code: "RISK_UNAVAILABLE",
    message: "Retry later",
  });
});
describe("risk forms and canonical values", () => {
  it("preserves decimal rates, canonical confidence and predecessor revision on retry", async () => {
    render(
      <RiskDefinitionForm
        accountId={account}
        query={query}
        calendars={[]}
        definition={definition}
        version={version}
        canWrite
      />,
    );
    expect(screen.getByLabelText("Tail confidence")).toHaveValue("0.9");
    fireEvent.submit(screen.getByRole("form"));
    await screen.findByRole("alert");
    const first = mocks.submit.mock.calls[0][0];
    expect(first).toMatchObject({
      kind: "create_version",
      definition_id: id,
      if_match: `"${id}:2"`,
      body: {
        content: {
          annual_risk_free: "0.012345678901234567",
          confidence: "0.900000000000000000",
        },
      },
    });
    fireEvent.submit(screen.getByRole("form"));
    await waitFor(() => expect(mocks.submit).toHaveBeenCalledTimes(2));
    expect(mocks.submit.mock.calls[1][0].idempotency_key).toBe(
      first.idempotency_key,
    );
    await screen.findByRole("alert");
    fireEvent.change(screen.getByLabelText("Annual risk-free rate"), {
      target: { value: "0.02" },
    });
    fireEvent.submit(screen.getByRole("form"));
    await waitFor(() => expect(mocks.submit).toHaveBeenCalledTimes(3));
    expect(mocks.submit.mock.calls[2][0].idempotency_key).not.toBe(
      first.idempotency_key,
    );
  });
  it("discards a late completed command after navigation intent", async () => {
    let finish!: (value: unknown) => void;
    mocks.submit.mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    render(
      <RiskDefinitionForm
        accountId={account}
        query={query}
        calendars={[]}
        definition={definition}
        version={version}
        canWrite
      />,
    );
    fireEvent.submit(screen.getByRole("form"));
    await waitFor(() => expect(mocks.submit).toHaveBeenCalledOnce());
    mocks.navigation.current++;
    await act(async () =>
      finish({ ok: true, kind: "definition", value: definition }),
    );
    expect(mocks.push).not.toHaveBeenCalled();
  });
  it("keeps selected sources across pages, rejects duplicate instruments and raw prices", async () => {
    const first = source(id),
      second = source(account),
      raw = source(
        "b8532ba7-36e4-43ef-aee4-a4e67c75ef9d",
        account,
        "raw_close",
      );
    const { rerender } = render(
      <RiskRunForm
        accountId={account}
        query={query}
        prepared={prepared}
        sources={[first, second, raw]}
        canWrite
      />,
    );
    expect(screen.getByLabelText(/raw_close/)).toBeDisabled();
    fireEvent.click(screen.getByLabelText(new RegExp(`^${id}`)));
    fireEvent.click(screen.getByLabelText(new RegExp(`^${account}`)));
    expect(screen.getByRole("alert")).toHaveTextContent("one return series");
    rerender(
      <RiskRunForm
        accountId={account}
        query={{ ...query, sources_cursor: "next" }}
        prepared={prepared}
        sources={[]}
        canWrite
      />,
    );
    expect(
      screen.getByText("1 of 32 assets selected across source pages."),
    ).toBeInTheDocument();
    fireEvent.submit(screen.getByRole("form"));
    await waitFor(() => expect(mocks.submit).toHaveBeenCalledOnce());
    expect(mocks.submit.mock.calls[0][0].body).toEqual({
      ...prepared,
      assets: [{ instrument_id: id, series_id: id }],
    });
  });
  it("disables internal commands without write access", () => {
    render(
      <RiskRunForm
        accountId={account}
        query={query}
        prepared={prepared}
        sources={[]}
        canWrite={false}
      />,
    );
    expect(
      screen.getByRole("button", { name: "Create risk run" }),
    ).toBeDisabled();
  });
  it("distinguishes zero, unavailable and signed tiny exact values", () => {
    const { rerender } = render(
      <RiskValue metric={{ value: "0", reason: null }} />,
    );
    expect(screen.getByText("0.0%")).toBeInTheDocument();
    rerender(
      <RiskValue metric={{ value: null, reason: "zero_denominator" }} />,
    );
    expect(screen.getByText("Unavailable")).toBeInTheDocument();
    expect(screen.getByText("Zero Denominator")).toBeInTheDocument();
    rerender(
      <RiskValue metric={{ value: "-0.000000000000000001", reason: null }} />,
    );
    expect(screen.getByTitle("-0.000000000000000001")).toHaveTextContent(
      "−0.0000000000000001%",
    );
  });
  it.each(["pending", "expired", "unavailable"] as const)(
    "does not invent a result for %s",
    (availability) => {
      render(
        <RiskResults run={{ ...run, result_availability: availability }} />,
      );
      expect(screen.getByText(/No financial result/)).toBeInTheDocument();
      expect(
        screen.queryByText("Annualized volatility"),
      ).not.toBeInTheDocument();
    },
  );
  it("bounds polling and restarts only on an explicit refresh", async () => {
    vi.useFakeTimers();
    try {
      render(<RiskJobControls run={run} canWrite />);
      await act(async () => vi.advanceTimersByTime(250000));
      expect(mocks.refresh).toHaveBeenCalledTimes(48);
      expect(screen.getByText(/Automatic refresh paused/)).toBeInTheDocument();
      await act(async () => vi.advanceTimersByTime(100000));
      expect(mocks.refresh).toHaveBeenCalledTimes(48);
      fireEvent.click(
        screen.getByRole("button", { name: "Refresh risk status" }),
      );
      await act(async () => vi.advanceTimersByTime(5000));
      expect(mocks.refresh).toHaveBeenCalledTimes(50);
    } finally {
      vi.useRealTimers();
    }
  });
});
