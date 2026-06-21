"""Request lifecycle and the status state machine.

`transition()` is the single entry point for changing a request's status:
it validates the move, persists it, writes an audit log, and records a
status-change SMS (delivery is wired in phase 7).
"""
from __future__ import annotations

from typing import Optional

from apps.core.services import write_audit_log

from ..models import Request, RequestMessageLog
from . import sms as sms_service

S = Request.Status

# Allowed status moves. Anything not listed is rejected by transition().
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    S.NEW: {S.OFFERED, S.CANCELLED},
    S.OFFERED: {S.CONTRACT_GENERATED, S.CANCELLED},
    S.CONTRACT_GENERATED: {S.CONTRACT_APPROVED, S.CANCELLED},
    S.CONTRACT_APPROVED: {S.AWAITING_PAYMENT, S.CANCELLED},
    S.AWAITING_PAYMENT: {S.PAID, S.CANCELLED},
    S.PAID: set(),
    S.CANCELLED: set(),
}


class TransitionError(Exception):
    """Raised when an illegal status transition is attempted."""


def create_request(*, full_name, mobile, province, city='', description='', user=None,
                   **extra_fields) -> Request:
    request = Request.objects.create(
        full_name=full_name,
        mobile=mobile,
        province=province,
        city=city,
        description=description,
        user=user,
        **extra_fields,
    )
    write_audit_log(
        actor=user,
        action='request.created',
        target_type='request',
        target_id=str(request.id),
        metadata={'mobile': mobile, 'province': province},
    )
    return request


def attach_user(request: Request, user) -> Request:
    """Link a request to its owner after OTP registration/login."""
    if request.user_id is None:
        request.user = user
        request.save(update_fields=['user', 'updated_at'])
        write_audit_log(
            actor=user,
            action='request.attached_user',
            target_type='request',
            target_id=str(request.id),
        )
    return request


def _record_status_sms(request: Request) -> None:
    """Send a status-change SMS and record it."""
    if not request.mobile:
        return
    sms_service.send_message(
        request=request,
        user=request.user,
        mobile=request.mobile,
        message_type=RequestMessageLog.MessageType.STATUS_CHANGE,
        body=f'وضعیت درخواست #{request.id}: {request.get_status_display()}',
    )


def transition(request: Request, to_status: str, *, actor=None, notify: bool = True,
               metadata: Optional[dict] = None) -> Request:
    allowed = ALLOWED_TRANSITIONS.get(request.status, set())
    if to_status not in allowed:
        raise TransitionError(f'گذار نامعتبر وضعیت: {request.status} → {to_status}')

    previous = request.status
    request.status = to_status
    request.save(update_fields=['status', 'updated_at'])

    write_audit_log(
        actor=actor,
        action='request.status_changed',
        target_type='request',
        target_id=str(request.id),
        metadata={'from': previous, 'to': to_status, **(metadata or {})},
    )
    if notify:
        _record_status_sms(request)
    return request
