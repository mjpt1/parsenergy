from django.contrib import admin
from django.http import HttpResponse
from django.urls import include, path
from django.conf import settings
from django.conf.urls.static import static
from django.views.i18n import JavaScriptCatalog
from apps.core import card as card_views
from apps.core.views import dashboard_router, home

ROBOTS_TXT = '\n'.join([
    'User-agent: *',
    'Disallow: /leads/',
    'Disallow: /admin/',
    'Disallow: /api/',
    '',
])

urlpatterns = [
    path('admin/', admin.site.urls),
    path('i18n/', include('django.conf.urls.i18n')),
    path('jsi18n/', JavaScriptCatalog.as_view(domain='django'), name='javascript-catalog'),
    path('accounts/', include('apps.accounts.urls')),
    path('api/', include('apps.api.urls')),
    path('leads/', include('apps.leads.urls')),
    # Capture links are private by URL; keep crawlers off them entirely.
    path('robots.txt', lambda r: HttpResponse(
        ROBOTS_TXT, content_type='text/plain'), name='robots'),
    path('analytics/', include('apps.analytics.urls')),
    path('plants/', include('apps.plants.urls')),
    path('alerts/', include('apps.alerts.urls')),
    path('core/', include('apps.core.urls')),
    path('reports/', include('apps.reports.urls')),
    path('pwa/', include('apps.pwa.urls')),
    path('vpp/', include('apps.vpp.urls', namespace='vpp')),
    path('requests/', include('apps.requests.urls')),
    path('dashboard/', dashboard_router, name='dashboard'),
    path('card/', card_views.card, name='card'),
    path('card/pars-energy.vcf', card_views.card_vcf, name='card-vcf'),
    path('card/qr/', card_views.card_qr, name='card-qr'),
    path('', home, name='home'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
elif settings.SERVE_MEDIA:
    # Production media serving for hosts without a dedicated web server for
    # uploads (e.g. cPanel/Passenger). Fine for low/medium-traffic apps.
    from django.urls import re_path
    from django.views.static import serve as _serve_media
    urlpatterns += [
        re_path(r'^media/(?P<path>.*)$', _serve_media, {'document_root': settings.MEDIA_ROOT}),
    ]
