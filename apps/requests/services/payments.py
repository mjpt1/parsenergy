"""Payment service: a pluggable gateway behind a stable business API.

A payment is always tied to a specific approved offer. `create_for_offer`
opens it and hands back the URL to send the customer to; `handle_callback`
settles it. Which gateway is used comes from SystemParameter:

    payment_provider     internal (default) | zarinpal | jibit | digipay
    payment_enabled      'true' / 'false' — false forces the internal backend
    payment_merchant_id  Zarinpal merchant id / Jibit apiKey / DigiPay client id
    payment_api_key      Jibit secretKey / DigiPay client secret   (secret)
    payment_username     DigiPay username
    payment_password     DigiPay password                          (secret)
    payment_sandbox      'true' routes to the gateway's test environment
    payment_site_url     absolute origin of this site, for the callback URL

Money note: offers are priced in Tomans (`RequestOffer.currency` defaults to
'تومان') and `RequestPayment.amount` is VAT-inclusive. Gateways disagree on the
unit — Zarinpal is told `currency: IRT` and gets the number unchanged, while
Jibit and DigiPay are Rial-denominated and go through `_to_rial()` (×10). Both
paths call `_assert_toman` first, which fails loudly rather than risk a ten-fold
error in either direction.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod

from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.models import SystemParameter
from apps.core.services import write_audit_log

from ..models import Request, RequestContract, RequestMessageLog, RequestOffer, RequestPayment
from . import lifecycle
from . import sms as sms_service

logger = logging.getLogger(__name__)

# Labels that mean "Toman". Anything else must not reach the gateway untranslated.
_TOMAN_LABELS = {'تومان', 'toman', 'irt', 'tmn', ''}


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
        return str(data.get('result', '')).lower() == 'success'


def _assert_toman(payment: RequestPayment) -> None:
    """Guard the Toman/Rial boundary.

    Offer amounts are Tomans. Gateways differ — Zarinpal is told `currency: IRT`
    and gets the number unchanged, while Jibit and DigiPay want Rials and get
    `_to_rial()`. If an offer is ever priced in something else, either path
    would be wrong by a factor of ten, so refuse instead of guessing.
    """
    label = (payment.offer.currency or '').strip().lower()
    if label not in _TOMAN_LABELS:
        raise PaymentError(
            _('واحد پول این پیشنهاد «%(cur)s» است و برای پرداخت آنلاین پشتیبانی نمی‌شود.')
            % {'cur': payment.offer.currency})


def _to_rial(payment: RequestPayment) -> int:
    """Tomans stored → Rials on the wire (×10). Only for Rial-denominated gateways."""
    _assert_toman(payment)
    return int(payment.amount) * 10


class ZarinpalBackend(PaymentBackend):
    """Zarinpal Payment Gateway (REST v4).

    `create()` opens a transaction and returns the StartPay URL; the Authority
    it hands back is stored on the payment so `verify()` can settle it. Verify
    is always a server-to-server call — the browser coming back from Zarinpal
    is never treated as proof of payment.
    """
    name = 'zarinpal'
    API = 'https://api.zarinpal.com/pg/v4/payment'
    START = 'https://payment.zarinpal.com/pg/StartPay/'
    SANDBOX_API = 'https://sandbox.zarinpal.com/pg/v4/payment'
    SANDBOX_START = 'https://sandbox.zarinpal.com/pg/StartPay/'

    def __init__(self, merchant_id: str, site_url: str, sandbox: bool = False):
        self.merchant_id = merchant_id
        self.site_url = (site_url or '').rstrip('/')
        self.sandbox = sandbox

    @property
    def _api(self) -> str:
        return self.SANDBOX_API if self.sandbox else self.API

    @property
    def _start(self) -> str:
        return self.SANDBOX_START if self.sandbox else self.START

    def _post(self, path: str, body: dict) -> dict:
        """POST to Zarinpal and return the parsed `data` object, or raise."""
        payload = json.dumps(dict(body, merchant_id=self.merchant_id)).encode('utf-8')
        req = urllib.request.Request(self._api + path, data=payload, method='POST', headers={
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        })
        # Zarinpal is an Iranian endpoint; bypass any ambient proxy so the call
        # leaves from this server's own (allow-listed) IP — same as Shahkar.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(req, timeout=15) as resp:
                raw = resp.read().decode('utf-8', 'ignore')
        except urllib.error.HTTPError as exc:
            detail = ''
            try:
                detail = exc.read().decode('utf-8', 'ignore')
            except Exception:  # noqa: BLE001
                pass
            logger.warning('Zarinpal HTTP %s on %s: %s', exc.code, path, detail[:500])
            raise PaymentError(
                _('درگاه پرداخت خطا داد (کد %(code)s).') % {'code': exc.code}) from exc
        except Exception as exc:  # noqa: BLE001 - surfaced to the user, not swallowed
            logger.warning('Zarinpal connection error on %s: %s', path, exc)
            raise PaymentError(_('ارتباط با درگاه پرداخت برقرار نشد.')) from exc
        try:
            parsed = json.loads(raw)
        except ValueError as exc:
            logger.warning('Zarinpal invalid JSON on %s: %s', path, raw[:200])
            raise PaymentError(_('پاسخ درگاه پرداخت نامعتبر است.')) from exc
        # Success carries `data`; failure carries `errors` (dict or list).
        data = parsed.get('data') or {}
        if not data or data.get('code') not in (100, 101):
            errors = parsed.get('errors') or {}
            if isinstance(errors, list):
                errors = errors[0] if errors else {}
            code = (errors or {}).get('code') or (data or {}).get('code')
            message = (errors or {}).get('message') or ''
            logger.warning('Zarinpal rejected %s: %s', path, raw[:300])
            raise PaymentError(
                message or (_('درگاه پرداخت تراکنش را نپذیرفت (کد %(code)s).') % {'code': code}))
        return data

    def create(self, payment):
        if not self.merchant_id:
            raise PaymentError(_('کد پذیرندهٔ درگاه پرداخت تنظیم نشده است.'))
        if not self.site_url:
            raise PaymentError(_('آدرس سایت برای بازگشت از درگاه تنظیم نشده است.'))
        _assert_toman(payment)
        callback = self.site_url + reverse(
            'requests:pay-callback', kwargs={'token': payment.token})
        data = self._post('/request.json', {
            'amount': int(payment.amount),
            'currency': 'IRT',  # amounts are Tomans; see _assert_toman
            'callback_url': callback,
            'description': f'پرداخت درخواست #{payment.request_id} — {payment.offer.title}'[:255],
            'metadata': {'mobile': payment.request.mobile or ''},
        })
        authority = str(data.get('authority') or '')
        if not authority:
            raise PaymentError(_('درگاه پرداخت کد پیگیری بازنگرداند.'))
        payment.authority = authority
        payment.save(update_fields=['authority', 'updated_at'])
        return self._start + authority

    def verify(self, payment, data):
        # The customer aborted at the gateway: Zarinpal sends Status=NOK.
        if str(data.get('Status') or data.get('status') or '').upper() != 'OK':
            return False
        authority = str(data.get('Authority') or data.get('authority') or '') or payment.authority
        if not authority:
            return False
        # An Authority that doesn't belong to this payment must never settle it.
        if payment.authority and authority != payment.authority:
            logger.warning('Zarinpal authority mismatch on payment %s', payment.id)
            return False
        _assert_toman(payment)
        result = self._post('/verify.json', {
            'amount': int(payment.amount),
            'currency': 'IRT',
            'authority': authority,
        })
        # 100 = verified now, 101 = already verified (safe to treat as paid).
        if result.get('code') not in (100, 101):
            return False
        data['ref'] = str(result.get('ref_id') or '')
        return True


class _TokenGatewayBackend(PaymentBackend):
    """Shared plumbing for gateways that need an access token per call.

    Tokens are fetched per operation rather than cached: payment volume here is
    a handful a day, and a stale-token bug during checkout costs far more than
    the extra round-trip.
    """

    def _request(self, url: str, body, *, headers=None, method='POST', form=False) -> dict:
        if form:
            data = urllib.parse.urlencode(body).encode('utf-8')
            content_type = 'application/x-www-form-urlencoded'
        else:
            data = json.dumps(body).encode('utf-8') if body is not None else b''
            content_type = 'application/json'
        req = urllib.request.Request(url, data=data, method=method, headers={
            'Content-Type': content_type, 'Accept': 'application/json',
            **(headers or {}),
        })
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(req, timeout=20) as resp:
                raw = resp.read().decode('utf-8', 'ignore')
        except urllib.error.HTTPError as exc:
            detail = ''
            try:
                detail = exc.read().decode('utf-8', 'ignore')
            except Exception:  # noqa: BLE001
                pass
            logger.warning('%s HTTP %s on %s: %s', self.name, exc.code, url, detail[:500])
            raise PaymentError(
                _('درگاه پرداخت خطا داد (کد %(code)s).') % {'code': exc.code}) from exc
        except Exception as exc:  # noqa: BLE001 - surfaced, not swallowed
            logger.warning('%s connection error on %s: %s', self.name, url, exc)
            raise PaymentError(_('ارتباط با درگاه پرداخت برقرار نشد.')) from exc
        try:
            return json.loads(raw) if raw else {}
        except ValueError as exc:
            logger.warning('%s invalid JSON on %s: %s', self.name, url, raw[:200])
            raise PaymentError(_('پاسخ درگاه پرداخت نامعتبر است.')) from exc


class JibitBackend(_TokenGatewayBackend):
    """Jibit PPG v3 (napi.jibit.ir).

    Amounts go on the wire in **Rials** with `currency: IRR`, so the stored
    Toman figure is multiplied by ten exactly once, in `_to_rial`.
    """
    name = 'jibit'
    BASE = 'https://napi.jibit.ir/ppg/v3'

    def __init__(self, api_key: str, secret_key: str, site_url: str):
        self.api_key = api_key
        self.secret_key = secret_key
        self.site_url = (site_url or '').rstrip('/')

    def _token(self) -> str:
        if not self.api_key or not self.secret_key:
            raise PaymentError(_('کلید و رمز درگاه جیبیت تنظیم نشده است.'))
        data = self._request(f'{self.BASE}/tokens',
                             {'apiKey': self.api_key, 'secretKey': self.secret_key})
        token = data.get('accessToken') or ''
        if not token:
            raise PaymentError(_('دریافت توکن از جیبیت ناموفق بود.'))
        return token

    def _auth(self) -> dict:
        return {'Authorization': f'Bearer {self._token()}'}

    def create(self, payment):
        if not self.site_url:
            raise PaymentError(_('آدرس سایت برای بازگشت از درگاه تنظیم نشده است.'))
        callback = self.site_url + reverse(
            'requests:pay-callback', kwargs={'token': payment.token})
        data = self._request(f'{self.BASE}/purchases', {
            'amount': _to_rial(payment),
            'currency': 'IRR',
            'callbackUrl': callback,
            'clientReferenceNumber': str(payment.token),
            'userIdentifier': (payment.request.mobile or '')[:50],
        }, headers=self._auth())
        url = data.get('pspSwitchingUrl') or ''
        purchase_id = str(data.get('purchaseId') or data.get('id') or '')
        if not url or not purchase_id:
            raise PaymentError(_('درگاه جیبیت آدرس پرداخت بازنگرداند.'))
        payment.authority = purchase_id
        payment.save(update_fields=['authority', 'updated_at'])
        return url

    def verify(self, payment, data):
        purchase_id = str(data.get('purchaseId') or '') or payment.authority
        if not purchase_id:
            return False
        if payment.authority and purchase_id != payment.authority:
            logger.warning('Jibit purchase mismatch on payment %s', payment.id)
            return False
        result = self._request(f'{self.BASE}/purchases/{purchase_id}/verify',
                               None, headers=self._auth())
        status = str(result.get('status') or '').upper()
        if status not in ('SUCCESS', 'ALREADY_VERIFIED'):
            logger.warning('Jibit verify returned %s for payment %s', status, payment.id)
            return False
        data['ref'] = str(result.get('referenceNumber') or purchase_id)
        return True


class DigipayBackend(_TokenGatewayBackend):
    """DigiPay UPG (mydigipay.com).

    Amounts are **Rials**. Auth is OAuth password grant with a Basic-authed
    client, so four credentials are needed; see the settings screen.
    """
    name = 'digipay'
    BASE = 'https://api.mydigipay.com/digipay/api'
    SANDBOX_BASE = 'https://uat.mydigipay.info/digipay/api'
    VERSION = '2022-02-02'

    def __init__(self, client_id, client_secret, username, password, site_url, sandbox=False):
        self.client_id = client_id
        self.client_secret = client_secret
        self.username = username
        self.password = password
        self.site_url = (site_url or '').rstrip('/')
        self.sandbox = sandbox

    @property
    def _base(self) -> str:
        return self.SANDBOX_BASE if self.sandbox else self.BASE

    def _token(self) -> str:
        import base64
        if not all((self.client_id, self.client_secret, self.username, self.password)):
            raise PaymentError(_('اطلاعات ورود درگاه دیجی‌پی کامل تنظیم نشده است.'))
        basic = base64.b64encode(
            f'{self.client_id}:{self.client_secret}'.encode()).decode()
        data = self._request(
            f'{self._base}/oauth/token',
            {'username': self.username, 'password': self.password, 'grant_type': 'password'},
            headers={'Authorization': f'Basic {basic}'}, form=True)
        token = data.get('access_token') or ''
        if not token:
            raise PaymentError(_('دریافت توکن از دیجی‌پی ناموفق بود.'))
        return token

    def _auth(self) -> dict:
        return {'Authorization': f'Bearer {self._token()}',
                'Agent': 'WEB', 'Digipay-Version': self.VERSION}

    def create(self, payment):
        if not self.site_url:
            raise PaymentError(_('آدرس سایت برای بازگشت از درگاه تنظیم نشده است.'))
        callback = self.site_url + reverse(
            'requests:pay-callback', kwargs={'token': payment.token})
        data = self._request(f'{self._base}/tickets/business?type=11', {
            'amount': _to_rial(payment),
            'cellNumber': (payment.request.mobile or ''),
            'providerId': str(payment.token),
            'callbackUrl': callback,
        }, headers=self._auth())
        url = data.get('redirectUrl') or ''
        ticket = str(data.get('ticket') or '')
        if not url:
            raise PaymentError(_('درگاه دیجی‌پی آدرس پرداخت بازنگرداند.'))
        payment.authority = ticket
        payment.save(update_fields=['authority', 'updated_at'])
        return url

    def verify(self, payment, data):
        tracking = str(data.get('trackingCode') or data.get('trackingcode') or '')
        if not tracking:
            return False
        result = self._request(f'{self._base}/purchases/verify?type=11', {
            'trackingCode': tracking,
            'providerId': str(payment.token),
        }, headers=self._auth())
        # DigiPay reports outcome in result.status; 0 means success.
        status = (result.get('result') or {}).get('status')
        if str(status) != '0':
            logger.warning('DigiPay verify status %s for payment %s', status, payment.id)
            return False
        data['ref'] = tracking
        return True


def _param(key: str, default: str = '') -> str:
    param = SystemParameter.objects.filter(key=key).first()
    return param.value if param else default


def get_backend() -> PaymentBackend:
    """Pick the gateway from SystemParameter.

    Falls back to the simulator whenever payments are disabled or the provider
    is unknown — never silently to a live gateway.
    """
    provider = _param('payment_provider', 'internal')
    if _param('payment_enabled', 'false') != 'true':
        return InternalPaymentBackend()
    site_url = _param('payment_site_url')
    if provider == 'zarinpal':
        return ZarinpalBackend(
            _param('payment_merchant_id'), site_url,
            sandbox=_param('payment_sandbox', 'true') == 'true')
    if provider == 'jibit':
        return JibitBackend(
            _param('payment_merchant_id'), _param('payment_api_key'), site_url)
    if provider == 'digipay':
        return DigipayBackend(
            _param('payment_merchant_id'), _param('payment_api_key'),
            _param('payment_username'), _param('payment_password'), site_url,
            sandbox=_param('payment_sandbox', 'true') == 'true')
    return InternalPaymentBackend()


@transaction.atomic
def create_for_offer(*, request: Request, offer: RequestOffer, actor=None) -> tuple[RequestPayment, str]:
    contract = RequestContract.objects.filter(request=request).first()
    if contract is None or contract.status != RequestContract.Status.APPROVED:
        raise PaymentError(_('بدون تأیید قرارداد امکان پرداخت وجود ندارد.'))  # rule 3
    if not request.identity_verified:
        raise PaymentError(_('بدون احراز هویت امکان پرداخت وجود ندارد.'))
    if not offer.has_price:
        raise PaymentError(_('مبلغ این پیشنهاد هنوز تعیین نشده است؛ لطفاً با کارشناس فروش تماس بگیرید.'))
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
        # A deliberate abort at the gateway (Zarinpal sends Status=NOK) is not a
        # failure — the customer can simply be offered the payment again. Only
        # the real gateway reports this; the internal simulator keeps using FAILED.
        aborted = str(data.get('Status') or data.get('status') or '').upper() == 'NOK'
        payment.status = (RequestPayment.Status.CANCELLED if aborted
                          else RequestPayment.Status.FAILED)
        payment.save(update_fields=['status', 'updated_at'])
        write_audit_log(
            actor=None, action='payment.failed', target_type='request_payment',
            target_id=str(payment.id),
            metadata={'aborted': aborted, 'authority': str(data.get('Authority', ''))[:64],
                      'status': str(data.get('Status') or data.get('result', ''))[:32]},
        )
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
        pattern=(sms_service.PAYMENT_PATTERN,
                 [req.full_name, payment.gateway_ref or str(req.id)]),
    )
    write_audit_log(actor=req.user, action='payment.paid', target_type='request_payment', target_id=str(payment.id))
    return payment
