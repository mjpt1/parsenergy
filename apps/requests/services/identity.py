"""Identity verification (Shahkar) via the Shabanic API.

Shahkar checks that a mobile number belongs to a given national id. This mirrors
the SMS service: a pluggable backend chosen from SystemParameter config, with a
mock backend so the flow works out of the box (and in tests) without network.

SystemParameter keys:
    shahkar_provider    'mock' (default) | 'shabanic'
    shahkar_enabled     'true' | 'false'
    shahkar_base_url    endpoint URL (default https://shabanic.ir/api/v1/shahkar)
    shahkar_api_key     security token (sent as the SHABANIC-API-KEY header)
    shahkar_mock_result 'true' (default) | 'false'  -- result the mock returns

API (per Shabanic's official Python sample, callShahkarApi.py): POST ``{base_url}``
with a JSON body ``{"mobile": <m>, "national_code": <n>}`` and header
``SHABANIC-API-KEY: <token>``; the response is JSON
``{"result": {"isValid": true}, "status": "DONE", ...}``.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from abc import ABC, abstractmethod

from django.utils.translation import gettext_lazy as _

from apps.core.models import SystemParameter

logger = logging.getLogger(__name__)

DEFAULT_SHAHKAR_URL = 'https://shabanic.ir/api/v1/shahkar'


class IdentityError(Exception):
    """Raised when verification cannot be completed (network/config errors)."""


class IdentityBackend(ABC):
    name = 'base'

    @abstractmethod
    def verify(self, mobile: str, national_code: str) -> tuple[bool, str]:
        """Return (matched, detail)."""


class MockIdentityBackend(IdentityBackend):
    """Default/dev backend: returns a configurable result with no network call."""
    name = 'mock'

    def __init__(self, result: bool = True):
        self.result = result

    def verify(self, mobile, national_code):
        logger.info('Shahkar(mock) %s / %s -> %s', mobile, national_code, self.result)
        return (self.result, 'mock')


class ShabanicIdentityBackend(IdentityBackend):
    """Calls the Shabanic Shahkar API exactly like the official Python sample:
    POST a JSON body ``{mobile, national_code}`` with the token in the
    ``SHABANIC-API-KEY`` header. A match is ``result.isValid == true`` (with
    ``status == 'DONE'``) in the JSON response."""
    name = 'shabanic'

    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url or DEFAULT_SHAHKAR_URL
        self.api_key = api_key

    def verify(self, mobile, national_code):
        if not self.api_key:
            raise IdentityError(_('پیکربندی سرویس احراز هویت کامل نیست.'))
        payload = json.dumps({'mobile': mobile, 'national_code': national_code}).encode('utf-8')
        request = urllib.request.Request(self.base_url, data=payload, method='POST', headers={
            'SHABANIC-API-KEY': self.api_key,
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        })
        # Shabanic is an Iranian endpoint that allow-lists the caller IP; bypass any
        # ambient HTTP(S) proxy so the request leaves from this server's own IP.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(request, timeout=15) as resp:
                body = resp.read().decode('utf-8', 'ignore')
        except urllib.error.HTTPError as exc:
            raw = ''
            try:
                raw = exc.read().decode('utf-8', 'ignore')
            except Exception:  # noqa: BLE001
                pass
            logger.warning('Shahkar HTTP %s: %s', exc.code, raw[:500])
            server_msg = ''
            if raw:
                try:
                    server_msg = (json.loads(raw) or {}).get('error', '') or ''
                except ValueError:
                    server_msg = ''
            raise IdentityError(
                server_msg or (_('سرویس احراز هویت خطا داد (کد %(code)s).') % {'code': exc.code})
            ) from exc
        except Exception as exc:  # noqa: BLE001
            logger.warning('Shahkar connection error: %s', exc)
            raise IdentityError(_('ارتباط با سرویس احراز هویت برقرار نشد.')) from exc
        try:
            data = json.loads(body)
        except ValueError as exc:
            raise IdentityError(_('پاسخ سرویس احراز هویت نامعتبر است.')) from exc
        result = data.get('result') or {}
        matched = bool(result.get('isValid')) and str(data.get('status', 'DONE')).upper() == 'DONE'
        track = data.get('trackId') or data.get('responseCode') or data.get('status') or ''
        return (matched, str(track)[:200])


def _param(key: str, default: str = '') -> str:
    param = SystemParameter.objects.filter(key=key).first()
    return param.value if param else default


def get_backend() -> IdentityBackend:
    provider = _param('shahkar_provider', 'mock')
    enabled = _param('shahkar_enabled', 'true') == 'true'
    if provider == 'shabanic' and enabled:
        return ShabanicIdentityBackend(_param('shahkar_base_url'), _param('shahkar_api_key'))
    return MockIdentityBackend(result=_param('shahkar_mock_result', 'true') == 'true')


def verify_identity(mobile: str, national_code: str) -> tuple[bool, str]:
    """Check (via Shahkar) that ``mobile`` belongs to ``national_code``."""
    return get_backend().verify(mobile, national_code)
