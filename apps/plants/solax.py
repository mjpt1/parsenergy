"""SolaX Cloud developer API (OAuth2 client credentials) -> plant telemetry.

    token:    POST {host}/openapi/auth/oauth/token  (client_id, client_secret, grant_type)
    realtime: GET  {host}/openapi/v2/device/realtime_data?snList=SN1,SN2&deviceType=1&businessType=1

Only one token is live per application, so it is cached on the CloudAccount and
renewed shortly before it expires; asking for a new one on every sync would
cancel the token any other client of the same application is using.
"""
from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from .models import CloudAccount, Equipment, Inverter, InverterSample, RealtimeMeasurement, TelemetryReading

logger = logging.getLogger(__name__)

TIMEOUT = 20
AUTH_OK, DATA_OK = 0, 10000
TOKEN_REJECTED = 10402
# SolaX deviceStatus codes that mean the inverter is not producing.
OFFLINE_STATUSES = {100: 'wait', 101: 'check', 103: 'fault', 104: 'permanent_fault', 107: 'off'}
STATUS_NAMES = {102: 'normal', 105: 'update', 106: 'eps_check', 108: 'self_test', 109: 'idle', 110: 'standby'}


class SolaxError(Exception):
    pass


def _call(url, *, data=None, token=None):
    headers = {'Accept': 'application/json'}
    body = None
    if data is not None:
        body = urllib.parse.urlencode(data).encode()
        headers['Content-Type'] = 'application/x-www-form-urlencoded'
    if token:
        headers['Authorization'] = f'bearer {token}'
    req = urllib.request.Request(url, data=body, headers=headers, method='POST' if body else 'GET')
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        raise SolaxError(f'HTTP {exc.code} از {urllib.parse.urlsplit(url).netloc}') from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise SolaxError(f'اتصال به {urllib.parse.urlsplit(url).netloc} برقرار نشد ({exc})') from exc
    except ValueError as exc:
        raise SolaxError('پاسخ سرور سولاکس قابل خواندن نبود.') from exc


def get_token(account: CloudAccount, *, force=False) -> str:
    now = timezone.now()
    if (not force and account.access_token and account.token_expires_at
            and account.token_expires_at - now > timedelta(hours=1)):
        return account.access_token
    reply = _call(f'{account.api_host.rstrip("/")}/openapi/auth/oauth/token', data={
        'client_id': account.client_id, 'client_secret': account.client_secret,
        'grant_type': 'client_credentials'})
    result = reply.get('result') or {}
    if reply.get('code') != AUTH_OK or not result.get('access_token'):
        raise SolaxError(f'ورود به سولاکس ناموفق بود: {reply.get("message") or reply.get("code")}')
    account.access_token = result['access_token']
    account.token_expires_at = now + timedelta(seconds=int(result.get('expires_in') or 2591999))
    account.save(update_fields=['access_token', 'token_expires_at', 'updated_at'])
    return account.access_token


def fetch_realtime(account: CloudAccount, serials: list[str]) -> dict[str, dict]:
    """Realtime rows keyed by inverter serial (keys lower-cased, as SolaX varies the case)."""
    query = urllib.parse.urlencode({'snList': ','.join(serials), 'deviceType': 1,
                                    'businessType': account.business_type})
    url = f'{account.api_host.rstrip("/")}/openapi/v2/device/realtime_data?{query}'
    reply = _call(url, token=get_token(account))
    if reply.get('code') == TOKEN_REJECTED:   # token cancelled elsewhere: renew once
        reply = _call(url, token=get_token(account, force=True))
    if reply.get('code') != DATA_OK:
        raise SolaxError(f'سولاکس داده نداد: {reply.get("message") or reply.get("code")}')
    rows = reply.get('result') or []
    if isinstance(rows, dict):
        rows = [rows]
    out = {}
    for row in rows:
        row = {str(k).lower(): v for k, v in row.items()}
        sn = str(row.get('devicesn') or '').strip()
        if sn:
            out[sn.upper()] = row
    return out


def _dec(value, default='0'):
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal(default)


def total_kw(row: dict, rated_kw=None) -> Decimal:
    """Total AC power in kW. SolaX sends watts for some plants and kilowatts for
    others (a 125 kW C&I inverter reported 66 at 66 kW), so the unit is read off
    the phase voltage x current when present, else off the inverter's rating."""
    raw = _dec(row.get('totalactivepower', row.get('acpower', 0)))
    measured = sum((_dec(row.get(f'acvoltage{i}')) * _dec(row.get(f'accurrent{i}')) for i in (1, 2, 3)),
                   Decimal('0')) / 1000
    if measured > 0:
        return raw if abs(raw - measured) <= abs(raw / 1000 - measured) else raw / 1000
    if rated_kw and raw <= _dec(rated_kw) * Decimal('1.5'):
        return raw
    return raw / 1000


def _number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _channels(row: dict, name: str, prefix: str) -> list[dict]:
    """PV strings or MPPT trackers from their nested map, power worked out from V x I."""
    values = row.get(name)
    if not isinstance(values, dict):
        return []
    pattern = re.compile(rf'^{prefix}(\d+)(voltage|current)$')
    found = {}
    for key, value in values.items():
        match = pattern.match(str(key).lower())
        number = _number(value)
        if match and number is not None:
            found.setdefault(int(match.group(1)), {})[match.group(2)] = number
    rows = []
    for index in sorted(found):
        voltage, current = found[index].get('voltage', 0), found[index].get('current', 0)
        rows.append({'number': index, 'voltage': voltage, 'current': current,
                     'kw': round(voltage * current / 1000, 3)})
    return rows


