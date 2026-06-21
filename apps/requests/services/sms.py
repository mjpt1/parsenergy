"""SMS service abstraction.

A pluggable backend sends the text; every message is persisted in
RequestMessageLog. The backend is chosen from SystemParameter config and
defaults to the console backend so the module works out of the box in dev.
"""
from __future__ import annotations

import json
import logging
import urllib.request
from abc import ABC, abstractmethod

from apps.core.models import SystemParameter

from ..models import RequestMessageLog

logger = logging.getLogger(__name__)


class SmsBackend(ABC):
    name = 'base'

    @abstractmethod
    def send(self, mobile: str, text: str) -> tuple[str, bool]:
        """Return (provider_message_id, success)."""


class ConsoleSmsBackend(SmsBackend):
    name = 'console'

    def send(self, mobile, text):
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

    def send(self, mobile, text):
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


def _param(key: str, default: str = '') -> str:
    param = SystemParameter.objects.filter(key=key).first()
    return param.value if param else default


def get_backend() -> SmsBackend:
    provider = _param('sms_provider', 'console')
    enabled = _param('sms_enabled', 'true') == 'true'
    if provider == 'http' and enabled:
        return HttpSmsBackend(_param('sms_base_url'), _param('sms_api_key'), _param('sms_sender'))
    return ConsoleSmsBackend()


def deliver(log: RequestMessageLog) -> RequestMessageLog:
    """Send an already-recorded (queued) message and update its delivery status."""
    backend = get_backend()
    provider_id, ok = backend.send(log.mobile, log.body)
    log.provider = backend.name
    log.provider_message_id = provider_id
    log.status = RequestMessageLog.Status.SENT if ok else RequestMessageLog.Status.FAILED
    log.save(update_fields=['provider', 'provider_message_id', 'status'])
    return log


def send_message(*, mobile, body, message_type, request=None, user=None) -> RequestMessageLog:
    """Record a message and deliver it in one step."""
    log = RequestMessageLog.objects.create(
        request=request,
        user=user,
        mobile=mobile,
        body=body,
        message_type=message_type,
        status=RequestMessageLog.Status.QUEUED,
    )
    return deliver(log)
