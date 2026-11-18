"""Extra figures for the management dashboard.

`dashboard_context.build_lead_fleet_context` already produces the counts every
role dashboard needs. This module adds the things only the executive view asks
for — trends, conversion ratios, waiting times, per-person workload and the
SLA countdown table — and is kept separate so the other dashboards are not
made to pay for queries they never render.

Everything here reads the database. Where a figure genuinely cannot be derived
from what we store, the function returns ``None`` and the template shows a dash
rather than a number that would be made up.
"""
from __future__ import annotations

from datetime import timedelta

from django.db.models import Avg, Count, F, Q, Sum
from django.utils import timezone

from apps.alerts.models import AlertEvent
from apps.plants.models import Inverter, Plant, PVModule
from apps.requests import repositories
from apps.requests.models import Request, RequestContract, RequestOffer, Ticket
from apps.requests.services import lifecycle



def _pct(part, whole, digits=0):
    """Percentage, or None when there is nothing to divide by.

    A zero denominator is not "0%" — it is "no answer yet". Returning None
    keeps an empty system from reporting a confident 0 everywhere.
    """
    if not whole:
        return None
    value = (part / whole) * 100
    return round(value, digits) if digits else int(round(value))


def _hours_between(start, end):
    if not start or not end or end < start:
        return None
    return (end - start).total_seconds() / 3600.0


