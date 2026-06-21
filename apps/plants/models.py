from django.conf import settings
from django.db import models
from django.utils import timezone
from decimal import Decimal


class Plant(models.Model):
    class ConnectionStatus(models.TextChoices):
        ONLINE = 'online', 'Online'
        OFFLINE = 'offline', 'Offline'
        DEGRADED = 'degraded', 'Degraded'

    name = models.CharField(max_length=255)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='plants')
    external_code = models.CharField(max_length=64, unique=True)
    location_name = models.CharField(max_length=255)
    latitude = models.DecimalField(max_digits=10, decimal_places=6)
    longitude = models.DecimalField(max_digits=10, decimal_places=6)
    capacity_kw = models.DecimalField(max_digits=12, decimal_places=2)
    connection_status = models.CharField(max_length=16, choices=ConnectionStatus.choices, default=ConnectionStatus.ONLINE)
    timezone = models.CharField(max_length=64, default='Asia/Tehran')
    protocol = models.CharField(max_length=32, default='modbus')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class PlantGroup(models.Model):
    name = models.CharField(max_length=255)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='plant_groups')
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class PlantGroupMembership(models.Model):
    plant = models.ForeignKey(Plant, on_delete=models.CASCADE, related_name='group_memberships')
    group = models.ForeignKey(PlantGroup, on_delete=models.CASCADE, related_name='memberships')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('plant', 'group')


class PlantMembership(models.Model):
    class AccessLevel(models.TextChoices):
        OWNER = 'owner', 'Owner'
        OPERATOR = 'operator', 'Operator'
        ANALYST = 'analyst', 'Analyst'
        VIEWER = 'viewer', 'Viewer'

    plant = models.ForeignKey(Plant, on_delete=models.CASCADE, related_name='memberships')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='plant_memberships')
    access_level = models.CharField(max_length=16, choices=AccessLevel.choices, default=AccessLevel.VIEWER)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('plant', 'user')


class Inverter(models.Model):
    plant = models.ForeignKey(Plant, on_delete=models.CASCADE, related_name='inverters')
    serial_number = models.CharField(max_length=128)
    model_name = models.CharField(max_length=128)
    status = models.CharField(max_length=32, default='online')
    online = models.BooleanField(default=True)
    rated_power_kw = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0'))
    firmware_version = models.CharField(max_length=64, blank=True)
    manufacturer = models.CharField(max_length=128, blank=True)

    class Meta:
        unique_together = ('plant', 'serial_number')

    def __str__(self):
        return f'{self.plant.name} - {self.serial_number}'


class Sensor(models.Model):
    class SensorType(models.TextChoices):
        TEMPERATURE = 'temperature', 'Temperature'
        IRRADIANCE = 'irradiance', 'Irradiance'
        WIND = 'wind', 'Wind'
        HUMIDITY = 'humidity', 'Humidity'

    plant = models.ForeignKey(Plant, on_delete=models.CASCADE, related_name='sensors')
    name = models.CharField(max_length=128, default='sensor')
    sensor_type = models.CharField(max_length=32, choices=SensorType.choices)
    unit = models.CharField(max_length=32)
    is_active = models.BooleanField(default=True)


class Meter(models.Model):
    plant = models.ForeignKey(Plant, on_delete=models.CASCADE, related_name='meters')
    meter_code = models.CharField(max_length=128)
    online = models.BooleanField(default=True)
    protocol = models.CharField(max_length=64, default='modbus')


class Equipment(models.Model):
    class Category(models.TextChoices):
        INVERTER = 'inverter', 'Inverter'
        SENSOR = 'sensor', 'Sensor'
        METER = 'meter', 'Meter'
        OTHER = 'other', 'Other'

    class Health(models.TextChoices):
        HEALTHY = 'healthy', 'Healthy'
        WARNING = 'warning', 'Warning'
        CRITICAL = 'critical', 'Critical'

    plant = models.ForeignKey(Plant, on_delete=models.CASCADE, related_name='equipment')
    category = models.CharField(max_length=16, choices=Category.choices)
    name = models.CharField(max_length=128)
    serial_number = models.CharField(max_length=128, blank=True)
    health_status = models.CharField(max_length=16, choices=Health.choices, default=Health.HEALTHY)
    online = models.BooleanField(default=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)


class Transformer(models.Model):
    plant = models.ForeignKey(Plant, on_delete=models.CASCADE, related_name='transformers')
    name = models.CharField(max_length=128)
    capacity_kva = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0'))
    status = models.CharField(max_length=32, default='online')
    online = models.BooleanField(default=True)
    manufacturer = models.CharField(max_length=128, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f'{self.plant.name} - {self.name}'


class Gateway(models.Model):
    plant = models.ForeignKey(Plant, on_delete=models.CASCADE, related_name='gateways')
    name = models.CharField(max_length=128)
    ip_address = models.CharField(max_length=64)
    protocol = models.CharField(max_length=64, default='modbus')
    online = models.BooleanField(default=True)
    firmware_version = models.CharField(max_length=64, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)

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
        RAW = 'raw', 'Raw'
        MINUTE = 'minute', 'Minute'
        HOUR = 'hour', 'Hour'
        DAY = 'day', 'Day'
        MONTH = 'month', 'Month'

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
