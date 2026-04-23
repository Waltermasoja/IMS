// IMS Pro Service Worker — minimal static asset cache.
// Scope: install & serve static assets offline; dynamic pages always go to network.
// Sync of offline POS sales is deferred (internet assumed reliable per customer brief).

const CACHE_NAME = 'ims-pro-static-v1';
const STATIC_ASSETS = [
  '/static/css/output.css',
  '/static/js/alpine.min.js',
  '/static/css/fontawesome/all.min.css',
  '/static/manifest.json',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_ASSETS).catch(() => {}))
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);

  // Static assets: cache-first
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(
      caches.match(request).then((cached) =>
        cached ||
        fetch(request).then((resp) => {
          const copy = resp.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(request, copy));
          return resp;
        })
      )
    );
    return;
  }

  // API + HTML: network-first, no fallback (online-only for now).
});
