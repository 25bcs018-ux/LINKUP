const CACHE_NAME = 'linkup-shell-v4';
const APP_SHELL = [
  '/',
  '/front',
  '/login',
  '/register',
  '/manifest.webmanifest',
  '/linkup-secure/',
  '/linkup-secure/link',
  '/linkup-secure/manifest.webmanifest',
  '/static/styles.css',
  '/static/front.css',
  '/static/chats.css',
  '/static/support.css',
  '/linkup-secure/static/secure.css',
  '/static/linkup_logo.svg',
  '/static/nova_logo.svg',
  '/static/register_suggest.js',
  '/static/pwa-register.js'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(APP_SHELL)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(
      keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))
    )).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (url.pathname.startsWith('/api/')) return;

  if (url.pathname === '/chats' || url.pathname === '/service-worker.js') {
    event.respondWith(fetch(request));
    return;
  }

  // Keep static assets fresh on mobile to avoid sticky stale UI behavior.
  if (url.pathname.startsWith('/static/') || url.pathname.startsWith('/linkup-secure/static/')) {
    event.respondWith(
      fetch(request)
        .then((response) => {
          const cloned = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(request, cloned));
          return response;
        })
        .catch(async () => {
          const cached = await caches.match(request);
          if (cached) return cached;
          throw new Error('offline');
        })
    );
    return;
  }

  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (APP_SHELL.includes(url.pathname)) {
            const cloned = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(request, cloned));
          }
          return response;
        })
        .catch(async () => {
          const cached = await caches.match(request);
          return cached || caches.match('/front') || caches.match('/');
        })
    );
    return;
  }

  event.respondWith(
    caches.match(request).then((cached) => {
      if (cached) return cached;
      return fetch(request).then((response) => {
        if (APP_SHELL.includes(url.pathname) || url.pathname.startsWith('/static/')) {
          const cloned = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(request, cloned));
        }
        return response;
      });
    })
  );
});
