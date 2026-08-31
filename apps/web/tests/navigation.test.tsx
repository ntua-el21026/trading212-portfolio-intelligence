import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DesktopNavigation, MobileNavigation } from "../components/navigation";

const navigation = vi.hoisted(() => ({ pathname: "/holdings" }));

vi.mock("next/navigation", () => ({
  usePathname: () => navigation.pathname,
}));

describe("responsive navigation", () => {
  beforeEach(() => {
    navigation.pathname = "/holdings";
  });

  it("marks the current desktop route", () => {
    render(<DesktopNavigation />);

    expect(screen.getByRole("link", { name: "Holdings" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(
      screen.getByRole("navigation", { name: "Portfolio" }),
    ).toBeInTheDocument();
  });

  it("provides five bounded mobile destinations", () => {
    render(<MobileNavigation />);

    expect(
      screen.getByRole("navigation", { name: "Primary" }),
    ).toBeInTheDocument();
    expect(screen.getAllByRole("link")).toHaveLength(5);
  });
});
