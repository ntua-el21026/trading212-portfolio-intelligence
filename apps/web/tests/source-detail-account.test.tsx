import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SourceApiError, XrayApiError } from "@trading212/api-contracts";

import SourceSnapshotPage from "../app/(portfolio)/sources/snapshots/[kind]/[snapshotId]/page";
import XraySourcePage from "../app/(portfolio)/xray/sources/[snapshotId]/page";
import { AccountProvider } from "../components/account-context";
import {
  resolveAccountSelection,
  type AccountParameter,
} from "../lib/account-selection";
import { getDemoPortfolio } from "../lib/demo-data";

const mocks = vi.hoisted(() => ({
  selectedAccount: vi.fn(),
  sources: vi.fn(),
  xray: vi.fn(),
  priceHeader: vi.fn(),
  fxHeader: vi.fn(),
  benchmarkHeader: vi.fn(),
  priceRows: vi.fn(),
  fxRows: vi.fn(),
  benchmarkRows: vi.fn(),
  constituentHeader: vi.fn(),
  holdings: vi.fn(),
  query: "",
  pathname: "/sources",
  push: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(mocks.query),
  usePathname: () => mocks.pathname,
  useRouter: () => ({ push: mocks.push }),
  notFound: () => {
    throw new Error("not found");
  },
}));
vi.mock("../lib/api-adapter", () => ({
  loadSelectedAccount: mocks.selectedAccount,
}));
vi.mock("../lib/auth", () => ({
  requireWebAccess: async () => ({ isDemo: false }),
}));
vi.mock("../lib/planning-selection", () => ({
  // Only valid path IDs use this stub. Account selection uses the real strict resolver.
  planningUuid: (value: string | string[] | undefined) =>
    typeof value === "string" ? value : undefined,
}));
vi.mock("../lib/source-adapter", async () => {
  const { SourceApiError } = await import("@trading212/api-contracts");
  return {
    sourceClients: mocks.sources,
    sourceData: (response: { data: unknown }) => response.data,
    sourceResult: async <T,>(operation: () => Promise<T>) => {
      try {
        return { ok: true, data: await operation() };
      } catch (error) {
        if (!(error instanceof SourceApiError)) throw error;
        return { ok: false, code: error.code, message: error.message };
      }
    },
  };
});
vi.mock("../lib/xray-adapter", () => ({
  xrayClients: mocks.xray,
  xrayData: (response: { data: unknown }) => response.data,
}));
// Keep the actual server pages and actual AccountProvider/AccountView boundary.
// These detail subcomponents are presentation leaves, not authorization mocks.
vi.mock("../components/source-details", () => ({
  SourceProvenanceDetails: () => <p>Source provenance</p>,
  SourceLicenseDetails: ({ license }: { license: { attribution: string } }) => (
    <p>{license.attribution}</p>
  ),
}));
vi.mock("../components/composite-source-details", () => ({
  CompositeSourceDetails: () => <p>Retained composite evidence</p>,
}));

const first = getDemoPortfolio().summary.account;
const second = {
  ...first,
  id: "ab402b97-943c-4b95-94c6-b5eb6f2e6dc1",
  display_name: "Second account",
};
const foreign = "ffffffff-ffff-4fff-8fff-ffffffffffff";
const snapshotId = "40000000-0000-4000-8000-000000000001";
const runId = "50000000-0000-4000-8000-000000000001";
const at = "2026-09-10T16:00:00Z";
const license = {
  id: snapshotId,
  provider_id: snapshotId,
  version: "1",
  effective_at: at,
  attribution: "Retained source attribution",
  evidence_key: "synthetic-evidence",
  retention_days: 30,
  store: "allowed",
  display: "allowed",
  report: "allowed",
  export: "allowed",
};
const sourceHeader = {
  id: snapshotId,
  period: { start: "2026-09-01", end: "2026-09-10" },
  content_digest: "a".repeat(64),
  provenance: {
    provider_id: snapshotId,
    license_version_id: snapshotId,
    adapter_version: "synthetic-1",
    schema_version: "source-1",
    source_revision: "1",
    revision_order: "1",
    effective_at: at,
    first_observed_at: at,
    synthetic: true,
  },
  coverage: {
    expected_count: 0,
    available_count: 0,
    gap_count: 0,
    gaps: [],
    gaps_truncated: false,
    quality: "fresh",
  },
  freshness: {
    state: "fresh",
    policy_version: "synthetic-1",
    reference_at: at,
    max_age_seconds: 86400,
  },
  license,
  latest_retrieval: null,
};
const series = {
  id: snapshotId,
  provider_id: snapshotId,
  license_version_id: snapshotId,
  kind: "security_price",
  provider_key: "Synthetic security",
  mapping_version: "1",
  mapping_id: snapshotId,
  instrument_id: snapshotId,
  basis: "raw_close",
  currency: "EUR",
  calendar_id: "synthetic-calendar",
  calendar_version: "1",
};
const constituentHeader = {
  id: snapshotId,
  fund_instrument_id: snapshotId,
  fund_mapping_id: snapshotId,
  fund_name: "Retained fund source",
  source_at: at,
  first_observed_at: at,
  content_digest: "b".repeat(64),
  provider_id: snapshotId,
  provider_name: "Synthetic provider",
  license,
  holding_count: 1,
  known_weight: "1",
  unresolved_weight: "0",
  cash_weight: "0",
  quality: "fresh",
  confidence: "1",
  freshness: sourceHeader.freshness,
  freshness_evaluated_at: at,
};
const kinds = ["price", "fx", "benchmark", "composite", "xray"] as const;
type Kind = (typeof kinds)[number];
type Search = Record<string, string | string[] | undefined>;

