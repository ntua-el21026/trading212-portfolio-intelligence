import { render as renderView, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { AccountProvider } from "../components/account-context";
import {
  resolveAccountSelection,
  type AccountParameter,
} from "../lib/account-selection";
import { getDemoPortfolio } from "../lib/demo-data";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  SourceApiError,
  type BenchmarkDefinitionSummary,
  type FxSnapshotHeader,
  type PriceSnapshotHeader,
  type BenchmarkSnapshotHeader,
} from "@trading212/api-contracts";
import SourcesPage from "../app/(portfolio)/sources/page";
import SourceSnapshotPage from "../app/(portfolio)/sources/snapshots/[kind]/[snapshotId]/page";

const mocks = vi.hoisted(() => ({
  clients: vi.fn(),
  accounts: vi.fn(),
  market: vi.fn(),
  benchmark: vi.fn(),
  fx: vi.fn(),
  definitions: vi.fn(),
  priceHeader: vi.fn(),
  fxHeader: vi.fn(),
  benchmarkHeader: vi.fn(),
  observations: vi.fn(),
  access: vi.fn(),
}));
// Next's server-only boundary is unavailable in jsdom; retain its typed-result
// contract while exercising the actual server page render and navigation.
vi.mock("../lib/source-adapter", async () => {
  const { SourceApiError } = await import("@trading212/api-contracts");
  return {
    sourceClients: mocks.clients,
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
vi.mock("../lib/auth", () => ({ requireWebAccess: mocks.access }));
vi.mock("../lib/api-adapter", () => ({
  loadSelectedAccount: async (requested?: AccountParameter) =>
    resolveAccountSelection(await mocks.accounts(), requested),
}));
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/sources",
  useRouter: () => ({ push: vi.fn() }),
  notFound: () => {
    throw new Error("Not found");
  },
}));
vi.mock("../lib/planning-selection", () => ({
  planningUuid: (value: string | string[] | undefined) =>
    Array.isArray(value) ? value[0] : value,
  planningHref: (path: string, values: Record<string, string | undefined>) => {
    const query = new URLSearchParams();
    for (const [key, value] of Object.entries(values)) {
      if (value) query.set(key, value);
    }
    return query.size ? `${path}?${query}` : path;
  },
}));
vi.mock("../components/benchmark-form", () => ({
  BenchmarkForm: () => <div aria-label="Benchmark editor" />,
}));

const id = "40000000-0000-4000-8000-000000000001";
const at = "2026-08-31T12:00:00Z";
const account = {
  ...getDemoPortfolio().summary.account,
  id,
  display_name: "Owned account",
  reporting_currency: "EUR",
};
function render(content: ReactNode) {
  return renderView(
    <AccountProvider accounts={[account]}>{content}</AccountProvider>,
  );
}
const definition: BenchmarkDefinitionSummary = {
  id,
  name: "Owned benchmark",
  reporting_currency: "EUR",
  revision: 1,
  revision_etag: `"${id}:1"`,
  state: "active",
  created_at: at,
  updated_at: at,
  latest_version_id: id,
  version_count: 1,
};
const fxHeader: FxSnapshotHeader = {
  id,
  calendar_id: "synthetic-fx-calendar",
  calendar_version: "2026-08-fx-v3",
  period: { start: "2026-08-03", end: "2026-08-28" },
  content_digest: "a".repeat(64),
  coverage: {
    expected_count: 20,
    available_count: 20,
    gap_count: 0,
    gaps: [],
    gaps_truncated: false,
    quality: "fresh",
  },
  freshness: {
    state: "stale",
    policy_version: "synthetic-reference-freshness-1",
    reference_at: at,
    max_age_seconds: 604800,
  },
  provenance: {
    provider_id: id,
    license_version_id: id,
    adapter_version: "replay-1",
    schema_version: "source-1",
    source_revision: "first",
    revision_order: "1",
    effective_at: at,
    first_observed_at: at,
    synthetic: true,
  },
  license: {
    id,
    provider_id: id,
    version: "1",
    effective_at: at,
    attribution: "Synthetic test data",
    evidence_key: "synthetic-test-license",
    retention_days: 3650,
    store: "allowed",
    display: "allowed",
    report: "allowed",
    export: "allowed",
  },
  latest_retrieval: null,
};
const {
  calendar_id: calendarId,
  calendar_version: calendarVersion,
  ...commonHeader
} = fxHeader;
const priceHeader: PriceSnapshotHeader = {
  ...commonHeader,
  series: {
    id,
    provider_id: id,
    license_version_id: id,
    kind: "security_price",
    provider_key: "Synthetic holding",
    mapping_version: "1",
    mapping_id: id,
    instrument_id: id,
    basis: "raw_close",
    currency: "EUR",
    calendar_id: `${calendarId}-price`,
    calendar_version: `${calendarVersion}-price`,
  },
};
const benchmarkHeader: BenchmarkSnapshotHeader = {
  ...commonHeader,
  kind: "provider_series",
  benchmark_version_id: null,
  series: {
    ...priceHeader.series,
    kind: "benchmark_level",
    mapping_id: null,
    instrument_id: null,
    calendar_id: `${calendarId}-benchmark`,
    calendar_version: `${calendarVersion}-benchmark`,
  },
};

