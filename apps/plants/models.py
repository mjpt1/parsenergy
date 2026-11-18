import re

from django.conf import settings
from django.db import models
from django.utils import timezone
from decimal import Decimal


class Plant(models.Model):
    class ConnectionStatus(models.TextChoices):
        ONLINE = 'online', 'متصل'
        OFFLINE = 'offline', 'قطع'
        DEGRADED = 'degraded', 'ناپایدار'

    name = models.CharField(max_length=255, verbose_name='نام نیروگاه')
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='plants', verbose_name='مالک (مشتری)')
    external_code = models.CharField(max_length=64, unique=True, verbose_name='کد نیروگاه')
    location_name = models.CharField(max_length=255, verbose_name='محل نیروگاه')
    latitude = models.DecimalField(max_digits=10, decimal_places=6, verbose_name='عرض جغرافیایی')
    longitude = models.DecimalField(max_digits=10, decimal_places=6, verbose_name='طول جغرافیایی')
    capacity_kw = models.DecimalField(max_digits=12, decimal_places=2, verbose_name='ظرفیت (کیلووات)')
    connection_status = models.CharField(max_length=16, choices=ConnectionStatus.choices, default=ConnectionStatus.ONLINE, verbose_name='وضعیت اتصال')
    timezone = models.CharField(max_length=64, default='Asia/Tehran', verbose_name='منطقهٔ زمانی')
    protocol = models.CharField(max_length=32, default='modbus', verbose_name='پروتکل ارتباطی')
    # Physical panel/module grid for layout heat-map (rows × cols).
    layout_rows = models.PositiveSmallIntegerField(default=8, verbose_name='تعداد ردیف پنل‌ها')
    layout_cols = models.PositiveSmallIntegerField(default=12, verbose_name='تعداد ستون پنل‌ها')
    is_active = models.BooleanField(default=True, verbose_name='فعال')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    @property
    def active_capacity_kw(self):
        """kWp actually wired to an inverter; the full capacity until sections are recorded."""
        sections = [s for s in self.sections.all() if s.inverter_id]
        return sum((s.kwp for s in sections), Decimal('0')) if sections else self.capacity_kw


class PlantGroup(models.Model):
    name = models.CharField(max_length=255, verbose_name='نام گروه')
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='plant_groups', verbose_name='مالک')
    description = models.TextField(blank=True, verbose_name='توضیحات')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class PlantGroupMembership(models.Model):
    plant = models.ForeignKey(Plant, on_delete=models.CASCADE, related_name='group_memberships', verbose_name='نیروگاه')
    group = models.ForeignKey(PlantGroup, on_delete=models.CASCADE, related_name='memberships', verbose_name='گروه')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('plant', 'group')


class PlantMembership(models.Model):
    class AccessLevel(models.TextChoices):
        OWNER = 'owner', 'مالک'
        OPERATOR = 'operator', 'اپراتور'
        ANALYST = 'analyst', 'تحلیلگر'
        VIEWER = 'viewer', 'فقط مشاهده'

    plant = models.ForeignKey(Plant, on_delete=models.CASCADE, related_name='memberships')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='plant_memberships')
    access_level = models.CharField(max_length=16, choices=AccessLevel.choices, default=AccessLevel.VIEWER)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('plant', 'user')


class CloudAccount(models.Model):
    """An inverter maker's cloud API account (an application on its developer portal).

    One account serves every inverter registered under it; the inverters point
    here and the sync command reads them in batches.
    """

    class Provider(models.TextChoices):
        SOLAX = 'solax', 'SolaX Cloud'

    name = models.CharField('نام حساب', max_length=128)
    provider = models.CharField('سرویس', max_length=16, choices=Provider.choices, default=Provider.SOLAX)
    class BusinessType(models.IntegerChoices):
        RESIDENTIAL = 1, 'خانگی (Residential)'
        COMMERCIAL = 4, 'تجاری-صنعتی (C&I)'

    api_host = models.CharField('آدرس API', max_length=128, default='https://openapi-eu.solaxcloud.com')
    # SolaX answers only for the plant type the devices are registered under.
    business_type = models.PositiveSmallIntegerField('نوع نیروگاه در سولاکس', choices=BusinessType.choices,
                                                     default=BusinessType.RESIDENTIAL)
    client_id = models.CharField('Client ID', max_length=128)
    client_secret = models.CharField('Client Secret', max_length=256)
    # The provider allows one live token per application; it is kept here so
    # every sync reuses it instead of cancelling the previous one.
    access_token = models.TextField(blank=True, editable=False)
    token_expires_at = models.DateTimeField(null=True, blank=True, editable=False)
    last_error = models.CharField(max_length=500, blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.name} ({self.get_provider_display()})'


