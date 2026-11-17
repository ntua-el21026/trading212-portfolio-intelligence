import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ThemeControl, ThemeProvider } from "../components/theme";
import { THEME_COOKIE, themePreference } from "../lib/theme";

function preference(initialPreference: "light" | "dark" | "system" = "system") {
  return render(
    <ThemeProvider initialPreference={initialPreference}>
      <ThemeControl />
    </ThemeProvider>,
  );
}

beforeEach(() => {
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  document.cookie = `${THEME_COOKIE}=; Path=/; Max-Age=0`;
  delete document.documentElement.dataset.theme;
  document.head
    .querySelectorAll('meta[name="theme-color"]')
    .forEach((node) => node.remove());
});

describe("local appearance preference", () => {
  it("admits only known visual enum values from an untrusted cookie", () => {
    for (const value of [
      undefined,
      null,
      "",
      "blue",
      "DARK",
      "dark; Path=/",
      {},
    ]) {
      expect(themePreference(value)).toBe("system");
    }
    expect(themePreference("light")).toBe("light");
    expect(themePreference("dark")).toBe("dark");
  });

  it("renders the server preference without a client-only initialization step", () => {
    preference("dark");
    expect(screen.getByRole("combobox", { name: "Appearance" })).toHaveValue(
      "dark",
    );
  });

  it("switches the root and persists only the visual preference, without touching other cookies", async () => {
    const user = userEvent.setup();
    document.cookie = "unrelated_preference=preserved; Path=/";
    preference();
    const control = screen.getByRole("combobox", { name: "Appearance" });
    for (const value of ["dark", "light", "system"]) {
      await user.selectOptions(control, value);
      expect(document.documentElement.dataset.theme).toBe(value);
      expect(document.cookie).toContain(`${THEME_COOKIE}=${value}`);
      expect(document.cookie).toContain("unrelated_preference=preserved");
    }
    document.cookie = "unrelated_preference=; Path=/; Max-Age=0";
  });

  it("updates browser chrome on system changes and removes the listener on unmount", () => {
    let dark = false;
    let listener: (() => void) | undefined;
    const remove = vi.fn();
    vi.spyOn(window, "matchMedia").mockImplementation(
      () =>
        ({
          get matches() {
            return dark;
          },
          media: "(prefers-color-scheme: dark)",
          addEventListener: (_type: string, callback: () => void) => {
            listener = callback;
          },
          removeEventListener: remove,
        }) as unknown as MediaQueryList,
    );
    const meta = document.createElement("meta");
    meta.name = "theme-color";
    document.head.append(meta);
    const view = preference();
    expect(meta.content).toBe("#fcfdfd");
    act(() => {
      dark = true;
      listener?.();
    });
    expect(meta.content).toBe("#10171b");
    view.unmount();
    expect(remove).toHaveBeenCalledWith("change", listener);
  });

  it("remains usable if visual preference persistence is denied", async () => {
    const user = userEvent.setup();
    preference();
    vi.spyOn(document, "cookie", "set").mockImplementation(() => {
      throw new Error("storage denied");
    });
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Appearance" }),
      "dark",
    );
    expect(screen.getByRole("combobox", { name: "Appearance" })).toHaveValue(
      "dark",
    );
    expect(document.documentElement.dataset.theme).toBe("dark");
  });
});
