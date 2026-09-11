import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  SourceApiError,
  type Account,
  type BenchmarkDefinitionDetail,
} from "@trading212/api-contracts";
import BenchmarkPage from "../app/(portfolio)/sources/benchmarks/[definitionId]/page";
import { AccountProvider } from "../components/account-context";
import {
  resolveAccountSelection,
  type AccountParameter,
} from "../lib/account-selection";
import { getDemoPortfolio } from "../lib/demo-data";

const mocks = vi.hoisted(() => ({
  clients: vi.fn(),
  accounts: vi.fn(),
  detail: vi.fn(),
  market: vi.fn(),
  benchmark: vi.fn(),
  query: "",
}));
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(mocks.query),
  usePathname: () => "/sources/benchmarks/40000000-0000-4000-8000-000000000001",
  useRouter: () => ({ push: vi.fn() }),
  notFound: () => {
    throw new Error("not found");
  },
}));
// Match the existing page tests' server-only boundary stub. Account validation
// still uses the actual strict resolver; only valid resource IDs use this helper.
vi.mock("../lib/planning-selection", () => ({
  planningUuid: (value: string | string[] | undefined) =>
    typeof value === "string" ? value : undefined,
  planningHref: (path: string, values: Record<string, string | undefined>) => {
    const query = new URLSearchParams();
    for (const [key, value] of Object.entries(values)) {
      if (value) query.set(key, value);
    }
    return query.size ? path + "?" + query.toString() : path;
  },
}));
vi.mock("../lib/api-adapter", () => ({
  loadSelectedAccount: async (requested?: AccountParameter) =>
    resolveAccountSelection(
      await mocks.accounts(),
      requested,
      process.env.T212PI_ACCOUNT_ID,
    ),
}));
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
// Command behavior is covered by benchmark-form.test.tsx; this suite checks route access.
vi.mock("../components/benchmark-form", () => ({
  BenchmarkForm: () => <section aria-label="Benchmark editor" />,
}));

const id = "40000000-0000-4000-8000-000000000001";
const at = "2026-08-31T12:00:00Z";
const first = {
  ...getDemoPortfolio().summary.account,
  id: "40000000-0000-4000-8000-000000000002",
};
const second = { ...first, id: "40000000-0000-4000-8000-000000000003" };
const version: NonNullable<BenchmarkDefinitionDetail["selected_version"]> = {
  id,
  definition_id: id,
  version_number: 1,
  content: {
    reporting_currency: "EUR",
    effective_at: at,
    return_basis: "total_return",
    calendar_id: "synthetic-weekdays",
    calendar_version: "2026-08-v1",
    rebalance_rule: "buy_and_hold",
    components: [{ source_id: id, weight: "1" }],
  },
  content_digest: "a".repeat(64),
  published_at: at,
  normalization_adjustments: [],
};
const detail: BenchmarkDefinitionDetail = {
  definition: {
    id,
    name: "Owned benchmark",
    reporting_currency: "EUR",
    revision: 1,
    revision_etag: '"' + id + ':1"',
    state: "active",
    created_at: at,
    updated_at: at,
    latest_version_id: id,
    version_count: 1,
  },
  selected_version: version,
  versions: {
    items: [version],
    total: 26,
    limit: 25,
    next_cursor: "signed_next",
  },
};
function tree(
  content: ReactNode,
  accounts: readonly Account[] = [first, second],
) {
  return <AccountProvider accounts={accounts}>{content}</AccountProvider>;
}
async function page(account?: AccountParameter) {
  return BenchmarkPage({
    params: Promise.resolve({ definitionId: id }),
    searchParams: Promise.resolve({
      ...(account === undefined ? {} : { account }),
      version: id,
      cursor: "incoming_page",
    }),
  });
}

