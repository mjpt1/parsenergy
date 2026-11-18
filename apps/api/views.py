from rest_framework import viewsets, permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.authtoken.models import Token
from django.shortcuts import get_object_or_404
from django.contrib.auth import authenticate
from apps.accounts.models import Role, Permission, UserRole
from apps.plants.models import (
    Plant,
    PlantGroup,
    PlantGroupMembership,
    Inverter,
    Equipment,
    Transformer,
    Gateway,
    TelemetryReading,
    EnvironmentalReading,
    PlantMembership,
    RealtimeMeasurement,
    HistoricalMeasurement,
)
from apps.plants.scoping import plant_scope_for_user as _plant_scope_for_user
from apps.vpp.models import VPP, VPPMember, DispatchSchedule
from apps.alerts.models import AlertRule, AlertEvent, Notification
from apps.core.models import AuditLog, ServerHealthMetric, DatabaseBackup, APIConnection, ProtocolAdapter, SystemParameter, SecuritySetting
from .serializers import (
    PlantSerializer, InverterSerializer, TelemetrySerializer, EnvironmentalSerializer,
    TransformerSerializer, GatewaySerializer, VPPSerializer, VPPMemberSerializer, DispatchScheduleSerializer,
    AlertRuleSerializer, AlertEventSerializer, NotificationSerializer, PlantMembershipSerializer,
    PlantGroupSerializer, PlantGroupMembershipSerializer,
    AuditLogSerializer, ServerHealthMetricSerializer, DatabaseBackupSerializer, APIConnectionSerializer,
    ProtocolAdapterSerializer, SystemParameterSerializer, SecuritySettingSerializer,
    RoleSerializer, PermissionSerializer, UserRoleSerializer,
    RealtimeMeasurementSerializer, HistoricalMeasurementSerializer, MeasurementUploadSerializer,
)
from apps.analytics.services import calculate_kpis
from apps.ml.views import prediction_api as ml_prediction_api
from apps.monitoring.services import ingest_telemetry


class IsAdminRole(permissions.BasePermission):
    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and (request.user.is_superuser or request.user.has_permission_code('admin.access'))
        )


class PlantViewSet(viewsets.ModelViewSet):
    serializer_class = PlantSerializer

    def get_queryset(self):
        return _plant_scope_for_user(self.request.user)


class InverterViewSet(viewsets.ModelViewSet):
    serializer_class = InverterSerializer

    def get_queryset(self):
        return Inverter.objects.filter(plant__in=_plant_scope_for_user(self.request.user))


class TransformerViewSet(viewsets.ModelViewSet):
    serializer_class = TransformerSerializer

    def get_queryset(self):
        return Transformer.objects.filter(plant__in=_plant_scope_for_user(self.request.user))


class GatewayViewSet(viewsets.ModelViewSet):
    serializer_class = GatewaySerializer

    def get_queryset(self):
        return Gateway.objects.filter(plant__in=_plant_scope_for_user(self.request.user))


class VPPViewSet(viewsets.ModelViewSet):
    serializer_class = VPPSerializer

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser or getattr(user, 'role', '') == 'admin':
            return VPP.objects.all()
        return VPP.objects.filter(owner=user)


class VPPMemberViewSet(viewsets.ModelViewSet):
    serializer_class = VPPMemberSerializer

    def get_queryset(self):
        if self.request.user.is_superuser or getattr(self.request.user, 'role', '') == 'admin':
            return VPPMember.objects.select_related('vpp', 'plant').all()
        return VPPMember.objects.select_related('vpp', 'plant').filter(vpp__owner=self.request.user)


class DispatchScheduleViewSet(viewsets.ModelViewSet):
    serializer_class = DispatchScheduleSerializer

    def get_queryset(self):
        if self.request.user.is_superuser or getattr(self.request.user, 'role', '') == 'admin':
            return DispatchSchedule.objects.select_related('vpp').all()
        return DispatchSchedule.objects.select_related('vpp').filter(vpp__owner=self.request.user)


