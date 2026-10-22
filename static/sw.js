/* Service worker: app code = network-first, vendor = stale-while-revalidate, card media = cache-first, API = network only. */
const SHELL = 'shell-v1';
const MEDIA = 'media-v1';
const SHELL_FILES = ['/', '/static/app.js', '/static/style.css', '/manifest.webmanifest',
  '/static/vendor/katex/katex.min.js', '/static/vendor/katex/auto-render.min.js', '/static/vendor/katex/katex.min.css'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(SHELL).then(c => c.addAll(SHELL_FILES)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => ![SHELL, MEDIA].includes(k)).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

async function staleWhileRevalidate(req, cacheName) {
  const cache = await caches.open(cacheName);
  const hit = await cache.match(req, { ignoreSearch: true });
  const net = fetch(req).then(r => { if (r.ok) cache.put(req, r.clone()); return r; }).catch(() => hit);
  return hit || net;
}
async function networkFirst(req, cacheName) {
  const cache = await caches.open(cacheName);
  try { const r = await fetch(req); if (r.ok) cache.put(req, r.clone()); return r; }
  catch (e) { return (await cache.match(req, { ignoreSearch: true })) || Response.error(); }
}
async function cacheFirst(req, cacheName) {
  const cache = await caches.open(cacheName);
  const hit = await cache.match(req);
  if (hit) return hit;
  const r = await fetch(req);
  if (r.ok) cache.put(req, r.clone());
  return r;
}

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.origin !== location.origin) return;
  if (url.pathname.startsWith('/api/')) return; // always live data
  if (url.pathname.startsWith('/media/')) return e.respondWith(cacheFirst(e.request, MEDIA));
  if (e.request.mode === 'navigate') return e.respondWith(fetch(e.request).catch(() => caches.match('/')));
  // vendored libs & icons never change between deploys; app code must always be fresh
  if (url.pathname.startsWith('/static/vendor/') || url.pathname.startsWith('/static/icons/')) return e.respondWith(staleWhileRevalidate(e.request, SHELL));
  if (url.pathname.startsWith('/static/') || url.pathname === '/manifest.webmanifest') return e.respondWith(networkFirst(e.request, SHELL));
});
