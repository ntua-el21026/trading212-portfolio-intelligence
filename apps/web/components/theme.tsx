"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useId,
  useState,
  type ReactNode,
} from "react";
import { Surface } from "@trading212/ui";
import { Palette } from "lucide-react";
import {
  THEME_COOKIE,
  type ThemePreference,
  themePreference,
} from "../lib/theme";

const ThemeContext = createContext<{
  preference: ThemePreference;
  choose: (preference: ThemePreference) => void;
} | null>(null);

/** Server-selected root attribute and CSS media queries resolve the first paint. */
export function ThemeProvider({
  initialPreference,
  children,
}: Readonly<{ initialPreference: ThemePreference; children: ReactNode }>) {
  const [preference, setPreference] = useState(initialPreference);
  const choose = useCallback((value: ThemePreference) => {
    const selected = themePreference(value);
    document.documentElement.dataset.theme = selected;
    setPreference(selected);
    // This nonsensitive enum is also read during SSR; no auth cookies are touched.
    try {
      document.cookie = `${THEME_COOKIE}=${selected}; Path=/; Max-Age=31536000; SameSite=Lax${window.location.protocol === "https:" ? "; Secure" : ""}`;
    } catch {
      // Restricted storage still permits changing the current document's theme.
    }
  }, []);

  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const updateChrome = () => {
      const dark =
        preference === "dark" || (preference === "system" && media.matches);
      for (const meta of document.querySelectorAll<HTMLMetaElement>(
        'meta[name="theme-color"]',
      )) {
        meta.content = dark ? "#10171b" : "#fcfdfd";
      }
    };
    updateChrome();
    media.addEventListener("change", updateChrome);
    return () => media.removeEventListener("change", updateChrome);
  }, [preference]);

  return (
    <ThemeContext.Provider value={{ preference, choose }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function ThemeControl() {
  const theme = useContext(ThemeContext);
  const id = useId();
  if (!theme) return null;
  return (
    <label className="theme-control" htmlFor={id}>
      <span>Appearance</span>
      <select
        id={id}
        value={theme.preference}
        onChange={(event) => theme.choose(themePreference(event.target.value))}
      >
        <option value="system">System</option>
        <option value="light">Light</option>
        <option value="dark">Dark</option>
      </select>
    </label>
  );
}

export function ThemeSettings() {
  return (
    <Surface className="settings-card" compact>
      <h2>
        <Palette aria-hidden="true" size={19} /> Appearance
      </h2>
      <p className="settings-copy">
        Choose a light or dark workspace, or follow your device. Your preference
        stays in this browser.
      </p>
      <ThemeControl />
    </Surface>
  );
}
