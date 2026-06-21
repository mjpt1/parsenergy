from django import forms
from django.db.models import Q
from django.utils import timezone
from typing import Any, cast
from .models import (
    Plant, PlantGroup, PlantGroupMembership, Inverter, Sensor, Meter,
    Equipment, Transformer, Gateway, PlantMembership,
)


def _plant_scope_for_user(user):
    if user is None or user.is_superuser or getattr(user, 'role', '') == 'admin':
        return Plant.objects.all()
    member_ids = PlantMembership.objects.filter(user=user, active=True).values_list('plant_id', flat=True)
    return Plant.objects.filter(Q(owner=user) | Q(id__in=member_ids)).distinct()


class PlantForm(forms.ModelForm):
    class Meta:
        model = Plant
        fields = ['name', 'external_code', 'owner', 'location_name', 'latitude', 'longitude', 'capacity_kw', 'connection_status', 'timezone', 'protocol', 'is_active']

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if user is not None and not (user.is_superuser or getattr(user, 'role', '') == 'admin'):
            owner_field = cast(Any, self.fields['owner'])
            owner_field.initial = user
            owner_field.disabled = True


class PlantGroupForm(forms.ModelForm):
    class Meta:
        model = PlantGroup
        fields = ['name', 'description', 'owner']

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if user is not None and not (user.is_superuser or getattr(user, 'role', '') == 'admin'):
            owner_field = cast(Any, self.fields['owner'])
            owner_field.initial = user
            owner_field.disabled = True


class PlantGroupMembershipForm(forms.ModelForm):
    class Meta:
        model = PlantGroupMembership
        fields = ['plant', 'group']

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if user is not None and not (user.is_superuser or getattr(user, 'role', '') == 'admin'):
            plant_field = cast(Any, self.fields['plant'])
            group_field = cast(Any, self.fields['group'])
            plant_field.queryset = _plant_scope_for_user(user)
            group_field.queryset = group_field.queryset.filter(owner=user)


class InverterForm(forms.ModelForm):
    class Meta:
        model = Inverter
        fields = ['plant', 'serial_number', 'model_name', 'status', 'online', 'rated_power_kw', 'firmware_version', 'manufacturer']

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if user is not None and not (user.is_superuser or getattr(user, 'role', '') == 'admin'):
            plant_field = cast(Any, self.fields['plant'])
            plant_field.queryset = _plant_scope_for_user(user)


class SensorForm(forms.ModelForm):
    class Meta:
        model = Sensor
        fields = ['plant', 'name', 'sensor_type', 'unit', 'is_active']

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if user is not None and not (user.is_superuser or getattr(user, 'role', '') == 'admin'):
            plant_field = cast(Any, self.fields['plant'])
            plant_field.queryset = _plant_scope_for_user(user)


class MeterForm(forms.ModelForm):
    class Meta:
        model = Meter
        fields = ['plant', 'meter_code', 'online', 'protocol']

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if user is not None and not (user.is_superuser or getattr(user, 'role', '') == 'admin'):
            plant_field = cast(Any, self.fields['plant'])
            plant_field.queryset = _plant_scope_for_user(user)


class EquipmentForm(forms.ModelForm):
    last_seen_at = forms.DateTimeField(
        required=False,
        widget=forms.DateTimeInput(
            attrs={
                'type': 'datetime-local',
                'placeholder': 'YYYY-MM-DD HH:MM',
                'step': '60',
            },
            format='%Y-%m-%dT%H:%M',
        ),
        input_formats=['%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M'],
    )

    class Meta:
        model = Equipment
        fields = ['plant', 'category', 'name', 'serial_number', 'health_status', 'online', 'last_seen_at']

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if not self.is_bound and not self.initial.get('last_seen_at') and not getattr(self.instance, 'pk', None):
            self.initial['last_seen_at'] = timezone.localtime(timezone.now()).strftime('%Y-%m-%dT%H:%M')
        if user is not None and not (user.is_superuser or getattr(user, 'role', '') == 'admin'):
            plant_field = cast(Any, self.fields['plant'])
            plant_field.queryset = _plant_scope_for_user(user)


class TransformerForm(forms.ModelForm):
    last_seen_at = forms.DateTimeField(
        required=False,
        widget=forms.DateTimeInput(
            attrs={
                'type': 'datetime-local',
                'placeholder': 'YYYY-MM-DD HH:MM',
                'step': '60',
            },
            format='%Y-%m-%dT%H:%M',
        ),
        input_formats=['%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M'],
    )

    class Meta:
        model = Transformer
        fields = ['plant', 'name', 'capacity_kva', 'status', 'online', 'manufacturer', 'last_seen_at']

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        self.fields['manufacturer'].widget.attrs.update({'placeholder': 'سازنده'})
        if not self.is_bound and not self.initial.get('last_seen_at') and not getattr(self.instance, 'pk', None):
            self.initial['last_seen_at'] = timezone.localtime(timezone.now()).strftime('%Y-%m-%dT%H:%M')
        if user is not None and not (user.is_superuser or getattr(user, 'role', '') == 'admin'):
            plant_field = cast(Any, self.fields['plant'])
            plant_field.queryset = _plant_scope_for_user(user)


class GatewayForm(forms.ModelForm):
    last_seen_at = forms.DateTimeField(
        required=False,
        widget=forms.DateTimeInput(
            attrs={
                'type': 'datetime-local',
                'placeholder': 'YYYY-MM-DD HH:MM',
                'step': '60',
            },
            format='%Y-%m-%dT%H:%M',
        ),
        input_formats=['%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M'],
    )

    class Meta:
        model = Gateway
        fields = ['plant', 'name', 'ip_address', 'protocol', 'online', 'firmware_version', 'last_seen_at']

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if not self.is_bound and not self.initial.get('last_seen_at') and not getattr(self.instance, 'pk', None):
            self.initial['last_seen_at'] = timezone.localtime(timezone.now()).strftime('%Y-%m-%dT%H:%M')
        if user is not None and not (user.is_superuser or getattr(user, 'role', '') == 'admin'):
            plant_field = cast(Any, self.fields['plant'])
            plant_field.queryset = _plant_scope_for_user(user)