class Inverter(models.Model):
    class DataSource(models.TextChoices):
        MANUAL = 'manual', 'دستی / بدون اتصال'
        SOLAX = 'solax', 'SolaX Cloud'

    plant = models.ForeignKey(Plant, on_delete=models.CASCADE, related_name='inverters')
    serial_number = models.CharField(max_length=128)
    model_name = models.CharField(max_length=128)
    status = models.CharField(max_length=32, default='online')
    online = models.BooleanField(default=True)
    rated_power_kw = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0'))
    firmware_version = models.CharField(max_length=64, blank=True)
    manufacturer = models.CharField(max_length=128, blank=True)
    # --- Live data from the maker's cloud -----------------------------------
    data_source = models.CharField(max_length=16, choices=DataSource.choices, default=DataSource.MANUAL)
    cloud_account = models.ForeignKey(CloudAccount, on_delete=models.SET_NULL, null=True, blank=True,
                                      related_name='inverters')
    registration_no = models.CharField(max_length=64, blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    last_sync_error = models.CharField(max_length=500, blank=True)
    # The cloud reports today's yield as a running total; the last value is kept
    # so each sync stores only the energy produced since the previous one.
    last_daily_yield_kwh = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    # Latest detail reported by the cloud: temperature, phases, MPPT and PV strings.
    latest_data = models.JSONField(default=dict, blank=True)

    class Meta:
        unique_together = ('plant', 'serial_number')

    def __str__(self):
        return f'{self.plant.name} - {self.serial_number}'


class Sensor(models.Model):
    class SensorType(models.TextChoices):
        TEMPERATURE = 'temperature', 'دما'
        IRRADIANCE = 'irradiance', 'تابش'
        WIND = 'wind', 'باد'
        HUMIDITY = 'humidity', 'رطوبت'

    plant = models.ForeignKey(Plant, on_delete=models.CASCADE, related_name='sensors', verbose_name='نیروگاه')
    name = models.CharField(max_length=128, default='sensor', verbose_name='نام سنسور')
    sensor_type = models.CharField(max_length=32, choices=SensorType.choices, verbose_name='نوع سنسور')
    unit = models.CharField(max_length=32, verbose_name='واحد اندازه‌گیری')
    is_active = models.BooleanField(default=True, verbose_name='فعال')

    def __str__(self):
        return self.name


class Meter(models.Model):
    plant = models.ForeignKey(Plant, on_delete=models.CASCADE, related_name='meters', verbose_name='نیروگاه')
    meter_code = models.CharField(max_length=128, verbose_name='کد کنتور')
    online = models.BooleanField(default=True, verbose_name='متصل است')
    protocol = models.CharField(max_length=64, default='modbus', verbose_name='پروتکل ارتباطی')

    def __str__(self):
        return self.meter_code


class Equipment(models.Model):
    class Category(models.TextChoices):
        INVERTER = 'inverter', 'اینورتر'
        SENSOR = 'sensor', 'سنسور'
        METER = 'meter', 'کنتور'
        OTHER = 'other', 'سایر'

    class Health(models.TextChoices):
        HEALTHY = 'healthy', 'سالم'
        WARNING = 'warning', 'هشدار'
        CRITICAL = 'critical', 'بحرانی'

    plant = models.ForeignKey(Plant, on_delete=models.CASCADE, related_name='equipment', verbose_name='نیروگاه')
    category = models.CharField(max_length=16, choices=Category.choices, verbose_name='نوع تجهیز')
    name = models.CharField(max_length=128, verbose_name='نام تجهیز')
    serial_number = models.CharField(max_length=128, blank=True, verbose_name='شماره سریال')
    health_status = models.CharField(max_length=16, choices=Health.choices, default=Health.HEALTHY, verbose_name='وضعیت سلامت')
    online = models.BooleanField(default=True, verbose_name='متصل است')
    last_seen_at = models.DateTimeField(null=True, blank=True, verbose_name='آخرین اتصال')

    def __str__(self):
        return self.name


class Transformer(models.Model):
    plant = models.ForeignKey(Plant, on_delete=models.CASCADE, related_name='transformers', verbose_name='نیروگاه')
    name = models.CharField(max_length=128, verbose_name='نام ترانس')
    capacity_kva = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0'), verbose_name='ظرفیت (کیلوولت‌آمپر)')
    status = models.CharField(max_length=32, default='online', verbose_name='وضعیت')
    online = models.BooleanField(default=True, verbose_name='متصل است')
    manufacturer = models.CharField(max_length=128, blank=True, verbose_name='سازنده')
    last_seen_at = models.DateTimeField(null=True, blank=True, verbose_name='آخرین اتصال')

    def __str__(self):
        return f'{self.plant.name} - {self.name}'


class Gateway(models.Model):
    plant = models.ForeignKey(Plant, on_delete=models.CASCADE, related_name='gateways', verbose_name='نیروگاه')
    name = models.CharField(max_length=128, verbose_name='نام گیت‌وی')
    ip_address = models.CharField(max_length=64, verbose_name='آدرس IP')
    protocol = models.CharField(max_length=64, default='modbus', verbose_name='پروتکل ارتباطی')
    online = models.BooleanField(default=True, verbose_name='متصل است')
    firmware_version = models.CharField(max_length=64, blank=True, verbose_name='نسخهٔ نرم‌افزار')
    last_seen_at = models.DateTimeField(null=True, blank=True, verbose_name='آخرین اتصال')

    def __str__(self):
        return f'{self.plant.name} - {self.name}'


class RealtimeMeasurement(models.Model):
    class Parameter(models.TextChoices):
        VOLTAGE = 'voltage', 'Voltage (V)'
        CURRENT = 'current', 'Current (A)'
        POWER = 'power', 'Power (W)'
        ENERGY = 'energy', 'Energy (kWh)'
        TEMPERATURE = 'temperature', 'Temperature (°C)'
        IRRADIANCE = 'irradiance', 'Irradiance (W/m²)'
        FREQUENCY = 'frequency', 'Frequency (Hz)'

    timestamp = models.DateTimeField(default=timezone.now, db_index=True)
    plant = models.ForeignKey(Plant, on_delete=models.CASCADE, related_name='realtime_measurements')
    equipment = models.ForeignKey(Equipment, on_delete=models.CASCADE, related_name='realtime_measurements')
    parameter = models.CharField(max_length=32, choices=Parameter.choices)
    value = models.DecimalField(max_digits=15, decimal_places=6)
    unit = models.CharField(max_length=16)
    quality = models.CharField(max_length=16, default='good')  # good, bad, uncertain

    class Meta:
        indexes = [
            models.Index(fields=['timestamp', 'plant']),
            models.Index(fields=['equipment', 'parameter']),
        ]

    def __str__(self):
        return f'{self.plant.name} - {self.equipment.name} - {self.parameter}: {self.value} {self.unit}'


class HistoricalMeasurement(models.Model):
    class Aggregation(models.TextChoices):
        RAW = 'raw', 'خام'
        MINUTE = 'minute', 'دقیقه‌ای'
        HOUR = 'hour', 'ساعتی'
        DAY = 'day', 'روزانه'
        MONTH = 'month', 'ماهانه'

    timestamp = models.DateTimeField()
    plant = models.ForeignKey(Plant, on_delete=models.CASCADE, related_name='historical_measurements')
    equipment = models.ForeignKey(Equipment, on_delete=models.CASCADE, related_name='historical_measurements')
    parameter = models.CharField(max_length=32, choices=RealtimeMeasurement.Parameter.choices)
    value = models.DecimalField(max_digits=15, decimal_places=6)
    unit = models.CharField(max_length=16)
    aggregation = models.CharField(max_length=16, choices=Aggregation.choices, default=Aggregation.RAW)
    quality = models.CharField(max_length=16, default='good')

    class Meta:
        indexes = [
            models.Index(fields=['timestamp', 'plant', 'aggregation']),
            models.Index(fields=['equipment', 'parameter', 'aggregation']),
        ]

    def __str__(self):
        return f'{self.plant.name} - {self.equipment.name} - {self.parameter} ({self.aggregation}): {self.value} {self.unit}'


class TelemetryReading(models.Model):
    plant = models.ForeignKey(Plant, on_delete=models.CASCADE, related_name='telemetry')
    inverter = models.ForeignKey(Inverter, on_delete=models.CASCADE, related_name='telemetry_readings', null=True, blank=True)
    power_kw = models.DecimalField(max_digits=12, decimal_places=3)
    voltage_v = models.DecimalField(max_digits=12, decimal_places=3)
    current_a = models.DecimalField(max_digits=12, decimal_places=3)
    frequency_hz = models.DecimalField(max_digits=12, decimal_places=3)
    energy_kwh = models.DecimalField(max_digits=14, decimal_places=3, default=Decimal('0'))
    status = models.CharField(max_length=64, default='normal')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=('plant', '-created_at')),
            models.Index(fields=('inverter', '-created_at')),
        ]


