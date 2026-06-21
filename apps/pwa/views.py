from django.http import JsonResponse, HttpResponse
from django.shortcuts import render


def manifest_view(request):
    data = {
        'name': 'Pars Energy',
        'short_name': 'Pars Energy',
        'start_url': '/',
        'scope': '/',
        'display': 'standalone',
        'background_color': '#0b1218',
        'theme_color': '#0b1218',
        'icons': [
            {
                'src': '/static/img/pwa-icon.svg',
                'sizes': '512x512',
                'type': 'image/svg+xml',
                'purpose': 'any',
            }
        ],
    }
    return JsonResponse(data)


def offline_view(request):
    return render(request, 'pwa/offline.html')


def service_worker_view(request):
    return HttpResponse("""
const CACHE_NAME = 'pars-energy-v6';
const PRECACHE_URLS = [
  '/static/css/main.css',
  '/static/js/main.js',
  '/static/img/pwa-icon.svg',
  '/pwa/manifest.json',
  '/pwa/offline.html',
];
self.addEventListener('install', event => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(PRECACHE_URLS))
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

  // Only cache versioned static assets. Dynamic HTML (e.g. the AJAX panel
  // fetches) must never be cached: doing so replays stale CSRF tokens and
  // leaks per-user authenticated content from a shared cache. Let the browser
  // fetch those from the network normally.
  const isStaticAsset = url.pathname.startsWith('/static/') ||
    url.pathname === '/pwa/manifest.json' ||
    url.pathname === '/pwa/offline.html';
  if (!isStaticAsset) return;

  event.respondWith(
    caches.match(event.request).then(cached => {
      if (cached) return cached;
      return fetch(event.request).then(response => {
        const responseClone = response.clone();
        caches.open(CACHE_NAME).then(cache => cache.put(event.request, responseClone));
        return response;
      });
    })
  );
});
""", content_type='application/javascript')