function scopedQuery(kind: Kind, account: AccountParameter = first.id): Search {
  return { account, ...(kind === "xray" ? { run: runId } : {}) };
}
async function page(kind: Kind, query: Search) {
  if (kind === "xray")
    return XraySourcePage({
      params: Promise.resolve({ snapshotId }),
      searchParams: Promise.resolve(query),
    });
  if (kind === "composite") {
    // Exercise the real early composite-return branch with a stubbed presentation leaf.
    mocks.benchmarkHeader.mockResolvedValue({ data: { inputs: [] } });
    mocks.benchmarkRows.mockResolvedValue({
      data: {
        kind: "composite",
        items: [],
        total: 0,
        limit: 25,
        next_cursor: null,
      },
    });
  }
  return SourceSnapshotPage({
    params: Promise.resolve({
      kind: kind === "composite" ? "benchmark" : kind,
      snapshotId,
    }),
    searchParams: Promise.resolve(query),
  });
}
function tree(content: ReactNode, accounts = [first, second]) {
  return (
    <AccountProvider accounts={accounts} preferred={first.id}>
      {content}
    </AccountProvider>
  );
}
function marker(kind: Kind) {
  return kind === "xray"
    ? "Retained fund source"
    : kind === "composite"
      ? "Retained composite evidence"
      : "Retained source attribution";
}
function headerCall(kind: Kind) {
  return kind === "xray"
    ? mocks.constituentHeader
    : kind === "price"
      ? mocks.priceHeader
      : kind === "fx"
        ? mocks.fxHeader
        : mocks.benchmarkHeader;
}
function rowsCall(kind: Kind) {
  return kind === "xray"
    ? mocks.holdings
    : kind === "price"
      ? mocks.priceRows
      : kind === "fx"
        ? mocks.fxRows
        : mocks.benchmarkRows;
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.query = "";
  mocks.pathname = "/sources";
  mocks.selectedAccount.mockImplementation(
    async (requested: AccountParameter) =>
      resolveAccountSelection([first, second], requested, first.id),
  );
  mocks.priceHeader.mockResolvedValue({ data: { ...sourceHeader, series } });
  mocks.fxHeader.mockResolvedValue({
    data: {
      ...sourceHeader,
      calendar_id: "synthetic-calendar",
      calendar_version: "1",
    },
  });
  mocks.benchmarkHeader.mockResolvedValue({
    data: {
      ...sourceHeader,
      kind: "provider_series",
      benchmark_version_id: null,
      series: {
        ...series,
        kind: "benchmark_level",
        instrument_id: null,
        mapping_id: null,
      },
    },
  });
  for (const operation of [mocks.priceRows, mocks.fxRows, mocks.benchmarkRows])
    operation.mockResolvedValue({
      data: { items: [], total: 26, limit: 25, next_cursor: "next_page" },
    });
  mocks.constituentHeader.mockResolvedValue({ data: constituentHeader });
  mocks.holdings.mockResolvedValue({
    data: { items: [], total: 26, limit: 25, next_cursor: "next_page" },
  });
  mocks.sources.mockResolvedValue({
    sources: {
      get_price_snapshot: mocks.priceHeader,
      get_fx_snapshot: mocks.fxHeader,
      get_benchmark_snapshot: mocks.benchmarkHeader,
      list_price_observations: mocks.priceRows,
      list_fx_observations: mocks.fxRows,
      list_benchmark_observations: mocks.benchmarkRows,
    },
  });
  mocks.xray.mockResolvedValue({
    xray: {
      get_constituent_snapshot: mocks.constituentHeader,
      list_constituent_holdings: mocks.holdings,
    },
  });
});

