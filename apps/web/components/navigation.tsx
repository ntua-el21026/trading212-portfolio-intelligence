"use client";

import {
  BriefcaseBusiness,
  ChartPie,
  CircleDollarSign,
  Clock3,
  LayoutDashboard,
  ListTree,
  RefreshCw,
  Settings,
  ShieldCheck,
  TrendingUp,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

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
  { href: "/income", icon: CircleDollarSign, label: "Income" },
] as const;

const secondaryItems = [
  { href: "/settings", icon: Settings, label: "Settings" },
] as const;

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
  return (
    <nav aria-label="Portfolio" className="side-navigation">
      <ul>
        {primaryItems.map(({ href, icon: Icon, label }) => (
          <li key={href}>
            <Link
              prefetch={false}
              aria-current={isCurrent(pathname, href) ? "page" : undefined}
              className="nav-link"
              href={href}
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
              aria-current={isCurrent(pathname, href) ? "page" : undefined}
              className="nav-link"
              href={href}
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
  return (
    <nav aria-label="Primary" className="mobile-navigation">
      {mobileItems.map(({ href, icon: Icon, label }) => (
        <Link
          prefetch={false}
          aria-current={isCurrent(pathname, href) ? "page" : undefined}
          className="mobile-nav-link"
          href={href}
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
  return (
    <details className="mobile-section-navigation">
      <summary>All sections</summary>
      <nav aria-label="All portfolio sections">
        {[...primaryItems, ...secondaryItems].map(({ href, label }) => (
          <Link
            prefetch={false}
            key={href}
            href={href}
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
