import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PremiumProviderStatusCard } from "../components/premium-provider-status";
import { account, other, status } from "./premium-provider-fixtures";
describe("provider status card", () => {
  it("shows the fixed capabilities and keeps configuration distinct from verification", () => {
    render(
      <PremiumProviderStatusCard
        accountId={account}
        result={{ ok: true, data: status }}
      />,
    );
    expect(
      screen.getByText(/Configuration presence does not verify a credential/),
    ).toBeVisible();
    const av = within(screen.getByLabelText("Alpha Vantage capabilities"));
    const ecb = within(screen.getByLabelText("ECB capabilities"));
    expect(av.getByText("Daily prices")).toBeVisible();
    expect(av.getByText("ETF profile")).toBeVisible();
    expect(av.getByText("Company overview")).toBeVisible();
    expect(av.getByText("News")).toBeVisible();
    expect(ecb.getByText("Reference FX")).toBeVisible();
    expect(ecb.getByText("Eligible, unverified")).toBeVisible();
    expect(
      ecb.getByText(/3 of 24 owner\/provider attempts charged today/),
    ).toBeVisible();
    expect(
      av.getByText(/Canonical constituent publication is unavailable/),
    ).toBeVisible();
  });
  it("clears metadata when account changes and renders safe denial", () => {
    const { rerender } = render(
      <PremiumProviderStatusCard
        accountId={account}
        result={{ ok: true, data: status }}
      />,
    );
    rerender(
      <PremiumProviderStatusCard
        accountId={other}
        result={{ ok: true, data: status }}
      />,
    );
    expect(screen.queryByText("Reference FX")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(
      "could not be verified for this account",
    );
    rerender(
      <PremiumProviderStatusCard
        accountId={other}
        result={{
          ok: false,
          code: "ACCESS_DENIED",
          message: "Current access is required.",
        }}
      />,
    );
    expect(screen.getByRole("status")).toHaveTextContent(
      "Current access is required.",
    );
  });
});
