"""Marketer performance, measured from the leads they brought in.

A marketer is credited through the QR link a lead arrived by (`Lead.marketer`),
never through anything the visitor typed. Everything below is a count over
that attribution within a date window, so the manager's report and its
printout are always the same numbers.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta

from django.contrib.auth import get_user_model
from django.db.models import Count, Max, Q, Sum
from django.utils import timezone

from apps.requests.models import Request

from .models import Lead

WON_STATUSES = (Request.Status.CONTRACT_APPROVED, Request.Status.AWAITING_PAYMENT,
                Request.Status.PAID)
LOST_STATUSES = (Request.Status.CLOSED, Request.Status.CANCELLED)

# Reminders are not repeated within this window, however often the button is
# pressed — a second SMS an hour after the first only annoys the visitor.
REMINDER_COOLDOWN = timedelta(hours=24)


def window(date_from, date_to):
    """Aware datetimes covering whole days; either end may be open."""
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.combine(date_from, time.min), tz) if date_from else None
    end = timezone.make_aware(datetime.combine(date_to, time.max), tz) if date_to else None
    return start, end


def leads_in(start=None, end=None):
    qs = Lead.objects.select_related('request', 'marketer', 'source')
    if start:
        qs = qs.filter(created_at__gte=start)
    if end:
        qs = qs.filter(created_at__lte=end)
    return qs


_AGG = dict(
    total=Count('id'),
    stage2=Count('id', filter=Q(stage2_completed=True)),
    hot=Count('id', filter=Q(temperature=Lead.Temperature.HOT)),
    warm=Count('id', filter=Q(temperature=Lead.Temperature.WARM)),
    cold=Count('id', filter=Q(temperature=Lead.Temperature.COLD)),
    unqualified=Count('id', filter=Q(temperature=Lead.Temperature.UNQUALIFIED)),
    referred=Count('id', filter=Q(request__isnull=False)
                   & ~Q(request__department=Request.Department.MARKETING)),
    won=Count('id', filter=Q(request__status__in=WON_STATUSES)),
    lost=Count('id', filter=Q(request__status__in=LOST_STATUSES)),
    reminders=Sum('reminder_count'),
    last_lead=Max('created_at'),
)


def _pct(part, whole):
    return round(100 * part / whole) if whole else 0


def _finish(row: dict) -> dict:
    row['reminders'] = row.get('reminders') or 0
    row['stage1_only'] = row['total'] - row['stage2']
    row['stage2_pct'] = _pct(row['stage2'], row['total'])
    row['referred_pct'] = _pct(row['referred'], row['total'])
    row['won_pct'] = _pct(row['won'], row['total'])
    return row


_COUNTS = ('total', 'stage2', 'hot', 'warm', 'cold', 'unqualified', 'referred', 'won', 'lost')


def summarise(qs) -> dict:
    """The same figures as a report row, over any lead queryset."""
    row = qs.aggregate(**_AGG)
    for key in _COUNTS:
        row[key] = row[key] or 0
    return _finish(row)


def marketer_rows(start=None, end=None) -> tuple[list[dict], dict]:
    """One row per marketer (every marketing user, even with zero leads),
    a row for the public QR if it brought anything in, and a total row."""
    User = get_user_model()
    qs = leads_in(start, end)
    by_id = {r['marketer']: r for r in qs.values('marketer').annotate(**_AGG)}

    empty = {k: 0 for k in _AGG}
    empty['last_lead'] = None
    people = User.objects.filter(Q(role='marketing') | Q(pk__in=[k for k in by_id if k]))
    rows = []
    for user in people.order_by('first_name', 'last_name', 'username'):
        row = dict(empty, **by_id.get(user.pk, {}))
        row.update(marketer=user, name=user.get_full_name() or user.username)
        rows.append(_finish(row))
    if None in by_id:
        rows.append(_finish(dict(by_id[None], marketer=None, name='QR عمومی (بدون بازاریاب)')))
    rows.sort(key=lambda r: (-r['total'], r['name']))

    return rows, summarise(qs)


def stage_one_only(qs=None):
    """Leads that filled the first form and never came back for the second."""
    qs = qs if qs is not None else Lead.objects.select_related('request', 'marketer')
    return qs.filter(stage2_completed=False, request__isnull=False).exclude(request__mobile='')


def can_remind(lead, now=None) -> bool:
    now = now or timezone.now()
    return lead.last_reminder_at is None or now - lead.last_reminder_at >= REMINDER_COOLDOWN