def build_executive_metrics(user) -> dict:
    now = timezone.now()
    dept = Request.Department
    status = Request.Status
    sp = Request.SalesPhase
    sla = lifecycle.STAGE_SLA_HOURS
    base = repositories.scope_requests_by_department(user, Request.objects.all())
    open_qs = base.exclude(status__in=(status.CLOSED, status.CANCELLED))

    # --- funnel ------------------------------------------------------------
    counts = {
        'marketing': base.filter(department=dept.MARKETING).count(),
        'qualification': base.filter(
            department=dept.SALES, sales_phase=sp.QUALIFICATION).count(),
        'technical': base.filter(department=dept.TECHNICAL).count(),
        'negotiation': base.filter(
            department=dept.SALES, sales_phase=sp.NEGOTIATION).count(),
        'done': base.filter(department=dept.DONE).count(),
    }
    total = base.count()
    stage_counts = dict(open_qs.order_by().values_list('funnel_stage').annotate(n=Count('id')))
    open_total = sum(stage_counts.values())
    funnel = [
        {'label': label, 'count': stage_counts.get(key, 0), 'pct': _pct(stage_counts.get(key, 0), open_total)}
        for key, label in Request.FunnelStage.choices
    ]

    # --- week-on-week intake ----------------------------------------------
    week_ago = now - timedelta(days=7)
    two_weeks_ago = now - timedelta(days=14)
    this_week = base.filter(created_at__gte=week_ago).count()
    last_week = base.filter(created_at__gte=two_weeks_ago, created_at__lt=week_ago).count()
    if last_week:
        trend_pct = int(round(((this_week - last_week) / last_week) * 100))
    elif this_week:
        trend_pct = None  # growth from zero is not a percentage
    else:
        trend_pct = 0

    # --- how long the contact queue has been waiting ----------------------
    waiting = open_qs.filter(department=dept.SALES, sales_phase=sp.QUALIFICATION)
    wait_hours = [
        _hours_between(r.stage_entered_at, now)
        for r in waiting.only('stage_entered_at')
    ]
    wait_hours = [h for h in wait_hours if h is not None]
    avg_wait_hours = round(sum(wait_hours) / len(wait_hours), 1) if wait_hours else None

    # --- marketing ---------------------------------------------------------
    exhibition_total = base.filter(exhibition__isnull=False).count()
    website_total = total - exhibition_total
    reviewed = base.filter(marketing_reviewed_at__isnull=False).count()
    # Of the leads marketing has finished with, how many went forward rather
    # than being dropped? Leads still sitting in the marketing queue are not
    # counted either way — they have not been decided yet.
    marketing_decided = reviewed + base.filter(
        department=dept.DONE, marketing_reviewed_at__isnull=True,
        status=status.CLOSED).count()
    qualify_rate = _pct(reviewed, marketing_decided)

    # --- sales -------------------------------------------------------------
    offers_total = repositories.scope_related_by_department(
        user, RequestOffer.objects.all()).count()
    contracts_total = repositories.scope_related_by_department(
        user, RequestContract.objects.all()).count()

    workload = []
    rows = (
        base.filter(sales_assignee__isnull=False)
        .values('sales_assignee__id', 'sales_assignee__first_name',
                'sales_assignee__last_name', 'sales_assignee__username')
        .annotate(
            active=Count('id', filter=~Q(status__in=(
                status.CLOSED, status.CANCELLED, status.PAID))),
            closed=Count('id', filter=Q(department=dept.DONE, crm_transferred=True)),
        )
        .order_by('-active')[:8]
    )
    for row in rows:
        name = (f"{row.get('sales_assignee__first_name') or ''} "
                f"{row.get('sales_assignee__last_name') or ''}").strip()
        workload.append({
            'label': name or row.get('sales_assignee__username') or '—',
            'active': row['active'],
            'closed': row['closed'],
        })

    # --- technical / fleet -------------------------------------------------
    plants = Plant.objects.all()
    plant_count = plants.count()
    capacity_kw = plants.aggregate(total=Sum('capacity_kw'))['total'] or 0
    inverters_online = Inverter.objects.filter(online=True).count()
    inverters_total = Inverter.objects.count()
    # Plants described by roof sections report through their inverters; their
    # old placeholder cells never receive data and would read as unhealthy.
    grid_modules = PVModule.objects.filter(plant__sections__isnull=True)
    module_total = grid_modules.count()
    module_ok = grid_modules.filter(status=PVModule.Status.OK).count()
    # Named for what it actually measures. Real yield efficiency needs metered
    # output against rated capacity over a period; until telemetry is flowing
    # that number would be invented, so this reports module health instead.
    module_health_pct = _pct(module_ok, module_total, digits=1)

    # --- operations / SLA --------------------------------------------------
    cutoff = now - timedelta(hours=sla)
    in_flight = open_qs.filter(
        department__in=(dept.MARKETING, dept.SALES, dept.TECHNICAL))
    in_flight_count = in_flight.count()
    overdue_count = in_flight.filter(stage_entered_at__lt=cutoff).count()
    sla_compliance_pct = _pct(in_flight_count - overdue_count, in_flight_count, digits=1)

    handled = AlertEvent.objects.filter(
        acknowledged=True, acknowledged_at__isnull=False)
    avg_ack_minutes = handled.aggregate(
        avg=Avg(F('acknowledged_at') - F('created_at')))['avg']
    if avg_ack_minutes is not None:
        avg_ack_minutes = int(round(avg_ack_minutes.total_seconds() / 60))

    # --- attention list ----------------------------------------------------
    hide_identity = repositories.is_identity_restricted(user)

    def _title(req):
        if hide_identity:
            return f'درخواست #{req.id}'
        return req.full_name or f'درخواست #{req.id}'

    attention = []
    seen = set()
    for req in in_flight.filter(stage_entered_at__lt=cutoff).order_by('stage_entered_at')[:6]:
        attention.append({
            'id': req.id,
            'title': _title(req),
            'reason': f'در مرحلهٔ {req.get_department_display()} مانده',
            'tag': 'عقب‌افتاده',
            'tone': 'bad',
        })
        seen.add(req.id)
    for req in open_qs.filter(department=dept.SALES, sales_assignee__isnull=True)[:4]:
        if req.id in seen:
            continue
        attention.append({
            'id': req.id, 'title': _title(req),
            'reason': 'هیچ کارشناسی تخصیص نیافته',
            'tag': 'بدون مسئول', 'tone': 'warn',
        })
        seen.add(req.id)
    for req in open_qs.filter(department=dept.MARKETING).filter(
            Q(bill_id='') | Q(latitude__isnull=True))[:4]:
        if req.id in seen:
            continue
        missing = []
        if not req.bill_id:
            missing.append('قبض برق')
        if req.latitude is None:
            missing.append('موقعیت نقشه')
        attention.append({
            'id': req.id, 'title': _title(req),
            'reason': 'ناقص: ' + ' و '.join(missing),
            'tag': 'نقص اطلاعات', 'tone': 'warn',
        })
        seen.add(req.id)

    # --- SLA table ---------------------------------------------------------
    sla_rows = []
    tracked = (
        open_qs.select_related('sales_assignee', 'technical_assignee')
        .order_by('stage_entered_at')[:12]
    )
    for req in tracked:
        age = _hours_between(req.stage_entered_at, now)
        if age is None:
            remaining = None
        else:
            remaining = sla - age
        if req.department == dept.TECHNICAL:
            owner = req.technical_assignee
            owner_dept = 'فنی'
        else:
            owner = req.sales_assignee
            owner_dept = 'فروش'
        place = ' / '.join(x for x in (req.province, req.city) if x) or '—'
        if req.area_m2:
            place = f'{place} ({req.area_m2:,} متر)'
        stage = req.get_department_display()
        if req.sales_phase:
            stage = req.get_sales_phase_display()
        sla_rows.append({
            'id': req.id,
            'title': _title(req),
            'from_qr': req.how_heard == Request.HowHeard.EXHIBITION,
            'place': place,
            'stage': stage,
            'owner': (owner.get_full_name() or owner.username) if owner else None,
            'owner_dept': owner_dept,
            'remaining_h': None if remaining is None else int(remaining),
            'overdue': remaining is not None and remaining < 0,
        })

    return {
        'funnel': funnel,
        'conversion_pct': _pct(counts['done'], total, digits=1),
        'lead_trend_pct': trend_pct,
        'leads_this_week': this_week,
        'avg_wait_hours': avg_wait_hours,
        'plant_count': plant_count,
        'capacity_kw': capacity_kw,
        'inverters_online': inverters_online,
        'inverters_total': inverters_total,
        'module_health_pct': module_health_pct,
        'website_leads': website_total,
        'exhibition_leads': exhibition_total,
        'qualify_rate_pct': qualify_rate,
        'offers_total': offers_total,
        'contracts_total': contracts_total,
        'sla_compliance_pct': sla_compliance_pct,
        'overdue_count': overdue_count,
        'avg_ack_minutes': avg_ack_minutes,
        'workload': workload,
        'attention': attention,
        'sla_rows': sla_rows,
    }


