from django.urls import path
from .views import manifest_view, service_worker_view, offline_view

app_name = 'pwa'

urlpatterns = [
    path('manifest.json', manifest_view, name='manifest'),
    path('service-worker.js', service_worker_view, name='service-worker'),
    path('offline.html', offline_view, name='offline'),
]
