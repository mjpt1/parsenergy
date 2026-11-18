"""Shared lead + fleet KPI payload for role and executive dashboards."""
from __future__ import annotations

from datetime import timedelta

from django.db.models import Count, Q
from django.utils import timezone

from apps.alerts.models import AlertEvent
from apps.plants.layout import module_grid_payload, plant_map_points
from apps.plants.models import Plant, PVModule
from apps.plants.scoping import plant_scope_for_user
from apps.requests import repositories
from apps.requests.models import Request
from apps.requests.services import lifecycle


def resolve_dashboard_role(user) -> str:
    if repositories.is_management(user) or user.is_superuser or getattr(user, 'role', '') == 'admin':
        return 'admin'
    if repositories.is_marketing(user):
        return 'marketing'
    if repositories.is_sales(user):
        return 'sales'
    if repositories.is_technical(user):
        return 'technical'
    if repositories.is_operations(user):
        return 'operations'
    role = getattr(user, 'role', '') or 'owner'
    if role in ('owner', 'customer'):
        return role
    return 'owner'


def _age_hours(dt):
    if not dt:
        return None
    return round((timezone.now() - dt).total_seconds() / 3600.0, 1)


def build_lead_fleet_context(user) -> dict:
    """KPI + queues + map used by every staff/executive dashboard."""
    base = repositories.scope_requests_by_department(user, Request.objects.all())
    dept = Request.Department
    status = Request.Status
    sla = lifecycle.STAGE_SLA_HOURS
    cutoff = timezone.now() - timedelta(hours=sla)
    role = resolve_dashboard_role(user)
    hide_identity = repositories.is_identity_restricted(user)

    stats = {
        'total': base.count(),
        'new_leads': base.filter(department=dept.MARKETING).count(),
        'in_marketing': base.filter(department=dept.MARKETING).count(),
        'in_sales_qualify': base.filter(
            department=dept.SALES, sales_phase=Request.SalesPhase.QUALIFICATION).count(),
        'in_technical': base.filter(department=dept.TECHNICAL).count(),
        'in_negotiation': base.filter(
            department=dept.SALES, sales_phase=Request.SalesPhase.NEGOTIATION).count(),
        'done': base.filter(department=dept.DONE).count(),
        'hold': base.filter(status=status.HOLD).count(),
        'closed': base.filter(status=status.CLOSED).count(),
        'crm_transferred': base.filter(crm_transferred=True).count(),
        'high_priority': base.filter(priority__in=('high', 'urgent')).count(),
        'needs_contact': base.filter(
            department=dept.SALES,
            sales_phase=Request.SalesPhase.QUALIFICATION,
        ).exclude(status__in=(status.HOLD, status.CLOSED, status.CANCELLED)).count(),
        'offers_ready': base.filter(
            department=dept.SALES,
            sales_phase=Request.SalesPhase.NEGOTIATION,
            status=status.OFFERED,
        ).count(),
        'overdue': repositories.overdue_requests(base).count(),
        'unassigned_sales': base.filter(
            department=dept.SALES, sales_assignee__isnull=True).count(),
    }

    incomplete_qs = base.filter(department=dept.MARKETING).filter(
        Q(bill_id='') | Q(latitude__isnull=True) | Q(longitude__isnull=True)
    )
    stats['incomplete'] = incomplete_qs.count()
    stats['missing_map'] = base.filter(Q(latitude__isnull=True) | Q(longitude__isnull=True)).count()
    stats['missing_bill'] = base.filter(bill_id='').count()
    stats['forwarded'] = (
        stats['in_sales_qualify'] + stats['in_technical']
        + stats['in_negotiation'] + stats['done']
    )
    stats['sales_open'] = stats['in_sales_qualify'] + stats['in_negotiation']

    by_source = list(
        base.exclude(lead_source='')
        .values('lead_source').annotate(n=Count('id')).order_by('-n')[:10]
    )
    by_campaign = list(
        base.exclude(campaign_name='')
        .values('campaign_name').annotate(n=Count('id')).order_by('-n')[:10]
    )
    by_province = list(
        base.values('province').annotate(n=Count('id')).order_by('-n')[:10]
    )
    by_how_heard = list(
        base.exclude(how_heard='')
        .values('how_heard').annotate(n=Count('id')).order_by('-n')[:10]
    )
    by_request_type = list(
        base.exclude(request_type='')
        .values('request_type').annotate(n=Count('id')).order_by('-n')[:10]
    )

    by_assignee = list(
        base.filter(department=dept.SALES)
        .values('sales_assignee__id', 'sales_assignee__first_name', 'sales_assignee__last_name',
                'sales_assignee__username')
        .annotate(n=Count('id')).order_by('-n')[:12]
    )
    for row in by_assignee:
        name = f"{row.get('sales_assignee__first_name') or ''} {row.get('sales_assignee__last_name') or ''}".strip()
        row['label'] = name or row.get('sales_assignee__username') or 'بدون مسئول'

    completed = base.filter(technical_completed_at__isnull=False, triaged_at__isnull=False)
    durations = []
    for row in completed.values_list('triaged_at', 'technical_completed_at')[:500]:
        if row[0] and row[1] and row[1] >= row[0]:
            durations.append((row[1] - row[0]).total_seconds() / 3600.0)
    avg_proposal_hours = round(sum(durations) / len(durations), 1) if durations else None

    # --- Role queues ---
    marketing_queue = []
    for req in base.filter(department=dept.MARKETING).order_by('-updated_at')[:12]:
        issues = []
        if not req.bill_id:
            issues.append('فاقد قبض')
        if req.latitude is None or req.longitude is None:
            issues.append('بدون نقشه')
        marketing_queue.append({
            'id': req.id,
            'source': req.lead_source or req.how_heard or '—',
            'campaign': req.campaign_name or '—',
            'province': req.province,
            'city': req.city,
            'request_type': req.get_request_type_display() if req.request_type else '—',
            'has_map': req.latitude is not None and req.longitude is not None,
            'complete': not issues,
            'issues': ' / '.join(issues) if issues else 'کامل',
        })

    sales_queue = []
    sales_qs = base.filter(department=dept.SALES).exclude(
        status__in=(status.CLOSED, status.CANCELLED)
    ).select_related('sales_assignee').order_by('-priority', '-updated_at')[:15]
    for req in sales_qs:
        sales_queue.append({
            'id': req.id,
            'name': req.full_name,
            'mobile': req.mobile,
            'priority': req.priority,
            'phase': req.get_sales_phase_display() if req.sales_phase else req.get_department_display(),
            'status': req.get_status_display(),
            'has_map': req.latitude is not None,
            'assignee': (
                req.sales_assignee.get_full_name() or req.sales_assignee.username
            ) if req.sales_assignee_id else '—',
            'updated': req.updated_at,
            'age_h': _age_hours(req.stage_entered_at or req.updated_at),
        })

    technical_queue = []
    for req in base.filter(department=dept.TECHNICAL).order_by('-priority', 'stage_entered_at')[:15]:
        technical_queue.append({
            'id': req.id,
            'province': req.province,
            'city': req.city,
            'site': req.get_request_type_display() if req.request_type else '—',
            'priority': req.priority,
            'has_map': req.latitude is not None,
            'status': req.get_status_display(),
            'age_h': _age_hours(req.stage_entered_at or req.updated_at),
        })

    ops_critical = []
    for req in base.filter(
        department__in=(dept.MARKETING, dept.SALES, dept.TECHNICAL),
        stage_entered_at__lt=cutoff,
    ).exclude(status__in=(status.CLOSED, status.CANCELLED, status.PAID)).order_by('stage_entered_at')[:12]:
        ops_critical.append({
            'id': req.id,
            'problem': 'عقب‌افتاده',
            'stage': req.get_department_display(),
            'age_h': _age_hours(req.stage_entered_at),
            'assignee_missing': req.department == dept.SALES and not req.sales_assignee_id,
        })
    for req in base.filter(department=dept.SALES, sales_assignee__isnull=True).exclude(
        status__in=(status.CLOSED, status.CANCELLED))[:8]:
        if not any(x['id'] == req.id for x in ops_critical):
            ops_critical.append({
                'id': req.id,
                'problem': 'بدون مسئول فروش',
                'stage': req.get_department_display(),
                'age_h': _age_hours(req.stage_entered_at),
                'assignee_missing': True,
            })

    closed_recent = list(
        base.filter(status=status.CLOSED).order_by('-updated_at')[:8]
    )

    lead_points = []
    for req in base.exclude(latitude__isnull=True).exclude(longitude__isnull=True)[:200]:
        lead_points.append({
            'id': None,
            'name': f'لید #{req.id}' if hide_identity else (req.full_name or f'#{req.id}'),
            'lat': float(req.latitude),
            'lng': float(req.longitude),
            'power': 0,
            'online': True,
            'alerts': 0,
            'hot_cells': 0,
            'location': f'{req.province} / {req.city}'.strip(' /'),
        })

    plant_points = []
    fleet_stats = {'plants': 0, 'alerts': 0, 'hot_cells': 0, 'online': 0, 'offline': 0, 'warn_cells': 0}
    fleet_alerts = []
    module_grid = None
    selected_plant = None
    # All staff roles see geography (leads + plants). Cell heat-map only for
    # technical / ops / management (and plant-capable roles).
    show_geo = role in ('marketing', 'sales', 'technical', 'operations', 'admin')
    show_cells = role in ('technical', 'operations', 'admin') or getattr(user, 'can_access_plants', False)
    if show_geo or show_cells:
        # Marketing/sales may not have plant RBAC; still show delivered sites on the map.
        if role in ('marketing', 'sales'):
            plants = Plant.objects.all().prefetch_related('modules', 'inverters')
        else:
            plants = plant_scope_for_user(user).prefetch_related('modules', 'inverters')
        plant_points = plant_map_points(plants)
        fleet_stats['plants'] = plants.count()
        fleet_stats['alerts'] = AlertEvent.objects.filter(
            rule__plant__in=plants, acknowledged=False).count()
        fleet_stats['hot_cells'] = PVModule.objects.filter(
            plant__in=plants, status=PVModule.Status.HOT).count()
        fleet_stats['warn_cells'] = PVModule.objects.filter(
            plant__in=plants, status=PVModule.Status.WARN).count()
        fleet_stats['online'] = plants.filter(
            connection_status=Plant.ConnectionStatus.ONLINE).count()
        fleet_stats['offline'] = fleet_stats['plants'] - fleet_stats['online']
        fleet_alerts = list(
            AlertEvent.objects.filter(rule__plant__in=plants, acknowledged=False)
            .select_related('rule', 'rule__plant').order_by('-created_at')[:10]
        )
        if show_cells:
            selected_plant = (
                plants.filter(modules__status=PVModule.Status.HOT).distinct().first()
                or plants.order_by('name').first()
            )
            if selected_plant is not None:
                # Read-only: never scaffold modules from a dashboard page view.
                module_grid = module_grid_payload(selected_plant)

    # Marketing/sales prefer lead map; others prefer fleet map.
    if role in ('marketing', 'sales'):
        map_points = lead_points or plant_points
    else:
        map_points = plant_points or lead_points

    from apps.requests.todo import build_todo
    todo = build_todo(role, {**stats, 'sla_hours': sla}, fleet_stats, user)

    return {
        'todo': todo,
        'dashboard_role': role,
        'hide_customer_identity': hide_identity,
        'sla_hours': sla,
        'stats': stats,
        'by_source': by_source,
        'by_campaign': by_campaign,
        'by_province': by_province,
        'by_how_heard': by_how_heard,
        'by_request_type': by_request_type,
        'by_assignee': by_assignee,
        'avg_proposal_hours': avg_proposal_hours,
        'map_points': map_points,
        'lead_map_points': lead_points,
        'fleet_stats': fleet_stats,
        'fleet_alerts': fleet_alerts,
        'marketing_queue': marketing_queue,
        'sales_queue': sales_queue,
        'technical_queue': technical_queue,
        'ops_critical': ops_critical,
        'closed_recent': closed_recent,
        'module_grid': module_grid,
        'selected_plant': selected_plant,
        'recent_requests': list(base.order_by('-updated_at')[:10]),
    }