def build_nav_counts(user) -> dict:
    """Badge numbers for the sidebar. One cheap query per badge, counts only."""
    dept = Request.Department
    status = Request.Status
    sp = Request.SalesPhase
    base = repositories.scope_requests_by_department(user, Request.objects.all())
    open_qs = base.exclude(status__in=(status.CLOSED, status.CANCELLED))
    week_ago = timezone.now() - timedelta(days=7)

    counts = {
        'pipeline': open_qs.count(),
        'website_new': open_qs.filter(
            department=dept.MARKETING, exhibition__isnull=True,
            created_at__gte=week_ago).count(),
        'qr_leads': open_qs.filter(exhibition__isnull=False).count(),
        'offers': open_qs.filter(
            department=dept.SALES, sales_phase=sp.QUALIFICATION).count(),
        'contracts': repositories.scope_related_by_department(
            user, RequestContract.objects.all()).count(),
        'alerts': 0,
        'tickets': 0,
    }
    if getattr(user, 'can_access_plants', False) or repositories.is_management(user):
        counts['alerts'] = AlertEvent.objects.filter(acknowledged=False).count()
    counts['tickets'] = Ticket.objects.exclude(status=Ticket.Status.CLOSED).count()
    counts['finance_pending'] = 0
    if repositories.is_management(user) or repositories.is_financial(user):
        from apps.requests.services.project import finance_pending_count
        counts['finance_pending'] = finance_pending_count()
    counts['setting_approvals'] = 0
    if repositories.is_management(user):
        from apps.core.models import SettingChangeRequest
        counts['setting_approvals'] = SettingChangeRequest.objects.filter(
            status=SettingChangeRequest.Status.PENDING).count()
    return counts
