import { beforeEach, describe, expect, it, vi } from "vitest";

const auth = vi.hoisted(() => ({
  revokeApiSession: vi.fn(),
  revokeLocalDemoSession: vi.fn(),
}));

vi.mock("../lib/auth", () => ({
  CSRF_COOKIE: "t212pi_csrf",
  SESSION_COOKIE: "t212pi_session",
  revokeApiSession: auth.revokeApiSession,
  revokeLocalDemoSession: auth.revokeLocalDemoSession,
}));

vi.mock("../lib/runtime", () => ({
  assertSameOrigin: vi.fn(),
  isExplicitDemoMode: () => false,
}));

import { POST } from "../app/api/auth/sign-out/route";

describe("sign-out revocation boundary", () => {
  beforeEach(() => {
    auth.revokeApiSession.mockReset();
    auth.revokeLocalDemoSession.mockReset();
  });

  it("does not clear the browser session when upstream revocation is unconfirmed", async () => {
    auth.revokeApiSession.mockRejectedValueOnce(
      new Error("upstream unavailable"),
    );
    const response = await POST(
      new Request("http://localhost/api/auth/sign-out", {
        method: "POST",
        headers: {
          cookie: "t212pi_session=session-token; t212pi_csrf=csrf-token",
          origin: "http://localhost",
        },
      }),
    );

    expect(response.status).toBe(503);
    expect(response.headers.get("set-cookie")).toBeNull();
    await expect(response.json()).resolves.toEqual({
      error:
        "Server session revocation could not be confirmed. Retry sign-out.",
    });
  });
});
