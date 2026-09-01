import type { Metadata } from "next";
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

export default function RootLayout({
  children,
}: Readonly<{ children: ReactNode }>) {
  return (
    <html data-scroll-behavior="smooth" lang="en" suppressHydrationWarning>
      <body>{children}</body>
    </html>
  );
}
