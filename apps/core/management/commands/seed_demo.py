from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.plants.models import Plant, Inverter, Sensor, Meter, Equipment, TelemetryReading, EnvironmentalReading, PlantMembership
from apps.alerts.models import AlertRule


class Command(BaseCommand):
    help = 'Create demo admin/owner accounts, sample plants, and operational data.'

    def handle(self, *args, **options):
        User = get_user_model()

        admin_user, admin_created = User.objects.get_or_create(
            username='admin',
            defaults={
                'email': 'admin@solarops.local',
                'role': 'admin',
                'is_staff': True,
                'is_superuser': True,
            },
        )
        if admin_created:
            admin_user.set_password('Admin12345!')
            admin_user.save()

        owner_user, owner_created = User.objects.get_or_create(
            username='owner1',
            defaults={
                'email': 'owner1@solarops.local',
                'role': 'owner',
            },
        )
        if owner_created:
            owner_user.set_password('Owner12345!')
            owner_user.save()

        plant, plant_created = Plant.objects.get_or_create(
            external_code='PLANT-001',
            defaults={
                'name': 'Solar Farm 001',
                'owner': owner_user,
                'location_name': 'Tehran',
                'latitude': 35.689200,
                'longitude': 51.389000,
                'capacity_kw': 5000,
                'connection_status': 'online',
                'timezone': 'Asia/Tehran',
                'protocol': 'modbus',
            },
        )
        if not plant_created:
            plant.owner = owner_user
            plant.save()

        PlantMembership.objects.get_or_create(
            plant=plant,
            user=owner_user,
            defaults={'access_level': 'owner', 'active': True},
        )

        inverter, _ = Inverter.objects.get_or_create(
            plant=plant,
            serial_number='INV-001',
            defaults={
                'model_name': 'SUN-100K',
                'status': 'online',
                'online': True,
                'rated_power_kw': 100,
                'firmware_version': '1.0.0',
                'manufacturer': 'SolarTech',
            },
        )

        Sensor.objects.get_or_create(plant=plant, name='Ambient Temp', sensor_type='temperature', defaults={'unit': 'C', 'is_active': True})
        Meter.objects.get_or_create(plant=plant, meter_code='MTR-001', defaults={'online': True, 'protocol': 'modbus'})
        Equipment.objects.get_or_create(plant=plant, category='inverter', name='Main Inverter', serial_number='INV-001', defaults={'health_status': 'healthy', 'online': True, 'last_seen_at': timezone.now()})

        TelemetryReading.objects.create(
            plant=plant,
            inverter=inverter,
            power_kw=1250.5,
            voltage_v=690.0,
            current_a=1820.3,
            frequency_hz=50.0,
            energy_kwh=12450.5,
            status='normal',
        )
        EnvironmentalReading.objects.create(plant=plant, temperature_c=31.4, irradiance_wm2=920.0)

        AlertRule.objects.get_or_create(
            plant=plant,
            name='High Voltage',
            defaults={
                'metric': 'voltage_v',
                'threshold_value': 750,
                'comparator': '>',
                'severity': 'high',
                'channels': 'email,sms,push',
                'enabled': True,
            },
        )

        self.stdout.write(self.style.SUCCESS('Demo data created successfully.'))
        self.stdout.write(self.style.SUCCESS('Admin login: admin / Admin12345!'))
        self.stdout.write(self.style.SUCCESS('Owner login: owner1 / Owner12345!'))
