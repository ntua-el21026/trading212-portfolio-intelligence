import { render, screen } from "@testing-library/react";
import type { ComponentProps } from "react";
import type { OwnerLayoutView } from "@trading212/api-contracts";
import { describe, expect, it, vi } from "vitest";
import { OwnerLayoutDisplay } from "../components/owner-layout-views";
import { getDemoPortfolio } from "../lib/demo-data";
vi.mock("../components/navigation-intent", () => ({
  default: (props: ComponentProps<"a">) => <a {...props} />,
}));
const id = "00000000-0000-4000-8000-000000000001";
const at = "2026-09-15T12:00:00Z";
function value(): OwnerLayoutView {
  const bundle = getDemoPortfolio();
  const version = {
    id,
    number: 1,
    content_digest: "a".repeat(64),
    created_at: at,
  };
  return {
    id,
    revision: 1,
    state: "active",
    version,
    versions: [version],
    content: {
      schema_version: 1,
      name: "Owner",
      description: "",
      account_id: bundle.summary.account.id,
      columns: 3,
      density: "compact",
      widgets: [
        { id, kind: "portfolio_summary", label: "Summary", selection: null },
      ],
    },
  };
}
describe("current canonical layout previews", () => {
  it("preserves original exact amount/currency and unavailable reasons beside formatted values", () => {
    const original = getDemoPortfolio();
    const bundle = {
      ...original,
      summary: {
        ...original.summary,
        total_value: {
          ...original.summary.total_value,
          value: "123456789012345678.123456789012345678",
          reporting_currency: "GBP",
        },
        cash_balance: {
          ...original.summary.cash_balance,
          value: null,
          availability: "unavailable" as const,
          unavailable_reason: "cash_original_source_absent",
        },
      },
    };
    const view = render(<OwnerLayoutDisplay value={value()} bundle={bundle} />);
    expect(
      view.container.querySelector(
        '[data-layout-metric="Total portfolio value"]',
      )?.textContent,
    ).toBe("123456789012345678.123456789012345678 GBP");
    expect(
      view.container.querySelector('[data-layout-metric="Cash"]')?.textContent,
    ).toContain("Unavailable");
    expect(view.container.textContent).toContain("cash_original_source_absent");
    expect(
      view.container.querySelector('[data-layout-metric="Cash"]')?.textContent,
    ).not.toContain("0 EUR");
    expect(view.container.textContent).toContain(
      original.summary.total_value.methodology,
    );
  });
  it("shows absent current portfolio honestly and keeps saved view navigation explicit", () => {
    const input = value();
    const template = {
      ...input,
      content: { ...input.content, account_id: null },
    };
    render(<OwnerLayoutDisplay value={template} bundle={null} />);
    expect(screen.getByText("Choose an account")).toBeVisible();
    expect(screen.queryByText("Total portfolio value")).not.toBeInTheDocument();
  });
});
