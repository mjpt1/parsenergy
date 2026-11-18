"""Everything the inverter cloud reports for a plant, as figures and chart series."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from apps.core.localtime import day_start, local_day

from .models import InverterSample, TelemetryReading
from .revenue import LIVE_MAX_AGE, _jalali_time, jalali_text, number_text, plant_rates

RANGES = {'1': 1, '7': 7, '30': 30}
MAX_POINTS = 240
KWH = 'kWh'

FIELD_GROUPS = [
    ('خروجی به شبکه', [
        ('totalactivepower', 'توان اکتیو کل', ''), ('totalreactivepower', 'توان راکتیو کل', ''),
        ('totalpowerfactor', 'ضریب توان', ''), ('gridfrequency', 'فرکانس شبکه', 'Hz'),
        ('acvoltage1', 'ولتاژ فاز ۱', 'V'), ('acvoltage2', 'ولتاژ فاز ۲', 'V'), ('acvoltage3', 'ولتاژ فاز ۳', 'V'),
        ('accurrent1', 'جریان فاز ۱', 'A'), ('accurrent2', 'جریان فاز ۲', 'A'), ('accurrent3', 'جریان فاز ۳', 'A'),
        ('acpower1', 'توان فاز ۱', ''), ('acpower2', 'توان فاز ۲', ''), ('acpower3', 'توان فاز ۳', ''),
        ('acfrequency1', 'فرکانس فاز ۱', 'Hz'), ('acfrequency2', 'فرکانس فاز ۲', 'Hz'), ('acfrequency3', 'فرکانس فاز ۳', 'Hz'),
        ('l1l2voltage', 'ولتاژ خط L1-L2', 'V'), ('l1l3voltage', 'ولتاژ خط L1-L3', 'V'), ('l2l3voltage', 'ولتاژ خط L2-L3', 'V'),
    ]),
    ('انرژی', [
        ('dailyyield', 'تولید امروز', KWH), ('totalyield', 'تولید کل', KWH),
        ('dailyacoutput', 'خروجی AC امروز', KWH), ('totalacoutput', 'خروجی AC کل', KWH),
        ('dailyacinput', 'ورودی AC امروز', KWH), ('totalacinput', 'ورودی AC کل', KWH),
    ]),
    ('تبادل با شبکه', [
        ('gridpower', 'توان تبادلی شبکه', ''), ('todayimportenergy', 'خرید از شبکه امروز', KWH),
        ('totalimportenergy', 'خرید از شبکه کل', KWH), ('todayexportenergy', 'فروش به شبکه امروز', KWH),
        ('totalexportenergy', 'فروش به شبکه کل', KWH), ('gridpowerm2', 'توان کنتور دوم', ''),
        ('todayimportenergym2', 'خرید امروز کنتور دوم', KWH), ('totalimportenergym2', 'خرید کل کنتور دوم', KWH),
        ('todayexportenergym2', 'فروش امروز کنتور دوم', KWH), ('totalexportenergym2', 'فروش کل کنتور دوم', KWH),
    ]),
    ('ورودی پنل‌ها و اینورتر', [
        ('mppttotalinputpower', 'توان ورودی کل', ''), ('invertertemperature', 'دمای اینورتر', '°C'),
    ]),
    ('خروجی اضطراری (EPS)', [
        (f'epsl{phase}{key}', f'{label} فاز {digit}', unit)
        for phase, digit in ((1, '۱'), (2, '۲'), (3, '۳'))
        for key, label, unit in (('voltage', 'ولتاژ', 'V'), ('current', 'جریان', 'A'),
                                 ('activepower', 'توان اکتیو', ''), ('apparentpower', 'توان ظاهری', ''))
    ]),
]
_KNOWN = {key for _, rows in FIELD_GROUPS for key, _, _ in rows}


def _text(value, places=1):
    return '—' if value is None else number_text(Decimal(str(value)), places)


def _field_groups(values):
    groups = []
    for title, rows in FIELD_GROUPS:
        items = [{'label': label, 'value': _text(values[key], 2), 'unit': unit}
                 for key, label, unit in rows if key in values]
        if items and (not title.startswith('خروجی اضطراری') or any(values[key] for key, _, _ in rows if key in values)):
            groups.append({'title': title, 'items': items})
    other = [{'label': key, 'value': _text(value, 2), 'unit': ''}
             for key, value in sorted(values.items())
             if key not in _KNOWN and not key.startswith(('pv', 'mppt')) and key != 'devicestatus']
    if other:
        groups.append({'title': 'سایر داده‌ها', 'items': other})
    return groups


def _thin(rows):
    step = max(1, len(rows) // MAX_POINTS)
    return rows[::step]


def _label(moment, days):
    local = timezone.localtime(moment)
    return local.strftime('%H:%M') if days == 1 else _jalali_time(moment)[5:]


def _line(key, title, unit, labels, series):
    series = [item for item in series if any(v is not None for v in item['data'])]
    return {'id': key, 'title': title, 'unit': unit, 'type': 'line', 'labels': labels, 'series': series}


def _channel_series(samples, field, prefix):
    numbers = sorted({row['number'] for s in samples for row in s.data.get(field) or []})
    series = []
    for number in numbers:
        data = []
        for sample in samples:
            match = next((r for r in sample.data.get(field) or [] if r['number'] == number), None)
            data.append(match['kw'] if match else None)
        series.append({'name': f'{prefix} {number}', 'data': data})
    return series


def _inverter_block(inverter, since, days, now):
    readings = _thin(list(TelemetryReading.objects.filter(inverter=inverter, created_at__gte=since)
                          .order_by('created_at').values_list('created_at', 'power_kw')))
    samples = _thin(list(InverterSample.objects.filter(inverter=inverter, created_at__gte=since).order_by('created_at')))
    labels = [_label(s.created_at, days) for s in samples]

    def pick(key):
        return [s.data.get(key) for s in samples]

    def phase(key, index):
        out = []
        for sample in samples:
            rows = sample.data.get('phases') or []
            out.append(rows[index].get(key) if index < len(rows) else None)
        return out

    charts = [
        _line(f'power-{inverter.pk}', 'توان خروجی', 'kW', [_label(t, days) for t, _ in readings],
              [{'name': 'توان خروجی', 'data': [float(p) for _, p in readings]}]),
        _line(f'dc-{inverter.pk}', 'توان ورودی پنل‌ها', 'kW', labels, [{'name': 'ورودی', 'data': pick('dc_kw')}]),
        _line(f'temp-{inverter.pk}', 'دمای اینورتر', '°C', labels, [{'name': 'دما', 'data': pick('temperature_c')}]),
        _line(f'volt-{inverter.pk}', 'ولتاژ فازها', 'V', labels,
              [{'name': f'فاز {i + 1}', 'data': phase('voltage', i)} for i in range(3)]),
        _line(f'amp-{inverter.pk}', 'جریان فازها', 'A', labels,
              [{'name': f'فاز {i + 1}', 'data': phase('current', i)} for i in range(3)]),
        _line(f'freq-{inverter.pk}', 'فرکانس شبکه', 'Hz', labels, [{'name': 'فرکانس', 'data': pick('grid_frequency')}]),
        _line(f'pf-{inverter.pk}', 'ضریب توان', '', labels, [{'name': 'ضریب توان', 'data': pick('power_factor')}]),
        _line(f'mppt-{inverter.pk}', 'توان ورودی‌های MPPT', 'kW', labels, _channel_series(samples, 'mppt', 'MPPT')),
        _line(f'pv-{inverter.pk}', 'توان رشته‌های پنل', 'kW', labels, _channel_series(samples, 'pv', 'PV')),
    ]
    data = inverter.latest_data or {}
    last = inverter.telemetry_readings.order_by('-created_at').first()
    fresh = last is not None and now - last.created_at <= LIVE_MAX_AGE
    ac_kw = float(last.power_kw) if fresh else None
    dc_kw = data.get('dc_kw') if fresh else None
    efficiency = ac_kw * 100 / dc_kw if ac_kw is not None and dc_kw else None
    if efficiency is not None and efficiency > 100:   # the two figures were not measured together
        efficiency = None
    cards = [
        ('توان خروجی', _text(ac_kw), 'kW'), ('توان ورودی پنل‌ها', _text(dc_kw), 'kW'),
        ('بازده تبدیل', _text(efficiency), '٪'), ('دمای اینورتر', _text(data.get('temperature_c')), '°C'),
        ('تولید کل', _text(data.get('total_yield_kwh'), 0), KWH), ('ضریب توان', _text(data.get('power_factor'), 2), ''),
        ('فرکانس', _text(data.get('grid_frequency'), 2), 'Hz'),
    ]
    return {
        'name': inverter.model_name or inverter.serial_number,
        'serial': inverter.serial_number,
        'rated': _text(inverter.rated_power_kw, 0),
        'status': 'متصل و در حال ارسال داده' if fresh else 'بدون دادهٔ تازه',
        'fresh': fresh,
        'updated': _jalali_time(last.created_at) if last else '',
        'cards': [{'label': a, 'value': b, 'unit': c} for a, b, c in cards],
        'charts': [c for c in charts if c['series'] and c['labels']],
        'fields': _field_groups(data.get('fields') or {}),
    }


def _daily_charts(plant, days):
    today = timezone.localdate()
    count = max(days, 7)
    first = today - timedelta(days=count - 1)
    energy = {}
    for moment, kwh in TelemetryReading.objects.filter(plant=plant, created_at__gte=day_start(first)).values_list(
            'created_at', 'energy_kwh'):
        day = local_day(moment)
        energy[day] = energy.get(day, Decimal('0')) + (kwh or 0)
    rates = plant_rates(plant)
    labels, kwh_values, income_values = [], [], []
    for offset in range(count):
        day = first + timedelta(days=offset)
        value = energy.get(day, Decimal('0'))
        rate = next((r.rate_rial_per_kwh for r in reversed(rates) if r.valid_from <= day), None)
        labels.append(jalali_text(day)[5:])
        kwh_values.append(round(float(value), 1))
        income_values.append(round(float(value * rate / 10)) if rate else None)
    charts = [{'id': 'daily-energy', 'title': 'تولید روزانه', 'unit': KWH, 'type': 'bar', 'labels': labels,
               'series': [{'name': 'تولید', 'data': kwh_values}]}]
    if rates:
        charts.append({'id': 'daily-income', 'title': 'درآمد برآوردی روزانه', 'unit': 'تومان', 'type': 'bar',
                       'labels': labels, 'series': [{'name': 'درآمد', 'data': income_values}]})
    return charts


def build_monitor(plant, range_key='1'):
    days = RANGES.get(range_key, 1)
    now = timezone.now()
    since = now - timedelta(days=days)
    inverters = list(plant.inverters.order_by('id'))
    return {
        'plant': plant.name,
        'range': str(days),
        'daily': _daily_charts(plant, days),
        'inverters': [_inverter_block(inverter, since, days, now) for inverter in inverters],
    }