class TelemetryViewSet(viewsets.ModelViewSet):
    serializer_class = TelemetrySerializer

    def get_queryset(self):
        return TelemetryReading.objects.filter(plant__in=_plant_scope_for_user(self.request.user)).order_by('-created_at')

    def create(self, request, *args, **kwargs):
        plant_id = request.data.get('plant')
        inverter_id = request.data.get('inverter')
        if not plant_id:
            return Response({'detail': 'plant is required'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            plant = _plant_scope_for_user(request.user).get(id=plant_id)
        except Plant.DoesNotExist:
            return Response({'detail': 'plant not found'}, status=status.HTTP_404_NOT_FOUND)

        inverter = None
        if inverter_id:
            inverter = Inverter.objects.filter(id=inverter_id, plant=plant).first()

        telemetry, events = ingest_telemetry(
            plant=plant,
            inverter=inverter,
            payload=request.data,
            actor=request.user,
        )
        serializer = self.get_serializer(telemetry)
        return Response({'telemetry': serializer.data, 'alert_events': len(events)}, status=status.HTTP_201_CREATED)


class EnvironmentalViewSet(viewsets.ModelViewSet):
    serializer_class = EnvironmentalSerializer

    def get_queryset(self):
        return EnvironmentalReading.objects.filter(plant__in=_plant_scope_for_user(self.request.user)).order_by('-created_at')


class AlertRuleViewSet(viewsets.ModelViewSet):
    serializer_class = AlertRuleSerializer

    def get_queryset(self):
        return AlertRule.objects.filter(plant__in=_plant_scope_for_user(self.request.user))


class AlertEventViewSet(viewsets.ModelViewSet):
    serializer_class = AlertEventSerializer

    def get_queryset(self):
        return AlertEvent.objects.filter(rule__plant__in=_plant_scope_for_user(self.request.user)).order_by('-created_at')


class NotificationViewSet(viewsets.ModelViewSet):
    serializer_class = NotificationSerializer

    def get_queryset(self):
        if self.request.user.is_superuser or getattr(self.request.user, 'role', '') == 'admin':
            return Notification.objects.all().order_by('-created_at')
        return Notification.objects.filter(user=self.request.user).order_by('-created_at')


class PlantMembershipViewSet(viewsets.ModelViewSet):
    queryset = PlantMembership.objects.select_related('plant', 'user').all()
    serializer_class = PlantMembershipSerializer
    permission_classes = [IsAdminRole]


class PlantGroupViewSet(viewsets.ModelViewSet):
    serializer_class = PlantGroupSerializer

    def get_queryset(self):
        if self.request.user.is_superuser or self.request.user.has_permission_code('admin.access'):
            return PlantGroup.objects.select_related('owner').all()
        return PlantGroup.objects.filter(owner=self.request.user)


class PlantGroupMembershipViewSet(viewsets.ModelViewSet):
    serializer_class = PlantGroupMembershipSerializer

    def get_queryset(self):
        if self.request.user.is_superuser or self.request.user.has_permission_code('admin.access'):
            return PlantGroupMembership.objects.select_related('plant', 'group').all()
        return PlantGroupMembership.objects.filter(group__owner=self.request.user)


class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = AuditLog.objects.select_related('actor').all()
    serializer_class = AuditLogSerializer
    permission_classes = [IsAdminRole]


class ServerHealthMetricViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ServerHealthMetric.objects.all()
    serializer_class = ServerHealthMetricSerializer
    permission_classes = [IsAdminRole]


class DatabaseBackupViewSet(viewsets.ModelViewSet):
    queryset = DatabaseBackup.objects.all()
    serializer_class = DatabaseBackupSerializer
    permission_classes = [IsAdminRole]


class APIConnectionViewSet(viewsets.ModelViewSet):
    queryset = APIConnection.objects.all()
    serializer_class = APIConnectionSerializer
    permission_classes = [IsAdminRole]


class ProtocolAdapterViewSet(viewsets.ModelViewSet):
    queryset = ProtocolAdapter.objects.all()
    serializer_class = ProtocolAdapterSerializer
    permission_classes = [IsAdminRole]


class SystemParameterViewSet(viewsets.ModelViewSet):
    queryset = SystemParameter.objects.all()
    serializer_class = SystemParameterSerializer
    permission_classes = [IsAdminRole]


class SecuritySettingViewSet(viewsets.ModelViewSet):
    queryset = SecuritySetting.objects.all()
    serializer_class = SecuritySettingSerializer
    permission_classes = [IsAdminRole]


class RoleViewSet(viewsets.ModelViewSet):
    queryset = Role.objects.all()
    serializer_class = RoleSerializer
    permission_classes = [IsAdminRole]


class PermissionViewSet(viewsets.ModelViewSet):
    queryset = Permission.objects.all()
    serializer_class = PermissionSerializer
    permission_classes = [IsAdminRole]


class UserRoleViewSet(viewsets.ModelViewSet):
    queryset = UserRole.objects.select_related('user', 'role').all()
    serializer_class = UserRoleSerializer
    permission_classes = [IsAdminRole]


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def kpi_api(request, plant_id):
    plant = get_object_or_404(_plant_scope_for_user(request.user), id=plant_id)
    return Response(calculate_kpis(plant))


@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def auth_login(request):
    username = request.data.get('username')
    password = request.data.get('password')
    user = authenticate(username=username, password=password)
    if not user:
        return Response({'detail': 'Invalid credentials'}, status=status.HTTP_400_BAD_REQUEST)
    token, _ = Token.objects.get_or_create(user=user)
    return Response({'token': token.key})


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def auth_logout(request):
    Token.objects.filter(user=request.user).delete()
    return Response({'detail': 'Logged out'})


prediction_api = ml_prediction_api


class RealtimeMeasurementViewSet(viewsets.ModelViewSet):
    serializer_class = RealtimeMeasurementSerializer
    queryset = RealtimeMeasurement.objects.select_related('plant', 'equipment').order_by('-timestamp')

    def get_queryset(self):
        return RealtimeMeasurement.objects.filter(
            plant__in=_plant_scope_for_user(self.request.user)
        ).select_related('plant', 'equipment').order_by('-timestamp')


class HistoricalMeasurementViewSet(viewsets.ModelViewSet):
    serializer_class = HistoricalMeasurementSerializer
    queryset = HistoricalMeasurement.objects.select_related('plant', 'equipment').order_by('-timestamp')

    def get_queryset(self):
        return HistoricalMeasurement.objects.filter(
            plant__in=_plant_scope_for_user(self.request.user)
        ).select_related('plant', 'equipment').order_by('-timestamp')


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def upload_measurements(request):
    """
    API endpoint for gateways to upload measurement data.
    Gateways authenticate with a DRF token (Authorization: Token <key>).
    Expects JSON payload with plant_code, equipment_serial, measurements list, and optional timestamp.
    """
    serializer = MeasurementUploadSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    plant_code = serializer.validated_data['plant_code']
    equipment_serial = serializer.validated_data['equipment_serial']
    measurements = serializer.validated_data['measurements']
    timestamp = serializer.validated_data.get('timestamp')

    plant = _plant_scope_for_user(request.user).filter(external_code=plant_code).first()
    if plant is None:
        return Response({'detail': 'Plant not found'}, status=status.HTTP_404_NOT_FOUND)

    try:
        equipment = Equipment.objects.get(plant=plant, serial_number=equipment_serial)
    except Equipment.DoesNotExist:
        return Response({'detail': 'Equipment not found'}, status=status.HTTP_404_NOT_FOUND)

    created_measurements = []
    telemetry_payload = {}
    for measurement_data in measurements:
        parameter = measurement_data.get('parameter')
        value = measurement_data.get('value')
        unit = measurement_data.get('unit', '')
        quality = measurement_data.get('quality', 'good')

        if not parameter or value is None:
            continue

        try:
            parsed_value = float(value)
        except (TypeError, ValueError):
            parsed_value = value

        if parameter == 'power':
            telemetry_payload['power_kw'] = float(parsed_value)
        elif parameter == 'voltage':
            telemetry_payload['voltage_v'] = float(parsed_value)
        elif parameter == 'current':
            telemetry_payload['current_a'] = float(parsed_value)
        elif parameter == 'frequency':
            telemetry_payload['frequency_hz'] = float(parsed_value)
        elif parameter == 'energy':
            telemetry_payload['energy_kwh'] = float(parsed_value)
        elif parameter == 'temperature':
            telemetry_payload['temperature_c'] = float(parsed_value)
        elif parameter == 'irradiance':
            telemetry_payload['irradiance_wm2'] = float(parsed_value)

        measurement_kwargs = {
            'plant': plant,
            'equipment': equipment,
            'parameter': parameter,
            'value': parsed_value,
            'unit': unit,
            'quality': quality,
        }
        if timestamp is not None:
            measurement_kwargs['timestamp'] = timestamp

        realtime_measurement = RealtimeMeasurement.objects.create(**measurement_kwargs)
        created_measurements.append(realtime_measurement)

        HistoricalMeasurement.objects.create(
            timestamp=realtime_measurement.timestamp,
            plant=plant,
            equipment=equipment,
            parameter=parameter,
            value=realtime_measurement.value,
            unit=unit,
            quality=quality,
            aggregation='raw',
        )

    alert_events = []
    if telemetry_payload:
        telemetry_payload.setdefault('status', 'uploaded')
        telemetry_payload.setdefault('energy_kwh', 0)
        _, alert_events = ingest_telemetry(
            plant=plant,
            inverter=None,
            payload=telemetry_payload,
            actor=request.user if request.user.is_authenticated else None,
        )

    return Response({
        'detail': f'Created {len(created_measurements)} measurements',
        'measurements': RealtimeMeasurementSerializer(created_measurements, many=True).data,
        'alerts_triggered': len(alert_events),
    }, status=status.HTTP_201_CREATED)