class EnvironmentalReading(models.Model):
    plant = models.ForeignKey(Plant, on_delete=models.CASCADE, related_name='environmental_readings')
    temperature_c = models.DecimalField(max_digits=8, decimal_places=2)
    irradiance_wm2 = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)


class PVModule(models.Model):
    """One physical PV module/cell in the plant layout grid.

    Temperature and status drive the buyer/technical heat-map. Status is kept
    in sync from temperature thresholds unless explicitly set to FAULT/OFFLINE.
    """

    class Status(models.TextChoices):
        OK = 'ok', 'عادی'
        WARN = 'warn', 'هشدار دما'
        HOT = 'hot', 'داغ'
        OFFLINE = 'offline', 'آفلاین'
        FAULT = 'fault', 'خطا'

    WARN_TEMP_C = Decimal('55')
    HOT_TEMP_C = Decimal('70')

    plant = models.ForeignKey(Plant, on_delete=models.CASCADE, related_name='modules')
    row = models.PositiveSmallIntegerField()
    col = models.PositiveSmallIntegerField()
    code = models.CharField(max_length=64, blank=True)
    string_code = models.CharField(max_length=32, blank=True)
    inverter = models.ForeignKey(
        Inverter, on_delete=models.SET_NULL, null=True, blank=True, related_name='modules')
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OK)
    temperature_c = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal('40'))
    relative_power_pct = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal('100'))
    last_seen_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('plant', 'row', 'col')
        indexes = [
            models.Index(fields=['plant', 'status']),
            models.Index(fields=['plant', 'row', 'col']),
        ]
        ordering = ['row', 'col']

    def __str__(self):
        return self.code or f'{self.plant_id}-R{self.row}-C{self.col}'

    def apply_temperature_status(self, *, save=False):
        """Derive warn/hot/ok from temperature unless offline/fault."""
        if self.status in (self.Status.OFFLINE, self.Status.FAULT):
            return self.status
        temp = self.temperature_c or Decimal('0')
        if temp >= self.HOT_TEMP_C:
            self.status = self.Status.HOT
        elif temp >= self.WARN_TEMP_C:
            self.status = self.Status.WARN
        else:
            self.status = self.Status.OK
        if save:
            self.save(update_fields=['status', 'updated_at'])
        return self.status

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = f'C-R{self.row}-C{self.col}'
        if self.status not in (self.Status.OFFLINE, self.Status.FAULT):
            self.apply_temperature_status(save=False)
        super().save(*args, **kwargs)