describe.each(kinds)("%s source account boundary", (kind) => {
  it.each([
    ["malformed", "not-an-account"],
    ["empty", ""],
    ["foreign", foreign],
    ["duplicate", [first.id, second.id]],
  ] as const)(
    "rejects an explicit %s account before any source read",
    async (_label, account) => {
      // Keep a preferred first account available so fallback would disclose real fixture content.
      const requested = typeof account === "string" ? account : [...account];
      render(tree(await page(kind, scopedQuery(kind, requested))));
      expect(mocks.selectedAccount).toHaveBeenCalledWith(requested);
      expect(screen.getByText("Account unavailable")).toBeVisible();
      expect(mocks.sources).not.toHaveBeenCalled();
      expect(mocks.xray).not.toHaveBeenCalled();
      expect(screen.queryByText(marker(kind))).not.toBeInTheDocument();
    },
  );

  it("forwards the exact authorized account to both source reads", async () => {
    mocks.query = "account=" + second.id;
    render(
      tree(
        await page(kind, {
          ...scopedQuery(kind, second.id),
          cursor: "incoming_page",
        }),
      ),
    );
    expect(mocks.selectedAccount).toHaveBeenCalledWith(second.id);
    const scope = {
      account_id: second.id,
      ...(kind === "xray" ? { run_id: runId } : {}),
    };
    expect(headerCall(kind)).toHaveBeenCalledWith(snapshotId, scope);
    expect(rowsCall(kind)).toHaveBeenCalledWith(snapshotId, {
      ...scope,
      cursor: "incoming_page",
      limit: 25,
    });
    expect(screen.getByText(marker(kind))).toBeVisible();
    expect(screen.queryByText("Owner-wide source")).not.toBeInTheDocument();
  });

  it("masks retained details under a changed heading and a late other-account result", async () => {
    mocks.query = "account=" + first.id;
    const retained = await page(kind, scopedQuery(kind));
    const view = render(tree(retained));
    expect(screen.getByText(marker(kind))).toBeVisible();
    mocks.query = "account=" + second.id;
    view.rerender(tree(retained));
    expect(screen.queryByText(marker(kind))).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(
      "Loading the selected portfolio",
    );
    const lateSecond = await page(kind, scopedQuery(kind, second.id));
    mocks.query = "account=" + first.id;
    view.rerender(tree(lateSecond));
    expect(screen.queryByText(marker(kind))).not.toBeInTheDocument();
    view.rerender(tree(retained));
    expect(screen.getByText(marker(kind))).toBeVisible();
  });

  it("keeps an absent account owner-wide even with a configured preferred account", async () => {
    mocks.selectedAccount.mockRejectedValue(
      new Error("An owner-wide read must not request portfolio grants."),
    );
    render(tree(await page(kind, {})));
    expect(mocks.selectedAccount).not.toHaveBeenCalled();
    expect(headerCall(kind)).toHaveBeenCalledWith(snapshotId, {});
    const options = rowsCall(kind).mock.calls[0][1];
    expect(Object.hasOwn(options, "account_id")).toBe(false);
    expect(Object.hasOwn(options, "run_id")).toBe(false);
    expect(screen.getByText("Owner-wide source")).toBeVisible();
    expect(screen.getByText(marker(kind))).toBeVisible();
    if (kind !== "composite") {
      const next = screen.getByRole("link", {
        name: kind === "xray" ? "Next holdings" : "Next page",
      });
      const query = new URL(
        next.getAttribute("href")!,
        "https://portfolio.example",
      ).searchParams;
      expect(query.has("account")).toBe(false);
      expect(query.has("run")).toBe(false);
      expect(query.get("cursor")).toBe("next_page");
    }
  });
});

it("keeps constituent owner-wide diagnostics accessible with no portfolio accounts", async () => {
  mocks.selectedAccount.mockRejectedValue(new Error("No portfolio grant"));
  render(tree(await page("xray", {}), []));
  expect(screen.getByText("Owner-wide source")).toBeVisible();
  expect(screen.getByText("Retained fund source")).toBeVisible();
  expect(mocks.selectedAccount).not.toHaveBeenCalled();
});

it.each([
  { account: first.id },
  { run: runId },
  { account: first.id, run: [runId, runId] },
  { account: first.id, run: runId, unexpected: "canary" },
])(
  "rejects incomplete or ambiguous X-ray source scope before source dispatch",
  async (query) => {
    render(tree(await page("xray", query)));
    expect(screen.getByText("Invalid source selection")).toBeVisible();
    expect(mocks.xray).not.toHaveBeenCalled();
  },
);

it("keeps both account and retained run on constituent pagination", async () => {
  mocks.query = "account=" + first.id;
  render(
    tree(
      await page("xray", { ...scopedQuery("xray"), cursor: "incoming_page" }),
    ),
  );
  for (const name of ["Next holdings", "First holdings"]) {
    const link = screen.getByRole("link", { name });
    const query = new URL(
      link.getAttribute("href")!,
      "https://portfolio.example",
    ).searchParams;
    expect(query.get("account")).toBe(first.id);
    expect(query.get("run")).toBe(runId);
  }
});

it.each(["fx", "xray"] as const)(
  "masks a retained %s source error after an account switch",
  async (kind) => {
    const error =
      kind === "xray"
        ? new XrayApiError(
            "ACCESS_DENIED",
            403,
            "Prior scoped source is unavailable",
          )
        : new SourceApiError(
            "ACCESS_DENIED",
            403,
            "Prior scoped source is unavailable",
          );
    headerCall(kind).mockRejectedValue(error);
    mocks.query = "account=" + first.id;
    const retained = await page(kind, scopedQuery(kind));
    const view = render(tree(retained));
    expect(
      screen.getByText("Prior scoped source is unavailable"),
    ).toBeVisible();
    mocks.query = "account=" + second.id;
    view.rerender(tree(retained));
    expect(
      screen.queryByText("Prior scoped source is unavailable"),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(
      "Loading the selected portfolio",
    );
  },
);
