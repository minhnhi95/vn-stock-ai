/* VN Stock AI Analyzer — Service Worker */
/* eslint-disable no-restricted-globals */

const VERSION = 'v1';
const SHELL_CACHE = `vnstock-shell-${VERSION}`;
const ASSET_CACHE = `vnstock-assets-${VERSION}`;
const API_CACHE = `vnstock-api-${VERSION}`;

const SHELL_URLS = [
  '/',
  '/index.html',
  '/manifest.webmanifest',
  '/favicon.svg',
];

// ---------- Install: precache the app shell ----------
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(SHELL_CACHE).then((cache) => cache.addAll(SHELL_URLS)).then(() => self.skipWaiting())
  );
});

// ---------- Activate: clear caches from older versions ----------
self.addEventListener('activate', (event) => {
  const allowList = new Set([SHELL_CACHE, ASSET_CACHE, API_CACHE]);
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys.map((key) => {
            if (!allowList.has(key)) {
              return caches.delete(key);
            }
            return null;
          })
        )
      )
      .then(() => self.clients.claim())
  );
});

// ---------- Helpers ----------
const isApiRequest = (url) => url.pathname.startsWith('/api/');

const isAssetRequest = (request, url) => {
  if (request.destination === 'style' || request.destination === 'script' || request.destination === 'image' || request.destination === 'font') {
    return true;
  }
  return /\.(?:js|css|svg|png|jpg|jpeg|webp|gif|ico|woff2?)$/i.test(url.pathname);
};

const isNavigationRequest = (request) =>
  request.mode === 'navigate' || (request.method === 'GET' && request.headers.get('accept')?.includes('text/html'));

// Network-first: try the network, fall back to cache on failure.
const networkFirst = async (request, cacheName) => {
  const cache = await caches.open(cacheName);
  try {
    const fresh = await fetch(request);
    if (fresh && fresh.ok) {
      cache.put(request, fresh.clone());
    }
    return fresh;
  } catch (err) {
    const cached = await cache.match(request);
    if (cached) return cached;
    throw err;
  }
};

// Stale-while-revalidate: serve cache immediately, refresh in background.
const staleWhileRevalidate = async (request, cacheName) => {
  const cache = await caches.open(cacheName);
  const cached = await cache.match(request);
  const network = fetch(request)
    .then((response) => {
      if (response && response.ok) {
        cache.put(request, response.clone());
      }
      return response;
    })
    .catch(() => null);
  return cached || network || fetch(request);
};

// Cache-first with network fallback for the app shell / navigations.
const navigationHandler = async (request) => {
  try {
    const fresh = await fetch(request);
    const cache = await caches.open(SHELL_CACHE);
    cache.put('/index.html', fresh.clone());
    return fresh;
  } catch (err) {
    const cache = await caches.open(SHELL_CACHE);
    const cached = (await cache.match(request)) || (await cache.match('/index.html')) || (await cache.match('/'));
    if (cached) return cached;
    throw err;
  }
};

// ---------- Fetch routing ----------
self.addEventListener('fetch', (event) => {
  const { request } = event;

  // Only handle GET — leave POST/PUT/DELETE alone (likely API mutations).
  if (request.method !== 'GET') return;

  const url = new URL(request.url);

  // Ignore cross-origin requests — let the browser handle them normally.
  if (url.origin !== self.location.origin) return;

  if (isApiRequest(url)) {
    event.respondWith(networkFirst(request, API_CACHE));
    return;
  }

  if (isNavigationRequest(request)) {
    event.respondWith(navigationHandler(request));
    return;
  }

  if (isAssetRequest(request, url)) {
    event.respondWith(staleWhileRevalidate(request, ASSET_CACHE));
  }
});

// Allow the page to trigger an immediate activation after an update.
self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});