def numeric_fields(row: dict) -> dict:
    """Every number the cloud sent, nested maps included, under lower-case names."""
    values = {}
    for key, value in row.items():
        if isinstance(value, dict):
            values.update(numeric_fields({str(k).lower(): v for k, v in value.items()}))
        elif not isinstance(value, bool):
            number = _number(value)
            if number is not None:
                values[str(key).lower()] = number
    return values


def detail_snapshot(row: dict) -> dict:
    """What the page shows about an inverter beyond power and daily energy."""
    pv, mppt = _channels(row, 'pvmap', 'pv'), _channels(row, 'mpptmap', 'mppt')
    phases = []
    for number in (1, 2, 3):
        voltage, current = _number(row.get(f'acvoltage{number}')), _number(row.get(f'accurrent{number}'))
        if voltage is not None or current is not None:
            phases.append({'number': number, 'voltage': voltage or 0, 'current': current or 0})
    source = mppt or pv
    return {
        'temperature_c': _number(row.get('invertertemperature')),
        'total_yield_kwh': _number(row.get('totalyield')),
        'power_factor': _number(row.get('totalpowerfactor')),
        'grid_frequency': _number(row.get('gridfrequency')),
        'dc_kw': round(sum(item['kw'] for item in source), 2) if source else None,
        'phases': phases,
        'pv': pv,
        'mppt': mppt,
        'fields': numeric_fields(row),
    }


def store_reading(inverter: Inverter, row: dict) -> None:
    """Write one realtime row as telemetry the dashboards and reports already read."""
    now = timezone.now()
    power_kw = total_kw(row, inverter.rated_power_kw)
    daily = _dec(row.get('dailyyield'), default='0')
    prev = inverter.last_daily_yield_kwh
    # Energy since the previous sync; the cloud's daily counter restarts at midnight.
    delta = daily if prev is None or daily < prev else daily - prev
    status_code = row.get('devicestatus')
    online = status_code not in OFFLINE_STATUSES if status_code is not None else power_kw > 0
    equipment, _ = Equipment.objects.get_or_create(
        plant=inverter.plant, serial_number=inverter.serial_number,
        defaults={'category': 'inverter', 'name': inverter.model_name or inverter.serial_number,
                  'health_status': 'healthy'})
    Equipment.objects.filter(pk=equipment.pk).update(online=online, last_seen_at=now)
    TelemetryReading.objects.create(
        plant=inverter.plant, inverter=inverter, power_kw=power_kw,
        voltage_v=_dec(row.get('gridvoltage', row.get('l1voltage', 0))),
        current_a=_dec(row.get('gridcurrent', row.get('l1current', 0))),
        frequency_hz=_dec(row.get('gridfrequency', 0)), energy_kwh=delta,
        status=STATUS_NAMES.get(status_code, OFFLINE_STATUSES.get(status_code, 'normal')))
    for parameter, value, unit in (('power', power_kw, 'kW'), ('energy', delta, 'kWh')):
        RealtimeMeasurement.objects.create(timestamp=now, plant=inverter.plant, equipment=equipment,
                                           parameter=parameter, value=value, unit=unit)
    inverter.online = online
    inverter.status = STATUS_NAMES.get(status_code, OFFLINE_STATUSES.get(status_code, inverter.status))
    inverter.last_daily_yield_kwh = daily
    inverter.last_synced_at = now
    inverter.last_sync_error = ''
    inverter.latest_data = detail_snapshot(row)
    InverterSample.objects.create(inverter=inverter, data={
        key: value for key, value in inverter.latest_data.items() if key != 'fields'})
    inverter.save(update_fields=['online', 'status', 'last_daily_yield_kwh', 'last_synced_at', 'last_sync_error',
                                 'latest_data'])


def sync_account(account: CloudAccount) -> tuple[int, list[str]]:
    """Read every SolaX inverter of this account. Returns (stored, problems)."""
    inverters = list(account.inverters.filter(data_source=Inverter.DataSource.SOLAX).select_related('plant'))
    if not inverters:
        return 0, []
    stored, problems = 0, []
    try:
        for start in range(0, len(inverters), 10):   # the API takes up to 10 serials per call
            batch = inverters[start:start + 10]
            rows = fetch_realtime(account, [i.serial_number.strip() for i in batch])
            for inv in batch:
                row = rows.get(inv.serial_number.strip().upper())
                if row is None:
                    inv.last_sync_error = 'این شماره سریال در حساب سولاکس پیدا نشد.'
                    inv.save(update_fields=['last_sync_error'])
                    problems.append(f'{inv.serial_number}: {inv.last_sync_error}')
                    continue
                store_reading(inv, row)
                stored += 1
        account.last_error = ''
    except SolaxError as exc:
        account.last_error = str(exc)[:500]
        problems.append(account.last_error)
        Inverter.objects.filter(pk__in=[i.pk for i in inverters]).update(last_sync_error=account.last_error)
    account.save(update_fields=['last_error', 'updated_at'])
    return stored, problems
