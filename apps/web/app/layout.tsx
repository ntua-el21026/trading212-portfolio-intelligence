import type { Metadata, Viewport } from "next";
import { PwaRuntime } from "../components/pwa-runtime";
import type { ReactNode } from "react";
import { cookies } from "next/headers";
import { ThemeProvider } from "../components/theme";
import { THEME_COOKIE, themePreference } from "../lib/theme";

import "@trading212/ui/styles.css";
import "./styles.css";

export const metadata: Metadata = {
  description: "Private, strictly read-only portfolio intelligence.",
  title: {
    default: "Portfolio Intelligence",
    template: "%s · Portfolio Intelligence",
  },
};

export async function generateViewport(): Promise<Viewport> {
  const preference = themePreference(
    (await cookies()).get(THEME_COOKIE)?.value,
  );
  return {
    themeColor:
      preference === "system"
        ? [
            { media: "(prefers-color-scheme: light)", color: "#fcfdfd" },
            { media: "(prefers-color-scheme: dark)", color: "#10171b" },
          ]
        : preference === "dark"
          ? "#10171b"
          : "#fcfdfd",
  };
}

export default async function RootLayout({
  children,
}: Readonly<{ children: ReactNode }>) {
  const preference = themePreference(
    (await cookies()).get(THEME_COOKIE)?.value,
  );
  return (
    <html data-scroll-behavior="smooth" data-theme={preference} lang="en">
      <body>
        <ThemeProvider initialPreference={preference}>
          <PwaRuntime />
          {children}
        </ThemeProvider>
      </body>
    </html>
  );
}
