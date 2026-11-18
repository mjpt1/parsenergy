"""Reverse geocoding through map.ir.

Turns the latitude/longitude a customer drops on the map into a Persian street
address, so nobody has to type one. Tiles themselves need no credentials — only
this lookup does, and the key stays on the server: it is never sent to the
browser, which is why the panel calls our own endpoint instead of map.ir.

SystemParameter keys:
    map_api_key     map.ir API key, sent as the ``x-api-key`` header (secret)
    map_base_url    endpoint base (default https://map.ir)

Same house style as the SMS and Shahkar services: stdlib urllib, a 15s timeout,
HTTPError handled separately from transport errors, and the proxy bypassed —
map.ir is an Iranian endpoint and a proxy in front of it only adds failures.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request

from django.utils.translation import gettext_lazy as _

from apps.core.models import SystemParameter

logger = logging.getLogger(__name__)

DEFAULT_MAP_BASE_URL = 'https://map.ir'
TIMEOUT_SECONDS = 15


class GeocodingError(Exception):
    """Raised when an address cannot be looked up (config or network errors)."""


def _param(key: str, default: str = '') -> str:
    param = SystemParameter.objects.filter(key=key).first()
    return param.value if param else default


def is_configured() -> bool:
    return bool(_param('map_api_key').strip() or _param('neshan_api_key').strip())


NESHAN_REVERSE_URL = 'https://api.neshan.org/v5/reverse'


def _neshan_reverse(lat: float, lng: float, api_key: str) -> dict:
    """Neshan reverse geocoding (platform.neshan.org, v5), used as a backup."""
    query = urllib.parse.urlencode({'lat': f'{lat:.6f}', 'lng': f'{lng:.6f}'})
    req = urllib.request.Request(f'{NESHAN_REVERSE_URL}?{query}', headers={
        'Api-Key': api_key, 'Accept': 'application/json'})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=TIMEOUT_SECONDS) as resp:
            payload = json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode('utf-8', 'replace')[:200]
        logger.warning('Neshan reverse geocode failed: HTTP %s %s', exc.code, detail)
        raise GeocodingError(_('سرویس نقشه پاسخ نداد.')) from exc
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        logger.warning('Neshan reverse geocode unreachable: %s', exc)
        raise GeocodingError(_('ارتباط با سرویس نقشه برقرار نشد.')) from exc
    if payload.get('status') != 'OK':
        raise GeocodingError(_('سرویس نقشه پاسخ نداد.'))
    state = (payload.get('state') or '').strip()
    if state.startswith('استان '):
        state = state[len('استان '):]
    return {
        'address': (payload.get('formatted_address') or '').strip(),
        'postal_address': '',
        'province': state,
        'city': (payload.get('city') or '').strip(),
    }


def reverse(lat: float, lng: float) -> dict:
    """Address for a point: map.ir first, Neshan if map.ir is missing or fails."""
    neshan_key = _param('neshan_api_key').strip()
    try:
        return _mapir_reverse(lat, lng)
    except GeocodingError:
        if not neshan_key:
            raise
    return _neshan_reverse(lat, lng, neshan_key)


def _mapir_reverse(lat: float, lng: float) -> dict:
    """Return ``{'address', 'postal_address', 'province', 'city'}`` for a point.

    Raises GeocodingError when the key is missing or map.ir cannot be reached;
    callers treat the address as a convenience and carry on without it.
    """
    api_key = _param('map_api_key').strip()
    if not api_key:
        raise GeocodingError(_('کلید نقشه تنظیم نشده است.'))

    base = (_param('map_base_url').strip() or DEFAULT_MAP_BASE_URL).rstrip('/')
    query = urllib.parse.urlencode({'lat': f'{lat:.6f}', 'lon': f'{lng:.6f}'})
    url = f'{base}/reverse/no?{query}'

    req = urllib.request.Request(url, headers={
        'x-api-key': api_key,
        'Accept': 'application/json',
    })
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=TIMEOUT_SECONDS) as resp:
            payload = json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode('utf-8', 'replace')[:200]
        logger.warning('map.ir reverse geocode failed: HTTP %s %s', exc.code, detail)
        raise GeocodingError(_('سرویس نقشه پاسخ نداد.')) from exc
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        logger.warning('map.ir reverse geocode unreachable: %s', exc)
        raise GeocodingError(_('ارتباط با سرویس نقشه برقرار نشد.')) from exc

    return {
        'address': (payload.get('address') or '').strip(),
        'postal_address': (payload.get('postal_address') or '').strip(),
        'province': (payload.get('province') or '').strip(),
        'city': (payload.get('city') or '').strip(),
    }
