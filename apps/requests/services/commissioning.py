"""Linking requests to their customer and turning a won request into a plant.

* `claim_requests` is the single place where unowned requests are attached to
  a customer who has proven (by OTP) that they own the mobile number.
* `commission_plant` creates the plant for a request exactly once; it runs
  automatically when a request is paid or closed as won by sales, and from the
  technical "راه‌اندازی نیروگاه" button.
"""
from __future__ import annotations

import logging

from django.db import transaction

from apps.core.services import write_audit_log

from ..models import Request

logger = logging.getLogger(__name__)


def is_customer_account(user) -> bool:
    """Customer-side accounts (OTP `customer` and self-registered `owner`), never staff."""
    if user is None or not getattr(user, 'is_authenticated', False):
        return False
    if user.is_superuser or user.is_staff:
        return False
    return getattr(user, 'role', '') in (user.Role.CUSTOMER, user.Role.OWNER)


def _give_plant_to(plant, user) -> None:
    if plant.owner_id != user.id and not is_customer_account(plant.owner):
        plant.owner = user
        plant.save(update_fields=['owner', 'updated_at'])


def claim_requests(user, mobile: str) -> int:
    """Attach unowned requests for an OTP-verified mobile to this customer."""
    if not mobile or not is_customer_account(user):
        return 0
    claimed = list(Request.objects.filter(mobile=mobile, user__isnull=True).select_related('plant'))
    for req in claimed:
        req.user = user
        req.save(update_fields=['user', 'updated_at'])
        if req.plant_id:
            _give_plant_to(req.plant, user)
        write_audit_log(actor=user, action='request.attached_user',
                        target_type='request', target_id=str(req.id))
    return len(claimed)


def commission_plant(request: Request, *, actor=None):
    """Create (once) the plant for this request and return it.

    The plant name carries only the request id — technical staff work on it
    and must not see the customer's identity.
    """
    from apps.plants.models import Plant

    if request.plant_id:
        return request.plant
    owner = request.user or actor
    if owner is None:
        return None
    location_name = (
        request.install_address or f'{request.province} {request.city}'
    ).strip() or request.province or '-'
    plant, _created = Plant.objects.get_or_create(
        external_code=f'REQ-{request.id}',
        defaults={
            'name': f'درخواست #{request.id}',
            'owner': owner,
            'location_name': location_name,
            'latitude': float(request.latitude or 0),
            'longitude': float(request.longitude or 0),
            'capacity_kw': 0,
        },
    )
    request.plant = plant
    request.save(update_fields=['plant', 'updated_at'])
    write_audit_log(actor=actor, action='request.plant_commissioned',
                    target_type='request', target_id=str(request.id),
                    metadata={'plant_id': plant.id, 'automatic': actor is None})
    return plant


def auto_commission(request: Request) -> None:
    """Best effort: a plant problem must never undo a payment or a closed deal."""
    if request.user_id is None or request.plant_id:
        return
    try:
        with transaction.atomic():
            commission_plant(request)
    except Exception:  # noqa: BLE001
        logger.exception('Automatic plant commissioning failed for request %s', request.id)
