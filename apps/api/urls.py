from django.urls import path, include
from rest_framework.routers import DefaultRouter
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from .views import (
    PlantViewSet, InverterViewSet, TransformerViewSet, GatewayViewSet, VPPViewSet, VPPMemberViewSet, DispatchScheduleViewSet, TelemetryViewSet, EnvironmentalViewSet,
    AlertRuleViewSet, AlertEventViewSet, NotificationViewSet, PlantMembershipViewSet,
    PlantGroupViewSet, PlantGroupMembershipViewSet,
    AuditLogViewSet, ServerHealthMetricViewSet, DatabaseBackupViewSet, APIConnectionViewSet,
    ProtocolAdapterViewSet, SystemParameterViewSet, SecuritySettingViewSet,
    RoleViewSet, PermissionViewSet, UserRoleViewSet,
    RealtimeMeasurementViewSet, HistoricalMeasurementViewSet, upload_measurements,
    kpi_api, prediction_api, auth_login, auth_logout,
)

router = DefaultRouter()
router.register('plants', PlantViewSet, basename='plant')
router.register('inverters', InverterViewSet, basename='inverter')
router.register('transformers', TransformerViewSet, basename='transformer')
router.register('gateways', GatewayViewSet, basename='gateway')
router.register('vpps', VPPViewSet, basename='vpp')
router.register('vpp-members', VPPMemberViewSet, basename='vpp-member')
router.register('dispatch-schedules', DispatchScheduleViewSet, basename='dispatch-schedule')
router.register('telemetry', TelemetryViewSet, basename='telemetry')
router.register('environmental', EnvironmentalViewSet, basename='environmental')
router.register('alert-rules', AlertRuleViewSet, basename='alert-rule')
router.register('alert-events', AlertEventViewSet, basename='alert-event')
router.register('notifications', NotificationViewSet, basename='notification')
router.register('plant-memberships', PlantMembershipViewSet)
router.register('plant-groups', PlantGroupViewSet, basename='plant-group')
router.register('plant-group-memberships', PlantGroupMembershipViewSet, basename='plant-group-membership')
router.register('audit-logs', AuditLogViewSet)
router.register('server-health', ServerHealthMetricViewSet)
router.register('db-backups', DatabaseBackupViewSet)
router.register('api-connections', APIConnectionViewSet)
router.register('protocol-adapters', ProtocolAdapterViewSet)
router.register('system-parameters', SystemParameterViewSet)
router.register('security-settings', SecuritySettingViewSet)
router.register('roles', RoleViewSet)
router.register('permissions', PermissionViewSet)
router.register('user-roles', UserRoleViewSet)
router.register('realtime-measurements', RealtimeMeasurementViewSet)
router.register('historical-measurements', HistoricalMeasurementViewSet)

urlpatterns = [
    path('', include(router.urls)),
    path('', include('apps.requests.api_urls')),
    path('auth/login/', auth_login, name='api-login'),
    path('auth/logout/', auth_logout, name='api-logout'),
    path('schema/', SpectacularAPIView.as_view(), name='schema'),
    path('docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('plants/<int:plant_id>/kpi/', kpi_api, name='kpi-api'),
    path('predict/', prediction_api, name='predict-api'),
    path('measurements/upload/', upload_measurements, name='upload-measurements'),
]
