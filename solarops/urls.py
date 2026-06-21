from django.contrib import admin
from django.urls import include, path
from django.conf import settings
from django.conf.urls.static import static
from django.views.i18n import JavaScriptCatalog
from apps.core.views import dashboard_router

urlpatterns = [
    path('admin/', admin.site.urls),
    path('i18n/', include('django.conf.urls.i18n')),
    path('jsi18n/', JavaScriptCatalog.as_view(domain='django'), name='javascript-catalog'),
    path('accounts/', include('apps.accounts.urls')),
    path('api/', include('apps.api.urls')),
    path('analytics/', include('apps.analytics.urls')),
    path('plants/', include('apps.plants.urls')),
    path('alerts/', include('apps.alerts.urls')),
    path('core/', include('apps.core.urls')),
    path('reports/', include('apps.reports.urls')),
    path('pwa/', include('apps.pwa.urls')),
    path('vpp/', include('apps.vpp.urls', namespace='vpp')),
    path('requests/', include('apps.requests.urls')),
    path('', dashboard_router, name='dashboard'),
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
