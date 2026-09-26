/* ============================================================
   WALL STREET CAPITAL — Service Worker
   ============================================================
   Minimal service worker. Its only real jobs:
     1. Satisfy the "installable PWA" requirement (Android needs a
        service worker with a fetch handler to fire beforeinstallprompt)
     2. Cache the app shell so the site loads instantly on repeat visits
     3. Fall back gracefully when offline

   It does NOT cache API responses or user data. Everything under
   /api/ always goes straight to the network.
   ============================================================ */

const CACHE_NAME = "wsc-shell-v1";

// The minimum set of assets needed to render the shell offline.
// Everything else is fetched on demand.
const SHELL_ASSETS = [
  "/",
  "/index.html",
  "/login.html",
  "/signup.html",
  "/dashboard.html",
  "/contact.html",
  "/privacy.html",
  "/terms.html",
  "/faq.html",
  "/status.html",
  "/css/styles.css",
  "/js/theme.js",
  "/js/api.js",
  "/images/wsc-logo.png",
  "/images/pwa/icon-192-v2.png",
  "/images/pwa/icon-512-v2.png",
  "/manifest.webmanifest"
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => cache.addAll(SHELL_ASSETS).catch(() => {}))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k))
      )
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  const url = new URL(req.url);

  // Never touch API calls, auth, or anything outside our origin
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api/")) return;
  if (url.pathname.startsWith("/uploads/")) return;

  // Only handle GET
  if (req.method !== "GET") return;

  // Network-first for HTML so users always get fresh pages
  if (req.headers.get("accept")?.includes("text/html")) {
    event.respondWith(
      fetch(req)
        .then((res) => {
          const copy = res.clone();
          caches.open(CACHE_NAME).then((c) => c.put(req, copy)).catch(() => {});
          return res;
        })
        .catch(() => caches.match(req).then((r) => r || caches.match("/index.html")))
    );
    return;
  }

  // Cache-first for static assets (css, js, images, fonts)
  event.respondWith(
    caches.match(req).then((cached) => {
      if (cached) return cached;
      return fetch(req).then((res) => {
        // Only cache successful, same-origin responses
        if (res && res.status === 200 && res.type === "basic") {
          const copy = res.clone();
          caches.open(CACHE_NAME).then((c) => c.put(req, copy)).catch(() => {});
        }
        return res;
      });
    })
  );
});