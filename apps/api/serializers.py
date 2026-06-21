from rest_framework import serializers
from apps.accounts.models import Role, Permission, UserRole
from apps.plants.models import (
    Plant,
    PlantGroup,
    PlantGroupMembership,
    Inverter,
    Transformer,
    Gateway,
    TelemetryReading,
    EnvironmentalReading,
    PlantMembership,
    RealtimeMeasurement,
    HistoricalMeasurement,
)
from apps.vpp.models import VPP, VPPMember, DispatchSchedule
from apps.alerts.models import AlertRule, AlertEvent, Notification
from apps.core.models import AuditLog, ServerHealthMetric, DatabaseBackup, APIConnection, ProtocolAdapter, SystemParameter, SecuritySetting


class PlantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Plant
        fields = '__all__'


class InverterSerializer(serializers.ModelSerializer):
    class Meta:
        model = Inverter
        fields = '__all__'


class TransformerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Transformer
        fields = '__all__'


class GatewaySerializer(serializers.ModelSerializer):
    class Meta:
        model = Gateway
        fields = '__all__'


class VPPSerializer(serializers.ModelSerializer):
    class Meta:
        model = VPP
        fields = '__all__'


class VPPMemberSerializer(serializers.ModelSerializer):
    class Meta:
        model = VPPMember
        fields = '__all__'


class DispatchScheduleSerializer(serializers.ModelSerializer):
    class Meta:
        model = DispatchSchedule
        fields = '__all__'


class TelemetrySerializer(serializers.ModelSerializer):
    class Meta:
        model = TelemetryReading
        fields = '__all__'


class EnvironmentalSerializer(serializers.ModelSerializer):
    class Meta:
        model = EnvironmentalReading
        fields = '__all__'


class AlertRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = AlertRule
        fields = '__all__'


class AlertEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = AlertEvent
        fields = '__all__'


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = '__all__'


class PlantMembershipSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlantMembership
        fields = '__all__'


class PlantGroupSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlantGroup
        fields = '__all__'


class RealtimeMeasurementSerializer(serializers.ModelSerializer):
    plant_name = serializers.CharField(source='plant.name', read_only=True)
    equipment_name = serializers.CharField(source='equipment.name', read_only=True)

    class Meta:
        model = RealtimeMeasurement
        fields = '__all__'


class HistoricalMeasurementSerializer(serializers.ModelSerializer):
    plant_name = serializers.CharField(source='plant.name', read_only=True)
    equipment_name = serializers.CharField(source='equipment.name', read_only=True)

    class Meta:
        model = HistoricalMeasurement
        fields = '__all__'


class MeasurementUploadSerializer(serializers.Serializer):
    """Serializer for uploading measurement data from gateways"""
    plant_code = serializers.CharField(max_length=64)
    equipment_serial = serializers.CharField(max_length=128)
    measurements = serializers.ListField(
        child=serializers.DictField(
            child=serializers.CharField()
        )
    )
    timestamp = serializers.DateTimeField(required=False)


class PlantGroupMembershipSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlantGroupMembership
        fields = '__all__'


class AuditLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditLog
        fields = '__all__'


class ServerHealthMetricSerializer(serializers.ModelSerializer):
    class Meta:
        model = ServerHealthMetric
        fields = '__all__'


class DatabaseBackupSerializer(serializers.ModelSerializer):
    class Meta:
        model = DatabaseBackup
        fields = '__all__'


class APIConnectionSerializer(serializers.ModelSerializer):
    class Meta:
        model = APIConnection
        fields = '__all__'


class ProtocolAdapterSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProtocolAdapter
        fields = '__all__'


class SystemParameterSerializer(serializers.ModelSerializer):
    class Meta:
        model = SystemParameter
        fields = '__all__'

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if instance.is_secret:
            data['value'] = '********'
        return data


class SecuritySettingSerializer(serializers.ModelSerializer):
    class Meta:
        model = SecuritySetting
        fields = '__all__'


class RoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Role
        fields = '__all__'


class PermissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Permission
        fields = '__all__'


class UserRoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserRole
        fields = '__all__'
