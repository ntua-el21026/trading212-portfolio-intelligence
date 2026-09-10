import { webcrypto } from "node:crypto";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ReportSelectionForm } from "../components/report-selection";
import { parseReportQuery } from "../lib/report-query";
import { accountId, job, jobId, snapshot } from "./report-fixtures";

const navigation = vi.hoisted(() => ({
  search: "",
  listeners: new Set<() => void>(),
  command: vi.fn(),
  push: vi.fn(),
  refresh: vi.fn(),
}));
vi.mock("../lib/report-actions", () => ({
  submitReportCommand: navigation.command,
}));
vi.mock("next/navigation", async () => {
  const { useSyncExternalStore } =
    await vi.importActual<typeof import("react")>("react");
  return {
    useRouter: () => ({ push: navigation.push, refresh: navigation.refresh }),
    useSearchParams: () =>
      new URLSearchParams(
        useSyncExternalStore(
          (listener) => {
            navigation.listeners.add(listener);
            return () => {
              navigation.listeners.delete(listener);
            };
          },
          () => navigation.search,
          () => navigation.search,
        ),
      ),
  };
});

const choices = { targets: [], plans: [], benchmarks: [], warnings: [] };
const initial = parseReportQuery({});
const originalReplace = window.history.replaceState.bind(window.history);

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((complete) => {
    resolve = complete;
  });
  return { promise, resolve };
}

function navigate(search: string) {
  originalReplace({ __NA: true }, "", `/reports${search ? `?${search}` : ""}`);
  navigation.search = search;
  for (const listener of navigation.listeners) listener();
}

function form(defaultCutoff = snapshot.source_cutoff_at) {
  return (
    <ReportSelectionForm
      accountId={accountId}
      snapshot={snapshot}
      initial={initial}
      choices={choices}
      canCreate
      defaultCutoff={defaultCutoff}
    />
  );
}

