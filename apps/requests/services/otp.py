"""OTP issuing and verification for SMS registration/login and contract approval.

Codes are persisted on OtpVerification; the SMS carrying the code is recorded
in RequestMessageLog (queued). Actual delivery is wired in phase 7.
"""
from __future__ import annotations

import secrets
from datetime import timedelta

from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from ..models import OtpVerification, RequestMessageLog
from . import sms as sms_service

OTP_LENGTH = 5
OTP_TTL_MINUTES = 2
OTP_MAX_ATTEMPTS = 5


class OtpError(Exception):
    """Raised on any OTP verification failure (not found / expired / wrong / locked)."""


def generate_code() -> str:
    return ''.join(str(secrets.randbelow(10)) for _ in range(OTP_LENGTH))


def issue(*, mobile: str, purpose: str, request=None) -> OtpVerification:
    # Invalidate any previous unused codes for the same mobile + purpose.
    OtpVerification.objects.filter(
        mobile=mobile, purpose=purpose, is_used=False,
    ).update(is_used=True)

    # MelliPayamak's OTP service creates and sends the code itself; we only
    # keep what it returns. Without it (or if it fails) we use our own code.
    # The contract code has its own approved pattern ("{0} کد تایید قرارداد
    # شما {1} ..."), which names the customer; it beats the generic OTP service.
    is_contract = purpose == OtpVerification.Purpose.CONTRACT_APPROVAL
    provider_code, note = (None, '') if is_contract else sms_service.provider_otp(mobile)
    code = provider_code or generate_code()
    otp = OtpVerification.objects.create(
        mobile=mobile,
        code=code,
        purpose=purpose,
        request=request,
        expires_at=timezone.now() + timedelta(minutes=OTP_TTL_MINUTES),
    )
    if provider_code:
        RequestMessageLog.objects.create(
            request=request, mobile=mobile,
            body=f'کد تأیید شما: {code}',
            message_type=RequestMessageLog.MessageType.OTP,
            provider=note, status=RequestMessageLog.Status.SENT,
        )
    else:
        name = (getattr(request, 'full_name', '') or '') if request is not None else ''
        sms_service.send_message(
            request=request,
            mobile=mobile,
            body=f'کد تأیید شما: {code}',
            message_type=RequestMessageLog.MessageType.OTP,
            pattern=(sms_service.CONTRACT_PATTERN, [name, code]) if is_contract else None,
        )
    return otp


def verify(*, mobile: str, code: str, purpose: str) -> OtpVerification:
    otp = (
        OtpVerification.objects
        .filter(mobile=mobile, purpose=purpose, is_used=False)
        .order_by('-created_at')
        .first()
    )
    if otp is None:
        raise OtpError(_('کد معتبری یافت نشد. دوباره درخواست کد دهید.'))
    if otp.is_expired:
        raise OtpError(_('کد منقضی شده است. دوباره درخواست کد دهید.'))
    if otp.attempts >= OTP_MAX_ATTEMPTS:
        otp.is_used = True
        otp.save(update_fields=['is_used'])
        raise OtpError(_('تعداد تلاش بیش از حد مجاز است. دوباره درخواست کد دهید.'))

    otp.attempts += 1
    if otp.code != code:
        otp.save(update_fields=['attempts'])
        raise OtpError(_('کد واردشده نادرست است.'))

    otp.is_used = True
    otp.verified_at = timezone.now()
    otp.save(update_fields=['attempts', 'is_used', 'verified_at'])
    return otp
