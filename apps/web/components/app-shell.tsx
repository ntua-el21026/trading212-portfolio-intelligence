"use client";

import { CommandPalette } from "./command-palette";
import { NavigationIntentProvider } from "./navigation-intent";

import { Info, LockKeyhole, RotateCw, UserRound } from "lucide-react";
import Link from "./navigation-intent";
import type { FocusEvent, ReactNode } from "react";

import type { Account } from "@trading212/api-contracts";
import { accountHref } from "../lib/account-selection";
import {
  AccountProvider,
  AccountSelector,
  useAccountSelection,
} from "./account-context";
import { formatDateTime } from "../lib/format";
interface ShellAccess {
  displayName: string;
  isDemo: boolean;
}
import {
  DesktopNavigation,
  MobileNavigation,
  MobileSectionNavigation,
} from "./navigation";

export function AppShell({
  access,
  accounts,
  preferred,
  children,
}: Readonly<{
  access: ShellAccess;
  accounts: readonly Account[];
  preferred?: string;
  children: ReactNode;
}>) {
  return (
    <NavigationIntentProvider>
      <AccountProvider accounts={accounts} preferred={preferred}>
        <SelectedAppShell access={access}>{children}</SelectedAppShell>
      </AccountProvider>
    </NavigationIntentProvider>
  );
}

/** Keep the complete keyboard control clear when native focus reveals only part. */
function revealFocusedControl(event: FocusEvent<HTMLElement>) {
  const target = event.target;
  if (!(target instanceof HTMLElement) || !target.matches(":focus-visible"))
    return;
  const region = target.closest<HTMLElement>(
    ".table-scroll, .target-table-scroll, .xray-page .table-wrap",
  );
  if (region && region !== target && region.scrollWidth > region.clientWidth) {
    const control = target.getBoundingClientRect();
    const viewport = region.getBoundingClientRect();
    const left = viewport.left + region.clientLeft + 8;
    const right = viewport.left + region.clientLeft + region.clientWidth - 8;
    const delta =
      control.left < left
        ? control.left - left
        : control.right > right
          ? control.right - right
          : 0;
    if (delta) region.scrollBy({ left: delta, behavior: "instant" });
  }

  // Textarea focus can reveal its caret while leaving the control below the fold.
  const shell = event.currentTarget.closest(".app-shell");
  const header = shell?.querySelector("header.topbar")?.getBoundingClientRect();
  const navigation = shell?.querySelector<HTMLElement>(".mobile-navigation");
  const top = Math.max(0, header?.bottom ?? 0) + 8;
  const bottom =
    (navigation && getComputedStyle(navigation).display !== "none"
      ? navigation.getBoundingClientRect().top
      : window.innerHeight) - 8;
  const control = target.getBoundingClientRect();
  // Oversized scroll regions retain their own scrolling and native focus position.
  if (!control.width || !control.height || control.height > bottom - top)
    return;
  const delta =
    control.top < top
      ? control.top - top
      : control.bottom > bottom
        ? control.bottom - bottom
        : 0;
  if (delta) window.scrollBy({ top: delta, behavior: "instant" });
}

function SelectedAppShell({
  access,
  children,
}: Readonly<{ access: ShellAccess; children: ReactNode }>) {
  const { selection } = useAccountSelection();
  const account = selection.account;
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        Skip to portfolio content
      </a>
      <header className="topbar">
        <Link className="brand" href={accountHref("/", account?.id ?? null)}>
          Portfolio Intelligence
        </Link>
        <AccountSelector />
        <div className="topbar__sync">
          <RotateCw aria-hidden="true" size={19} strokeWidth={1.7} />
          <span>
            <small>Last synced</small>
            {account?.last_refresh_at
              ? formatDateTime(account?.last_refresh_at)
              : "Not yet synchronized"}
          </span>
        </div>
        <div className="topbar__account">
          <CommandPalette />
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

      <main
        className="app-main"
        id="main-content"
        tabIndex={-1}
        onFocusCapture={revealFocusedControl}
      >
        {access.isDemo ? (
          <div className="demo-ribbon" role="status">
            <Info aria-hidden="true" size={16} />
            Synthetic demo data · no broker request was made
          </div>
        ) : null}
        <AccountSelector mobile />
        <MobileSectionNavigation />
        {children}
      </main>

      <aside
        className="read-only-strip"
        aria-label="Read-only product boundary"
      >
        <LockKeyhole aria-hidden="true" size={18} />
        <span>
          <strong>Read-only</strong>
          No broker changes or trades can be made here.
        </span>
      </aside>
      <MobileNavigation />
    </div>
  );
}
