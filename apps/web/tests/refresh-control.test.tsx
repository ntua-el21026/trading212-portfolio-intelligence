import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RefreshControl } from "../components/refresh-control";
import { demoRefreshRun } from "../lib/demo-data";

describe("read-only synchronization control", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("reports that a demo run made no broker request", async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify(demoRefreshRun), {
          headers: { "content-type": "application/json" },
          status: 200,
        }),
      ),
    );
    render(<RefreshControl demo />);

    await user.click(
      screen.getByRole("button", { name: "Run demo synchronization" }),
    );

    expect(await screen.findByText("Synchronization completed")).toBeVisible();
    expect(
      screen.getByText(/no external broker request was made/i),
    ).toBeVisible();
    expect(fetch).toHaveBeenCalledWith(
      "/api/refresh",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("keeps an upstream secret canary out of web output", async () => {
    const user = userEvent.setup();
    const secretCanary = [
      "phase1",
      "web",
      "secret",
      "canary",
      "4f08a7dba163",
    ].join("-");
    const consoleCalls: unknown[][] = [];
    for (const method of ["error", "log", "warn"] as const) {
      vi.spyOn(console, method).mockImplementation((...values: unknown[]) => {
        consoleCalls.push(values);
      });
    }
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockRejectedValue(
          new Error(`Bearer ${secretCanary}: upstream failure`),
        ),
    );
    render(<RefreshControl demo={false} />);

    await user.click(screen.getByRole("button", { name: "Synchronize now" }));

    expect(
      await screen.findByText("Synchronization unavailable"),
    ).toBeVisible();
    expect(screen.getByText(/No portfolio data was changed/i)).toBeVisible();
    expect(document.documentElement.outerHTML).not.toContain(secretCanary);
    expect(JSON.stringify(consoleCalls)).not.toContain(secretCanary);
    expect(fetch).toHaveBeenCalledWith(
      "/api/refresh",
      expect.objectContaining({ method: "POST" }),
    );
  });
});
