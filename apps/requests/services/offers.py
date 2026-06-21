"""Offer rules: max 3 per request, activation toggling, and selection."""
from __future__ import annotations

from decimal import Decimal

from django.utils.translation import gettext_lazy as _

from apps.core.services import write_audit_log

from ..models import Request, RequestOffer
from . import lifecycle

MAX_OFFERS_PER_REQUEST = 3


class OfferError(Exception):
    """Raised on business-rule violations around offers."""


def add_offer(*, request: Request, title: str, amount, valid_until=None,
              description: str = '', currency: str = 'IRR', vat_percent: int = 10,
              created_by=None) -> RequestOffer:
    if request.offers.count() >= MAX_OFFERS_PER_REQUEST:
        raise OfferError(_('حداکثر %(n)d پیشنهاد برای هر درخواست مجاز است.') % {'n': MAX_OFFERS_PER_REQUEST})

    offer = RequestOffer.objects.create(
        request=request,
        title=title,
        amount=Decimal(str(amount)),
        currency=currency,
        vat_percent=vat_percent,
        description=description,
        valid_until=valid_until,
        created_by=created_by,
    )
    write_audit_log(
        actor=created_by,
        action='offer.created',
        target_type='request_offer',
        target_id=str(offer.id),
        metadata={'request': request.id, 'amount': str(offer.amount)},
    )
    # First offer moves the request into the "offered" state.
    if request.status == Request.Status.NEW:
        lifecycle.transition(request, Request.Status.OFFERED, actor=created_by)
    return offer


def toggle_active(offer: RequestOffer, *, actor=None) -> RequestOffer:
    offer.is_active = not offer.is_active
    offer.save(update_fields=['is_active'])
    write_audit_log(
        actor=actor,
        action='offer.toggled',
        target_type='request_offer',
        target_id=str(offer.id),
        metadata={'is_active': offer.is_active},
    )
    return offer


def select_offer(*, request: Request, offer: RequestOffer, actor=None):
    """Customer selects a payable offer, which generates the contract."""
    if offer.request_id != request.id:
        raise OfferError(_('این پیشنهاد متعلق به این درخواست نیست.'))
    if not offer.is_payable:
        raise OfferError(_('این پیشنهاد قابل انتخاب نیست (غیرفعال یا منقضی).'))
    from .contracts import generate_contract
    return generate_contract(request=request, offer=offer, actor=actor)
