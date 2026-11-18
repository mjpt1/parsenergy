"""Wipe the operational data entered while testing, keeping the setup intact.

This is for the "we tried the system out, now start clean" moment: it removes
every request, offer, contract, payment, ticket, plant and customer account,
but leaves behind everything that was *configured* rather than *entered* —
staff accounts, roles and permissions, system parameters (SMS, Shahkar,
payment gateway), the evaluation form builder and the contract templates.

    python manage.py clear_test_data            # preview only, writes nothing
    python manage.py clear_test_data --apply    # actually delete
    python manage.py clear_test_data --apply --include-audit   # also audit log

Deleting is irreversible, so take a database dump first.
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.alerts.models import AlertEvent, AlertRule, Notification
from apps.core.models import AuditLog
from apps.plants.models import (
    EnvironmentalReading, Equipment, Gateway, HistoricalMeasurement, Inverter,
    Meter, Plant, PlantGroup, PlantGroupMembership, PlantMembership, PVModule,
    RealtimeMeasurement, Sensor, TelemetryReading, Transformer,
)
from apps.requests.models import (
    OtpVerification, Request, RequestContract, RequestMessageLog, RequestOffer,
    RequestPayment, Ticket, TicketMessage, UserProfileCompletion,
)
from apps.vpp.models import DispatchSchedule, VPP, VPPMember


class Command(BaseCommand):
    help = 'Delete test requests, plants and customer accounts; keep staff and settings.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true',
                            help='Actually delete (default is a dry run).')
        parser.add_argument('--include-audit', action='store_true',
                            help='Also clear the audit log (kept by default).')

    def _plan(self, include_audit):
        """Deletion order: children first, so no FK protects a parent row."""
        User = get_user_model()
        customers = User.objects.filter(role='customer').exclude(is_staff=True).exclude(is_superuser=True)

        plan = [
            ('TicketMessage', TicketMessage.objects.all()),
            ('Ticket', Ticket.objects.all()),
            ('RequestPayment', RequestPayment.objects.all()),
            ('RequestContract', RequestContract.objects.all()),
            ('RequestOffer', RequestOffer.objects.all()),
            ('RequestMessageLog', RequestMessageLog.objects.all()),
            ('Request', Request.objects.all()),
            ('OtpVerification', OtpVerification.objects.all()),
            ('UserProfileCompletion', UserProfileCompletion.objects.all()),

            ('DispatchSchedule', DispatchSchedule.objects.all()),
            ('VPPMember', VPPMember.objects.all()),
            ('VPP', VPP.objects.all()),

            ('Notification', Notification.objects.all()),
            ('AlertEvent', AlertEvent.objects.all()),
            ('AlertRule', AlertRule.objects.all()),

            ('PVModule', PVModule.objects.all()),
            ('RealtimeMeasurement', RealtimeMeasurement.objects.all()),
            ('HistoricalMeasurement', HistoricalMeasurement.objects.all()),
            ('TelemetryReading', TelemetryReading.objects.all()),
            ('EnvironmentalReading', EnvironmentalReading.objects.all()),
            ('Inverter', Inverter.objects.all()),
            ('Sensor', Sensor.objects.all()),
            ('Meter', Meter.objects.all()),
            ('Equipment', Equipment.objects.all()),
            ('Transformer', Transformer.objects.all()),
            ('Gateway', Gateway.objects.all()),
            ('PlantGroupMembership', PlantGroupMembership.objects.all()),
            ('PlantMembership', PlantMembership.objects.all()),
            ('PlantGroup', PlantGroup.objects.all()),
            ('Plant', Plant.objects.all()),

            ('User (customers)', customers),
        ]
        if include_audit:
            plan.append(('AuditLog', AuditLog.objects.all()))
        return plan

    def handle(self, *args, **options):
        apply_changes = bool(options['apply'])
        plan = self._plan(bool(options['include_audit']))

        counts = [(label, qs.count()) for label, qs in plan]
        total = sum(count for _, count in counts)

        for label, count in counts:
            if count:
                self.stdout.write(f'  {label:<24} {count}')
        self.stdout.write(f'  {"TOTAL":<24} {total}')

        if not total:
            self.stdout.write(self.style.SUCCESS('Nothing to delete.'))
            return

        if not apply_changes:
            self.stdout.write(self.style.WARNING(
                'Dry run — nothing was deleted. Re-run with --apply to delete.'))
            return

        with transaction.atomic():
            for _, qs in plan:
                qs.delete()

        User = get_user_model()
        self.stdout.write(self.style.SUCCESS(
            f'Deleted {total} rows. Staff accounts kept: {User.objects.count()}'))
