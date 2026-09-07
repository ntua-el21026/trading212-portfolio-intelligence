import { beforeEach, describe, expect, it, vi } from "vitest";
import { submitBenchmarkCommand } from "../lib/source-actions";

const mocks = vi.hoisted(() => ({
  clients: vi.fn(),
  create: vi.fn(),
  version: vi.fn(),
  archive: vi.fn(),
  revalidate: vi.fn(),
}));
vi.mock("../lib/source-adapter", () => ({
  sourceClients: mocks.clients,
  sourceData: (value: { data: unknown }) => value.data,
}));
vi.mock("next/cache", () => ({ revalidatePath: mocks.revalidate }));
const id = "40000000-0000-4000-8000-000000000001";
const content = {
  reporting_currency: "EUR",
  effective_at: "2026-08-31T12:00:00Z",
  return_basis: "total_return",
  calendar_id: "synthetic-weekdays",
  calendar_version: "2026-08-v1",
  rebalance_rule: "buy_and_hold",
  components: [{ source_id: id, weight: "0.999999999999999999" }],
};

describe("benchmark server actions", () => {
  beforeEach(() => {
    mocks.clients.mockReset().mockResolvedValue({
      sources: {
        create_benchmark_definition: mocks.create,
        create_benchmark_version: mocks.version,
        archive_benchmark_definition: mocks.archive,
      },
    });
    mocks.create.mockReset();
    mocks.version.mockReset();
    mocks.archive.mockReset();
    mocks.revalidate.mockReset();
  });
  it("authenticates before serializing or validating caller content", async () => {
    mocks.clients.mockRejectedValue(new Error("Authentication required"));
    const toJSON = vi.fn();
    await expect(submitBenchmarkCommand({ toJSON })).rejects.toThrow(
      "Authentication required",
    );
    expect(toJSON).not.toHaveBeenCalled();
    expect(mocks.create).not.toHaveBeenCalled();
  });
  it("rejects oversized or unknown fields without reflecting them", async () => {
    const value = await submitBenchmarkCommand({
      kind: "create",
      idempotency_key: "one",
      body: {
        name: "Test",
        content,
        privateCanary: "source-action-private-canary",
      },
    });
    expect(value).toMatchObject({ ok: false, code: "VALIDATION_FAILED" });
    expect(JSON.stringify(value)).not.toContain("source-action-private-canary");
    expect(
      await submitBenchmarkCommand({ value: "x".repeat(65537) }),
    ).toMatchObject({ ok: false, code: "REQUEST_TOO_LARGE" });
    expect(mocks.create).not.toHaveBeenCalled();
  });
  it("forwards exact weights, normalization consent and aggregate revision", async () => {
    const detail = { definition: { id } };
    mocks.version.mockResolvedValue({ data: detail });
    expect(
      await submitBenchmarkCommand({
        kind: "version",
        definition_id: id,
        if_match: `"${id}:7"`,
        idempotency_key: "version-one",
        body: { content, normalize: true },
      }),
    ).toEqual({ ok: true, value: detail });
    expect(mocks.version).toHaveBeenCalledWith(
      id,
      { content, normalize: true },
      { idempotencyKey: "version-one", ifMatch: `"${id}:7"` },
    );
    expect(mocks.revalidate.mock.calls).toEqual([
      ["/sources"],
      [`/sources/benchmarks/${id}`],
    ]);
  });
  it("archives through its fixed command with an empty typed body", async () => {
    mocks.archive.mockResolvedValue({ data: { definition: { id } } });
    expect(
      await submitBenchmarkCommand({
        kind: "archive",
        definition_id: id,
        if_match: `"${id}:2"`,
        idempotency_key: "archive-one",
      }),
    ).toMatchObject({ ok: true });
    expect(mocks.archive).toHaveBeenCalledWith(
      id,
      {},
      { idempotencyKey: "archive-one", ifMatch: `"${id}:2"` },
    );
  });
});
