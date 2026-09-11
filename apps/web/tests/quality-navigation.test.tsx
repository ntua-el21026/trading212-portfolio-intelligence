import {
  Children,
  isValidElement,
  type ReactElement,
  type ReactNode,
} from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { IntelligenceDataQuality } from "@trading212/api-contracts";

const mocks = vi.hoisted(() => ({
  quality: vi.fn(),
  legacy: vi.fn(),
  access: vi.fn(),
  selectedAccount: vi.fn(),
}));
vi.mock("../lib/source-adapter", () => ({
  sourceClients: async () => ({
    sources: { get_intelligence_data_quality: mocks.quality },
  }),
  sourceData: <T,>(response: { data: T }) => response.data,
}));
vi.mock("../lib/api-adapter", () => ({
  loadQualityView: mocks.legacy,
  loadSelectedAccount: mocks.selectedAccount,
  readDemoViewState: (value?: string) => value ?? "default",
}));
vi.mock("../lib/auth", () => ({ requireWebAccess: mocks.access }));

import { IntelligenceQualityPanel } from "../components/intelligence-quality";
import QualityPage from "../app/(portfolio)/quality/page";
import { getDemoPortfolio } from "../lib/demo-data";
import type { QualityBundle } from "../lib/contracts";

const account = "ab402b97-943c-4b95-94c6-b5eb6f2e6dc1";
const at = "2026-09-11T10:00:00Z";
const both = {
  account,
  analytics_kind: "valuation",
  sources_limit: "1",
  sources_cursor: "source-old",
  state: "partial",
  cursor: "legacy-old",
  unknown: "private-unknown-canary",
};
type Search = Record<string, string | string[] | undefined>;

function qualityFixture(): IntelligenceDataQuality {
  return {
    state: "quality",
    account_id: account,
    analytics_kind: "valuation",
    checked_at: at,
    selection_at: at,
    schema_version: "1.0.0",
    supported_kinds: [
      "valuation",
      "actual_vs_target",
      "drift",
      "performance",
      "benchmark",
      "income",
      "attribution",
      "cash_flow",
      "xray",
    ],
    selection_state: "retained",
    selection: {
      kind: "valuation",
      id: account,
      input_id: null,
      input_kind: null,
      input_digest: "a".repeat(64),
      content_digest: "b".repeat(64),
      method_version: "valuation_v1",
      reporting_currency: "EUR",
      valuation_at: at,
      source_cutoff_at: at,
      created_at: at,
      period_start: null,
      period_end: null,
    },
    metrics: (
      [
        "portfolio_total",
        "positions",
        "cash",
        "current_price",
        "direct_allocation",
      ] as const
    ).map((key) => ({
      key,
      recorded_availability: "available",
      recorded_quality: "fresh",
      quality_basis: "metric",
      current_usability: "usable",
      freshness: "fresh",
      freshness_basis: "required_sources",
      missing_input: "complete",
      license_applicability: "not_applicable",
      reasons: [],
    })),
    reconciliation: {
      visibility: "permission_required",
      id: null,
      as_of: null,
      status: null,
      complete: null,
      discrepancy_count: null,
      reason: null,
    },
    activity_visibility: "permission_required",
    targets_visibility: "permission_required",
    sources: {
      items: [
        {
          identity: {
            kind: "portfolio_snapshot",
            id: account,
            parent_id: null,
          },
          provider_id: null,
          license_version_id: null,
          content_digest: null,
          effective_at: at,
          first_observed_at: at,
          expires_at: null,
          recorded_quality: "fresh",
          expected_count: null,
          available_count: null,
          freshness: {
            state: "fresh",
            policy_version: "fixture",
            reference_at: at,
            max_age_seconds: 900,
          },
          current_usability: "usable",
          retention: "retained",
          license_applicability: "not_applicable",
          reasons: [],
        },
      ],
      exact_total: 2,
      limit: 1,
      next_cursor: "source-next",
      expires_at: at,
    },
  };
}

function legacyFixture(): QualityBundle {
  const demo = getDemoPortfolio();
  return {
    summary: demo.summary,
    quality: demo.quality,
    reconciliation: demo.reconciliation,
    discrepancies: {
      items: demo.reconciliation.issues,
      limit: 50,
      total: demo.reconciliation.issues.length + 1,
      next_cursor: "legacy-next",
    },
  };
}

