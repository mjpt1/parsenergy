from rest_framework import serializers
from apps.accounts.models import Role, Permission, UserRole
from apps.plants.models import (
    Plant,
    PlantGroup,
    PlantGroupMembership,
    Equipment,
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
from apps.plants.scoping import plant_scope_for_user


def _request_user(context):
    request = context.get('request') if context else None
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return None
    return user


def _is_admin_user(user) -> bool:
    return bool(
        user
        and (user.is_superuser or getattr(user, 'role', '') == 'admin' or user.has_permission_code('admin.access'))
    )


def _plant_scope(context):
    user = _request_user(context)
    if user is None:
        return Plant.objects.none()
    return plant_scope_for_user(user)


class OwnedObjectSerializerMixin:
    owner_field = 'owner'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        user = _request_user(self.context)
        field = self.fields.get(self.owner_field)
        if field is not None and user is not None and not _is_admin_user(user):
            field.required = False

    def validate(self, attrs):
        attrs = super().validate(attrs)
        user = _request_user(self.context)
        requested_owner = attrs.get(self.owner_field)
        if user is not None and not _is_admin_user(user) and requested_owner not in (None, user):
            raise serializers.ValidationError({self.owner_field: 'You cannot assign this object to another user.'})
        return attrs

    def create(self, validated_data):
        user = _request_user(self.context)
        if user is not None and not _is_admin_user(user):
            validated_data[self.owner_field] = user
        return super().create(validated_data)

    def update(self, instance, validated_data):
        user = _request_user(self.context)
        if user is not None and not _is_admin_user(user):
            validated_data.pop(self.owner_field, None)
        return super().update(instance, validated_data)


class PlantScopedSerializerMixin:
    plant_field = 'plant'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        plant_field = self.fields.get(self.plant_field)
        if plant_field is not None:
            plant_field.queryset = _plant_scope(self.context)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        plant = attrs.get(self.plant_field) or getattr(self.instance, self.plant_field, None)
        if plant is not None and not _plant_scope(self.context).filter(pk=plant.pk).exists():
            raise serializers.ValidationError({self.plant_field: 'Plant is outside your access scope.'})
        return attrs


class EquipmentScopedSerializerMixin(PlantScopedSerializerMixin):
    equipment_field = 'equipment'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        equipment_field = self.fields.get(self.equipment_field)
        if equipment_field is not None:
            equipment_field.queryset = Equipment.objects.filter(plant__in=_plant_scope(self.context))

    def validate(self, attrs):
        attrs = super().validate(attrs)
        plant = attrs.get(self.plant_field) or getattr(self.instance, self.plant_field, None)
        equipment = attrs.get(self.equipment_field) or getattr(self.instance, self.equipment_field, None)
        if equipment is not None and not _plant_scope(self.context).filter(pk=equipment.plant_id).exists():
            raise serializers.ValidationError({self.equipment_field: 'Equipment is outside your access scope.'})
        if plant is not None and equipment is not None and equipment.plant_id != plant.id:
            raise serializers.ValidationError({self.equipment_field: 'Equipment must belong to the selected plant.'})
        return attrs


class PlantSerializer(OwnedObjectSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = Plant
        fields = '__all__'
        extra_kwargs = {'owner': {'required': False}}


class InverterSerializer(PlantScopedSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = Inverter
        fields = '__all__'


class TransformerSerializer(PlantScopedSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = Transformer
        fields = '__all__'


class GatewaySerializer(PlantScopedSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = Gateway
        fields = '__all__'


class VPPSerializer(OwnedObjectSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = VPP
        fields = '__all__'
        extra_kwargs = {'owner': {'required': False}}


class VPPMemberSerializer(serializers.ModelSerializer):
    class Meta:
        model = VPPMember
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        user = _request_user(self.context)
        if user is not None and not _is_admin_user(user):
            self.fields['vpp'].queryset = VPP.objects.filter(owner=user)
            self.fields['plant'].queryset = Plant.objects.filter(owner=user)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        user = _request_user(self.context)
        vpp = attrs.get('vpp') or getattr(self.instance, 'vpp', None)
        plant = attrs.get('plant') or getattr(self.instance, 'plant', None)
        if user is not None and not _is_admin_user(user):
            if vpp is not None and vpp.owner_id != user.id:
                raise serializers.ValidationError({'vpp': 'VPP is outside your access scope.'})
            if plant is not None and plant.owner_id != user.id:
                raise serializers.ValidationError({'plant': 'Only owned plants can be added to your VPP.'})
        return attrs


class DispatchScheduleSerializer(serializers.ModelSerializer):
    class Meta:
        model = DispatchSchedule
        fields = '__all__'
        extra_kwargs = {'created_by': {'required': False}}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        user = _request_user(self.context)
        if user is not None and not _is_admin_user(user):
            self.fields['vpp'].queryset = VPP.objects.filter(owner=user)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        user = _request_user(self.context)
        vpp = attrs.get('vpp') or getattr(self.instance, 'vpp', None)
        if user is not None and not _is_admin_user(user) and vpp is not None and vpp.owner_id != user.id:
            raise serializers.ValidationError({'vpp': 'VPP is outside your access scope.'})
        return attrs


class TelemetrySerializer(PlantScopedSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = TelemetryReading
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        inverter_field = self.fields.get('inverter')
        if inverter_field is not None:
            inverter_field.queryset = Inverter.objects.filter(plant__in=_plant_scope(self.context))

    def validate(self, attrs):
        attrs = super().validate(attrs)
        plant = attrs.get('plant') or getattr(self.instance, 'plant', None)
        inverter = attrs.get('inverter') or getattr(self.instance, 'inverter', None)
        if inverter is not None and not _plant_scope(self.context).filter(pk=inverter.plant_id).exists():
            raise serializers.ValidationError({'inverter': 'Inverter is outside your access scope.'})
        if plant is not None and inverter is not None and inverter.plant_id != plant.id:
            raise serializers.ValidationError({'inverter': 'Inverter must belong to the selected plant.'})
        return attrs


class EnvironmentalSerializer(PlantScopedSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = EnvironmentalReading
        fields = '__all__'


class AlertRuleSerializer(PlantScopedSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = AlertRule
        fields = '__all__'


class AlertEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = AlertEvent
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        rule_field = self.fields.get('rule')
        if rule_field is not None:
            rule_field.queryset = AlertRule.objects.filter(plant__in=_plant_scope(self.context))

    def validate(self, attrs):
        attrs = super().validate(attrs)
        rule = attrs.get('rule') or getattr(self.instance, 'rule', None)
        if rule is not None and not _plant_scope(self.context).filter(pk=rule.plant_id).exists():
            raise serializers.ValidationError({'rule': 'Alert rule is outside your access scope.'})
        return attrs


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = '__all__'

    def validate(self, attrs):
        attrs = super().validate(attrs)
        user = _request_user(self.context)
        target_user = attrs.get('user') or getattr(self.instance, 'user', None)
        if user is not None and not _is_admin_user(user) and target_user not in (None, user):
            raise serializers.ValidationError({'user': 'You cannot create notifications for another user.'})
        return attrs

    def create(self, validated_data):
        user = _request_user(self.context)
        if user is not None and not _is_admin_user(user):
            validated_data['user'] = user
        return super().create(validated_data)


class PlantMembershipSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlantMembership
        fields = '__all__'


class PlantGroupSerializer(OwnedObjectSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = PlantGroup
        fields = '__all__'
        extra_kwargs = {'owner': {'required': False}}


class RealtimeMeasurementSerializer(EquipmentScopedSerializerMixin, serializers.ModelSerializer):
    plant_name = serializers.CharField(source='plant.name', read_only=True)
    equipment_name = serializers.CharField(source='equipment.name', read_only=True)

    class Meta:
        model = RealtimeMeasurement
        fields = '__all__'


class HistoricalMeasurementSerializer(EquipmentScopedSerializerMixin, serializers.ModelSerializer):
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        user = _request_user(self.context)
        if user is not None and not _is_admin_user(user):
            self.fields['plant'].queryset = _plant_scope(self.context)
            self.fields['group'].queryset = PlantGroup.objects.filter(owner=user)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        user = _request_user(self.context)
        plant = attrs.get('plant') or getattr(self.instance, 'plant', None)
        group = attrs.get('group') or getattr(self.instance, 'group', None)
        if user is not None and not _is_admin_user(user):
            if plant is not None and not _plant_scope(self.context).filter(pk=plant.pk).exists():
                raise serializers.ValidationError({'plant': 'Plant is outside your access scope.'})
            if group is not None and group.owner_id != user.id:
                raise serializers.ValidationError({'group': 'Plant group is outside your access scope.'})
        return attrs


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
