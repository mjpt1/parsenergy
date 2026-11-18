"""Estimated plant income: recorded production priced at the rate of its own date.

Rates are dated, so adding next year's rate never changes what earlier days
earned. Production from before a plant's first rate is reported as unpriced
rather than valued at a rate that did not apply yet.

Windows are summed with plain datetime ranges (see apps.core.localtime).
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import jdatetime
from django.db.models import Sum
from django.utils import timezone

from apps.core.localtime import day_start

from .models import PlantTariff, TelemetryReading
from .scoping import plant_scope_for_user

LIVE_MAX_AGE = timedelta(minutes=30)   # the cloud sync runs every 5 minutes
_FA_DIGITS = str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹')
_TO_LATIN = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')


def revenue_plants(user):
    """Plants whose income this user may see; finance reads all of them."""
    from .models import Plant
    if getattr(user, 'role', '') == 'financial':
        return Plant.objects.all()
    return plant_scope_for_user(user)


def number_text(value, places=0):
    text = f'{Decimal(value):,.{places}f}'
    return text.replace(',', '٬').replace('.', '٫').translate(_FA_DIGITS)


def to_latin_digits(text):
    return str(text or '').translate(_TO_LATIN).strip()


def parse_jalali(text):
    """'۱۴۰۵/۰۸/۲۷' -> Gregorian date. Raises ValueError when it is not a real date."""
    parts = to_latin_digits(text).replace('-', '/').split('/')
    if len(parts) != 3:
        raise ValueError('bad date')
    year, month, day = (int(p) for p in parts)
    return jdatetime.date(year, month, day).togregorian()


def jalali_text(day):
    return jdatetime.date.fromgregorian(date=day).strftime('%Y/%m/%d').translate(_FA_DIGITS)


def _jalali_time(moment):
    local = timezone.localtime(moment)
    return jdatetime.datetime.fromgregorian(datetime=local).strftime('%Y/%m/%d %H:%M').translate(_FA_DIGITS)


def plant_rates(plant):
    return list(PlantTariff.objects.filter(plant=plant).order_by('valid_from'))


def current_rate(rates, today):
    active = [r for r in rates if r.valid_from <= today]
    return active[-1] if active else None


def _energy(plant, start, end):
    readings = TelemetryReading.objects.filter(plant=plant)
    if start is not None:
        readings = readings.filter(created_at__gte=start)
    if end is not None:
        readings = readings.filter(created_at__lt=end)
    return readings.aggregate(total=Sum('energy_kwh'))['total'] or Decimal('0')


def window_income(plant, rates, start, end):
    """(priced kWh, rial, unpriced kWh) for readings in [start, end)."""
    kwh = rial = Decimal('0')
    for index, rate in enumerate(rates):
        seg_start = day_start(rate.valid_from)
        seg_end = day_start(rates[index + 1].valid_from) if index + 1 < len(rates) else None
        low = max(seg_start, start) if start is not None else seg_start
        high = seg_end if end is None else (end if seg_end is None else min(seg_end, end))
        if high is not None and low >= high:
            continue
        energy = _energy(plant, low, high)
        kwh += energy
        rial += energy * rate.rate_rial_per_kwh
    first = day_start(rates[0].valid_from) if rates else None
    unpriced = Decimal('0')
    if first is None:
        unpriced = _energy(plant, start, end)
    elif start is None or start < first:
        unpriced = _energy(plant, start, first if end is None else min(first, end))
    return kwh, rial, unpriced


def _period(key, label, plant, rates, start, end):
    kwh, rial, unpriced = window_income(plant, rates, start, end)
    return {
        'key': key, 'label': label,
        'toman': rial / 10,
        'toman_text': number_text(rial / 10),
        'kwh_text': number_text(kwh, 1),
        'unpriced_text': number_text(unpriced, 1) if unpriced > 0 else '',
    }


def custom_period(plant, first_day, last_day):
    label = f'{jalali_text(first_day)} تا {jalali_text(last_day)}'
    return _period('custom', label, plant, plant_rates(plant),
                   day_start(first_day), day_start(last_day + timedelta(days=1)))


def _live_power(plant, now):
    """(kW from fresh readings, newest reading time) — one latest reading per inverter."""
    inverter_ids = list(plant.inverters.values_list('pk', flat=True))
    readings = TelemetryReading.objects.filter(plant=plant)
    if inverter_ids:
        latest = [readings.filter(inverter_id=pk).order_by('-created_at').first() for pk in inverter_ids]
    else:
        latest = [readings.order_by('-created_at').first()]
    latest = [r for r in latest if r is not None]
    newest = max((r.created_at for r in latest), default=None)
    fresh = [r for r in latest if now - r.created_at <= LIVE_MAX_AGE]
    if not fresh:
        return None, newest
    return sum((r.power_kw for r in fresh), Decimal('0')), newest


def build_revenue(plant):
    now = timezone.now()
    today = timezone.localdate()
    rates = plant_rates(plant)
    rate = current_rate(rates, today)
    jalali_today = jdatetime.date.fromgregorian(date=today)
    month_first = jdatetime.date(jalali_today.year, jalali_today.month, 1).togregorian()
    year_first = jdatetime.date(jalali_today.year, 1, 1).togregorian()
    today_start = day_start(today)
    windows = [
        ('today', 'امروز', today_start, None),
        ('yesterday', 'دیروز', day_start(today - timedelta(days=1)), today_start),
        ('week', '۷ روز اخیر', day_start(today - timedelta(days=6)), None),
        ('month', 'این ماه', day_start(month_first), None),
        ('year', 'امسال', day_start(year_first), None),
        ('all', 'از ابتدا', None, None),
    ]
    power, last_at = _live_power(plant, now)
    per_hour = power * rate.rate_rial_per_kwh / 10 if power is not None and rate else None
    if last_at is None:
        note = 'هنوز داده‌ای از این نیروگاه نرسیده است.'
    elif power is None:
        note = f'داده تازه‌ای نرسیده است. آخرین دریافت: {_jalali_time(last_at)}'
    else:
        note = f'توان فعلی {number_text(power, 1)} کیلووات، آخرین دریافت: {_jalali_time(last_at)}'
    return {
        'plant_id': plant.pk,
        'plant_name': plant.name,
        'has_rate': rate is not None,
        'rate_toman_text': number_text(rate.rate_rial_per_kwh / 10, 1) if rate else '',
        'rate_from_text': jalali_text(rate.valid_from) if rate else '',
        'now_toman_text': number_text(per_hour) if per_hour is not None else '—',
        'now_note': note,
        'periods': [_period(key, label, plant, rates, start, end) for key, label, start, end in windows],
    }


def bill_groups(bills, mode):
    """Official statements grouped for the chart. A statement belongs to the month it starts in."""
    groups = {}
    for bill in sorted(bills, key=lambda item: item.period_start):
        start = jdatetime.date.fromgregorian(date=bill.period_start)
        if mode == 'year':
            key, label = start.year, str(start.year).translate(_FA_DIGITS)
        elif mode == 'month':
            key = (start.year, start.month)
            label = f'{start.year}/{start.month:02d}'.translate(_FA_DIGITS)
        else:
            key, label = bill.pk, f'{jalali_text(bill.period_start)} تا {jalali_text(bill.period_end)}'
        group = groups.setdefault(key, {'label': label, 'energy': Decimal('0'), 'benchmark': Decimal('0')})
        group['energy'] += bill.energy_kwh
        group['benchmark'] += bill.benchmark_kwh or 0
    rows = list(groups.values())
    top = max((max(g['energy'], g['benchmark']) for g in rows), default=Decimal('0')) or Decimal('1')
    for group in rows:
        group['energy_text'] = number_text(group['energy'])
        group['energy_width'] = f'{group["energy"] * 100 / top:.1f}'
        group['benchmark_text'] = number_text(group['benchmark']) if group['benchmark'] else ''
        group['benchmark_width'] = f'{group["benchmark"] * 100 / top:.1f}'
        group['ratio_text'] = number_text(group['energy'] * 100 / group['benchmark'], 1) if group['benchmark'] else ''
    return rows
