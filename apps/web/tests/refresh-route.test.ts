import { beforeEach, describe, expect, it, vi } from "vitest";
import { demoRefreshRun } from "../lib/demo-data";

const mocks = vi.hoisted(() => ({
  access: vi.fn(),
  sameOrigin: vi.fn(),
  request: vi.fn(),
  getRun: vi.fn(),
}));
vi.mock("../lib/auth", () => ({ getWebAccess: mocks.access }));
vi.mock("../lib/runtime", () => ({ assertSameOrigin: mocks.sameOrigin }));
vi.mock("../lib/api-adapter", () => ({
  requestRefresh: mocks.request,
  loadRefreshRun: mocks.getRun,
}));
import { GET, POST } from "../app/api/refresh/route";

const account = demoRefreshRun.account_id;
const run = demoRefreshRun.id;
const url = (query: string) => "http://localhost/api/refresh?" + query;

describe("fixed account and synchronization status boundary", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    mocks.access.mockResolvedValue({ userId: "synthetic-session" });
    mocks.request.mockResolvedValue(demoRefreshRun);
    mocks.getRun.mockResolvedValue(demoRefreshRun);
  });

  it.each([
    ["POST", ""],
    ["POST", "account=invalid"],
    ["POST", "account=" + account + "&account=" + account],
    ["POST", "account=" + account + "&path=/secrets"],
    ["GET", "account=" + account],
    ["GET", "account=" + account + "&run=invalid"],
    ["GET", "account=" + account + "&run=" + run + "&run=" + run],
    [
      "GET",
      "account=" + account + "&run=" + run + "&url=https://invalid.example",
    ],
  ])(
    "rejects malformed %s selections before adapter dispatch",
    async (method, query) => {
      const response = await (method === "POST" ? POST : GET)(
        new Request(url(query), { method }),
      );
      expect(response.status).toBe(400);
      expect(response.headers.get("cache-control")).toBe("private, no-store");
      expect(mocks.request).not.toHaveBeenCalled();
      expect(mocks.getRun).not.toHaveBeenCalled();
    },
  );

  it("requires authentication for both fixed operations", async () => {
    mocks.access.mockResolvedValue(null);
    for (const [method, handler, query] of [
      ["POST", POST, "account=" + account],
      ["GET", GET, "account=" + account + "&run=" + run],
    ] as const) {
      const response = await handler(new Request(url(query), { method }));
      expect(response.status).toBe(401);
      expect(response.headers.get("cache-control")).toBe("private, no-store");
    }
    expect(mocks.request).not.toHaveBeenCalled();
    expect(mocks.getRun).not.toHaveBeenCalled();
  });

  it("enforces same origin before a synchronization command", async () => {
    mocks.sameOrigin.mockImplementation(() => {
      throw new Error("private-origin-canary");
    });
    const response = await POST(
      new Request(url("account=" + account), { method: "POST" }),
    );
    expect(response.status).toBe(503);
    expect(await response.text()).not.toContain("private-origin-canary");
    expect(mocks.request).not.toHaveBeenCalled();
  });

  it("gets only the selected durable run and never queues a replacement", async () => {
    const response = await GET(
      new Request(url("account=" + account + "&run=" + run)),
    );
    expect(response.status).toBe(200);
    expect(mocks.getRun).toHaveBeenCalledExactlyOnceWith(account, run);
    expect(mocks.request).not.toHaveBeenCalled();
    expect(await response.json()).toEqual(demoRefreshRun);
    expect(response.headers.get("cache-control")).toBe("private, no-store");
  });

  it.each([
    { ...demoRefreshRun, account_id: "ab402b97-943c-4b95-94c6-b5eb6f2e6dc1" },
    { ...demoRefreshRun, id: "ab402b97-943c-4b95-94c6-b5eb6f2e6dc1" },
    { error: "private-refresh-payload-canary" },
  ])("rejects a response outside the requested run identity", async (body) => {
    mocks.getRun.mockResolvedValue(body);
    const response = await GET(
      new Request(url("account=" + account + "&run=" + run)),
    );
    expect(response.status).toBe(503);
    expect(await response.text()).toBe(
      JSON.stringify({
        error: "The synchronization status could not be confirmed.",
      }),
    );
  });
});
