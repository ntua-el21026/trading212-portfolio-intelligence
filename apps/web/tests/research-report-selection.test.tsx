import { webcrypto } from "node:crypto";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ResearchReportSelection } from "../components/research-report-selection";
import { researchReportSource } from "../lib/research-report-query";
import type { ResearchReportActionResult } from "../lib/research-report-actions";
import { account, id, item, other } from "./research-ui-fixtures";
const mocks = vi.hoisted(() => ({
  submit: vi.fn(),
  push: vi.fn(),
  navigation: { current: 0 },
}));
vi.mock("../lib/research-report-actions", () => ({
  submitResearchReportCommand: mocks.submit,
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: mocks.push }) }));
vi.mock("../components/navigation-intent", () => ({
  useNavigationVersionRef: () => mocks.navigation,
}));
const source = researchReportSource(item, account);
if (!source) throw new Error("fixture source missing");
const selected = source;
const empty = {
  family: "research" as const,
  item_id: id,
  note_revision_ids: [],
};
beforeEach(() => {
  vi.resetAllMocks();
  mocks.navigation.current = 0;
  vi.stubGlobal("crypto", webcrypto);
  mocks.submit.mockResolvedValue({
    ok: false,
    code: "REPORT_UNAVAILABLE",
    message: "Retry.",
  });
});
afterEach(() => vi.unstubAllGlobals());
describe("explicit research report selection", () => {
  it("starts with no automatic note or review capture and retains retry identity", async () => {
    render(
      <ResearchReportSelection
        item={item}
        source={selected}
        initialPins={empty}
        canCreate
      />,
    );
    expect(
      screen.getByLabelText("Exact owner note revision IDs (optional)"),
    ).toHaveValue("");
    expect(
      screen.getByLabelText("Exact review acknowledgment ID (optional)"),
    ).toHaveValue("");
    expect(screen.getByText("X-ray source cutoff")).toBeVisible();
    expect(screen.getByText("Research source cutoff")).toBeVisible();
    fireEvent.click(
      screen.getByRole("button", { name: "Create research report" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "REPORT_UNAVAILABLE",
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Create research report" }),
    );
    await waitFor(() => expect(mocks.submit).toHaveBeenCalledTimes(2));
    expect(mocks.submit.mock.calls[0]).toEqual(mocks.submit.mock.calls[1]);
    expect(mocks.submit.mock.calls[0][0].premium_run).toEqual(empty);
  });
  it("sends exact historical note and review IDs with all four formats", async () => {
    render(
      <ResearchReportSelection
        item={item}
        source={selected}
        initialPins={empty}
        canCreate
      />,
    );
    fireEvent.change(
      screen.getByLabelText("Exact owner note revision IDs (optional)"),
      { target: { value: other } },
    );
    fireEvent.change(
      screen.getByLabelText("Exact review acknowledgment ID (optional)"),
      { target: { value: other } },
    );
    for (const format of ["CSV", "JSON", "XLSX"])
      fireEvent.click(screen.getByRole("checkbox", { name: format }));
    fireEvent.click(
      screen.getByRole("button", { name: "Create research report" }),
    );
    await screen.findByRole("alert");
    expect(mocks.submit.mock.calls[0][0]).toMatchObject({
      premium_run: {
        family: "research",
        item_id: id,
        note_revision_ids: [other],
        review_acknowledgment_id: other,
      },
      formats: ["pdf", "csv", "json", "xlsx"],
    });
    expect(mocks.submit.mock.calls[0][0].premium_run).not.toHaveProperty(
      "run_id",
    );
  });
  it("rejects duplicate versions locally without invoking a report command", async () => {
    render(
      <ResearchReportSelection
        item={item}
        source={selected}
        initialPins={empty}
        canCreate
      />,
    );
    fireEvent.change(
      screen.getByLabelText("Exact owner note revision IDs (optional)"),
      { target: { value: `${id}\n${id}` } },
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Create research report" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "distinct exact note revision",
    );
    expect(mocks.submit).not.toHaveBeenCalled();
  });
  it("discards a late response after navigation changes", async () => {
    let finish!: (value: ResearchReportActionResult) => void;
    mocks.submit.mockImplementation(
      () =>
        new Promise<ResearchReportActionResult>((resolve) => {
          finish = resolve;
        }),
    );
    render(
      <ResearchReportSelection
        item={item}
        source={selected}
        initialPins={empty}
        canCreate
      />,
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Create research report" }),
    );
    mocks.navigation.current += 1;
    await act(async () =>
      finish({ ok: false, code: "OLD_ACCOUNT", message: "Old result" }),
    );
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(mocks.push).not.toHaveBeenCalled();
  });
  it("discloses missing creation access without submitting", () => {
    render(
      <ResearchReportSelection
        item={item}
        source={selected}
        initialPins={empty}
        canCreate={false}
      />,
    );
    expect(
      screen.getByRole("button", { name: "Create research report" }),
    ).toBeDisabled();
    expect(
      screen.getByText("Research report creation unavailable"),
    ).toBeVisible();
  });
});
