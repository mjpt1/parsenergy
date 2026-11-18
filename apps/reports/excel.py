"""Plant performance workbook (reports/<id>/excel/): the customer's "تحلیل عملکرد".

Sheets: summary (KPI cards + charts), daily (30 days), hourly profile, monthly
(12 Jalali months), inverters, alerts, raw readings (7 days). Days are grouped
in Python because the production database has no time-zone tables (see
apps/core/localtime.py). Totals use live formulas so the sheet stays usable
after the customer filters or edits it.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from io import BytesIO

import jdatetime
from django.utils import timezone
from openpyxl import Workbook
from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.formatting.rule import CellIsRule, ColorScaleRule, DataBarRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from apps.alerts.models import AlertEvent
from apps.core.localtime import day_start

FONT = 'Tahoma'            # ships with every Windows/Office install and shapes Persian well
DARK, MID, LIGHT, PALE = '0D5F33', '1F8A4C', 'E8F5EC', 'F6FBF7'
GOLD, LINE, MUTED, RED = 'E0A526', 'CFE3D6', '6B7C72', 'C0392B'
CO2_KG_PER_KWH = 0.65      # Iran grid emission factor (estimate)
WEEKDAYS = ['دوشنبه', 'سه‌شنبه', 'چهارشنبه', 'پنجشنبه', 'جمعه', 'شنبه', 'یکشنبه']
MONTHS = ['فروردین', 'اردیبهشت', 'خرداد', 'تیر', 'مرداد', 'شهریور',
          'مهر', 'آبان', 'آذر', 'دی', 'بهمن', 'اسفند']
STATUS_FA = {'normal': 'عادی', 'online': 'عادی', 'wait': 'در انتظار', 'check': 'بررسی', 'fault': 'خطا',
             'permanent_fault': 'خطای دائمی', 'off': 'خاموش', 'update': 'به‌روزرسانی', 'idle': 'بیکار',
             'standby': 'آماده‌به‌کار', 'self_test': 'خودآزمایی', 'eps_check': 'بررسی EPS', 'offline': 'قطع'}
CONNECTION_FA = {'online': 'متصل', 'offline': 'قطع', 'degraded': 'ناپایدار', 'maintenance': 'در حال تعمیر'}
SEVERITY_FA = {'low': 'کم', 'medium': 'متوسط', 'high': 'زیاد', 'critical': 'بحرانی'}

thin = Side(style='thin', color=LINE)
BOX = Border(left=thin, right=thin, top=thin, bottom=thin)
NUM1, NUM0, PCT = '#,##0.0', '#,##0', '0.0%'


def jdate(day) -> str:
    return jdatetime.date.fromgregorian(date=day).strftime('%Y/%m/%d')


def jdatetime_text(dt) -> str:
    return jdatetime.datetime.fromgregorian(datetime=timezone.localtime(dt)).strftime('%Y/%m/%d %H:%M')


def font(size=10, bold=False, color='1D2B22'):
    return Font(name=FONT, size=size, bold=bold, color=color)


def fill(color):
    return PatternFill('solid', fgColor=color)


def new_sheet(wb, title, widths):
    ws = wb.create_sheet(title)
    ws.sheet_view.rightToLeft = True
    ws.sheet_view.showGridLines = False
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.page_setup.orientation = 'landscape'
    ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = 1, 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_options.horizontalCentered = True
    return ws


def banner(ws, title, subtitle, span):
    last = get_column_letter(span)
    ws.merge_cells(f'A1:{last}1')
    ws.merge_cells(f'A2:{last}2')
    ws['A1'] = title
    ws['A1'].font = font(16, True, 'FFFFFF')
    ws['A2'] = subtitle
    ws['A2'].font = font(9, color='DCEFE3')
    for row, height in ((1, 34), (2, 20)):
        ws.row_dimensions[row].height = height
        for col in range(1, span + 1):
            ws.cell(row, col).fill = fill(DARK)
        ws.cell(row, 1).alignment = Alignment(horizontal='right', vertical='center', indent=1)
    for col in range(1, span + 1):
        ws.cell(3, col).fill = fill(GOLD)
    ws.row_dimensions[3].height = 4


def show_axes(chart):
    chart.x_axis.delete = False
    chart.y_axis.delete = False
    chart.y_axis.majorGridlines.spPr = None
    chart.y_axis.number_format = '#,##0'
    chart.y_axis.scaling.min = 0
    chart.y_axis.title = chart.x_axis.title = None   # units go in the heading above the chart
    chart.title = None
    return chart


def chart_heading(ws, ref, text):
    ws[ref] = text
    ws[ref].font = font(11, True, DARK)


def table(ws, top, headers, rows, formats=None, total=None):
    """Header row at `top`, rows below, optional totals row of formulas. Returns the last data row."""
    formats = formats or {}
    for c, h in enumerate(headers, start=1):
        cell = ws.cell(top, c, h)
        cell.font = font(10, True, 'FFFFFF')
        cell.fill = fill(MID)
        cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        cell.border = BOX
    ws.row_dimensions[top].height = 30
    r = top
    for i, row in enumerate(rows):
        r = top + 1 + i
        for c, value in enumerate(row, start=1):
            cell = ws.cell(r, c, value)
            cell.font = font(10)
            cell.border = BOX
            cell.alignment = Alignment(horizontal='center', vertical='center')
            if i % 2:
                cell.fill = fill(PALE)
            if c in formats:
                cell.number_format = formats[c]
    if total and rows:
        tr = r + 1
        for c in range(1, len(headers) + 1):
            cell = ws.cell(tr, c)
            cell.fill = fill(LIGHT)
            cell.border = BOX
            cell.font = font(10, True, DARK)
            cell.alignment = Alignment(horizontal='center', vertical='center')
        ws.cell(tr, 1, total.get('label', 'جمع / میانگین'))
        for c, func in total.items():
            if c == 'label':
                continue
            col = get_column_letter(c)
            ws.cell(tr, c, f'={func}({col}{top + 1}:{col}{r})').number_format = formats.get(c, NUM1)
    return r


def collect(plant):
    """One pass over the last year of readings, grouped by local day and hour."""
    today = timezone.localdate()
    year_ago = today - timedelta(days=365)
    days = defaultdict(lambda: {'kwh': 0.0, 'peak': 0.0, 'n': 0})
    hourly_today = defaultdict(lambda: [0.0, 0.0, 0])     # hour -> [power sum, kwh, n]
    hourly_avg = defaultdict(lambda: [0.0, 0])            # hour -> [power sum, n] over 30 days
    month_ago = today - timedelta(days=29)
    rows = plant.telemetry.filter(created_at__gte=day_start(year_ago)).values_list('created_at', 'power_kw', 'energy_kwh')
    for ts, power, kwh in rows.iterator(chunk_size=5000):
        local = timezone.localtime(ts)
        d, p, e = local.date(), float(power or 0), float(kwh or 0)
        day = days[d]
        day['kwh'] += e
        day['peak'] = max(day['peak'], p)
        day['n'] += 1
        if d >= month_ago:
            hourly_avg[local.hour][0] += p
            hourly_avg[local.hour][1] += 1
        if d == today:
            h = hourly_today[local.hour]
            h[0] += p
            h[1] += e
            h[2] += 1
    return today, days, hourly_today, hourly_avg


def build_performance_workbook(plant) -> bytes:
    installed = float(plant.capacity_kw or 0)
    capacity = float(plant.active_capacity_kw or 0)
    today, days, hourly_today, hourly_avg = collect(plant)
    window = [today - timedelta(days=i) for i in range(29, -1, -1)]
    with_data = [d for d in window if days.get(d, {}).get('n')]
    energy_30 = sum(days[d]['kwh'] for d in with_data)
    peak_30 = max((days[d]['peak'] for d in with_data), default=0)
    # Today is still in progress, so averages and ratings use complete days only.
    full_days = [d for d in with_data if d != today]
    avg_day = sum(days[d]['kwh'] for d in full_days) / len(full_days) if full_days else 0
    spec_yield = avg_day / capacity if capacity else 0
    cap_factor = avg_day / (capacity * 24) if capacity else 0
    best = max(full_days, key=lambda d: days[d]['kwh'], default=None)
    alerts = AlertEvent.objects.filter(rule__plant=plant).select_related('rule').order_by('-created_at')
    active_alerts = alerts.filter(acknowledged=False).count()
    inverters = list(plant.inverters.order_by('id'))
    generated = jdatetime_text(timezone.now())
    period = f'{jdate(window[0])} تا {jdate(today)}'

    wb = Workbook()
    wb.remove(wb.active)
    wb.properties.title = f'تحلیل عملکرد {plant.name}'
    wb.properties.creator = 'پارس تیدا'

    # ---------- Daily (built first: the summary charts read from it) ----------
    daily = new_sheet(wb, 'تولید روزانه', [14, 12, 16, 16, 18, 16, 14])
    banner(daily, f'تولید روزانه — {plant.name}', f'۳۰ روز اخیر: {period}   |   ظرفیت نصب‌شده: {installed:,.0f} کیلووات', 7)
    rows = []
    for d in window:
        info = days.get(d)
        kwh = round(info['kwh'], 2) if info and info['n'] else None
        rows.append([jdate(d), WEEKDAYS[d.weekday()], kwh,
                     round(info['peak'], 2) if kwh is not None else None,
                     round(kwh / capacity, 2) if kwh is not None and capacity else None,
                     (kwh / avg_day) if kwh is not None and avg_day and d != today else None,
                     'بدون داده' if kwh is None else 'امروز (در جریان)' if d == today else ('خوب' if kwh >= avg_day * 1.05 else
                                                     'کم' if kwh < avg_day * 0.8 else 'عادی')])
    top = 5
    last = table(daily, top, ['تاریخ', 'روز هفته', 'تولید (kWh)', 'بیشینه توان (kW)',
                              'بازده ویژه (kWh/kWp)', 'نسبت به میانگین', 'وضعیت'], rows,
                 {3: NUM1, 4: NUM1, 5: '0.00', 6: PCT},
                 {'label': 'جمع / میانگین', 3: 'SUM', 4: 'MAX', 5: 'AVERAGE', 6: 'AVERAGE'})
    daily.freeze_panes = f'A{top + 1}'
    daily.auto_filter.ref = f'A{top}:G{last}'
    daily.conditional_formatting.add(f'C{top + 1}:C{last}', DataBarRule(
        start_type='num', start_value=0, end_type='max', color='2FA35A', showValue=True))
    daily.conditional_formatting.add(f'F{top + 1}:F{last}', ColorScaleRule(
        start_type='num', start_value=0.6, start_color='F8D7D3', mid_type='num', mid_value=1,
        mid_color='FFFFFF', end_type='num', end_value=1.3, end_color='C8E9D2'))
    for word, color in (('کم', RED), ('خوب', MID), ('بدون داده', MUTED)):
        daily.conditional_formatting.add(f'G{top + 1}:G{last}', CellIsRule(
            operator='equal', formula=[f'"{word}"'], font=Font(name=FONT, bold=True, color=color)))
    daily_cats = Reference(daily, min_col=1, min_row=top + 1, max_row=last)
    daily_vals = Reference(daily, min_col=3, min_row=top, max_row=last)

    # ---------- Hourly profile ----------
    hourly = new_sheet(wb, 'پروفایل ساعتی', [12, 20, 22, 18])
    banner(hourly, f'پروفایل ساعتی توان — {plant.name}',
           f'امروز ({jdate(today)}) در مقایسه با میانگین ۳۰ روز اخیر', 4)
    hrows = []
    for h in range(24):
        t = hourly_today.get(h)
        a = hourly_avg.get(h)
        hrows.append([f'{h:02d}:00', round(t[0] / t[2], 2) if t and t[2] else None,
                      round(a[0] / a[1], 2) if a and a[1] else None, round(t[1], 2) if t else None])
    hlast = table(hourly, 5, ['ساعت', 'توان امروز (kW)', 'میانگین ۳۰ روز (kW)', 'تولید امروز (kWh)'],
                  hrows, {2: NUM1, 3: NUM1, 4: NUM1}, {'label': 'جمع / بیشینه', 2: 'MAX', 3: 'MAX', 4: 'SUM'})
    hourly.freeze_panes = 'A6'
    line = LineChart()
    line.title, line.y_axis.title, line.x_axis.title = 'منحنی توان روزانه', 'kW', 'ساعت'
    line.height, line.width = 9, 18
    line.add_data(Reference(hourly, min_col=2, max_col=3, min_row=5, max_row=hlast), titles_from_data=True)
    line.set_categories(Reference(hourly, min_col=1, min_row=6, max_row=hlast))
    line.series[0].graphicalProperties.line.solidFill = MID
    line.series[0].graphicalProperties.line.width = 28000
    line.series[1].graphicalProperties.line.solidFill = GOLD
    line.series[1].graphicalProperties.line.dashStyle = 'dash'
    line.series[0].smooth = line.series[1].smooth = True
    line.legend.position = 'b'
    chart_heading(hourly, 'F4', 'منحنی توان امروز و میانگین ۳۰ روز (کیلووات)')
    hourly.add_chart(show_axes(line), 'F5')

    # ---------- Monthly (Jalali months) ----------
    monthly = new_sheet(wb, 'تولید ماهانه', [20, 16, 18, 16, 16, 16])
    banner(monthly, f'تولید ماهانه — {plant.name}', 'تا ۱۲ ماه اخیر، به تقویم شمسی', 6)
    months = defaultdict(lambda: {'kwh': 0.0, 'peak': 0.0, 'days': 0})
    for d, info in days.items():
        if not info['n']:
            continue
        j = jdatetime.date.fromgregorian(date=d)
        m = months[(j.year, j.month)]
        m['kwh'] += info['kwh']
        m['peak'] = max(m['peak'], info['peak'])
        m['days'] += 1
    jt = jdatetime.date.fromgregorian(date=today)
    keys = []
    y, mo = jt.year, jt.month
    for _ in range(12):
        keys.append((y, mo))
        y, mo = (y - 1, 12) if mo == 1 else (y, mo - 1)
    keys = list(reversed(keys))
    while len(keys) > 1 and keys[0] not in months:
        keys.pop(0)
    mrows = []
    for y, mo in keys:
        m = months.get((y, mo))
        kwh = round(m['kwh'], 1) if m else None
        mrows.append([f'{MONTHS[mo - 1]} {y}', kwh, round(m['kwh'] / m['days'], 1) if m else None,
                      round(m['peak'], 1) if m else None, m['days'] if m else 0,
                      round(m['kwh'] * CO2_KG_PER_KWH / 1000, 2) if m else None])
    mlast = table(monthly, 5, ['ماه', 'تولید (kWh)', 'میانگین روزانه (kWh)', 'بیشینه توان (kW)',
                               'روزهای دارای داده', 'کاهش CO₂ (تن)'], mrows,
                  {2: NUM0, 3: NUM1, 4: NUM1, 5: NUM0, 6: '0.00'},
                  {'label': 'جمع', 2: 'SUM', 4: 'MAX', 5: 'SUM', 6: 'SUM'})
    monthly.freeze_panes = 'A6'
    monthly.conditional_formatting.add(f'B6:B{mlast}', DataBarRule(
        start_type='num', start_value=0, end_type='max', color=GOLD, showValue=True))
    bar_m = BarChart()
    bar_m.title, bar_m.y_axis.title = 'تولید ماهانه', 'kWh'
    bar_m.height, bar_m.width, bar_m.legend = 9, 18, None
    bar_m.add_data(Reference(monthly, min_col=2, min_row=5, max_row=mlast), titles_from_data=True)
    bar_m.set_categories(Reference(monthly, min_col=1, min_row=6, max_row=mlast))
    bar_m.series[0].graphicalProperties.solidFill = GOLD
    chart_heading(monthly, 'H4', 'تولید ماهانه (کیلووات‌ساعت)')
    monthly.add_chart(show_axes(bar_m), 'H5')

    # ---------- Inverters ----------
    inv = new_sheet(wb, 'اینورترها', [22, 18, 16, 14, 14, 12, 14, 20])
    banner(inv, f'اینورترها — {plant.name}', f'{len(inverters)} اینورتر ثبت‌شده', 8)
    irows = [[i.serial_number, i.model_name, i.manufacturer, float(i.rated_power_kw or 0),
              i.get_data_source_display(), STATUS_FA.get(i.status, i.status),
              'آنلاین' if i.online else 'قطع',
              jdatetime_text(i.last_synced_at) if i.last_synced_at else '—'] for i in inverters]
    ilast = table(inv, 5, ['شماره سریال', 'مدل', 'سازنده', 'توان نامی (kW)', 'منبع داده', 'وضعیت',
                           'ارتباط', 'آخرین دریافت داده'], irows or [['اینورتری ثبت نشده است.']],
                  {4: NUM1}, {'label': 'جمع', 4: 'SUM'} if irows else None)
    inv.conditional_formatting.add(f'G6:G{ilast}', CellIsRule(
        operator='equal', formula=['"قطع"'], font=Font(name=FONT, bold=True, color=RED)))
    inv.conditional_formatting.add(f'G6:G{ilast}', CellIsRule(
        operator='equal', formula=['"آنلاین"'], font=Font(name=FONT, bold=True, color=MID)))

    # ---------- Alerts ----------
    al = new_sheet(wb, 'هشدارها', [22, 60, 12, 14, 20])
    banner(al, f'هشدارها — {plant.name}', f'{active_alerts} هشدار فعال — ۱۰۰ هشدار اخیر', 5)
    arows = [[a.rule.name, a.message, SEVERITY_FA.get(a.severity, a.severity),
              'بررسی‌شده' if a.acknowledged else 'فعال', jdatetime_text(a.created_at)] for a in alerts[:100]]
    alast = table(al, 5, ['قانون', 'پیام', 'شدت', 'وضعیت', 'زمان'], arows or [['هشداری ثبت نشده است.']])
    if arows:
        al.auto_filter.ref = f'A5:E{alast}'
        al.conditional_formatting.add(f'D6:D{alast}', CellIsRule(
            operator='equal', formula=['"فعال"'], font=Font(name=FONT, bold=True, color=RED)))
        for r in range(6, alast + 1):
            al.cell(r, 2).alignment = Alignment(horizontal='right', vertical='center', wrap_text=True)
    al.freeze_panes = 'A6'

    # ---------- Raw readings ----------
    raw = new_sheet(wb, 'داده خام', [18, 20, 12, 12, 12, 12, 14, 12])
    banner(raw, f'داده‌های ثبت‌شده — {plant.name}', '۷ روز اخیر، به ترتیب زمان (جدیدترین بالا)', 8)
    readings = (plant.telemetry.filter(created_at__gte=day_start(today - timedelta(days=6)))
                .select_related('inverter').order_by('-created_at')[:5000])
    rrows = [[jdatetime_text(t.created_at), t.inverter.serial_number if t.inverter else '—',
              float(t.power_kw), float(t.voltage_v), float(t.current_a), float(t.frequency_hz),
              float(t.energy_kwh), STATUS_FA.get(t.status, t.status)] for t in readings]
    rlast = table(raw, 5, ['زمان', 'اینورتر', 'توان (kW)', 'ولتاژ (V)', 'جریان (A)', 'فرکانس (Hz)',
                           'انرژی (kWh)', 'وضعیت'], rrows or [['داده‌ای ثبت نشده است.']],
                  {3: '0.00', 4: '0.0', 5: '0.0', 6: '0.00', 7: '0.000'})
    raw.freeze_panes = 'A6'
    if rrows:
        raw.auto_filter.ref = f'A5:H{rlast}'

    # ---------- Summary (first tab) ----------
    s = new_sheet(wb, 'خلاصه عملکرد', [3, 17, 17, 3, 17, 17, 3, 17, 17, 3, 17, 17, 3])
    wb.move_sheet(s, offset=-(len(wb.sheetnames) - 1))
    wb.active = 0
    banner(s, f'گزارش تحلیل عملکرد نیروگاه {plant.name}',
           f'بازه: ۳۰ روز اخیر ({period})   |   تهیه‌شده در {generated}   |   پارس تیدا', 13)

    def card(row, col, value, label, fmt, accent=MID):
        c1, c2 = get_column_letter(col), get_column_letter(col + 1)
        s.merge_cells(f'{c1}{row}:{c2}{row}')
        s.merge_cells(f'{c1}{row + 1}:{c2}{row + 1}')
        v = s[f'{c1}{row}']
        v.value = value
        v.number_format = fmt
        v.font = font(18, True, accent)
        lab = s[f'{c1}{row + 1}']
        lab.value = label
        lab.font = font(9, color=MUTED)
        for r in (row, row + 1):
            for c in (col, col + 1):
                cell = s.cell(r, c)
                cell.fill = fill(LIGHT)
                cell.alignment = Alignment(horizontal='center', vertical='center')
                cell.border = Border(top=Side(style='medium', color=accent) if r == row else None,
                                     bottom=thin if r == row + 1 else None,
                                     left=thin if c == col + 1 else None, right=thin if c == col else None)
        s.row_dimensions[row].height = 36
        s.row_dimensions[row + 1].height = 22

    cards = [
        [(energy_30, 'تولید ۳۰ روز اخیر (kWh)', NUM0, MID),
         (days[today]['kwh'] if days.get(today) else 0, 'تولید امروز (kWh)', NUM1, MID),
         (avg_day, 'میانگین تولید روزانه (kWh)', NUM1, MID),
         (peak_30, 'بیشینه توان ثبت‌شده (kW)', NUM1, MID)],
        [(spec_yield, 'بازده ویژه روزانه (kWh/kWp)', '0.00', GOLD),
         (cap_factor, 'ضریب ظرفیت', PCT, GOLD),
         (energy_30 * CO2_KG_PER_KWH / 1000, 'کاهش انتشار CO₂ (تن، تخمینی)', '0.00', GOLD),
         (active_alerts, 'هشدار فعال', NUM0, RED if active_alerts else MID)],
    ]
    for i, row_cards in enumerate(cards):
        for j, (value, label, fmt, accent) in enumerate(row_cards):
            card(5 + i * 3, 2 + j * 3, value, label, fmt, accent)

    # plant facts + highlights
    s['B12'] = 'مشخصات نیروگاه'
    s['H12'] = 'نکات کلیدی'
    for ref in ('B12', 'H12'):
        s[ref].font = font(12, True, DARK)
    facts = [('نام نیروگاه', plant.name), ('کد', plant.external_code), ('محل', plant.location_name),
             ('ظرفیت نصب‌شده', f'{installed:,.0f} kW'), ('ظرفیت متصل به پایش', f'{capacity:,.2f} kW'), ('تعداد اینورتر', f'{len(inverters)}'),
             ('توان نامی اینورترها', f'{sum(float(i.rated_power_kw or 0) for i in inverters):,.0f} kW'),
             ('وضعیت اتصال', CONNECTION_FA.get(plant.connection_status, plant.get_connection_status_display()))]
    highlights = [
        ('بهترین روز', f'{jdate(best)} — {days[best]["kwh"]:,.0f} kWh' if best else '—'),
        ('روزهای دارای داده', f'{len(with_data)} روز از ۳۰ روز'),
        ('روزهای کم‌تولید (زیر ۸۰٪ میانگین)', f'{sum(1 for d in full_days if days[d]["kwh"] < avg_day * 0.8)} روز'),
        ('معادل ساعات کار با توان کامل', f'{spec_yield:,.2f} ساعت در روز'),
        ('اینورترهای قطع', f'{sum(1 for i in inverters if not i.online)} دستگاه از {len(inverters)}'),
    ]
    for block_col, pairs in ((2, facts), (8, highlights)):
        for k, (label, value) in enumerate(pairs):
            r = 13 + k
            lc, vc = get_column_letter(block_col), get_column_letter(block_col + 2)
            end = get_column_letter(block_col + 4)
            s.merge_cells(f'{lc}{r}:{get_column_letter(block_col + 1)}{r}')
            s.merge_cells(f'{vc}{r}:{end}{r}')
            s[f'{lc}{r}'] = label
            s[f'{lc}{r}'].font = font(9, True, DARK)
            for c in (block_col, block_col + 1):
                s.cell(r, c).fill = fill(LIGHT)
            s[f'{vc}{r}'] = value
            s[f'{vc}{r}'].font = font(10)
            for c in range(block_col, block_col + 5):
                s.cell(r, c).border = Border(bottom=thin)
                s.cell(r, c).alignment = Alignment(horizontal='right', vertical='center', indent=1)
            s.row_dimensions[r].height = 22

    bar = BarChart()
    bar.title, bar.y_axis.title = 'تولید روزانه — ۳۰ روز اخیر', 'kWh'
    bar.height, bar.width, bar.legend, bar.gapWidth = 8.5, 31, None, 40
    bar.add_data(daily_vals, titles_from_data=True)
    bar.set_categories(daily_cats)
    bar.series[0].graphicalProperties.solidFill = MID
    bar.series[0].graphicalProperties.line.solidFill = MID
    chart_heading(s, 'B20', 'تولید روزانه — ۳۰ روز اخیر (کیلووات‌ساعت)')
    s.add_chart(show_axes(bar), 'B21')
    note = 39
    s.merge_cells(f'B{note}:L{note}')
    s[f'B{note}'] = ('یادداشت: بازده ویژه = تولید روزانه ÷ ظرفیت نصب‌شده؛ ضریب ظرفیت = تولید ÷ (ظرفیت × ۲۴ ساعت) '
                     'در روزهای دارای داده؛ کاهش CO₂ با ضریب ۰٫۶۵ کیلوگرم بر کیلووات‌ساعت شبکهٔ ایران تخمین زده شده است.')
    s[f'B{note}'].font = font(8, color=MUTED)
    s[f'B{note}'].alignment = Alignment(horizontal='right', wrap_text=True, vertical='top')
    s.row_dimensions[note].height = 30
    s.page_setup.orientation = 'portrait'

    for ws in wb.worksheets:
        ws.sheet_properties.tabColor = GOLD if ws is s else MID
        ws.oddFooter.center.text = f'پارس تیدا — {plant.name} — صفحه &P از &N'
    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
