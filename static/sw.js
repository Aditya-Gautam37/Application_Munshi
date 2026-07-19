// Munshi service worker — deliberately minimal.
// This app is a live money/ledger tool, so we do NOT cache pages or API
// responses (stale balances or invoices would be dangerous). We only cache
// static, unchanging assets (css/icons) so the app shell loads fast and the
// browser treats this as an installable PWA. Everything else always hits
// the network.
const CACHE_NAME = 'munshi-static-v1';
const STATIC_ASSETS = [
  '/static/style.css',
  '/static/jl-app.css',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_ASSETS))
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((names) =>
      Promise.all(names.filter((n) => n !== CACHE_NAME).map((n) => caches.delete(n)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);
  const isStaticAsset = STATIC_ASSETS.some((p) => url.pathname === p);
  if (!isStaticAsset) return; // let the network handle everything else (pages, API, uploads)

  event.respondWith(
    caches.match(event.request).then((cached) => cached || fetch(event.request))
  );
});
