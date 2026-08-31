import {
  BriefcaseBusiness,
  ChevronDown,
  Info,
  LockKeyhole,
  RotateCw,
  UserRound,
} from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import type { AccountSummaryResponse } from "../lib/contracts";
import { formatDateTime } from "../lib/format";
import type { WebAccess } from "../lib/auth";
import { DesktopNavigation, MobileNavigation } from "./navigation";

export function AppShell({
  access,
  children,
  summary,
}: Readonly<{
  access: WebAccess;
  children: ReactNode;
  summary: AccountSummaryResponse;
}>) {
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        Skip to portfolio content
      </a>
      <header className="topbar">
        <Link className="brand" href="/">
          Portfolio Intelligence
        </Link>
        <div className="topbar__portfolio" aria-label="Selected portfolio">
          <BriefcaseBusiness aria-hidden="true" size={19} strokeWidth={1.7} />
          <span>{summary.account.display_name}</span>
          <ChevronDown aria-hidden="true" size={16} />
        </div>
        <div className="topbar__sync">
          <RotateCw aria-hidden="true" size={19} strokeWidth={1.7} />
          <span>
            <small>Last synced</small>
            {summary.account.last_refresh_at
              ? formatDateTime(summary.account.last_refresh_at)
              : "Not yet synchronized"}
          </span>
        </div>
        <div className="topbar__account">
          <UserRound aria-hidden="true" size={22} strokeWidth={1.6} />
          <span>
            <strong>{access.displayName}</strong>
            <small>
              {access.isDemo ? "Synthetic · read-only" : "Read-only"}
            </small>
          </span>
        </div>
      </header>

      <aside className="sidebar">
        <DesktopNavigation />
        {access.isDemo ? (
          <div className="sidebar-notice">
            <Info aria-hidden="true" size={19} strokeWidth={1.7} />
            <div>
              <strong>Demo data</strong>
              <p>
                All values are synthetic and for demonstration purposes only.
              </p>
            </div>
          </div>
        ) : null}
      </aside>

      <main className="app-main" id="main-content" tabIndex={-1}>
        {access.isDemo ? (
          <div className="demo-ribbon" role="status">
            <Info aria-hidden="true" size={16} />
            Synthetic demo data · no broker request was made
          </div>
        ) : null}
        {children}
      </main>

      <aside
        className="read-only-strip"
        aria-label="Read-only product boundary"
      >
        <LockKeyhole aria-hidden="true" size={18} />
        <span>
          <strong>Read-only</strong>
          No portfolio changes or trades can be made here.
        </span>
      </aside>
      <MobileNavigation />
    </div>
  );
}