_BLOCK_DIGITS = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')


def parse_panel_blocks(text):
    """'18x5, 18x5, 7x1' -> [(18, 5), (18, 5), (7, 1)] as (columns, rows)."""
    blocks = []
    for part in re.split(r'[,،+]', str(text or '').translate(_BLOCK_DIGITS)):
        part = part.strip().lower().replace('×', 'x').replace('*', 'x')
        if not part:
            continue
        match = re.fullmatch(r'(\d+)\s*x\s*(\d+)', part)
        if not match:
            raise ValueError(part)
        cols, rows = int(match.group(1)), int(match.group(2))
        if not (1 <= cols <= 60 and 1 <= rows <= 40):
            raise ValueError(part)
        blocks.append((cols, rows))
    if not blocks:
        raise ValueError('empty')
    return blocks


class PlantTariff(models.Model):
    """Electricity sale rate of a plant, in force from `valid_from` until the next one."""

    plant = models.ForeignKey(Plant, on_delete=models.CASCADE, related_name='tariffs', verbose_name='نیروگاه')
    rate_rial_per_kwh = models.DecimalField(max_digits=14, decimal_places=2, verbose_name='نرخ (ریال بر کیلووات‌ساعت)')
    valid_from = models.DateField(verbose_name='شروع اعمال')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='+', verbose_name='ثبت‌کننده')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('plant', 'valid_from')
        ordering = ['plant_id', 'valid_from']
        verbose_name = 'نرخ خرید برق'
        verbose_name_plural = 'نرخ‌های خرید برق'

    def __str__(self):
        return f'{self.plant} — {self.rate_rial_per_kwh}'


