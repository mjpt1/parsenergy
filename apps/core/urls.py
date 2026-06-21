from django.urls import path, include
from .views import admin_dashboard_data, owner_dashboard_data, set_calendar
from .management_views import (
    SystemParameterListView, SystemParameterCreateView, SystemParameterUpdateView, SystemParameterDeleteView,
    SecuritySettingListView, SecuritySettingCreateView, SecuritySettingUpdateView, SecuritySettingDeleteView,
    APIConnectionListView, APIConnectionCreateView, APIConnectionUpdateView, APIConnectionDeleteView,
    InverterAPIConnectionView,
    ProtocolAdapterListView, ProtocolAdapterCreateView, ProtocolAdapterUpdateView, ProtocolAdapterDeleteView,
    DatabaseBackupListView, DatabaseBackupCreateView, DatabaseBackupUpdateView, DatabaseBackupDeleteView,
    AuditLogListView, ServerHealthListView,
    AISettingsView, IntegrationSettingsView,
)

app_name = 'core'

urlpatterns = [
    path('dashboard/admin-data/', admin_dashboard_data, name='admin-dashboard-data'),
    path('dashboard/owner-data/', owner_dashboard_data, name='owner-dashboard-data'),
    path('set-calendar/', set_calendar, name='set-calendar'),
    path('parameters/', SystemParameterListView.as_view(), name='parameters'),
    path('parameters/create/', SystemParameterCreateView.as_view(), name='parameters-create'),
    path('parameters/<int:pk>/edit/', SystemParameterUpdateView.as_view(), name='parameters-edit'),
    path('parameters/<int:pk>/delete/', SystemParameterDeleteView.as_view(), name='parameters-delete'),
    path('security/', SecuritySettingListView.as_view(), name='security'),
    path('security/create/', SecuritySettingCreateView.as_view(), name='security-create'),
    path('security/<int:pk>/edit/', SecuritySettingUpdateView.as_view(), name='security-edit'),
    path('security/<int:pk>/delete/', SecuritySettingDeleteView.as_view(), name='security-delete'),
    path('connections/', APIConnectionListView.as_view(), name='connections'),
    path('connections/create/', APIConnectionCreateView.as_view(), name='connections-create'),
    path('connections/<int:pk>/edit/', APIConnectionUpdateView.as_view(), name='connections-edit'),
    path('connections/<int:pk>/delete/', APIConnectionDeleteView.as_view(), name='connections-delete'),
    path('inverters/api/', InverterAPIConnectionView.as_view(), name='inverter-api'),
    path('protocols/', ProtocolAdapterListView.as_view(), name='protocols'),
    path('protocols/create/', ProtocolAdapterCreateView.as_view(), name='protocols-create'),
    path('protocols/<int:pk>/edit/', ProtocolAdapterUpdateView.as_view(), name='protocols-edit'),
    path('protocols/<int:pk>/delete/', ProtocolAdapterDeleteView.as_view(), name='protocols-delete'),
    path('backups/', DatabaseBackupListView.as_view(), name='backups'),
    path('backups/create/', DatabaseBackupCreateView.as_view(), name='backups-create'),
    path('backups/<int:pk>/edit/', DatabaseBackupUpdateView.as_view(), name='backups-edit'),
    path('backups/<int:pk>/delete/', DatabaseBackupDeleteView.as_view(), name='backups-delete'),
    path('logs/', AuditLogListView.as_view(), name='logs'),
    path('health/', ServerHealthListView.as_view(), name='health'),
    path('ai/settings/', AISettingsView.as_view(), name='ai-settings'),
    path('integrations/settings/', IntegrationSettingsView.as_view(), name='integration-settings'),
    path('vpp/', include(('apps.vpp.urls', 'vpp'), namespace='vpp')),
]
