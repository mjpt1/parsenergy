from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from apps.alerts.models import AlertRule, Notification
from apps.core.models import APIConnection, AuditLog, DatabaseBackup, ProtocolAdapter, ServerHealthMetric, SystemParameter
from apps.plants.models import EnvironmentalReading, Equipment, Inverter, Meter, Plant, PlantMembership, Sensor, TelemetryReading


class Command(BaseCommand):
    help = 'Remove temporary seeded multi-plant demo data created by seed_temp_data command.'

    def add_arguments(self, parser):
        parser.add_argument('--tag', default='TMPDEMO', help='Prefix tag to delete')
        parser.add_argument('--keep-users', action='store_true', help='Keep temporary owner users')

    def handle(self, *args, **options):
        tag = str(options['tag']).strip().upper()
        keep_users = bool(options.get('keep_users'))

        User = get_user_model()

        plant_qs = Plant.objects.filter(external_code__startswith=f'{tag}-')

        deleted_rules = AlertRule.objects.filter(plant__in=plant_qs).count()
        AlertRule.objects.filter(plant__in=plant_qs).delete()

        TelemetryReading.objects.filter(plant__in=plant_qs).delete()
        EnvironmentalReading.objects.filter(plant__in=plant_qs).delete()
        PlantMembership.objects.filter(plant__in=plant_qs).delete()
        Inverter.objects.filter(plant__in=plant_qs).delete()
        Sensor.objects.filter(plant__in=plant_qs).delete()
        Meter.objects.filter(plant__in=plant_qs).delete()
        Equipment.objects.filter(plant__in=plant_qs).delete()

        deleted_plants = plant_qs.count()
        plant_qs.delete()

        deleted_notifications = Notification.objects.filter(title__startswith=f'{tag} ').count()
        Notification.objects.filter(title__startswith=f'{tag} ').delete()

        deleted_params = SystemParameter.objects.filter(key__startswith=f'{tag}.').count()
        SystemParameter.objects.filter(key__startswith=f'{tag}.').delete()

        APIConnection.objects.filter(name__startswith=f'{tag} ').delete()
        ProtocolAdapter.objects.filter(name__startswith=f'{tag} ').delete()
        DatabaseBackup.objects.filter(file_path__icontains=tag.lower()).delete()
        ServerHealthMetric.objects.filter(hostname__startswith=tag.lower()).delete()
        AuditLog.objects.filter(action__startswith=f'{tag}.').delete()

        deleted_users = 0
        if not keep_users:
            temp_user_qs = User.objects.filter(username__startswith=f'{tag.lower()}_owner')
            deleted_users = temp_user_qs.count()
            temp_user_qs.delete()

        self.stdout.write(self.style.SUCCESS(f'Temporary dataset removed for tag: {tag}'))
        self.stdout.write(self.style.SUCCESS(f'  plants: {deleted_plants}'))
        self.stdout.write(self.style.SUCCESS(f'  alert_rules: {deleted_rules}'))
        self.stdout.write(self.style.SUCCESS(f'  notifications: {deleted_notifications}'))
        self.stdout.write(self.style.SUCCESS(f'  system_parameters: {deleted_params}'))
        if not keep_users:
            self.stdout.write(self.style.SUCCESS(f'  users: {deleted_users}'))
        else:
            self.stdout.write(self.style.SUCCESS('  users: kept'))
