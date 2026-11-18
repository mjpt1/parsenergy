from decimal import Decimal

from django import forms
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _
from typing import Any, cast
from .models import (
    Plant, PlantGroup, PlantGroupMembership, Inverter, Sensor, Meter,
    Equipment, Transformer, Gateway, CloudAccount, PlantSection, parse_panel_blocks,
)


def _plant_scope_for_user(user):
    # Same rule as the views: technical/operations staff work on every plant,
    # which are owned by customers. A private copy here left them unable to
    # pick any plant in the inverter, sensor and meter forms.
    if user is None:
        return Plant.objects.all()
    from .scoping import plant_scope_for_user
    return plant_scope_for_user(user)


PROTOCOL_CHOICES = [('modbus', 'Modbus'), ('mqtt', 'MQTT'), ('opcua', 'OPC-UA'), ('http', 'HTTP')]
DEVICE_STATUS_CHOICES = [('online', 'متصل'), ('offline', 'قطع'), ('degraded', 'ناپایدار'), ('fault', 'خطا')]


def as_select(form, name, choices):
    """Show a free-text column as a list, keeping any older value it already holds."""
    field = form.fields[name]
    current = form.instance.pk and getattr(form.instance, name)
    options = list(choices)
    if current and current not in dict(options):
        options.append((current, current))
    form.fields[name] = forms.ChoiceField(
        label=field.label, help_text=field.help_text, required=field.required,
        initial=field.initial, choices=options)


def _person_label(user):
    name = user.get_full_name() or user.username
    return f'{name} — {user.phone_number}' if user.phone_number else name


def _next_plant_code():
    number = Plant.objects.count() + 1
    while Plant.objects.filter(external_code=f'PLT-{number:04d}').exists():
        number += 1
    return f'PLT-{number:04d}'


