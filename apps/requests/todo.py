""""Today's tasks" for each staff role: what is waiting on this person now.

Dashboards used to open on a row of counters, most of them zero, and left the
reader to work out which one needed them. This turns the same numbers into a
short list of actions, each with a button straight to the matching list, and
leaves out anything that is at zero.
"""
from __future__ import annotations

from django.urls import reverse

from apps.requests.models import Ticket


def _list(**params):
    from urllib.parse import urlencode
    return reverse('requests:admin-list') + ('?' + urlencode(params) if params else '')


_INSURANCE_TODO = ('بیمه‌نامهٔ منقضی یا نزدیک انقضا', '/requests/manage/?funnel_stage=execution&funnel_stage=operation',
                   'تا ۳۰ روز آینده')


def _expiring_policies() -> int:
    from apps.requests.services.delivery import expiring_policies
    return expiring_policies().count()


def build_todo(role: str, stats: dict, fleet: dict, user) -> list[dict]:
    """[{n, text, hint, url, tone}] with tone 'bad' for overdue/broken, 'warn' for waiting."""
    s, f = stats, fleet
    tickets = Ticket.objects.filter(status=Ticket.Status.OPEN)
    if role in ('technical', 'sales', 'marketing', 'operations'):
        tickets = tickets.filter(department=role)
    items = []

    def add(n, text, url, hint='', tone='warn'):
        if n:
            items.append({'n': n, 'text': text, 'hint': hint, 'url': url, 'tone': tone})

    overdue = ('درخواست از مهلت پیگیری گذشته', reverse('requests:admin-tracking') + '?overdue=1',
               f'بیش از {s.get("sla_hours", 72)} ساعت در یک مرحله مانده‌اند')
    plants_down = ('نیروگاه قطع است', reverse('plants:list'), 'داده‌ای از آن نمی‌رسد')
    alerts = ('هشدار بررسی‌نشده', reverse('alerts:events'), '')
    open_tickets = ('تیکت بی‌پاسخ', reverse('requests:admin-tickets'), '')

    if role == 'technical':
        add(s.get('in_technical'), 'درخواست منتظر پیشنهاد فنی', _list(department='technical'),
            'پیشنهاد فنی را ثبت کنید')
        add(f.get('offline'), *plants_down, tone='bad')
        add(f.get('alerts'), *alerts, tone='bad')
        add(f.get('hot_cells'), 'پنل با دمای بیش از حد', reverse('plants:dashboard'), '', tone='bad')
    elif role == 'sales':
        add(s.get('needs_contact'), 'مشتری منتظر تماس', _list(department='sales', sales_phase='qualification'),
            'تماس بگیرید و وضعیت را مشخص کنید')
        add(s.get('offers_ready'), 'پیشنهاد قیمت آماده برای مشتری', _list(department='sales', status='offered'),
            'پیشنهاد را با مشتری نهایی کنید')
        add(s.get('unassigned_sales'), 'درخواست بدون کارشناس فروش', _list(department='sales'),
            'یک کارشناس تعیین کنید', tone='bad')
    elif role == 'marketing':
        add(s.get('in_marketing'), 'درخواست تازه برای بررسی', _list(department='marketing'),
            'بررسی و به فروش ارجاع دهید')
        add(s.get('incomplete'), 'درخواست با اطلاعات ناقص', _list(department='marketing'),
            'قبض برق یا موقعیت روی نقشه ندارد')
    elif role == 'operations':
        add(s.get('overdue'), *overdue, tone='bad')
        add(s.get('unassigned_sales'), 'درخواست بدون کارشناس فروش', _list(department='sales'), '', tone='bad')
        add(f.get('offline'), *plants_down, tone='bad')
        add(_expiring_policies(), *_INSURANCE_TODO, tone='bad')
    else:  # management
        add(s.get('overdue'), *overdue, tone='bad')
        add(s.get('needs_contact'), 'مشتری منتظر تماس فروش', _list(department='sales', sales_phase='qualification'))
        add(s.get('in_technical'), 'درخواست منتظر پیشنهاد فنی', _list(department='technical'))
        add(s.get('unassigned_sales'), 'درخواست بدون کارشناس فروش', _list(department='sales'), '', tone='bad')
        add(f.get('offline'), *plants_down, tone='bad')
        add(f.get('alerts'), *alerts, tone='bad')
        add(_expiring_policies(), *_INSURANCE_TODO, tone='bad')
        from apps.requests.services.project import finance_pending_count
        add(finance_pending_count(), 'پرداخت منتظر تأیید مالی', reverse('requests:admin-payments'))
        from apps.core.models import SettingChangeRequest
        add(SettingChangeRequest.objects.filter(status=SettingChangeRequest.Status.PENDING).count(),
            'تغییر تنظیمات منتظر تأیید شما', reverse('core:setting-approvals'),
            'پیامک، شاهکار یا درگاه پرداخت')
    add(tickets.count(), *open_tickets)
    # Overdue and broken first, then the rest, each group by size.
    items.sort(key=lambda i: (i['tone'] != 'bad', -i['n']))
    return items
