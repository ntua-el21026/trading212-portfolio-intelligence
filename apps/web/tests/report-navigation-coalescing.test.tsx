import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ReportSelectionForm } from "../components/report-selection";
import { parseReportQuery } from "../lib/report-query";
import { accountId, snapshot } from "./report-fixtures";

const navigation = vi.hoisted(() => ({ search: "", writing: true }));
vi.mock("react", async () => ({
  ...(await vi.importActual<typeof import("react")>("react")),
  // Control only the transition completion boundary. Real Next/React integration
  // is exercised separately by the API-backed browser navigation regression.
  useTransition: () => [
    navigation.writing,
    (callback: () => void) => callback(),
  ],
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
  useSearchParams: () => new URLSearchParams(navigation.search),
}));
vi.mock("../lib/report-actions", () => ({ submitReportCommand: vi.fn() }));

const initial = new URLSearchParams({
  account: accountId,
  snapshot: snapshot.id,
  kind: "report",
  report_type: "portfolio_summary",
  dataset: "positions",
  start_date: "2026-09-01",
  end_date: "2026-09-07",
  source_cutoff_at: snapshot.source_cutoff_at,
  reporting_currency: "EUR",
  ttl_days: "7",
  formats: "pdf",
  sections: "overview,allocation,quality",
}).toString();
const choices = { targets: [], plans: [], benchmarks: [], warnings: [] };
const originalReplace = window.history.replaceState.bind(window.history);

function form() {
  return (
    <ReportSelectionForm
      accountId={accountId}
      snapshot={snapshot}
      initial={parseReportQuery(
        Object.fromEntries(new URLSearchParams(initial)),
      )}
      choices={choices}
      canCreate
      defaultCutoff={snapshot.source_cutoff_at}
    />
  );
}
function observe(search: string) {
  navigation.search = search;
  originalReplace({ __NA: true }, "", `/reports?${search}`);
}
function changeRetention(value: string) {
  fireEvent.change(screen.getByLabelText("Requested retention (days)"), {
    target: { value },
  });
  return new URL(window.location.href).searchParams.toString();
}

describe("coalesced report navigation", () => {
  beforeEach(() => {
    navigation.writing = true;
    observe(initial);
    // Hold search-param commits while allowing the actual form to write history.
    vi.spyOn(window.history, "replaceState").mockImplementation(
      originalReplace,
    );
  });
  afterEach(() => vi.restoreAllMocks());

  it.each([false, true])(
    "retires own A→B→A with delayed intermediate commit=%s",
    (intermediate) => {
      const view = render(form());
      const input = screen.getByLabelText("Requested retention (days)");
      const target = changeRetention("9");
      expect(changeRetention("7")).toBe(initial);
      if (intermediate) {
        act(() => observe(target));
        view.rerender(form());
        expect(screen.getByLabelText("Requested retention (days)")).toBe(input);
        expect(input).toHaveValue(7);
      }
      act(() => {
        observe(initial);
        navigation.writing = false;
      });
      view.rerender(form());
      expect(screen.getByLabelText("Requested retention (days)")).toBe(input);
      expect(input).toHaveValue(7);
      act(() => observe(target));
      view.rerender(form());
      expect(screen.getByLabelText("Requested retention (days)")).not.toBe(
        input,
      );
      expect(screen.getByLabelText("Requested retention (days)")).toHaveValue(
        9,
      );
    },
  );

  it("resets an own B superseded by real navigation back to the still-observed A", () => {
    const view = render(form());
    const input = screen.getByLabelText("Requested retention (days)");
    changeRetention("9");
    expect(input).toHaveValue(9);
    act(() => {
      observe(initial);
      navigation.writing = false;
    });
    view.rerender(form());
    expect(screen.getByLabelText("Requested retention (days)")).not.toBe(input);
    expect(screen.getByLabelText("Requested retention (days)")).toHaveValue(7);
  });

  it("keeps the latest draft through over32 coalesced writes and retires the entire batch", () => {
    const view = render(form());
    const input = screen.getByLabelText("Requested retention (days)");
    input.focus();
    let first = "";
    let latest = "";
    for (let index = 0; index < 100; index += 1) {
      latest = changeRetention(String((index % 30) + 1));
      if (index === 0) first = latest;
    }
    act(() => {
      observe(latest);
      navigation.writing = false;
    });
    view.rerender(form());
    expect(screen.getByLabelText("Requested retention (days)")).toBe(input);
    expect(input).toHaveValue(10);
    expect(input).toHaveFocus();
    act(() => observe(first));
    view.rerender(form());
    expect(screen.getByLabelText("Requested retention (days)")).not.toBe(input);
    expect(screen.getByLabelText("Requested retention (days)")).toHaveValue(1);
  });
});
