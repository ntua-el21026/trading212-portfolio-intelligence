import type { Metadata, Viewport } from "next";
import { PwaRuntime } from "../components/pwa-runtime";
import type { ReactNode } from "react";

import "@trading212/ui/styles.css";
import "./styles.css";

export const metadata: Metadata = {
  description: "Private, strictly read-only portfolio intelligence.",
  title: {
    default: "Portfolio Intelligence",
    template: "%s · Portfolio Intelligence",
  },
};

export const viewport: Viewport = { themeColor: "#101b20" };

export default function RootLayout({
  children,
}: Readonly<{ children: ReactNode }>) {
  return (
    <html data-scroll-behavior="smooth" lang="en" suppressHydrationWarning>
      <body>
        <PwaRuntime />
        {children}
      </body>
    </html>
  );
}