describe("report navigation and local drafts", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.stubGlobal("crypto", webcrypto);
    navigation.search = "";
    navigation.listeners.clear();
    originalReplace({ __NA: true }, "", "/reports");
    vi.spyOn(window.history, "replaceState").mockImplementation(
      (state, unused, url) => {
        originalReplace(state, unused, url);
        // Match Next's public native-history path: internal __NA writes bypass it.
        if (state?.__NA || state?._N) return;
        navigation.search = new URL(
          window.location.href,
        ).searchParams.toString();
        for (const listener of navigation.listeners) listener();
      },
    );
  });
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("restores defaults after editing the original default selection and returning through the router", async () => {
    const user = userEvent.setup();
    const view = render(form());
    await user.selectOptions(screen.getByLabelText("Output"), "export");
    await user.selectOptions(screen.getByLabelText("Dataset"), "dividends");
    await user.selectOptions(screen.getByLabelText("Format"), "xlsx");
    await user.clear(screen.getByLabelText("Requested retention (days)"));
    await user.type(screen.getByLabelText("Requested retention (days)"), "9");
    const remembered = new URL(window.location.href).searchParams.toString();
    expect(screen.getByLabelText("Output")).toHaveValue("export");
    act(() => navigate(""));
    view.rerender(form());
    expect(screen.getByLabelText("Output")).toHaveValue("report");
    expect(screen.getByLabelText("Report type")).toHaveValue(
      "portfolio_summary",
    );
    expect(screen.getByLabelText("Requested retention (days)")).toHaveValue(7);
    expect(screen.getByRole("checkbox", { name: /^PDF$/ })).toBeChecked();
    act(() => navigate(remembered));
    view.rerender(form());
    expect(screen.getByLabelText("Output")).toHaveValue("export");
    expect(screen.getByLabelText("Dataset")).toHaveValue("dividends");
    expect(screen.getByLabelText("Format")).toHaveValue("xlsx");
    expect(screen.getByLabelText("Requested retention (days)")).toHaveValue(9);
  });

  it("keeps rapid local typing and focus through same-selection refreshes", async () => {
    const user = userEvent.setup();
    const view = render(form());
    const cutoff = screen.getByLabelText("Source cutoff (UTC)");
    await user.clear(cutoff);
    const value = "2026-09-07T12:00:00.123456789+00:00";
    await user.type(cutoff, value);
    expect(value.length).toBeGreaterThan(32);
    expect(screen.getByLabelText("Source cutoff (UTC)")).toBe(cutoff);
    expect(cutoff).toHaveFocus();
    expect(cutoff).toHaveValue(value);
    view.rerender(form("2026-09-10T12:00:00Z"));
    expect(screen.getByLabelText("Source cutoff (UTC)")).toBe(cutoff);
    expect(cutoff).toHaveValue(value);
    fireEvent.change(screen.getByLabelText("Requested retention (days)"), {
      target: { value: "10" },
    });
    expect(screen.getByLabelText("Requested retention (days)")).toHaveValue(10);
  });

  it("preserves the pending command and its draft when history and polling props refresh", async () => {
    const user = userEvent.setup();
    const result = deferred<{
      ok: false;
      code: string;
      message: string;
    }>();
    navigation.command.mockReturnValue(result.promise);
    const view = render(form());
    const cutoff = screen.getByLabelText("Source cutoff (UTC)");
    await user.click(screen.getByRole("button", { name: "Generate report" }));
    await waitFor(() => expect(navigation.command).toHaveBeenCalledOnce());
    const query = new URLSearchParams(window.location.search);
    query.set("report", jobId);
    query.set("state", "running");
    query.set("cursor", "retained_history_page");
    act(() => navigate(query.toString()));
    view.rerender(form("2026-09-10T12:00:00Z"));
    expect(
      screen.getByRole("button", { name: "Saving request…" }),
    ).toBeDisabled();
    expect(screen.getByLabelText("Source cutoff (UTC)")).toBe(cutoff);
    expect(cutoff).toHaveValue(snapshot.source_cutoff_at);
    await act(async () =>
      result.resolve({
        ok: false,
        code: "REPORT_UNAVAILABLE",
        message: "Retry this saved request.",
      }),
    );
    expect(await screen.findByText(/REPORT_UNAVAILABLE/)).toBeVisible();
    expect(
      screen.getByRole("button", { name: "Generate report" }),
    ).toBeEnabled();
    expect(navigation.command).toHaveBeenCalledOnce();
  });

  it.each([
    "kind=untrusted-fragment",
    "constituent_snapshot_id=untrusted-fragment",
    "untrusted-fragment=unrecognized",
    "__proto__=untrusted-fragment",
    "kind=report&kind=export",
    "start_date=2026-09-08&end_date=2026-09-07",
  ])(
    "shows an explicit invalid-selection state for external query %s",
    (search) => {
      const view = render(form());
      act(() => navigate(search));
      view.rerender(form());
      expect(screen.getByText("Invalid report selection")).toBeVisible();
      expect(
        screen.getByRole("link", { name: "Reset the report selection" }),
      ).toHaveAttribute("href", "/reports");
      expect(
        screen.queryByRole("button", { name: "Generate report" }),
      ).not.toBeInTheDocument();
      expect(view.container.textContent).not.toContain("untrusted-fragment");
      act(() => navigate(""));
      view.rerender(form());
      expect(
        screen.getByRole("button", { name: "Generate report" }),
      ).toBeEnabled();
    },
  );

  it("initializes a remounted cached page from its current URL instead of old server form props", () => {
    navigate("kind=export&dataset=dividends&formats=xlsx&field_set=audit");
    render(form());
    expect(screen.getByLabelText("Output")).toHaveValue("export");
    expect(screen.getByLabelText("Dataset")).toHaveValue("dividends");
    expect(screen.getByLabelText("Format")).toHaveValue("xlsx");
    expect(screen.getByLabelText("Columns")).toHaveValue("audit");
  });

  it("keeps a completed old command from redirecting a form replaced by navigation", async () => {
    const user = userEvent.setup();
    const result = deferred<{
      ok: true;
      kind: "report";
      job: typeof job;
    }>();
    navigation.command.mockReturnValue(result.promise);
    const view = render(form());
    await user.click(screen.getByRole("button", { name: "Generate report" }));
    await waitFor(() => expect(navigation.command).toHaveBeenCalledOnce());
    act(() => navigate("kind=export&dataset=dividends"));
    view.rerender(form());
    expect(screen.getByRole("button", { name: "Create export" })).toBeEnabled();
    await act(async () => result.resolve({ ok: true, kind: "report", job }));
    expect(navigation.push).not.toHaveBeenCalled();
    expect(navigation.refresh).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Dataset")).toHaveValue("dividends");
    expect(navigation.command).toHaveBeenCalledOnce();
  });
});