describe("benchmark detail account boundary", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.query = "";
    mocks.accounts.mockResolvedValue([first, second]);
    mocks.detail.mockResolvedValue({ data: detail });
    const catalog = {
      data: {
        providers: [],
        series: { items: [], total: 0, limit: 100, next_cursor: null },
      },
    };
    mocks.market.mockResolvedValue(catalog);
    mocks.benchmark.mockResolvedValue(catalog);
    mocks.clients.mockResolvedValue({
      portfolio: { listAccounts: mocks.accounts },
      sources: {
        get_benchmark_definition: mocks.detail,
        get_market_source_status: mocks.market,
        get_benchmark_source_status: mocks.benchmark,
      },
    });
  });

  it("opens the owner-wide benchmark when no portfolio accounts exist", async () => {
    mocks.accounts.mockResolvedValue([]);
    render(tree(await page(), []));
    expect(
      screen.getByRole("heading", { name: "Owned benchmark" }),
    ).toBeVisible();
    expect(
      screen.getByRole("heading", { name: "Published versions" }),
    ).toBeVisible();
    expect(
      screen.getByRole("table", { name: "Benchmark composition" }),
    ).toHaveTextContent("1");
    expect(
      screen.getByRole("region", { name: "Benchmark editor" }),
    ).toBeVisible();
    expect(
      screen.getByText("Owner-wide benchmark", { exact: true }),
    ).toBeVisible();
    expect(mocks.market).not.toHaveBeenCalled();
    expect(mocks.benchmark).not.toHaveBeenCalled();
    expect(mocks.detail).toHaveBeenCalledWith(id, {
      limit: 25,
      cursor: "incoming_page",
      selected_version_id: id,
    });
    for (const name of ["Version 1", "Next page", "Back to benchmarks"]) {
      const href = screen.getByRole("link", { name }).getAttribute("href")!;
      expect(
        new URL(href, "https://portfolio.example").searchParams.has("account"),
      ).toBe(false);
    }
  });

  it("does not request portfolio grants for an absent account", async () => {
    mocks.accounts.mockRejectedValue(
      new Error("Portfolio access is unavailable"),
    );
    render(tree(await page()));
    expect(
      screen.getByRole("heading", { name: "Owned benchmark" }),
    ).toBeVisible();
    expect(mocks.accounts).not.toHaveBeenCalled();
    expect(mocks.market).not.toHaveBeenCalled();
    expect(mocks.benchmark).not.toHaveBeenCalled();
  });

  it.each([
    { requested: "" },
    { requested: "not-an-account" },
    { requested: [first.id, first.id] },
    { requested: "40000000-0000-4000-8000-000000000004" },
  ])(
    "rejects an explicitly invalid account before reading the definition: %j",
    async ({ requested }) => {
      render(tree(await page(requested)));
      expect(screen.getByText("Account unavailable")).toBeVisible();
      expect(mocks.detail).not.toHaveBeenCalled();
      expect(mocks.market).not.toHaveBeenCalled();
      expect(mocks.benchmark).not.toHaveBeenCalled();
      expect(
        screen.queryByRole("region", { name: "Benchmark editor" }),
      ).not.toBeInTheDocument();
    },
  );

  it("retains the selected account on catalog reads, versions and pagination", async () => {
    mocks.query = "account=" + first.id;
    render(tree(await page(first.id)));
    expect(
      screen.getByRole("heading", { name: "Owned benchmark" }),
    ).toBeVisible();
    expect(mocks.market).toHaveBeenCalledWith(first.id, { limit: 100 });
    expect(mocks.benchmark).toHaveBeenCalledWith(first.id, { limit: 100 });
    for (const name of ["Version 1", "Next page", "Back to benchmarks"]) {
      const href = screen.getByRole("link", { name }).getAttribute("href")!;
      expect(
        new URL(href, "https://portfolio.example").searchParams.get("account"),
      ).toBe(first.id);
    }
  });

  it.each(["detail", "error"] as const)(
    "masks a retained scoped %s after an account switch",
    async (kind) => {
      if (kind === "error")
        mocks.detail.mockRejectedValue(
          new SourceApiError(
            "ACCESS_DENIED",
            403,
            "Prior scoped benchmark is unavailable",
          ),
        );
      mocks.query = "account=" + first.id;
      const retained = await page(first.id);
      const view = render(tree(retained));
      const marker =
        kind === "detail"
          ? "Owned benchmark"
          : "Prior scoped benchmark is unavailable";
      expect(screen.getByText(marker, { exact: true })).toBeVisible();
      mocks.query = "account=" + second.id;
      view.rerender(tree(retained));
      expect(
        screen.queryByText(marker, { exact: true }),
      ).not.toBeInTheDocument();
      expect(screen.getByRole("status")).toHaveTextContent(
        "Loading the selected portfolio",
      );
    },
  );
});