class PlantSection(models.Model):
    """One roof or array of a plant, as it was actually built."""

    plant = models.ForeignKey(Plant, on_delete=models.CASCADE, related_name='sections', verbose_name='نیروگاه')
    name = models.CharField(max_length=120, verbose_name='نام سوله')
    inverter = models.ForeignKey(Inverter, on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name='sections', verbose_name='اینورتر متصل')
    blocks = models.CharField(max_length=120, verbose_name='بلوک‌های پنل')
    panel_watt = models.DecimalField(max_digits=7, decimal_places=2, verbose_name='توان هر پنل (وات)')
    panel_length_m = models.DecimalField(max_digits=5, decimal_places=3, null=True, blank=True,
                                         verbose_name='طول پنل (متر)')
    panel_width_m = models.DecimalField(max_digits=5, decimal_places=3, null=True, blank=True,
                                        verbose_name='عرض پنل (متر)')
    roof_area_m2 = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True,
                                       verbose_name='مساحت سوله (مترمربع)')
    tilt_text = models.CharField(max_length=40, blank=True, verbose_name='زاویهٔ شیب')
    azimuth_deg = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True,
                                      verbose_name='جهت (آزیموت، درجه)')
    sort_order = models.PositiveSmallIntegerField(default=0, verbose_name='ترتیب نمایش')

    class Meta:
        ordering = ['sort_order', 'id']
        verbose_name = 'سوله'
        verbose_name_plural = 'سوله‌ها'

    def __str__(self):
        return f'{self.plant} — {self.name}'

    @property
    def parsed_blocks(self):
        return parse_panel_blocks(self.blocks)

    @property
    def panel_count(self):
        return sum(cols * rows for cols, rows in self.parsed_blocks)

    @property
    def kwp(self):
        return self.panel_count * self.panel_watt / 1000

    @property
    def panels_area_m2(self):
        if not (self.panel_length_m and self.panel_width_m):
            return None
        return self.panel_count * self.panel_length_m * self.panel_width_m

    @property
    def roof_usage_pct(self):
        area = self.panels_area_m2
        return area * 100 / self.roof_area_m2 if area is not None and self.roof_area_m2 else None


class PlantBill(models.Model):
    """One official settlement statement, copied from the Mehrsun portal."""

    plant = models.ForeignKey(Plant, on_delete=models.CASCADE, related_name='bills', verbose_name='نیروگاه')
    customer_name = models.CharField(max_length=160, blank=True, verbose_name='نام مشتری')
    file_number = models.CharField(max_length=40, blank=True, verbose_name='شماره پرونده')
    period_start = models.DateField(verbose_name='از تاریخ')
    period_end = models.DateField(verbose_name='تا تاریخ')
    energy_kwh = models.DecimalField(max_digits=14, decimal_places=2, verbose_name='انرژی تولیدشده')
    benchmark_kwh = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True, verbose_name='معیار')
    income_rial = models.DecimalField(max_digits=18, decimal_places=0, verbose_name='درآمد تولید')
    balance_rial = models.DecimalField(max_digits=18, decimal_places=0, default=0, verbose_name='بدهکاری / بستانکاری')
    net_rial = models.DecimalField(max_digits=18, decimal_places=0, verbose_name='خالص پرداختی')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='+', verbose_name='ثبت‌کننده')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('plant', 'period_end')
        ordering = ['-period_end']
        verbose_name = 'صورتحساب نیروگاه'
        verbose_name_plural = 'صورتحساب‌های نیروگاه'

    def __str__(self):
        return f'{self.plant} — {self.period_end}'


class InverterSample(models.Model):
    """Compact history of the detail an inverter reports at each sync, for charts."""

    inverter = models.ForeignKey(Inverter, on_delete=models.CASCADE, related_name='samples')
    data = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=('inverter', '-created_at'))]
        verbose_name = 'نمونهٔ دادهٔ اینورتر'
        verbose_name_plural = 'نمونه‌های دادهٔ اینورتر'
