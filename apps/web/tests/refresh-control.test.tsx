import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RefreshControl } from "../components/refresh-control";
import { demoRefreshRun } from "../lib/demo-data";

const navigation = vi.hoisted(() => ({ refresh: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => navigation }));
const accountId = demoRefreshRun.account_id;
const otherAccountId = "ab402b97-943c-4b95-94c6-b5eb6f2e6dc1";
const response = (body: unknown) =>
  new Response(JSON.stringify(body), {
    headers: { "content-type": "application/json" },
  });

describe("account-bound read-only synchronization", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    navigation.refresh.mockReset();
  });

  it("reports actual demo success and preserves its no-broker warning", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(demoRefreshRun)));
    render(<RefreshControl accountId={accountId} demo />);
    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "Run demo synchronization" }));
    expect(await screen.findByText("Synchronization completed")).toBeVisible();
    expect(
      screen.getByText(/no external broker request was made/i),
    ).toBeVisible();
    expect(fetch).toHaveBeenCalledWith(
      `/api/refresh?account=${accountId}`,
      expect.objectContaining({ method: "POST", credentials: "same-origin" }),
    );
    expect(navigation.refresh).toHaveBeenCalledOnce();
  });

  it.each([
    ["queued", "Synchronization queued"],
    ["running", "Synchronization running"],
    ["partial", "Synchronization partially completed"],
    ["failed", "Synchronization failed"],
    ["cancelled", "Synchronization cancelled"],
  ])(
    "presents the actual %s state without a success claim",
    async (status, title) => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue(
          response({
            ...demoRefreshRun,
            status,
            completed_at:
              status === "queued" || status === "running"
                ? null
                : demoRefreshRun.completed_at,
          }),
        ),
      );
      render(<RefreshControl accountId={accountId} demo={false} />);
      await userEvent
        .setup()
        .click(screen.getByRole("button", { name: "Synchronize now" }));
      expect(await screen.findByText(title)).toBeVisible();
      expect(
        screen.queryByText("Synchronization completed"),
      ).not.toBeInTheDocument();
      if (status === "queued" || status === "running") {
        expect(
          screen.getByRole("button", { name: "Check status" }),
        ).toBeEnabled();
        expect(navigation.refresh).not.toHaveBeenCalled();
      }
    },
  );

  it("checks the same durable run without issuing another synchronization command", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(
        response({ ...demoRefreshRun, status: "queued", completed_at: null }),
      )
      .mockResolvedValueOnce(response(demoRefreshRun));
    vi.stubGlobal("fetch", fetcher);
    const user = userEvent.setup();
    render(<RefreshControl accountId={accountId} demo />);
    await user.click(
      screen.getByRole("button", { name: "Run demo synchronization" }),
    );
    await user.click(
      await screen.findByRole("button", { name: "Check status" }),
    );
    expect(await screen.findByText("Synchronization completed")).toBeVisible();
    expect(fetcher).toHaveBeenNthCalledWith(
      2,
      `/api/refresh?account=${accountId}&run=${demoRefreshRun.id}`,
      expect.objectContaining({ method: "GET" }),
    );
  });

  it.each([
    { ...demoRefreshRun, account_id: otherAccountId },
    { ...demoRefreshRun, status: "unknown" },
    { error: "secret-canary-upstream-error" },
  ])(
    "rejects a mismatched or malformed response without leaking its payload",
    async (body) => {
      vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(body)));
      render(<RefreshControl accountId={accountId} demo />);
      await userEvent
        .setup()
        .click(
          screen.getByRole("button", { name: "Run demo synchronization" }),
        );
      expect(
        await screen.findByText("Synchronization unavailable"),
      ).toBeVisible();
      expect(
        screen.queryByText("Synchronization completed"),
      ).not.toBeInTheDocument();
      expect(document.documentElement.outerHTML).not.toContain(
        "secret-canary-upstream-error",
      );
    },
  );

  it("cancels an old account request and ignores a late response even if the transport ignores abort", async () => {
    let finish: (value: Response) => void = () => {
      throw new Error("Pending request not initialized.");
    };
    const deferred = new Promise<Response>((resolve) => {
      finish = resolve;
    });
    const fetcher = vi.fn().mockReturnValue(deferred);
    vi.stubGlobal("fetch", fetcher);
    const view = render(<RefreshControl accountId={accountId} demo />);
    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "Run demo synchronization" }));
    const signal = fetcher.mock.calls[0][1].signal as AbortSignal;
    view.rerender(<RefreshControl accountId={otherAccountId} demo />);
    expect(signal.aborted).toBe(true);
    await act(async () => {
      finish(response(demoRefreshRun));
      await deferred;
    });
    expect(
      screen.queryByText("Synchronization completed"),
    ).not.toBeInTheDocument();
    expect(navigation.refresh).not.toHaveBeenCalled();
  });

  it("does not claim no data changed after an ambiguous network failure", async () => {
    const consoleCalls: unknown[][] = [];
    for (const method of ["error", "log", "warn"] as const) {
      vi.spyOn(console, method).mockImplementation((...values: unknown[]) =>
        consoleCalls.push(values),
      );
    }
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockRejectedValue(new Error("Bearer secret-canary-upstream-error")),
    );
    render(<RefreshControl accountId={accountId} demo={false} />);
    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "Synchronize now" }));
    expect(
      await screen.findByText("Synchronization unavailable"),
    ).toBeVisible();
    expect(screen.getByText(/status could not be confirmed/i)).toBeVisible();
    expect(document.documentElement.outerHTML).not.toContain(
      "secret-canary-upstream-error",
    );
    expect(JSON.stringify(consoleCalls)).not.toContain(
      "secret-canary-upstream-error",
    );
  });
});
