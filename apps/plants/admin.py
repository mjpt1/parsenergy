from django import forms
from django.contrib import admin
from django.utils import timezone
from .models import (
    Plant,
    Inverter,
    Sensor,
    Meter,
    TelemetryReading,
    EnvironmentalReading,
    PlantMembership,
    Equipment,
    Transformer,
    Gateway,
    PVModule,
)

class LastSeenAtAdminForm(forms.ModelForm):
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound and not self.initial.get('last_seen_at') and not getattr(self.instance, 'pk', None):
            self.initial['last_seen_at'] = timezone.localtime(timezone.now()).strftime('%Y-%m-%dT%H:%M')


class EquipmentAdminForm(LastSeenAtAdminForm):
    class Meta:
        model = Equipment
        fields = '__all__'


class TransformerAdminForm(LastSeenAtAdminForm):
    class Meta:
        model = Transformer
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'manufacturer' in self.fields:
            self.fields['manufacturer'].widget.attrs.update({'placeholder': 'سازنده'})


class GatewayAdminForm(LastSeenAtAdminForm):
    class Meta:
        model = Gateway
        fields = '__all__'


admin.site.register(Plant)
admin.site.register(PlantMembership)
admin.site.register(Inverter)
admin.site.register(Sensor)
admin.site.register(Meter)

@admin.register(Equipment)
class EquipmentAdmin(admin.ModelAdmin):
    form = EquipmentAdminForm


@admin.register(Transformer)
class TransformerAdmin(admin.ModelAdmin):
    form = TransformerAdminForm


@admin.register(Gateway)
class GatewayAdmin(admin.ModelAdmin):
    form = GatewayAdminForm

admin.site.register(TelemetryReading)
admin.site.register(EnvironmentalReading)


@admin.register(PVModule)
class PVModuleAdmin(admin.ModelAdmin):
    list_display = ('code', 'plant', 'row', 'col', 'status', 'temperature_c', 'string_code', 'inverter')
    list_filter = ('status', 'plant')
    search_fields = ('code', 'string_code', 'plant__name')
