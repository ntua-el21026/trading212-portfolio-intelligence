"use client";

import {
  Bell,
  BriefcaseBusiness,
  ChartPie,
  CircleDollarSign,
  Clock3,
  FileText,
  LayoutDashboard,
  ListTree,
  RefreshCw,
  Settings,
  SlidersHorizontal,
  ShieldCheck,
  TrendingUp,
} from "lucide-react";
import Link from "./navigation-intent";
import { usePathname } from "next/navigation";

import { accountHref } from "../lib/account-selection";
import { useAccountSelection } from "./account-context";

const primaryItems = [
  { href: "/", icon: LayoutDashboard, label: "Overview" },
  { href: "/holdings", icon: BriefcaseBusiness, label: "Holdings" },
  { href: "/allocation", icon: ChartPie, label: "Allocation" },
  { href: "/activity", icon: ListTree, label: "Activity" },
  { href: "/dividends", icon: CircleDollarSign, label: "Dividends" },
  { href: "/snapshots", icon: Clock3, label: "Snapshots" },
  { href: "/synchronization", icon: RefreshCw, label: "Synchronization" },
  { href: "/quality", icon: ShieldCheck, label: "Data quality" },
  { href: "/pies", icon: ChartPie, label: "Pies" },
  { href: "/drift", icon: ChartPie, label: "Drift" },
  { href: "/planner", icon: CircleDollarSign, label: "Planner" },
  { href: "/sources", icon: ShieldCheck, label: "Sources" },
  { href: "/performance", icon: TrendingUp, label: "Performance" },
  { href: "/risk", icon: ShieldCheck, label: "Risk" },
  { href: "/scenarios", icon: SlidersHorizontal, label: "Scenarios" },
  { href: "/projections", icon: TrendingUp, label: "Projections" },
  { href: "/research", icon: FileText, label: "Research" },
  {
    href: "/aggregation",
    icon: BriefcaseBusiness,
    label: "Account aggregation",
  },
  { href: "/income", icon: CircleDollarSign, label: "Income" },
  { href: "/xray", icon: ChartPie, label: "X-ray" },
  { href: "/reports", icon: FileText, label: "Reports" },
  { href: "/alerts", icon: Bell, label: "Alerts" },
] as const;

const secondaryItems = [
  { href: "/settings", icon: Settings, label: "Settings" },
] as const;

export const commandRoutes = [
  ...primaryItems,
  ...secondaryItems,
  { href: "/settings/layouts", label: "Saved layouts" },
].map(({ href, label }) => ({ href, label }));

const mobileItems = [
  primaryItems[0],
  primaryItems[1],
  primaryItems[3],
  primaryItems[4],
  primaryItems[7],
] as const;

function isCurrent(pathname: string, href: string): boolean {
  return href === "/" ? pathname === href : pathname.startsWith(href);
}

export function DesktopNavigation() {
  const pathname = usePathname();
  const { selection } = useAccountSelection();
  return (
    <nav aria-label="Portfolio" className="side-navigation">
      <ul>
        {primaryItems.map(({ href, icon: Icon, label }) => (
          <li key={href}>
            <Link
              prefetch={false}
              aria-label={label}
              aria-current={isCurrent(pathname, href) ? "page" : undefined}
              className="nav-link"
              href={accountHref(href, selection.account?.id ?? null)}
            >
              <Icon aria-hidden="true" size={19} strokeWidth={1.7} />
              <span>{label}</span>
            </Link>
          </li>
        ))}
      </ul>
      <ul className="side-navigation__secondary">
        {secondaryItems.map(({ href, icon: Icon, label }) => (
          <li key={href}>
            <Link
              prefetch={false}
              aria-label={label}
              aria-current={isCurrent(pathname, href) ? "page" : undefined}
              className="nav-link"
              href={accountHref(href, selection.account?.id ?? null)}
            >
              <Icon aria-hidden="true" size={19} strokeWidth={1.7} />
              <span>{label}</span>
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}

export function MobileNavigation() {
  const pathname = usePathname();
  const { selection } = useAccountSelection();
  return (
    <nav aria-label="Primary" className="mobile-navigation">
      {mobileItems.map(({ href, icon: Icon, label }) => (
        <Link
          prefetch={false}
          aria-label={label}
          aria-current={isCurrent(pathname, href) ? "page" : undefined}
          className="mobile-nav-link"
          href={accountHref(href, selection.account?.id ?? null)}
          key={href}
        >
          <Icon aria-hidden="true" size={22} strokeWidth={1.7} />
          <span>{label}</span>
        </Link>
      ))}
    </nav>
  );
}

export function MobileSectionNavigation() {
  const pathname = usePathname();
  const { selection } = useAccountSelection();
  return (
    <details className="mobile-section-navigation">
      <summary>All sections</summary>
      <nav aria-label="All portfolio sections">
        {[...primaryItems, ...secondaryItems].map(({ href, label }) => (
          <Link
            prefetch={false}
            key={href}
            href={accountHref(href, selection.account?.id ?? null)}
            aria-label={label}
            aria-current={isCurrent(pathname, href) ? "page" : undefined}
            onClick={(event) => {
              const menu = event.currentTarget.closest("details");
              if (menu) menu.open = false;
            }}
          >
            {label}
          </Link>
        ))}
      </nav>
    </details>
  );
}
