"""SMS service abstraction.

A pluggable backend sends the text; every message is persisted in
RequestMessageLog. The backend is chosen from SystemParameter config and
defaults to the console backend so the module works out of the box in dev.
"""
from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod

from apps.core.models import SystemParameter

from ..models import RequestMessageLog

logger = logging.getLogger(__name__)


class SmsBackend(ABC):
    name = 'base'

    @abstractmethod
    def send(self, mobile: str, text: str, message_type: str | None = None) -> tuple[str, bool]:
        """Return (provider_message_id_or_error, success)."""


class ConsoleSmsBackend(SmsBackend):
    name = 'console'

    def send(self, mobile, text, message_type=None):
        # Use logging (never a bare print): logging swallows stream encoding
        # errors, so non-ASCII text can't crash the request on a cp1252 console.
        logger.info('SMS -> %s: %s', mobile, text)
        return ('console', True)


class HttpSmsBackend(SmsBackend):
    """Generic HTTP backend: POSTs JSON {to, message, sender} to a configured URL."""
    name = 'http'

    def __init__(self, base_url: str, api_key: str = '', sender: str = ''):
        self.base_url = base_url
        self.api_key = api_key
        self.sender = sender

    def send(self, mobile, text, message_type=None):
        if not self.base_url:
            return ('no-endpoint', False)
        payload = json.dumps({'to': mobile, 'message': text, 'sender': self.sender}).encode('utf-8')
        request = urllib.request.Request(
            self.base_url, data=payload, headers={'Content-Type': 'application/json'},
        )
        if self.api_key:
            request.add_header('Authorization', f'Bearer {self.api_key}')
        try:
            with urllib.request.urlopen(request, timeout=10) as resp:
                body = resp.read().decode('utf-8', 'ignore')
                return ((body[:120] or 'sent'), 200 <= resp.status < 300)
        except Exception as exc:  # noqa: BLE001 - any delivery failure is recorded, not raised
            return (str(exc)[:120], False)


def _to_local(mobile: str) -> str:
    """Normalise an Iranian mobile to local format (09xxxxxxxxx) for IranPayamak."""
    m = (mobile or '').strip().replace(' ', '').replace('-', '')
    if m.startswith('+98'):
        m = '0' + m[3:]
    elif m.startswith('0098'):
        m = '0' + m[4:]
    elif m.startswith('98') and len(m) >= 12:
        m = '0' + m[2:]
    elif m.startswith('9') and len(m) == 10:
        m = '0' + m
    return m


