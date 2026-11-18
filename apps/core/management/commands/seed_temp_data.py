from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.alerts.models import AlertEvent, AlertRule, Notification
from apps.core.models import APIConnection, AuditLog, DatabaseBackup, ProtocolAdapter, ServerHealthMetric, SystemParameter
from apps.plants.models import (
    EnvironmentalReading,
    Equipment,
    Inverter,
    Meter,
    Plant,
    PlantMembership,
    Sensor,
    TelemetryReading,
)


class Command(BaseCommand):
    help = 'Seed temporary multi-plant demo data. Safe to remove with clear_temp_data command.'

    def add_arguments(self, parser):
        parser.add_argument('--tag', default='TMPDEMO', help='Prefix tag for temporary data set')

    def _owner_username(self, tag: str, index: int) -> str:
        return f"{tag.lower()}_owner{index}"

    def _cleanup_previous_seed(self, tag: str):
        plant_qs = Plant.objects.filter(external_code__startswith=f'{tag}-')
        AlertRule.objects.filter(plant__in=plant_qs).delete()
        TelemetryReading.objects.filter(plant__in=plant_qs).delete()
        EnvironmentalReading.objects.filter(plant__in=plant_qs).delete()
        PlantMembership.objects.filter(plant__in=plant_qs).delete()
        Inverter.objects.filter(plant__in=plant_qs).delete()
        Sensor.objects.filter(plant__in=plant_qs).delete()
        Meter.objects.filter(plant__in=plant_qs).delete()
        Equipment.objects.filter(plant__in=plant_qs).delete()
        plant_qs.delete()

        SystemParameter.objects.filter(key__startswith=f'{tag}.').delete()
        APIConnection.objects.filter(name__startswith=f'{tag} ').delete()
        ProtocolAdapter.objects.filter(name__startswith=f'{tag} ').delete()
        DatabaseBackup.objects.filter(file_path__icontains=tag.lower()).delete()
        ServerHealthMetric.objects.filter(hostname__startswith=tag.lower()).delete()
        AuditLog.objects.filter(action__startswith=f'{tag}.').delete()

    def handle(self, *args, **options):
        tag = str(options['tag']).strip().upper()
        User = get_user_model()

        self._cleanup_previous_seed(tag)

        owners = []
        for index in range(1, 4):
            username = self._owner_username(tag, index)
            owner, created = User.objects.get_or_create(
                username=username,
                defaults={
                    'email': f'{username}@solarops.local',
                    'role': 'owner',
                    'phone_number': f'+9891200000{index}',
                },
            )
            if created:
                owner.set_password('Owner12345!')
                owner.save()
            owners.append(owner)

        plants_data = [
            ('Tehran North', Decimal('35.765430'), Decimal('51.413214'), Decimal('2500.00'), 'modbus'),
            ('Qom Solar Park', Decimal('34.639944'), Decimal('50.875942'), Decimal('1800.00'), 'mqtt'),
            ('Isfahan Desert', Decimal('32.654627'), Decimal('51.668021'), Decimal('3200.00'), 'http'),
            ('Yazd Grid Edge', Decimal('31.897423'), Decimal('54.356856'), Decimal('2100.00'), 'modbus'),
            ('Kerman Valley', Decimal('30.283937'), Decimal('57.083362'), Decimal('2750.00'), 'opcua'),
        ]

        created_plants = []

        for index, row in enumerate(plants_data, start=1):
            location_name, lat, lng, capacity, protocol = row
            owner = owners[(index - 1) % len(owners)]
            external_code = f'{tag}-PLANT-{index:03d}'
            plant = Plant.objects.create(
                name=f'{tag} Solar Plant {index:03d}',
                owner=owner,
                external_code=external_code,
                location_name=location_name,
                latitude=lat,
                longitude=lng,
                capacity_kw=capacity,
                connection_status='online' if index % 2 else 'degraded',
                timezone='Asia/Tehran',
                protocol=protocol,
                is_active=True,
            )
            created_plants.append(plant)

            PlantMembership.objects.create(plant=plant, user=owner, access_level='owner', active=True)

            for inverter_idx in range(1, 3):
                inverter = Inverter.objects.create(
                    plant=plant,
                    serial_number=f'{tag}-INV-{index:03d}-{inverter_idx}',
                    model_name='SUN-110K',
                    status='online',
                    online=True,
                    rated_power_kw=Decimal('110.00'),
                    firmware_version='2.1.0',
                    manufacturer='SolarTech',
                )

                for hour in range(0, 24):
                    base = Decimal('450.0') + Decimal(index * 35) + Decimal(inverter_idx * 12)
                    power = base + Decimal((hour % 6) * 18)
                    TelemetryReading.objects.create(
                        plant=plant,
                        inverter=inverter,
                        power_kw=power,
                        voltage_v=Decimal('690.0') + Decimal(inverter_idx),
                        current_a=Decimal('820.0') + Decimal(hour * 2),
                        frequency_hz=Decimal('50.0'),
                        energy_kwh=power * Decimal('0.65'),
                        status='normal' if hour % 7 else 'warning',
                    )

            Sensor.objects.create(plant=plant, name=f'{tag} Temp Sensor {index}', sensor_type='temperature', unit='C', is_active=True)
            Sensor.objects.create(plant=plant, name=f'{tag} Irr Sensor {index}', sensor_type='irradiance', unit='W/m²', is_active=True)

            Meter.objects.create(plant=plant, meter_code=f'{tag}-MTR-{index:03d}', online=True, protocol=protocol)

            Equipment.objects.create(
                plant=plant,
                category='inverter',
                name=f'{tag} Main Inverter Rack {index}',
                serial_number=f'{tag}-EQ-{index:03d}',
                health_status='healthy',
                online=True,
                last_seen_at=timezone.now(),
            )

            for sample in range(1, 13):
                EnvironmentalReading.objects.create(
                    plant=plant,
                    temperature_c=Decimal('27.0') + Decimal(sample) / Decimal('10'),
                    irradiance_wm2=Decimal('800.0') + Decimal(sample * 8),
                )

            voltage_rule = AlertRule.objects.create(
                plant=plant,
                name=f'{tag} High Voltage Rule {index}',
                metric='voltage_v',
                threshold_value=Decimal('710.000'),
                comparator='>',
                severity='high',
                channels='email,sms,push',
                enabled=True,
            )

            event = AlertEvent.objects.create(
                rule=voltage_rule,
                message=f'{tag} simulated over-voltage at plant {index}',
                severity='high',
                acknowledged=False,
            )

            for channel in [Notification.Channel.EMAIL, Notification.Channel.SMS, Notification.Channel.PUSH]:
                notification = Notification.objects.create(
                    user=owner,
                    channel=channel,
                    title=f'{tag} alert {index}',
                    body=f'{tag} notification for {plant.name}',
                    sent=True,
                    delivery_status='sent',
                    provider_message_id=f'{tag}-{channel}-{index}',
                    delivered_at=timezone.now(),
                )

        SystemParameter.objects.create(
            key=f'{tag}.tariff_per_kwh',
            value='1.35',
            description=f'{tag} temporary tariff parameter',
            is_secret=False,
        )
        SystemParameter.objects.create(
            key=f'{tag}.maintenance_buffer_pct',
            value='7.5',
            description=f'{tag} temporary maintenance factor',
            is_secret=False,
        )

        APIConnection.objects.create(
            name=f'{tag} Dispatch API',
            base_url='https://example-solar-dispatch.local/api',
            auth_type='token',
            token='temp-token',
            is_active=True,
            last_success_at=timezone.now(),
        )

        ProtocolAdapter.objects.create(
            name=f'{tag} MQTT Adapter',
            protocol='mqtt',
            endpoint='mqtt://broker.local:1883',
            config={'qos': 1, 'retain': False},
            enabled=True,
        )

        DatabaseBackup.objects.create(
            file_path=f'/tmp/backups/{tag.lower()}_backup_001.dump',
            file_size_bytes=120_000_000,
            status='success',
            notes=f'{tag} temporary backup sample',
        )

        ServerHealthMetric.objects.create(
            hostname=f'{tag.lower()}-app-01',
            cpu_percent=Decimal('32.50'),
            memory_percent=Decimal('58.20'),
            disk_percent=Decimal('41.70'),
            queue_depth=3,
        )

        AuditLog.objects.create(
            actor=None,
            action=f'{tag}.seed',
            target_type='dataset',
            target_id=tag,
            metadata={'plants': len(created_plants), 'owners': len(owners)},
            ip_address='127.0.0.1',
        )

        self.stdout.write(self.style.SUCCESS(f'Temporary dataset seeded with tag: {tag}'))
        self.stdout.write(self.style.SUCCESS('Owners created (if missing):'))
        for owner in owners:
            self.stdout.write(self.style.SUCCESS(f'  - {owner.username} / Owner12345!'))
        self.stdout.write(self.style.SUCCESS('Use this command to remove it later:'))
        self.stdout.write(self.style.SUCCESS(f'  python manage.py clear_temp_data --tag {tag}'))
