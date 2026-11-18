"""The plant's live screen: one payload for the big-picture page of each plant."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import jdatetime
from django.core.cache import cache
from django.utils import timezone

from apps.core.localtime import day_start

from .models import TelemetryReading
from .revenue import (LIVE_MAX_AGE, _jalali_time, _live_power, build_revenue, jalali_text, number_text,
                      plant_rates)

CACHE_SECONDS = 45
MONTHS = ('فروردین', 'اردیبهشت', 'خرداد', 'تیر', 'مرداد', 'شهریور', 'مهر', 'آبان', 'آذر', 'دی', 'بهمن', 'اسفند')
_FA = str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹')
# Per kWh, from the national renewable portal's own calculator.
IMPACT = (
    ('کاهش انتشار CO₂', Decimal('0.599'), 'کیلوگرم', 0),
    ('معادل کاشت درخت', Decimal('0.024'), 'اصله', 0),
    ('صرفه‌جویی گاز طبیعی', Decimal('0.27'), 'مترمکعب', 0),
    ('صرفه‌جویی آب', Decimal('0.22'), 'لیتر', 0),
)


def _rate_on(rates, day):
    return next((r.rate_rial_per_kwh for r in reversed(rates) if r.valid_from <= day), None)


def _series(labels, kwh, toman):
    return {'labels': labels, 'kwh': [round(float(v), 1) for v in kwh],
            'toman': [round(float(v)) for v in toman] if toman is not None else None}


def _energy_views(plant, rates, now):
    today = timezone.localdate()
    jtoday = jdatetime.date.fromgregorian(date=today)
    year_first = jdatetime.date(jtoday.year, 1, 1).togregorian()
    first = min(year_first, today - timedelta(days=29))
    hours, days = {}, {}
    rows = TelemetryReading.objects.filter(plant=plant, created_at__gte=day_start(first)).values_list('created_at', 'energy_kwh')
    for moment, kwh in rows.iterator():
        local = timezone.localtime(moment)
        amount = kwh or Decimal('0')
        days[local.date()] = days.get(local.date(), Decimal('0')) + amount
        if local.date() == today:
            hours[local.hour] = hours.get(local.hour, Decimal('0')) + amount
    has_rate = bool(rates)

    def money(day, kwh):
        rate = _rate_on(rates, day)
        return kwh * rate / 10 if rate else Decimal('0')

    now_hour = timezone.localtime(now).hour
    hour_rows = [hours.get(h, Decimal('0')) for h in range(now_hour + 1)]
    views = {'day': _series([f'{h:02d}:00'.translate(_FA) for h in range(now_hour + 1)], hour_rows,
                            [money(today, v) for v in hour_rows] if has_rate else None)}
    for key, count in (('week', 7), ('month', 30)):
        span = [today - timedelta(days=count - 1 - i) for i in range(count)]
        values = [days.get(d, Decimal('0')) for d in span]
        views[key] = _series([jalali_text(d)[5:] for d in span], values,
                             [money(d, v) for d, v in zip(span, values)] if has_rate else None)
    month_kwh, month_toman = [Decimal('0')] * jtoday.month, [Decimal('0')] * jtoday.month
    for day, kwh in days.items():
        jday = jdatetime.date.fromgregorian(date=day)
        if jday.year == jtoday.year:
            month_kwh[jday.month - 1] += kwh
            month_toman[jday.month - 1] += money(day, kwh)
    views['year'] = _series(list(MONTHS[:jtoday.month]), month_kwh, month_toman if has_rate else None)
    return views


def _power_curve(plant):
    points = {}
    rows = TelemetryReading.objects.filter(plant=plant, created_at__gte=day_start(timezone.localdate())).order_by(
        'created_at').values_list('created_at', 'power_kw')
    for moment, power in rows.iterator():
        local = timezone.localtime(moment)
        slot = local.hour * 60 + local.minute - local.minute % 5
        points.setdefault(slot, {})[moment.isoformat()] = float(power)
    labels, values = [], []
    for slot in sorted(points):
        labels.append(f'{slot // 60:02d}:{slot % 60:02d}'.translate(_FA))
        values.append(round(sum(points[slot].values()), 1))
    return {'labels': labels, 'kw': values}


def _inverter_rows(plant, sections, now):
    today = timezone.localdate()
    rows, lifetime = [], Decimal('0')
    for inverter in plant.inverters.order_by('id'):
        last = inverter.telemetry_readings.order_by('-created_at').first()
        fresh = last is not None and now - last.created_at <= LIVE_MAX_AGE
        data = inverter.latest_data or {}
        lifetime += Decimal(str(data.get('total_yield_kwh') or 0))
        synced_today = inverter.last_synced_at and timezone.localtime(inverter.last_synced_at).date() == today
        today_kwh = inverter.last_daily_yield_kwh if synced_today and inverter.last_daily_yield_kwh is not None else Decimal('0')
        kwp = sum((s.kwp for s in sections if s.inverter_id == inverter.pk), Decimal('0')) or inverter.rated_power_kw
        power = last.power_kw if fresh else None
        state = ('ok', 'در حال تولید') if fresh and power > 0 else (
            ('idle', 'بدون تولید') if fresh else ('warn', 'بدون دادهٔ تازه'))
        rows.append({
            'name': inverter.model_name or inverter.serial_number, 'serial': inverter.serial_number,
            'tone': state[0], 'state': state[1], 'kwp': number_text(kwp, 2),
            'power': number_text(power, 1) if power is not None else '—',
            'today': number_text(today_kwh, 1),
            'hours': number_text(today_kwh / kwp, 2) if kwp else '—',
            'temperature': number_text(Decimal(str(data['temperature_c'])), 0) if fresh and data.get('temperature_c') is not None else '—',
        })
    return rows, lifetime


def _dc_power(plant, now):
    values = []
    for inverter in plant.inverters.all():
        if inverter.last_synced_at and now - inverter.last_synced_at <= LIVE_MAX_AGE:
            value = (inverter.latest_data or {}).get('dc_kw')
            if value is not None:
                values.append(Decimal(str(value)))
    return sum(values, Decimal('0')) if values else None


def _build(plant):
    now = timezone.now()
    revenue = build_revenue(plant)
    periods = {p['key']: p for p in revenue['periods']}
    rates = plant_rates(plant)
    sections = list(plant.sections.select_related('inverter'))
    connected = Decimal(plant.active_capacity_kw or 0)
    installed = sum((s.kwp for s in sections), Decimal('0')) or Decimal(plant.capacity_kw or 0)
    inverters, lifetime = _inverter_rows(plant, sections, now)
    power, last_at = _live_power(plant, now)
    today_kwh = sum((r for r in TelemetryReading.objects.filter(
        plant=plant, created_at__gte=day_start(timezone.localdate())).values_list('energy_kwh', flat=True) if r), Decimal('0'))
    if power is None:
        state = ('warn', 'بدون دادهٔ تازه') if last_at else ('idle', 'هنوز داده‌ای نرسیده')
    elif power > 0:
        state = ('ok', 'در حال تولید')
    else:
        state = ('idle', 'بدون تولید در این لحظه')
    dc = _dc_power(plant, now)
    percent = min(float(power * 100 / connected), 100) if power is not None and connected else 0
    return {
        'plant': {'name': plant.name, 'location': plant.location_name, 'contract': number_text(plant.capacity_kw, 0),
                  'installed': number_text(installed, 2), 'connected': number_text(connected, 2)},
        'status': {'tone': state[0], 'label': state[1], 'updated': _jalali_time(last_at) if last_at else ''},
        'live': {'power': number_text(power, 1) if power is not None else '—',
                 'dc': number_text(dc, 1) if dc is not None else '—',
                 'percent': round(percent), 'active': bool(power and power > 0)},
        'today': {'kwh': number_text(today_kwh, 1), 'toman': periods['today']['toman_text'] if rates else '—',
                  'hours': number_text(today_kwh / connected, 2) if connected else '—',
                  'per_hour': revenue['now_toman_text']},
        'totals': {'lifetime': number_text(lifetime, 0), 'income': periods['all']['toman_text'] if rates else '—',
                   'rate': revenue['rate_toman_text']},
        'impact': [{'label': label, 'value': number_text(lifetime * factor, places), 'unit': unit}
                   for label, factor, unit, places in IMPACT],
        'inverters': inverters,
        'unmonitored': [{'name': s.name, 'kwp': number_text(s.kwp, 2)} for s in sections if not s.inverter_id],
        'power_curve': _power_curve(plant),
        'energy': _energy_views(plant, rates, now),
    }


def build_screen(plant):
    key = f'plant-screen:{plant.pk}'
    payload = cache.get(key)
    if payload is None:
        payload = _build(plant)
        cache.set(key, payload, CACHE_SECONDS)
    return payload
