"""Remove fabricated PV-module telemetry left behind by the old dashboards.

Earlier versions scaffolded a full module grid — with invented temperatures and
hot/warn/fault statuses — the first time a plant's dashboard was opened. That
made brand-new plants look like they had failing hardware. This command clears
that fake state so the panel only ever shows real, reported data.

    python manage.py clear_demo_modules            # preview (no writes)
    python manage.py clear_demo_modules --apply    # reset to "never reported"
    python manage.py clear_demo_modules --apply --delete   # remove the rows
    python manage.py clear_demo_modules --apply --plant 3  # one plant only
"""
from decimal import Decimal

from django.core.management.base import BaseCommand

from apps.plants.models import PVModule


class Command(BaseCommand):
    help = 'Clear fabricated PV module statuses/temperatures (demo leftovers).'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true',
                            help='Actually write changes (default is a dry run).')
        parser.add_argument('--delete', action='store_true',
                            help='Delete the module rows instead of resetting them.')
        parser.add_argument('--plant', type=int, default=None,
                            help='Restrict to a single plant id.')

    def handle(self, *args, **options):
        qs = PVModule.objects.all()
        if options['plant']:
            qs = qs.filter(plant_id=options['plant'])

        total = qs.count()
        if not total:
            self.stdout.write(self.style.SUCCESS('No PV modules found — nothing to do.'))
            return

        by_status = {}
        for row in qs.values('status').distinct():
            s = row['status']
            by_status[s] = qs.filter(status=s).count()
        self.stdout.write(f'{total} modules across '
                          f'{qs.values("plant_id").distinct().count()} plant(s): {by_status}')

        if not options['apply']:
            action = 'deleted' if options['delete'] else 'reset to "never reported"'
            self.stdout.write(self.style.WARNING(
                f'Dry run — nothing written. Re-run with --apply to have them {action}.'))
            return

        if options['delete']:
            deleted, _ = qs.delete()
            self.stdout.write(self.style.SUCCESS(f'Deleted {deleted} module rows.'))
            return

        updated = qs.update(
            status=PVModule.Status.OFFLINE,
            temperature_c=Decimal('0'),
            relative_power_pct=Decimal('0'),
            last_seen_at=None,
        )
        self.stdout.write(self.style.SUCCESS(
            f'Reset {updated} modules to "never reported" (offline, no temperature/power).'))
