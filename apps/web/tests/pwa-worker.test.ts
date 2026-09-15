// @vitest-environment node
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import { describe, expect, it, vi } from "vitest";

const origin = "https://portfolio.example";
const source = readFileSync(
  new URL("../public/sw.js", import.meta.url),
  "utf8",
);
type WorkerEvent = {
  request?: Request;
  waitUntil?: (work: Promise<unknown>) => void;
  respondWith?: (response: Promise<Response>) => void;
};
function harness() {
  const events = new Map<string, (event: WorkerEvent) => void>();
  const storage = new Map<string, Map<string, Response>>();
  storage.set("unrelated-app-private", new Map());
  storage.set("t212pi-public-shell-old", new Map());
  const network = vi.fn(async (request: Request): Promise<Response> => {
    const path = new URL(request.url).pathname;
    const mime = path.endsWith(".html")
      ? "text/html"
      : path.endsWith(".css")
        ? "text/css"
        : "image/png";
    return new Response(
      path.endsWith(".html") ? "Public offline unavailability" : "public asset",
      {
        headers: { "Content-Type": mime },
      },
    );
  });
  const claim = vi.fn(async () => {});
  runInNewContext(source, {
    Request,
    Response,
    URL,
    Map,
    Promise,
    Error,
    self: {
      location: { origin },
      clients: { claim },
      skipWaiting: async () => {},
      addEventListener: (
        name: string,
        listener: (event: WorkerEvent) => void,
      ) => events.set(name, listener),
    },
    fetch: network,
    caches: {
      keys: async () => [...storage.keys()],
      delete: async (name: string) => storage.delete(name),
      open: async (name: string) => {
        if (!storage.has(name)) storage.set(name, new Map());
        const cache = storage.get(name)!;
        const key = (input: string | Request) =>
          typeof input === "string" ? new URL(input, origin).href : input.url;
        return {
          put: async (input: Request, response: Response) => {
            cache.set(key(input), response);
          },
          match: async (input: string | Request) =>
            cache.get(key(input))?.clone(),
        };
      },
    },
  });
  async function lifecycle(name: string) {
    let work: Promise<unknown> | undefined;
    events.get(name)!({
      waitUntil: (promise) => {
        work = promise;
      },
    });
    await work;
  }
  function request(path: string, mode?: "navigate", method = "GET") {
    const req = new Request(new URL(path, origin), { method });
    if (mode) Object.defineProperty(req, "mode", { value: mode });
    let response: Promise<Response> | undefined;
    events.get("fetch")!({
      request: req,
      respondWith: (value) => {
        response = value;
      },
    });
    return response;
  }
  return { storage, network, claim, lifecycle, request };
}

describe("public-only offline worker", () => {
  it("installs only five public files without credentials and deletes only obsolete owned caches", async () => {
    const h = harness();
    await h.lifecycle("install");
    await h.lifecycle("activate");
    expect(h.claim).toHaveBeenCalledOnce();
    expect(h.storage.has("unrelated-app-private")).toBe(true);
    expect(h.storage.has("t212pi-public-shell-old")).toBe(false);
    expect([...h.storage.get("t212pi-public-shell-v1")!.keys()].sort()).toEqual(
      [
        "/pwa/icon-192-v1.png",
        "/pwa/icon-512-v1.png",
        "/pwa/maskable-512-v1.png",
        "/pwa/offline-v1.css",
        "/pwa/offline-v1.html",
      ]
        .map((path) => origin + path)
        .sort(),
    );
    for (const [request] of h.network.mock.calls) {
      expect(request.credentials).toBe("omit");
      expect(request.redirect).toBe("error");
    }
  });

  it("does not store authenticated navigation and falls back to public content without API fallback", async () => {
    const h = harness();
    await h.lifecycle("install");
    h.network.mockResolvedValueOnce(
      new Response("private owner A financial canary"),
    );
    expect(
      await (await h.request("/research?account=owner-a", "navigate"))!.text(),
    ).toContain("private owner A");
    h.network.mockRejectedValueOnce(new TypeError("offline"));
    const offline = await h.request("/research?account=owner-b", "navigate");
    expect(await offline!.text()).toBe("Public offline unavailability");
    for (const path of [
      "/api/accounts/private",
      "/api/reports/private",
      "/research?_rsc=private",
      "/pwa/offline-v1.html?token=canary",
      "https://foreign.example/pwa/offline-v1.html",
    ])
      expect(h.request(path)).toBeUndefined();
    expect(
      h.request("/api/auth/local-session", undefined, "POST"),
    ).toBeUndefined();
    for (const cache of h.storage.values())
      for (const response of cache.values())
        expect(await response.clone().text()).not.toMatch(
          /private owner|canary/,
        );
  });

  it("rejects an invalid public asset before populating the new cache", async () => {
    const h = harness();
    h.network.mockResolvedValueOnce(
      new Response("private sign-in", {
        headers: { "Content-Type": "application/json" },
      }),
    );
    await expect(h.lifecycle("install")).rejects.toThrow(
      "public offline shell is unavailable",
    );
    expect(h.storage.has("t212pi-public-shell-v1")).toBe(false);
  });

  it("preserves unrelated caches and unconfirmed sign-out, then clears old shell versions after success", async () => {
    const h = harness();
    h.network.mockResolvedValueOnce(
      new Response("Revocation unconfirmed", { status: 503 }),
    );
    expect(
      (await h.request("/api/auth/sign-out", undefined, "POST"))!.status,
    ).toBe(503);
    expect(h.storage.has("t212pi-public-shell-old")).toBe(true);
    h.network.mockResolvedValueOnce(new Response("Signed out"));
    await h.request("/api/auth/sign-out", undefined, "POST");
    expect(h.storage.has("t212pi-public-shell-old")).toBe(false);
    expect(h.storage.has("unrelated-app-private")).toBe(true);
  });
});
