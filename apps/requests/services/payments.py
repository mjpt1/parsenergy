"""Internal payment service with a callback (no WooCommerce / generic product).

A payment is always tied to a specific approved offer. The internal backend
exposes a pay page and a callback; the abstraction allows swapping in a real
gateway later.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.services import write_audit_log

from ..models import Request, RequestContract, RequestMessageLog, RequestOffer, RequestPayment
from . import lifecycle
from . import sms as sms_service


class PaymentError(Exception):
    """Raised on payment business-rule violations."""


class PaymentBackend(ABC):
    name = 'base'

    @abstractmethod
    def create(self, payment: RequestPayment) -> str:
        """Return the URL the customer is sent to in order to pay."""

    @abstractmethod
    def verify(self, payment: RequestPayment, data: dict) -> bool:
        """Return True if the callback represents a successful payment."""


class InternalPaymentBackend(PaymentBackend):
    name = 'internal'

    def create(self, payment):
        return reverse('requests:pay', kwargs={'token': payment.token})

    def verify(self, payment, data):
        return str(data.get('result', 'success')).lower() == 'success'


def get_backend() -> PaymentBackend:
    return InternalPaymentBackend()


@transaction.atomic
def create_for_offer(*, request: Request, offer: RequestOffer, actor=None) -> tuple[RequestPayment, str]:
    contract = RequestContract.objects.filter(request=request).first()
    if contract is None or contract.status != RequestContract.Status.APPROVED:
        raise PaymentError(_('بدون تأیید قرارداد امکان پرداخت وجود ندارد.'))  # rule 3
    if not request.identity_verified:
        raise PaymentError(_('بدون احراز هویت امکان پرداخت وجود ندارد.'))
    if not offer.is_payable:
        raise PaymentError(_('این پیشنهاد قابل پرداخت نیست (غیرفعال یا منقضی).'))  # rule 2

    payment = RequestPayment.objects.filter(
        request=request, offer=offer, status=RequestPayment.Status.PENDING,
    ).first()
    if payment is None:
        # amount payable includes value-added tax.
        payment = RequestPayment.objects.create(request=request, offer=offer, amount=offer.total_amount)

    if request.status == Request.Status.CONTRACT_APPROVED:
        lifecycle.transition(request, Request.Status.AWAITING_PAYMENT, actor=actor)

    url = get_backend().create(payment)
    write_audit_log(
        actor=actor,
        action='payment.created',
        target_type='request_payment',
        target_id=str(payment.id),
        metadata={'request': request.id, 'amount': str(payment.amount)},
    )
    return payment, url


@transaction.atomic
def handle_callback(*, token, data: dict) -> RequestPayment:
    payment = (
        RequestPayment.objects.select_related('request', 'offer').filter(token=token).first()
    )
    if payment is None:
        raise PaymentError(_('پرداخت یافت نشد.'))
    if payment.status == RequestPayment.Status.PAID:
        return payment  # idempotent

    if not get_backend().verify(payment, data):
        payment.status = RequestPayment.Status.FAILED
        payment.save(update_fields=['status', 'updated_at'])
        write_audit_log(actor=None, action='payment.failed', target_type='request_payment', target_id=str(payment.id))
        return payment

    payment.status = RequestPayment.Status.PAID
    payment.paid_at = timezone.now()
    payment.gateway_ref = str(data.get('ref', '')) or payment.gateway_ref
    payment.save(update_fields=['status', 'paid_at', 'gateway_ref', 'updated_at'])

    req = payment.request
    if req.status == Request.Status.AWAITING_PAYMENT:
        # rule 4: paid; suppress the generic status SMS in favour of the success SMS below.
        lifecycle.transition(req, Request.Status.PAID, actor=req.user, notify=False)

    sms_service.send_message(  # rule 6: payment-success SMS, logged
        request=req,
        user=req.user,
        mobile=req.mobile,
        body=f'پرداخت درخواست #{req.id} با موفقیت انجام شد.',
        message_type=RequestMessageLog.MessageType.PAYMENT_SUCCESS,
    )
    write_audit_log(actor=req.user, action='payment.paid', target_type='request_payment', target_id=str(payment.id))
    return payment