function parameters(name: string) {
  const href = screen.getByRole("link", { name }).getAttribute("href");
  if (!href) throw new Error("Expected a local quality link.");
  const url = new URL(href, "http://localhost");
  expect(url.pathname).toBe("/quality");
  return Object.fromEntries(url.searchParams);
}

async function intelligence(search: Search) {
  return IntelligenceQualityPanel({
    accountId: account,
    search,
    demo: false,
    permitted: true,
  });
}

// Resolve just the existing async legacy child selected by the page. This unit
// harness does not simulate RSC navigation or execute the sibling a second time.
async function legacy(search: Search) {
  const tree = await QualityPage({ searchParams: Promise.resolve(search) });
  const content = tree.props.children as ReactElement<{ children: ReactNode }>;
  type Props = { params: Search; selectedAccountId: string };
  const child = Children.toArray(content.props.children).find(
    (node) => isValidElement<Props>(node) && "selectedAccountId" in node.props,
  );
  if (!isValidElement<Props>(child) || typeof child.type !== "function") {
    throw new Error("Expected the activity-authorized legacy panel.");
  }
  const component = child.type as (props: Props) => Promise<ReactElement>;
  return component(child.props);
}

describe("quality navigation preserves independent panels", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    mocks.quality.mockResolvedValue({
      data: qualityFixture(),
      notModified: false,
    });
    mocks.legacy.mockResolvedValue(legacyFixture());
    mocks.selectedAccount.mockResolvedValue({
      kind: "selected",
      account: { id: account },
    });
    mocks.access.mockResolvedValue({
      displayName: "Synthetic owner",
      isDemo: false,
      principal: {
        scopes: ["portfolio:read", "analytics:read", "activity:read"],
      },
    });
  });

  it("source next and first links preserve the legacy cursor and recognized state", async () => {
    render(await intelligence(both));
    expect(parameters("Next source page")).toEqual({
      account,
      analytics_kind: "valuation",
      sources_limit: "1",
      sources_cursor: "source-next",
      state: "partial",
      cursor: "legacy-old",
    });
    expect(parameters("First source page")).toEqual({
      account,
      analytics_kind: "valuation",
      sources_limit: "1",
      state: "partial",
      cursor: "legacy-old",
    });
    expect(mocks.quality).toHaveBeenCalledExactlyOnceWith(account, {
      analytics_kind: "valuation",
      limit: 1,
      cursor: "source-old",
    });
    expect(mocks.legacy).not.toHaveBeenCalled();
    expect(document.body.innerHTML).not.toContain("private-unknown-canary");
  });

  it("kind selection clears the source cursor while preserving legacy state", async () => {
    const user = userEvent.setup();
    render(await intelligence(both));
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Intelligence kind" }),
      "xray",
    );
    const form = screen
      .getByRole("button", { name: "Inspect intelligence quality" })
      .closest("form");
    if (!form) throw new Error("Expected the intelligence selection form.");
    expect(Object.fromEntries(new FormData(form))).toEqual({
      account,
      state: "partial",
      cursor: "legacy-old",
      analytics_kind: "xray",
      sources_limit: "1",
    });
    expect(form.querySelector('[name="sources_cursor"]')).toBeNull();
    expect(mocks.quality).toHaveBeenCalledTimes(1);
  });

  it("legacy next keeps the nondefault intelligence selection and pinned cursor", async () => {
    render(
      await legacy({
        ...both,
        analytics_kind: "performance",
        sources_limit: "50",
      }),
    );
    expect(parameters("Next page")).toEqual({
      account,
      state: "partial",
      analytics_kind: "performance",
      sources_limit: "50",
      sources_cursor: "source-old",
      cursor: "legacy-next",
    });
    expect(mocks.legacy).toHaveBeenCalledExactlyOnceWith(
      "legacy-old",
      "partial",
      account,
    );
    expect(mocks.quality).not.toHaveBeenCalled();
    expect(document.body.innerHTML).not.toContain("private-unknown-canary");
  });

  it("invalid legacy cursor is a local notice and does not block the authorized quality GET", async () => {
    const search = { ...both, cursor: ["private-invalid-cursor", "duplicate"] };
    const [qualityPanel, legacyPanel] = await Promise.all([
      intelligence(search),
      legacy(search),
    ]);
    render(
      <>
        {qualityPanel}
        {legacyPanel}
      </>,
    );
    expect(screen.getByText("Invalid reconciliation filters")).toBeVisible();
    expect(
      screen.getByRole("table", {
        name: "Complete metric status inventory for Valuation",
      }),
    ).toBeVisible();
    expect(mocks.legacy).not.toHaveBeenCalled();
    expect(mocks.quality).toHaveBeenCalledExactlyOnceWith(account, {
      analytics_kind: "valuation",
      limit: 1,
      cursor: "source-old",
    });
    expect(parameters("Next source page")).toEqual({
      account,
      analytics_kind: "valuation",
      sources_limit: "1",
      sources_cursor: "source-next",
      state: "partial",
    });
    expect(parameters("Reset invalid reconciliation filters")).toEqual({
      account,
      analytics_kind: "valuation",
      sources_limit: "1",
      sources_cursor: "source-old",
      state: "partial",
    });
    expect(document.body.innerHTML).not.toContain("private-invalid-cursor");
  });

  it("invalid intelligence cursor does not block legacy reads or discard its valid kind and page size", async () => {
    const search = {
      ...both,
      analytics_kind: "performance",
      sources_limit: "50",
      sources_cursor: "private-invalid\u0001cursor",
    };
    const [qualityPanel, legacyPanel] = await Promise.all([
      intelligence(search),
      legacy(search),
    ]);
    render(
      <>
        {qualityPanel}
        {legacyPanel}
      </>,
    );
    expect(screen.getByText("Invalid intelligence filters")).toBeVisible();
    expect(mocks.quality).not.toHaveBeenCalled();
    expect(mocks.legacy).toHaveBeenCalledExactlyOnceWith(
      "legacy-old",
      "partial",
      account,
    );
    expect(parameters("Next page")).toEqual({
      account,
      state: "partial",
      analytics_kind: "performance",
      sources_limit: "50",
      cursor: "legacy-next",
    });
    expect(parameters("Reset invalid intelligence filters")).toEqual({
      account,
      analytics_kind: "performance",
      sources_limit: "50",
      state: "partial",
      cursor: "legacy-old",
    });
    expect(document.body.innerHTML).not.toContain("private-invalid");
  });

  it("unknown legacy state and its dependent cursor are omitted without echoing either", async () => {
    const search = {
      ...both,
      state: "private-unknown-state",
      cursor: "private-state-bound-cursor",
    };
    render(
      <>
        {await intelligence(search)}
        {await legacy(search)}
      </>,
    );
    expect(screen.getByText("Invalid reconciliation filters")).toBeVisible();
    expect(parameters("Next source page")).toEqual({
      account,
      analytics_kind: "valuation",
      sources_limit: "1",
      sources_cursor: "source-next",
    });
    expect(mocks.legacy).not.toHaveBeenCalled();
    expect(mocks.quality).toHaveBeenCalledTimes(1);
    expect(document.body.innerHTML).not.toContain("private-unknown-state");
    expect(document.body.innerHTML).not.toContain("private-state-bound-cursor");
  });

  it("keeps runtime legacy failure local without retrying or duplicating either read", async () => {
    mocks.legacy.mockRejectedValue(new Error("private-backend-canary"));
    render(
      <>
        {await intelligence(both)}
        {await legacy(both)}
      </>,
    );
    expect(screen.getByText("Reconciliation view unavailable")).toBeVisible();
    expect(
      screen.getByRole("table", {
        name: "Complete metric status inventory for Valuation",
      }),
    ).toBeVisible();
    expect(mocks.quality).toHaveBeenCalledTimes(1);
    expect(mocks.legacy).toHaveBeenCalledTimes(1);
    expect(document.body.innerHTML).not.toContain("private-backend-canary");
  });

  it("does not parse or dispatch intelligence when that panel is not permitted", async () => {
    render(
      await IntelligenceQualityPanel({
        accountId: account,
        search: { ...both, sources_cursor: ["bad", "duplicate"] },
        demo: false,
        permitted: false,
      }),
    );
    expect(screen.getByText("Analytics access required")).toBeVisible();
    expect(
      screen.queryByText("Invalid intelligence filters"),
    ).not.toBeInTheDocument();
    expect(mocks.quality).not.toHaveBeenCalled();
    expect(mocks.legacy).not.toHaveBeenCalled();
  });
});
