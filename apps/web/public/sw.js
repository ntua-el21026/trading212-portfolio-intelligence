/* global caches, self, Request, Response, URL, fetch */
/* Only public, versioned shell assets enter CacheStorage. */
const CACHE_PREFIX = "t212pi-public-shell-";
const CACHE_NAME = `${CACHE_PREFIX}v1`;
const OFFLINE = "/pwa/offline-v1.html";
const PUBLIC_ASSETS = new Map([
  [OFFLINE, "text/html"],
  ["/pwa/offline-v1.css", "text/css"],
  ["/pwa/icon-192-v1.png", "image/png"],
  ["/pwa/icon-512-v1.png", "image/png"],
  ["/pwa/maskable-512-v1.png", "image/png"],
]);

async function removeObsoleteShells() {
  const names = await caches.keys();
  await Promise.all(
    names
      .filter((name) => name.startsWith(CACHE_PREFIX) && name !== CACHE_NAME)
      .map((name) => caches.delete(name)),
  );
}

self.addEventListener("install", (event) => {
  event.waitUntil(
    (async () => {
      // Failed or redirected fetches cannot install a partial offline shell.
      const entries = await Promise.all(
        [...PUBLIC_ASSETS].map(async ([path, mime]) => {
          const request = new Request(new URL(path, self.location.origin), {
            credentials: "omit",
            redirect: "error",
            cache: "reload",
          });
          const response = await fetch(request);
          if (
            !response.ok ||
            response.redirected ||
            response.type === "opaque" ||
            response.headers.get("content-type")?.split(";")[0].trim() !== mime
          )
            throw new Error("The public offline shell is unavailable.");
          return [request, response];
        }),
      );
      const cache = await caches.open(CACHE_NAME);
      await Promise.all(
        entries.map(([request, response]) => cache.put(request, response)),
      );
      await self.skipWaiting();
    })(),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      await removeObsoleteShells();
      await self.clients.claim();
    })(),
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (request.method === "POST" && url.pathname === "/api/auth/sign-out") {
    event.respondWith(
      (async () => {
        const response = await fetch(request);
        if (response.ok || response.type === "opaqueredirect")
          await removeObsoleteShells();
        return response;
      })(),
    );
    return;
  }
  if (request.method !== "GET") return;
  if (PUBLIC_ASSETS.has(url.pathname) && !url.search) {
    event.respondWith(
      (async () => {
        const cache = await caches.open(CACHE_NAME);
        return (await cache.match(url.href)) ?? fetch(request);
      })(),
    );
    return;
  }
  // Never cache authenticated HTML, RSC, API, reports, headers or credentials.
  // Only document navigation gets the dedicated public fallback; API errors
  // remain failures and cannot masquerade as successful financial responses.
  if (request.mode === "navigate") {
    event.respondWith(
      (async () => {
        try {
          return await fetch(request);
        } catch {
          const cache = await caches.open(CACHE_NAME);
          const shell = await cache.match(OFFLINE);
          return (
            shell ??
            new Response("Offline. Reconnect to view your portfolio.", {
              status: 503,
              headers: {
                "Content-Type": "text/plain",
                "Cache-Control": "no-store",
              },
            })
          );
        }
      })(),
    );
  }
});