class PlantForm(forms.ModelForm):
    class Meta:
        model = Plant
        fields = ['name', 'owner', 'location_name', 'capacity_kw', 'latitude', 'longitude',
                  'external_code', 'connection_status', 'protocol', 'layout_rows', 'layout_cols', 'is_active']
        help_texts = {
            'location_name': 'مثلاً «یزد، شهرک صنعتی».',
            'latitude': 'با کلیک روی نقشهٔ پایین خودکار پر می‌شود.',
            'longitude': 'با کلیک روی نقشهٔ پایین خودکار پر می‌شود.',
            'external_code': 'اگر خالی بماند، سامانه خودش یک کد می‌سازد.',
            'layout_rows': 'برای نمایش چیدمان پنل‌ها.',
            'layout_cols': 'برای نمایش چیدمان پنل‌ها.',
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        self.fields['external_code'].required = False
        as_select(self, 'protocol', PROTOCOL_CHOICES)
        owner_field = cast(Any, self.fields['owner'])
        owner_field.label_from_instance = _person_label
        if user is None or user.is_superuser or getattr(user, 'role', '') == 'admin':
            return
        if self.instance.pk:
            # Ownership decides who sees the plant in the customer panel, so
            # moving an existing plant stays with management.
            owner_field.disabled = True
            owner_field.help_text = 'تغییر مالک نیروگاه ثبت‌شده فقط با مدیر است.'
        else:
            owner_field.queryset = get_user_model().objects.filter(
                role__in=('customer', 'owner'), is_active=True).order_by('first_name', 'last_name', 'username')
            owner_field.required = False
            owner_field.empty_label = 'هنوز مشتری مشخص نیست'
            owner_field.help_text = 'اگر مشتری هنوز حساب ندارد، خالی بگذارید.'

    def clean_external_code(self):
        code = (self.cleaned_data.get('external_code') or '').strip()
        return code or self.instance.external_code or _next_plant_code()

    def clean(self):
        """Reject a plant pinned at (0, 0).

        Those coordinates sit in the Atlantic Ocean, so the fleet map zooms to
        open water and looks broken. Leaving the coordinate boxes at zero is
        the usual cause, so point the user at the map picker instead.
        """
        cd = super().clean()
        lat, lng = cd.get('latitude'), cd.get('longitude')
        if (lat is not None and lng is not None
                and abs(lat) < Decimal('0.5') and abs(lng) < Decimal('0.5')):
            self.add_error('latitude', _(
                'مختصات نزدیک نقطهٔ صفر است (وسط اقیانوس). محل نیروگاه را روی نقشهٔ زیر '
                'انتخاب کنید تا عرض و طول جغرافیایی درست پر شود.'))
        return cd


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
        fields = ['plant', 'serial_number', 'model_name', 'manufacturer', 'rated_power_kw', 'firmware_version',
                  'status', 'online', 'data_source', 'cloud_account', 'registration_no']
        labels = {
            'plant': 'نیروگاه', 'serial_number': 'شماره سریال اینورتر (SN)', 'model_name': 'مدل',
            'manufacturer': 'سازنده', 'rated_power_kw': 'توان نامی (kW)', 'firmware_version': 'نسخهٔ فریمور',
            'status': 'وضعیت', 'online': 'آنلاین', 'data_source': 'منبع داده',
            'cloud_account': 'حساب ابری', 'registration_no': 'شماره ثبت دانگل (Registration No.)',
        }
        help_texts = {
            'serial_number': 'دقیقاً همان SN که در پنل سولاکس (Device → Inverter) نوشته شده؛ معمولاً ۱۴ حرف و عدد.',
            'firmware_version': 'اختیاری.',
            'status': 'برای اینورتر متصل به سولاکس خودکار به‌روز می‌شود.',
            'data_source': '«SolaX Cloud» یعنی داده هر ۵ دقیقه خودکار از سولاکس خوانده می‌شود.',
            'cloud_account': 'حسابی که Client ID و Client Secret همین اینورتر در آن ثبت شده است.',
            'registration_no': 'اختیاری؛ شمارهٔ روی دانگل وای‌فای/LAN (برای پیگیری).',
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        self.fields['firmware_version'].required = False
        self.fields['data_source'].required = False
        if user is not None and not (user.is_superuser or getattr(user, 'role', '') == 'admin'):
            plant_field = cast(Any, self.fields['plant'])
            plant_field.queryset = _plant_scope_for_user(user)

    def clean_data_source(self):
        return self.cleaned_data.get('data_source') or Inverter.DataSource.MANUAL

    def clean_serial_number(self):
        # Copied from the cloud panel with spaces or lower case, it would never match.
        return self.cleaned_data['serial_number'].strip().upper()

    def clean(self):
        data = super().clean()
        if data.get('data_source') == Inverter.DataSource.SOLAX and not data.get('cloud_account'):
            self.add_error('cloud_account', 'برای اتصال به سولاکس، حساب ابری را انتخاب کنید.')
        return data


class CloudAccountForm(forms.ModelForm):
    class Meta:
        model = CloudAccount
        fields = ['name', 'provider', 'business_type', 'api_host', 'client_id', 'client_secret']
        help_texts = {
            'name': 'مثلاً «سولاکس پالایشگاه یزد».',
            'business_type': 'همان «Plant Type» در پنل سولاکس (Devices): C&I یعنی تجاری-صنعتی.',
            'api_host': 'پیش‌فرض برای حساب‌های اروپا/بین‌المللی درست است؛ فقط اگر سولاکس آدرس دیگری داده عوض کنید.',
            'client_id': 'از developer.solaxcloud.com → Application → Authorization.',
            'client_secret': 'از همان صفحه. پس از ذخیره نمایش داده نمی‌شود؛ برای نگه‌داشتن مقدار فعلی خالی بگذارید.',
        }
        widgets = {'client_secret': forms.PasswordInput(render_value=False, attrs={'autocomplete': 'new-password'})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields['client_secret'].required = False

    def clean_client_secret(self):
        value = self.cleaned_data.get('client_secret', '').strip()
        return value or self.instance.client_secret

    def save(self, commit=True):
        obj = super().save(commit=False)
        new_secret = (self.data.get(self.add_prefix('client_secret')) or '').strip()
        if new_secret or {'client_id', 'api_host'} & set(self.changed_data):
            obj.access_token, obj.token_expires_at = '', None   # new credentials need a new token
        if commit:
            obj.save()
        return obj


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
        as_select(self, 'protocol', PROTOCOL_CHOICES)
        if user is not None and not (user.is_superuser or getattr(user, 'role', '') == 'admin'):
            plant_field = cast(Any, self.fields['plant'])
            plant_field.queryset = _plant_scope_for_user(user)


class EquipmentForm(forms.ModelForm):
    class Meta:
        model = Equipment
        fields = ['plant', 'category', 'name', 'serial_number', 'health_status', 'online']

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if user is not None and not (user.is_superuser or getattr(user, 'role', '') == 'admin'):
            plant_field = cast(Any, self.fields['plant'])
            plant_field.queryset = _plant_scope_for_user(user)


class TransformerForm(forms.ModelForm):
    class Meta:
        model = Transformer
        fields = ['plant', 'name', 'capacity_kva', 'status', 'online', 'manufacturer']

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        as_select(self, 'status', DEVICE_STATUS_CHOICES)
        if user is not None and not (user.is_superuser or getattr(user, 'role', '') == 'admin'):
            plant_field = cast(Any, self.fields['plant'])
            plant_field.queryset = _plant_scope_for_user(user)


class GatewayForm(forms.ModelForm):
    class Meta:
        model = Gateway
        fields = ['plant', 'name', 'ip_address', 'protocol', 'online', 'firmware_version']

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        as_select(self, 'protocol', PROTOCOL_CHOICES)
        if user is not None and not (user.is_superuser or getattr(user, 'role', '') == 'admin'):
            plant_field = cast(Any, self.fields['plant'])
            plant_field.queryset = _plant_scope_for_user(user)


class PlantSectionForm(forms.ModelForm):
    class Meta:
        model = PlantSection
        fields = ['plant', 'name', 'inverter', 'blocks', 'panel_watt', 'panel_length_m', 'panel_width_m',
                  'roof_area_m2', 'tilt_text', 'azimuth_deg', 'sort_order']
        help_texts = {
            'inverter': 'تا وقتی اینورتر این سوله به پایش وصل نشده، خالی بماند.',
            'blocks': 'هر بلوک به شکل ستون×ردیف. نمونه: 18x5, 18x5, 7x1',
            'tilt_text': 'نمونه: ۱۰ تا ۱۵ درجه',
            'azimuth_deg': 'جنوب = ۱۸۰ درجه',
        }

    def clean_blocks(self):
        value = self.cleaned_data['blocks']
        try:
            blocks = parse_panel_blocks(value)
        except ValueError:
            raise forms.ValidationError('بلوک‌ها را به شکل 18x5, 18x5, 7x1 وارد کنید.')
        return ', '.join(f'{cols}x{rows}' for cols, rows in blocks)

    def clean(self):
        data = super().clean()
        plant, inverter = data.get('plant'), data.get('inverter')
        if plant and inverter and inverter.plant_id != plant.pk:
            self.add_error('inverter', 'این اینورتر متعلق به نیروگاه انتخاب‌شده نیست.')
        return data
