"""Data-access layer for the requests module.

Views and services go through these helpers instead of querying models
directly, so access scoping lives in exactly one place.
"""
from __future__ import annotations

from .models import Request, RequestOffer, RequestPayment


def is_request_manager(user) -> bool:
    """True for admins/superusers or holders of the requests.manage permission."""
    return bool(
        getattr(user, 'is_superuser', False)
        or getattr(user, 'role', '') == 'admin'
        or (hasattr(user, 'has_permission_code') and user.has_permission_code('requests.manage'))
    )


def requests_for_user(user):
    """Requests a user may see: all for managers, otherwise only their own."""
    qs = Request.objects.select_related('user')
    if is_request_manager(user):
        return qs
    return qs.filter(user=user)


def get_user_request(user, request_id):
    """Single request scoped to the user (None if not visible)."""
    return requests_for_user(user).filter(pk=request_id).first()


def filter_requests(*, status=None, province=None, date_from=None, date_to=None):
    """Admin list filtering by status / province / created date range."""
    qs = Request.objects.select_related('user').all()
    if status:
        qs = qs.filter(status=status)
    if province:
        qs = qs.filter(province=province)
    if date_from:
        qs = qs.filter(created_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(created_at__date__lte=date_to)
    return qs


def offers_for_request(request) -> list[RequestOffer]:
    return list(request.offers.all())


def offer_count(request) -> int:
    return request.offers.count()


def payment_by_token(token):
    return (
        RequestPayment.objects
        .select_related('request', 'offer')
        .filter(token=token)
        .first()
    )


def payments_for_request(request):
    return request.payments.select_related('offer').all()


def messages_for_request(request):
    return request.message_logs.all()