class IranpayamakSmsBackend(SmsBackend):
    """FarazSMS / iranpayamak (api.iranpayamak.com ws/v1).

    OTP codes are sent through an approved pattern (immediate delivery on a
    service line); other messages use the free-text endpoint. Auth is the
    ``Api-Key`` header; recipients are local (09...) and number_format='english'.
    """
    name = 'iranpayamak'
    BASE = 'https://api.iranpayamak.com/ws/v1'

    def __init__(self, api_key, line_number, pattern_code='', pattern_var='code',
                 number_format='english', base_url=''):
        self.api_key = api_key
        self.line_number = line_number
        self.pattern_code = pattern_code
        self.pattern_var = pattern_var or 'code'
        self.number_format = number_format or 'english'
        b = (base_url or '').strip().rstrip('/')
        # Accept a full /sms/pattern URL or a bare base; reduce to the ws/v1 base.
        for suffix in ('/sms/pattern', '/sms/simple'):
            if b.endswith(suffix):
                b = b[: -len(suffix)]
        self.base = b or self.BASE

    def _post(self, path, body):
        if not self.api_key or not self.line_number:
            return ('کلید API یا خط فرستنده تنظیم نشده', False)
        req = urllib.request.Request(
            self.base + path, data=json.dumps(body).encode('utf-8'),
            headers={'Api-Key': self.api_key, 'Content-Type': 'application/json',
                     'Accept': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read().decode('utf-8', 'ignore')
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode('utf-8', 'ignore') if hasattr(exc, 'read') else ''
            logger.warning('IranPayamak HTTP %s: %s', exc.code, detail[:200])
            return (f'http {exc.code}: {detail[:90]}', False)
        except Exception as exc:  # noqa: BLE001
            logger.warning('IranPayamak send error: %s', exc)
            return (str(exc)[:120], False)
        try:
            data = json.loads(raw)
        except ValueError:
            return (raw[:120] or 'sent', True)
        ok = data.get('status') == 'success'
        if not ok:
            logger.warning('IranPayamak rejected: %s', raw[:200])
            return (str(data.get('message') or raw)[:120], False)
        msg_id = (data.get('data') or {}).get('id')
        return (str(msg_id or 'sent'), True)

    def send(self, mobile, text, message_type=None):
        recipient = _to_local(mobile)
        if message_type == RequestMessageLog.MessageType.OTP and self.pattern_code:
            match = re.search(r'\d{4,8}', text or '')
            code = match.group(0) if match else (text or '')
            return self._post('/sms/pattern', {
                'code': self.pattern_code,
                'recipient': recipient,
                'attributes': {self.pattern_var: code},
                'line_number': self.line_number,
                'number_format': self.number_format,
            })
        # Notifications / non-OTP: free text (service lines may need approval).
        return self._post('/sms/simple', {
            'text': text,
            'recipients': [recipient],
            'line_number': self.line_number,
            'number_format': self.number_format,
        })


class MelliPayamakSmsBackend(SmsBackend):
    """ملی پیامک — melipayamak.com REST API (rest.payamak-panel.com).

    Unlike IranPayamak this panel authenticates with the account
    username/password rather than an API key, so `sms_username` holds the
    username and `sms_api_key` the password.

    OTP codes go through an approved pattern (``BaseServiceNumber`` + bodyId)
    which delivers instantly on a shared service line; everything else uses the
    plain ``SendSMS`` endpoint from your own line. A reply is considered
    successful only when ``RetStatus == 1``.
    """
    name = 'melipayamak'
    BASE = 'https://rest.payamak-panel.com/api/SendSMS'

    def __init__(self, username, password, sender='', pattern_code='', base_url=''):
        self.username = username
        self.password = password
        self.sender = sender
        self.pattern_code = pattern_code
        b = (base_url or '').strip().rstrip('/')
        for suffix in ('/SendSMS', '/BaseServiceNumber'):
            if b.endswith(suffix):
                b = b[: -len(suffix)]
        self.base = b or self.BASE

    def _post(self, path, body):
        if not self.username or not self.password:
            return ('نام کاربری یا رمز ملی پیامک تنظیم نشده', False)
        payload = dict(body, username=self.username, password=self.password)
        req = urllib.request.Request(
            # ensure_ascii=False: the pattern endpoint drops \uXXXX-escaped
            # Persian, so a name variable arrived empty ("عزیز،" with no name).
            self.base + path, data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
            headers={'Content-Type': 'application/json', 'Accept': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read().decode('utf-8', 'ignore')
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode('utf-8', 'ignore') if hasattr(exc, 'read') else ''
            logger.warning('MelliPayamak HTTP %s: %s', exc.code, detail[:200])
            return (f'http {exc.code}: {detail[:90]}', False)
        except Exception as exc:  # noqa: BLE001 - delivery failures are recorded, not raised
            logger.warning('MelliPayamak send error: %s', exc)
            return (str(exc)[:120], False)
        try:
            data = json.loads(raw)
        except ValueError:
            return (raw[:120] or 'sent', False)
        # RetStatus 1 = the call was accepted. Even then `Value` is only a
        # delivery id when it is a long number; a short one is MelliPayamak's
        # error code (11 = not sent, 14 = text contains a link, ...). Treating
        # those as success is how failed sends used to show up as "sent".
        value = str(data.get('Value') or '')
        if str(data.get('RetStatus')) != '1':
            logger.warning('MelliPayamak rejected: %s', raw[:200])
            code = value if value.isdigit() and len(value) <= 3 else ''
            reason = self.ERRORS.get(code, '')
            label = str(data.get('StrRetStatus') or value or raw)
            return (f'{label} {code} {reason}'.strip()[:120], False)
        if value.isdigit() and len(value) <= 3:
            logger.warning('MelliPayamak not sent: %s', raw[:200])
            return (f'{value} {self.ERRORS.get(value, "خطای ناشناخته")}'[:120], False)
        return (value or 'sent', True)

    # From the MelliPayamak web-service documentation.
    ERRORS = {
        '0': 'نام کاربری یا رمز عبور نادرست است',
        '2': 'اعتبار کافی نیست',
        '3': 'محدودیت ارسال روزانه',
        '4': 'محدودیت حجم ارسال',
        '5': 'شمارهٔ فرستنده معتبر نیست',
        '6': 'سامانه در حال به‌روزرسانی است',
        '7': 'متن حاوی کلمهٔ فیلترشده است',
        '9': 'ارسال از خط عمومی با وب‌سرویس ممکن نیست',
        '10': 'کاربر فعال نیست',
        '11': 'ارسال نشد',
        '12': 'مدارک کاربر کامل نیست',
        '14': 'متن حاوی لینک است',
        '15': 'عبارت «لغو11» در متن نیست',
        '35': 'شماره در لیست سیاه مخابرات است',
    }

    def send_pattern(self, mobile, body_id, args):
        """Send an approved pattern; `args` fill {0}, {1}, ... in order."""
        return self._post('/BaseServiceNumber', {
            'text': ';'.join(str(a).replace(';', ' ') for a in args),
            'to': _to_local(mobile),
            'bodyId': body_id,
        })

    def send(self, mobile, text, message_type=None):
        recipient = _to_local(mobile)
        if message_type == RequestMessageLog.MessageType.OTP and self.pattern_code:
            match = re.search(r'\d{4,8}', text or '')
            code = match.group(0) if match else (text or '')
            # `text` carries the pattern's variable values, ';'-separated.
            return self._post('/BaseServiceNumber', {
                'text': code,
                'to': recipient,
                'bodyId': self.pattern_code,
            })
        return self._post('/SendSMS', {
            'to': recipient,
            'from': self.sender,
            'text': text,
            'isflash': False,
        })


#: Approved MelliPayamak patterns for this account. They are built in so
#: nobody has to type them; a value saved in the settings page overrides one.
LEAD_LINK_PATTERN = 'sms_pattern_lead'          # "{0} عزیز، ... pars-tida.ir/leads/f/{1}"
CONTRACT_PATTERN = 'sms_pattern_contract'       # "{0} کد تایید قرارداد شما {1} ..."
RECEIVED_PATTERN = 'sms_pattern_received'      # "{0} عزیز، اطلاعات شما دریافت شد. کد پیگیری: {1}"
STATUS_PATTERN = 'sms_pattern_status'          # "وضعیت درخواست شماره {0} شما به «{1}» تغییر کرد."
PAYMENT_PATTERN = 'sms_pattern_payment'        # "{0} عزیز، پرداخت شما با موفقیت انجام شد. کد پیگیری: {1}"
PATTERN_DEFAULTS = {
    'sms_pattern_code': '520649',               # "کد ورود شما {0} ..."
    LEAD_LINK_PATTERN: '564762',
    CONTRACT_PATTERN: '520895',
    RECEIVED_PATTERN: '565043',
    STATUS_PATTERN: '565044',
    PAYMENT_PATTERN: '565046',
}


def pattern_code(key: str) -> str:
    """The pattern for `key`: the saved setting, else the built-in default."""
    return (_param(key) or PATTERN_DEFAULTS.get(key, '')).strip()


MELIPAYAMAK_OTP_URL ='https://console.melipayamak.com/api/send/otp/{key}'


def provider_otp(mobile: str) -> tuple[str | None, str]:
    """Ask MelliPayamak's own OTP service to create and send a code.

    Returns ``(code, note)``. ``code`` is None when the service is not set up
    or did not answer with a code; callers then fall back to sending a code we
    generate ourselves. The key is the token at the end of the console URL.
    """
    if _param('sms_enabled', 'true') != 'true':
        return None, 'disabled'
    if _param('sms_provider', 'console') not in ('melipayamak', 'mellipayamak'):
        return None, 'not melipayamak'
    key = _param('sms_otp_key').strip()
    if not key:
        return None, 'no otp key'
    req = urllib.request.Request(
        MELIPAYAMAK_OTP_URL.format(key=urllib.parse.quote(key, safe='')),
        data=json.dumps({'to': _to_local(mobile)}).encode('utf-8'),
        headers={'Content-Type': 'application/json', 'Accept': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode('utf-8', 'ignore'))
    except urllib.error.HTTPError as exc:
        logger.warning('MelliPayamak OTP HTTP %s', exc.code)
        return None, f'otp http {exc.code}'
    except Exception as exc:  # noqa: BLE001 - fall back to the pattern route
        logger.warning('MelliPayamak OTP error: %s', exc)
        return None, f'otp error: {str(exc)[:80]}'
    code = str(data.get('code') or '').strip()
    if not code.isdigit():
        logger.warning('MelliPayamak OTP rejected: %s', str(data.get('status'))[:200])
        return None, f'otp rejected: {str(data.get("status") or "")[:80]}'
    return code, 'melipayamak-otp'


def _param(key: str, default: str = '') -> str:
    param = SystemParameter.objects.filter(key=key).first()
    return param.value if param else default


def get_backend() -> SmsBackend:
    provider = _param('sms_provider', 'console')
    enabled = _param('sms_enabled', 'true') == 'true'
    if not enabled:
        return ConsoleSmsBackend()
    if provider in ('iranpayamak', 'ippanel', 'farazsms'):
        return IranpayamakSmsBackend(
            _param('sms_api_key'), _param('sms_sender'),
            pattern_code=_param('sms_pattern_code'),
            pattern_var=_param('sms_pattern_var', 'code'),
            base_url=_param('sms_base_url'))
    if provider in ('melipayamak', 'mellipayamak'):
        # Panel credentials: username in sms_username, password in sms_api_key.
        return MelliPayamakSmsBackend(
            _param('sms_username'), _param('sms_api_key'),
            sender=_param('sms_sender'),
            pattern_code=pattern_code('sms_pattern_code'),
            base_url=_param('sms_base_url'))
    if provider == 'http':
        return HttpSmsBackend(_param('sms_base_url'), _param('sms_api_key'), _param('sms_sender'))
    return ConsoleSmsBackend()


def deliver(log: RequestMessageLog, pattern: tuple[str, list] | None = None) -> RequestMessageLog:
    """Send an already-recorded (queued) message and update its delivery status.

    `pattern` is ``(setting_key, args)``. When that setting holds an approved
    pattern code and the backend supports patterns, the pattern is sent with
    ``args`` as its variables; otherwise the plain text in ``log.body`` is.
    Patterns go out on a service line, which reaches numbers that block
    advertising SMS and may carry our own link.
    """
    backend = get_backend()
    body_id = pattern_code(pattern[0]) if pattern else ''
    if body_id and hasattr(backend, 'send_pattern'):
        provider_id, ok = backend.send_pattern(log.mobile, body_id, pattern[1])
    else:
        provider_id, ok = backend.send(log.mobile, log.body, log.message_type)
    log.provider = backend.name
    log.provider_message_id = provider_id
    log.status = RequestMessageLog.Status.SENT if ok else RequestMessageLog.Status.FAILED
    log.save(update_fields=['provider', 'provider_message_id', 'status'])
    return log


def send_message(*, mobile, body, message_type, request=None, user=None,
                 pattern: tuple[str, list] | None = None) -> RequestMessageLog:
    """Record a message and deliver it in one step."""
    log = RequestMessageLog.objects.create(
        request=request,
        user=user,
        mobile=mobile,
        body=body,
        message_type=message_type,
        status=RequestMessageLog.Status.QUEUED,
    )
    return deliver(log, pattern)
