import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type {
  SourceSeries,
  BenchmarkDefinitionDetail,
} from "@trading212/api-contracts";
import { BenchmarkForm } from "../components/benchmark-form";

const mocks = vi.hoisted(() => ({
  command: vi.fn(),
  push: vi.fn(),
  refresh: vi.fn(),
}));
vi.mock("../lib/source-actions", () => ({
  submitBenchmarkCommand: mocks.command,
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mocks.push, refresh: mocks.refresh }),
}));
const id = "40000000-0000-4000-8000-000000000001";
const source: SourceSeries = {
  id,
  provider_id: id,
  license_version_id: id,
  kind: "benchmark_level",
  provider_key: "Synthetic index",
  mapping_version: "1",
  basis: "total_return",
  currency: "EUR",
  calendar_id: "synthetic-weekdays",
  calendar_version: "2026-08-v1",
};
const at = "2026-08-31T12:00:00Z";
const content = {
  reporting_currency: "EUR",
  effective_at: at,
  return_basis: "total_return" as const,
  calendar_id: source.calendar_id,
  calendar_version: source.calendar_version,
  rebalance_rule: "buy_and_hold" as const,
  components: [{ source_id: id, weight: "1" }],
};
const initial: BenchmarkDefinitionDetail = {
  definition: {
    id,
    name: "Retained benchmark",
    reporting_currency: "EUR",
    revision: 2,
    revision_etag: `"${id}:2"`,
    state: "active",
    created_at: at,
    updated_at: at,
    latest_version_id: id,
    version_count: 1,
  },
  selected_version: {
    id,
    definition_id: id,
    version_number: 1,
    content,
    content_digest: "a".repeat(64),
    published_at: at,
    normalization_adjustments: [],
  },
  versions: { items: [], total: 1, limit: 25, next_cursor: null },
};

describe("benchmark version editing", () => {
  beforeEach(() => {
    mocks.command.mockReset();
    mocks.push.mockReset();
    mocks.refresh.mockReset();
  });
  it("keeps exact weights and retry identity when a command fails", async () => {
    const user = userEvent.setup();
    mocks.command.mockRejectedValue(new Error("private-source-error-canary"));
    render(<BenchmarkForm sources={[source]} effectiveAt={at} />);
    await user.type(
      screen.getByRole("textbox", { name: "Name" }),
      "Exact benchmark",
    );
    const weight = screen.getByRole("textbox", { name: "Weight 1" });
    await user.clear(weight);
    await user.type(weight, "0.999999999999999999");
    await user.click(screen.getByRole("button", { name: "Create benchmark" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Your inputs are preserved",
    );
    await user.click(screen.getByRole("button", { name: "Create benchmark" }));
    expect(mocks.command.mock.calls[0][0].idempotency_key).toBe(
      mocks.command.mock.calls[1][0].idempotency_key,
    );
    expect(
      mocks.command.mock.calls[1][0].body.content.components[0].weight,
    ).toBe("0.999999999999999999");
    expect(weight).toHaveValue("0.999999999999999999");
    expect(document.documentElement.outerHTML).not.toContain(
      "private-source-error-canary",
    );
    expect(mocks.refresh).not.toHaveBeenCalled();
  });
  it("publishes a new immutable version using the retained aggregate token", async () => {
    const user = userEvent.setup();
    mocks.command.mockResolvedValue({
      ok: false,
      code: "REVISION_MISMATCH",
      message: "The benchmark changed.",
    });
    render(
      <BenchmarkForm sources={[source]} effectiveAt={at} initial={initial} />,
    );
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Rebalancing convention" }),
      "daily_rebalanced",
    );
    await user.click(
      screen.getByRole("button", { name: "Publish benchmark version" }),
    );
    expect(mocks.command).toHaveBeenCalledWith(
      expect.objectContaining({
        kind: "version",
        definition_id: id,
        if_match: `"${id}:2"`,
        body: expect.objectContaining({
          content: expect.objectContaining({
            rebalance_rule: "daily_rebalanced",
          }),
        }),
      }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Copy your unsaved inputs",
    );
    expect(
      screen.getByRole("combobox", { name: "Rebalancing convention" }),
    ).toHaveValue("daily_rebalanced");
  });
  it("supports source insertion/removal and explicit normalization consent", async () => {
    const user = userEvent.setup();
    mocks.command.mockResolvedValue({
      ok: false,
      code: "VALIDATION_FAILED",
      message: "Invalid weights",
    });
    render(<BenchmarkForm sources={[source]} effectiveAt={at} />);
    await user.click(screen.getByRole("button", { name: "Add source" }));
    expect(screen.getByRole("textbox", { name: "Weight 2" })).toHaveValue("0");
    await user.click(screen.getByRole("button", { name: "Remove source 2" }));
    await user.type(
      screen.getByRole("textbox", { name: "Name" }),
      "Explicit normalization",
    );
    await user.click(screen.getByRole("checkbox"));
    await user.click(screen.getByRole("button", { name: "Create benchmark" }));
    expect(mocks.command.mock.calls[0][0].body.normalize).toBe(true);
  });
  it("uses the available source basis when total return is unavailable", () => {
    render(
      <BenchmarkForm
        sources={[{ ...source, basis: "split_adjusted" }]}
        effectiveAt={at}
      />,
    );
    expect(screen.getByRole("combobox", { name: "Return basis" })).toHaveValue(
      "split_adjusted",
    );
  });
  it("keeps archived definition history visible and disables further publication", () => {
    render(
      <BenchmarkForm
        sources={[source]}
        effectiveAt={at}
        initial={{
          ...initial,
          definition: { ...initial.definition, state: "archived" },
        }}
      />,
    );
    expect(screen.getByText(/History remains available/)).toBeVisible();
    expect(
      screen.queryByRole("button", { name: "Publish benchmark version" }),
    ).not.toBeInTheDocument();
  });
  it("preserves the selected account when opening an accepted version", async () => {
    const user = userEvent.setup();
    const accountId = "40000000-0000-4000-8000-000000000009";
    mocks.command.mockResolvedValue({ ok: true, value: initial });
    render(
      <BenchmarkForm
        sources={[source]}
        effectiveAt={at}
        initial={initial}
        accountId={accountId}
      />,
    );
    await user.click(
      screen.getByRole("button", { name: "Publish benchmark version" }),
    );
    expect(mocks.push).toHaveBeenCalledWith(
      `/sources/benchmarks/${id}?account=${accountId}&version=${id}`,
    );
    expect(mocks.refresh).toHaveBeenCalledOnce();
  });
});
