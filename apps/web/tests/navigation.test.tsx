import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DesktopNavigation, MobileNavigation } from "../components/navigation";
import { AccountProvider } from "../components/account-context";
import { getDemoPortfolio } from "../lib/demo-data";

const navigation = vi.hoisted(() => ({ pathname: "/holdings" }));

vi.mock("next/navigation", () => ({
  usePathname: () => navigation.pathname,
  useRouter: () => ({ push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

describe("responsive navigation", () => {
  beforeEach(() => {
    navigation.pathname = "/holdings";
  });

  it("marks the current desktop route", () => {
    render(
      <AccountProvider accounts={[getDemoPortfolio().summary.account]}>
        <DesktopNavigation />
      </AccountProvider>,
    );

    expect(screen.getByRole("link", { name: "Holdings" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(
      screen.getByRole("navigation", { name: "Portfolio" }),
    ).toBeInTheDocument();
  });

  it("provides five bounded mobile destinations", () => {
    render(
      <AccountProvider accounts={[getDemoPortfolio().summary.account]}>
        <MobileNavigation />
      </AccountProvider>,
    );

    expect(
      screen.getByRole("navigation", { name: "Primary" }),
    ).toBeInTheDocument();
    expect(screen.getAllByRole("link")).toHaveLength(5);
    for (const link of screen.getAllByRole("link")) {
      expect(link.getAttribute("href")).toContain(
        `account=${getDemoPortfolio().summary.account.id}`,
      );
    }
  });
});
