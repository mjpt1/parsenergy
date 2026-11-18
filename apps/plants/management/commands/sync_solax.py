"""Read live data for every inverter connected to SolaX Cloud.

Run from cron every 5 minutes:  python manage.py sync_solax
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.plants.models import CloudAccount, InverterSample
from apps.plants.solax import sync_account


class Command(BaseCommand):
    help = 'Fetch realtime data from SolaX Cloud for all connected inverters.'

    def handle(self, *args, **options):
        for account in CloudAccount.objects.filter(provider=CloudAccount.Provider.SOLAX):
            stored, problems = sync_account(account)
            self.stdout.write(f'{account.name}: {stored} stored')
            for p in problems:
                self.stderr.write(f'  {p}')
        # Detailed samples are for recent charts; production history stays in telemetry.
        InverterSample.objects.filter(created_at__lt=timezone.now() - timedelta(days=180)).delete()
