from django.http import JsonResponse, HttpResponse
from django.shortcuts import render


def manifest_view(request):
    data = {
        'name': 'پارس انرژی',
        'short_name': 'پارس انرژی',
        'description': 'سامانهٔ مدیریت و پایش نیروگاه‌های خورشیدی پارس انرژی',
        'lang': 'fa-IR',
        'dir': 'rtl',
        'start_url': '/',
        'scope': '/',
        'display': 'standalone',
        'orientation': 'any',
        'background_color': '#0b1218',
        'theme_color': '#0b1218',
        'categories': ['business', 'productivity', 'utilities'],
        'icons': [
            {
                'src': '/static/img/pwa-icon.svg',
                'sizes': '192x192 512x512 any',
                'type': 'image/svg+xml',
                'purpose': 'any',
            },
            {
                'src': '/static/img/pwa-maskable.svg',
                'sizes': '192x192 512x512 any',
                'type': 'image/svg+xml',
                'purpose': 'maskable',
            },
        ],
    }
    return JsonResponse(data, json_dumps_params={'ensure_ascii': False})


def offline_view(request):
    return render(request, 'pwa/offline.html')


def service_worker_view(request):
    # NOTE: bump CACHE_NAME whenever the precache list changes. Static assets use
    # stale-while-revalidate so CSS/JS updates reach installed apps automatically
    # (the old cache-first strategy froze main.css/main.js and broke the app UI).
    return HttpResponse("""
const CACHE_NAME = 'pars-energy-v9';
const PRECACHE_URLS = [
  '/static/css/main.css',
  '/static/css/dark-fixes.css',
  '/static/css/responsive.css',
  '/static/js/main.js',
  '/static/img/pwa-icon.svg',
  '/pwa/manifest.json',
  '/pwa/offline.html',
];
self.addEventListener('install', event => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(PRECACHE_URLS).catch(() => {}))
  );
});
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys => Promise.all(
      keys.filter(key => key !== CACHE_NAME).map(key => caches.delete(key))
    )).then(() => self.clients.claim())
  );
});
self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET') return;
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin) return;

  // Navigations always hit the network so pages (and their CSRF tokens) are
  // never served stale; fall back to the offline page only when offline.
  if (event.request.mode === 'navigate') {
    event.respondWith(
      fetch(event.request).catch(() => caches.match('/pwa/offline.html'))
    );
    return;
  }

  // Dynamic HTML (AJAX panel fetches) must never be cached: doing so replays
  // stale CSRF tokens and leaks per-user content from a shared cache.
  const isStaticAsset = url.pathname.startsWith('/static/') ||
    url.pathname === '/pwa/manifest.json' ||
    url.pathname === '/pwa/offline.html';
  if (!isStaticAsset) return;

  // Stale-while-revalidate: serve the cached copy instantly for speed, but
  // always fetch a fresh copy in the background and update the cache, so the
  // installed app never gets stuck on an old stylesheet or script.
  event.respondWith(
    caches.open(CACHE_NAME).then(cache =>
      cache.match(event.request).then(cached => {
        const network = fetch(event.request).then(response => {
          if (response && response.status === 200) {
            cache.put(event.request, response.clone());
          }
          return response;
        }).catch(() => cached);
        return cached || network;
      })
    )
  );
});
""", content_type='application/javascript')