describe("source pages use authorized source results", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.access.mockResolvedValue({ isDemo: false });
    mocks.accounts.mockResolvedValue([account]);
    mocks.market.mockResolvedValue({
      data: {
        providers: [],
        series: { items: [], total: 0, limit: 25, next_cursor: null },
      },
    });
    mocks.benchmark.mockResolvedValue({
      data: {
        providers: [],
        series: { items: [], total: 0, limit: 25, next_cursor: null },
      },
    });
    mocks.fx.mockResolvedValue({
      data: {
        providers: [],
        pairs: { items: [], total: 0, limit: 25, next_cursor: null },
      },
    });
    mocks.definitions.mockResolvedValue({
      data: {
        items: [definition],
        total: 26,
        limit: 25,
        next_cursor: "signed_next",
      },
    });
    mocks.priceHeader.mockResolvedValue({ data: priceHeader });
    mocks.fxHeader.mockResolvedValue({ data: fxHeader });
    mocks.benchmarkHeader.mockResolvedValue({ data: benchmarkHeader });
    mocks.observations.mockResolvedValue({
      data: { items: [], total: 0, limit: 25, next_cursor: null },
    });
    mocks.clients.mockResolvedValue({
      portfolio: { listAccounts: mocks.accounts },
      sources: {
        get_market_source_status: mocks.market,
        get_benchmark_source_status: mocks.benchmark,
        get_fx_source_status: mocks.fx,
        list_benchmark_definitions: mocks.definitions,
        get_price_snapshot: mocks.priceHeader,
        get_fx_snapshot: mocks.fxHeader,
        get_benchmark_snapshot: mocks.benchmarkHeader,
        list_price_observations: mocks.observations,
        list_fx_observations: mocks.observations,
        list_benchmark_observations: mocks.observations,
      },
    });
  });

  it("lists and pages owned benchmark definitions without an account or catalog requests", async () => {
    mocks.accounts.mockResolvedValue([]);
    render(
      await SourcesPage({
        searchParams: Promise.resolve({
          kind: "definitions",
          search: "Owned",
          state: "all",
        }),
      }),
    );
    expect(
      screen.getByRole("link", { name: "Owned benchmark" }),
    ).toHaveAttribute("href", `/sources/benchmarks/${id}`);
    expect(screen.getByLabelText("Benchmark editor")).toBeVisible();
    expect(screen.getByRole("combobox", { name: "Account" })).toBeDisabled();
    const next = new URL(
      screen.getByRole("link", { name: "Next page" }).getAttribute("href")!,
      "https://portfolio.example",
    );
    expect(Object.fromEntries(next.searchParams)).toEqual({
      kind: "definitions",
      search: "Owned",
      basis: "all",
      state: "all",
      cursor: "signed_next",
    });
    expect(screen.getByText("Owner-wide benchmarks")).toBeVisible();
    expect(mocks.market).not.toHaveBeenCalled();
    expect(mocks.benchmark).not.toHaveBeenCalled();
    expect(mocks.definitions).toHaveBeenCalledWith({
      limit: 25,
      cursor: null,
      state: "all",
      search: "Owned",
    });
  });

  it.each(["market", "benchmark", "fx", "definitions"] as const)(
    "retains %s filters and navigation after a typed cursor failure",
    async (kind) => {
      const operation = {
        market: mocks.market,
        benchmark: mocks.benchmark,
        fx: mocks.fx,
        definitions: mocks.definitions,
      }[kind];
      operation.mockRejectedValueOnce(
        new SourceApiError(
          "CURSOR_INVALID",
          400,
          "The source page has expired.",
        ),
      );
      render(
        await SourcesPage({
          searchParams: Promise.resolve({
            account: id,
            kind,
            cursor: "expired_page",
            search: "Retained search",
            basis: "raw_close",
            state: "archived",
          }),
        }),
      );
      expect(screen.getByRole("status")).toHaveTextContent(
        "The source page has expired.",
      );
      expect(
        screen.getByRole("navigation", { name: "Source categories" }),
      ).toBeVisible();
      expect(screen.getByRole("combobox", { name: "Account" })).toHaveValue(id);
      if (kind !== "fx")
        expect(
          screen.getByRole("textbox", { name: "Search sources or benchmarks" }),
        ).toHaveValue("Retained search");
      const reload = new URL(
        screen
          .getByRole("link", { name: "Reload first page with these filters" })
          .getAttribute("href")!,
        "https://portfolio.example",
      );
      expect(Object.fromEntries(reload.searchParams)).toEqual({
        account: id,
        kind,
        search: "Retained search",
        basis: "raw_close",
        state: "archived",
      });
    },
  );

  it("keeps owned definitions accessible when optional source choices fail", async () => {
    mocks.market.mockRejectedValueOnce(
      new SourceApiError(
        "PROVIDER_UNAVAILABLE",
        503,
        "Source choices are temporarily unavailable.",
      ),
    );
    render(
      await SourcesPage({
        searchParams: Promise.resolve({ kind: "definitions" }),
      }),
    );
    expect(screen.getByRole("link", { name: "Owned benchmark" })).toBeVisible();
    expect(screen.getByRole("status")).toHaveTextContent(
      "Source choices are temporarily unavailable.",
    );
    expect(screen.getByLabelText("Benchmark editor")).toBeVisible();
  });

  it.each([
    ["fx", fxHeader.calendar_id, fxHeader.calendar_version],
    [
      "price",
      priceHeader.series.calendar_id,
      priceHeader.series.calendar_version,
    ],
    [
      "benchmark",
      benchmarkHeader.series.calendar_id,
      benchmarkHeader.series.calendar_version,
    ],
  ] as const)(
    "renders the retained %s calendar pins and keeps snapshot account scope",
    async (kind, expectedCalendar, expectedVersion) => {
      const user = userEvent.setup();
      render(
        await SourceSnapshotPage({
          params: Promise.resolve({ kind, snapshotId: id }),
          searchParams: Promise.resolve({ account: id }),
        }),
      );
      await user.click(screen.getByText("Reproduction details"));
      const reproduction = screen
        .getByText("Reproduction details")
        .closest("details")!;
      expect(within(reproduction).getByText(expectedCalendar)).toBeVisible();
      expect(within(reproduction).getByText(expectedVersion)).toBeVisible();
      expect(mocks.observations).toHaveBeenCalledWith(id, {
        account_id: id,
        limit: 25,
        cursor: null,
      });
      const headerOperation = {
        fx: mocks.fxHeader,
        price: mocks.priceHeader,
        benchmark: mocks.benchmarkHeader,
      }[kind];
      expect(headerOperation).toHaveBeenCalledWith(id, { account_id: id });
    },
  );
  it.each([
    { requested: "" },
    { requested: "not-an-account" },
    { requested: [id, id] },
  ])(
    "never treats an explicit invalid account as owner-wide benchmark access",
    async ({ requested }) => {
      mocks.accounts.mockResolvedValue([]);
      render(
        await SourcesPage({
          searchParams: Promise.resolve({
            kind: "definitions",
            account: requested,
          }),
        }),
      );
      expect(screen.getByText("Account unavailable")).toBeVisible();
      expect(
        screen.queryByText("Owner-wide benchmarks"),
      ).not.toBeInTheDocument();
      expect(mocks.definitions).not.toHaveBeenCalled();
      expect(mocks.market).not.toHaveBeenCalled();
      expect(mocks.benchmark).not.toHaveBeenCalled();
    },
  );
});
