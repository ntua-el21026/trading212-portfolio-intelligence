import { describe, expect, it, vi } from "vitest";
import {
  PremiumProviderApiClient,
  PremiumProviderApiError,
} from "@trading212/api-contracts";
import { account, status } from "./premium-provider-fixtures";
const response = (body: unknown) =>
  new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
describe("fixed premium status client", () => {
  it("uses the sole account metadata GET and never adds acquisition commands", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(response(status));
    const client = new PremiumProviderApiClient({
      baseUrl: "https://local.test",
      fetchImpl,
    });
    const result = await client.get_premium_provider_status(account);
    expect(String(fetchImpl.mock.calls[0][0])).toBe(
      `https://local.test/api/v1/accounts/${account}/premium-providers`,
    );
    expect(fetchImpl.mock.calls[0][1].method).toBe("GET");
    expect(fetchImpl.mock.calls[0][1].body).toBeUndefined();
    expect(fetchImpl.mock.calls[0][1].cache).toBe("no-store");
    expect(result.data).toEqual(status);
  });
  it("rejects verified-live and unknown credential fields", async () => {
    const bad = structuredClone(status);
    (bad.providers[0].capabilities[0] as unknown as { state: string }).state =
      "verified_live";
    for (const body of [
      bad,
      { ...status, credential_reference: "secret-canary" },
    ]) {
      const client = new PremiumProviderApiClient({
        baseUrl: "https://local.test",
        fetchImpl: vi.fn().mockResolvedValue(response(body)),
      });
      await expect(
        client.get_premium_provider_status(account),
      ).rejects.toBeInstanceOf(PremiumProviderApiError);
    }
  });
  it("rejects invalid account syntax before dispatch and keeps errors inert", async () => {
    const fetchImpl = vi.fn();
    const client = new PremiumProviderApiClient({
      baseUrl: "https://local.test",
      fetchImpl,
    });
    await expect(
      client.get_premium_provider_status("../../private"),
    ).rejects.toMatchObject({ code: "VALIDATION_FAILED" });
    expect(fetchImpl).not.toHaveBeenCalled();
    fetchImpl.mockResolvedValue(
      new Response(
        JSON.stringify({
          error: { code: "ACCESS_DENIED", message: "secret-canary" },
        }),
        { status: 403, headers: { "Content-Type": "application/json" } },
      ),
    );
    await expect(
      client.get_premium_provider_status(account),
    ).rejects.toMatchObject({
      message: "Provider status is not available for this account.",
    });
  });
});
