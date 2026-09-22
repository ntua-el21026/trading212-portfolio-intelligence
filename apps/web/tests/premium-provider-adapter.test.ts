import { beforeEach, describe, expect, it, vi } from "vitest";
import { PremiumProviderApiError } from "@trading212/api-contracts";
import { account, other, status } from "./premium-provider-fixtures";
const mocks = vi.hoisted(() => ({ authorize: vi.fn(), read: vi.fn() }));
vi.mock("server-only", () => ({}));
vi.mock("../lib/target-adapter", () => ({ targetClients: mocks.authorize }));
vi.mock("@trading212/api-contracts", async (original) => {
  const actual = await original<typeof import("@trading212/api-contracts")>();
  return {
    ...actual,
    PremiumProviderApiClient: class {
      get_premium_provider_status = mocks.read;
    },
  };
});
import { loadPremiumProviderStatus } from "../lib/premium-provider-adapter";
beforeEach(() => {
  vi.clearAllMocks();
  mocks.authorize.mockResolvedValue({
    options: { baseUrl: "https://local.test" },
  });
  mocks.read.mockResolvedValue({
    data: status,
    notModified: false,
    etag: null,
  });
});
describe("account-safe provider loader", () => {
  it("reauthorizes each read without retaining a private status cache", async () => {
    expect(await loadPremiumProviderStatus(account)).toEqual({
      ok: true,
      data: status,
    });
    await loadPremiumProviderStatus(account);
    expect(mocks.authorize).toHaveBeenCalledTimes(2);
    expect(mocks.read).toHaveBeenCalledWith(account);
  });
  it("rejects mismatched accounts and 304 instead of reusing prior private metadata", async () => {
    expect(await loadPremiumProviderStatus(other)).toMatchObject({
      ok: false,
      code: "INVALID_RESPONSE",
    });
    mocks.read.mockResolvedValue({
      data: null,
      notModified: true,
      etag: '"old"',
    });
    expect(await loadPremiumProviderStatus(account)).toMatchObject({
      ok: false,
      code: "INVALID_RESPONSE",
    });
  });
  it("uses fixed errors and propagates framework redirects", async () => {
    mocks.read.mockRejectedValue(
      new PremiumProviderApiError("ACCESS_DENIED", 403, "secret-canary"),
    );
    const result = await loadPremiumProviderStatus(account);
    expect(result).toMatchObject({ ok: false, code: "ACCESS_DENIED" });
    expect(JSON.stringify(result)).not.toContain("secret-canary");
    const redirect = new Error("NEXT_REDIRECT");
    mocks.authorize.mockRejectedValue(redirect);
    await expect(loadPremiumProviderStatus(account)).rejects.toBe(redirect);
  });
});
