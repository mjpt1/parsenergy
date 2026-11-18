"""Repair ownership left behind before requests were linked on every visit.

    python manage.py link_customer_requests           # report only
    python manage.py link_customer_requests --apply   # make the changes

1. Unowned requests go to the SMS-login account of the same mobile, if there is one.
2. Plants commissioned from a request but owned by staff go to the customer
   (the request's own customer, or the SMS-login account of its mobile, made if missing).
"""
from django.core.management.base import BaseCommand

from apps.core.services import write_audit_log
from apps.requests.models import Request
from apps.requests.services import lifecycle


class Command(BaseCommand):
    help = 'Attach unowned requests and staff-owned plants to their customers.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='make the changes (default: report only)')

    def handle(self, *args, apply=False, **options):
        out = self.stdout.write
        linked = no_account = 0
        for req in Request.objects.filter(user__isnull=True).order_by('id'):
            account = lifecycle.customer_account_for(req.mobile)
            if account is None:
                no_account += 1
                continue
            linked += 1
            out(f'request #{req.id} -> user #{account.pk}')
            if apply:
                Request.objects.filter(pk=req.pk, user__isnull=True).update(user=account)
        out(f'REQUESTS linked={linked} still_unowned_no_sms_account={no_account}')

        moved = blocked = 0
        for req in Request.objects.filter(plant__isnull=False).select_related('plant__owner', 'user'):
            plant = req.plant
            if lifecycle.is_customer_account(plant.owner):
                continue
            owner = (req.user if lifecycle.is_customer_account(req.user)
                     else lifecycle.customer_account_for(req.mobile, create=apply))
            if owner is None and apply:
                blocked += 1
                out(f'plant #{plant.pk} (request #{req.id}): mobile has a password account, left as is')
                continue
            moved += 1
            out(f'plant #{plant.pk} (request #{req.id}): owner user #{plant.owner_id} -> '
                f'{"user #%s" % owner.pk if owner else "new SMS account for the request mobile"}')
            if apply:
                old = plant.owner_id
                plant.owner = owner
                plant.save(update_fields=['owner', 'updated_at'])
                Request.objects.filter(pk=req.pk).update(user=owner)
                write_audit_log(actor=None, action='plant.owner_repaired', target_type='plant',
                                target_id=str(plant.pk), metadata={'from': old, 'to': owner.pk, 'request': req.id})
        out(f'PLANTS moved={moved} blocked={blocked} applied={apply}')
