import base64
import logging
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.contrib.auth import get_user_model
from django.db.models import Count, Sum
from apps.core.localtime import local_hour, on_or_after
from django.core.cache import cache
from django.http import HttpResponse, HttpResponseNotFound, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.cache import cache_control
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _

from apps.plants.models import (EnvironmentalReading, Equipment, Inverter, Plant,
                                PlantMembership, RealtimeMeasurement)
from apps.alerts.models import AlertEvent, Notification, AlertRule
from apps.core.models import (APIConnection, AuditLog, DatabaseBackup,
                              ProtocolAdapter, ServerHealthMetric)


from apps.core import geocoding, tiles

logger = logging.getLogger(__name__)

# 1x1 transparent PNG, used when every upstream refuses a tile.
_BLANK_TILE = base64.b64decode(
    b'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk'
    b'YPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==')
from apps.plants.scoping import plant_scope_for_user as _plant_scope_for_user

GEOCODE_RATE_PER_MINUTE = 40


def home(request):
    """Public landing page. Authenticated users go straight to their dashboard."""
    if request.user.is_authenticated:
        return redirect('dashboard')
    return render(request, 'landing.html', {'title': 'پارس انرژی'})


@login_required
def dashboard_router(request):
    """Single home for every role — render the role dashboard directly (no redirect loops)."""
    role = getattr(request.user, 'role', 'owner')
    if role == 'contractor':
        return redirect('requests:contractor-home')
    from apps.requests.dashboard_context import build_lead_fleet_context
    from apps.requests.executive_metrics import build_executive_metrics, build_nav_counts

    ROLE_TEMPLATES = {
        'marketing': 'requests/admin/dashboards/marketing.html',
        'sales': 'requests/admin/dashboards/sales.html',
        'operations': 'requests/admin/dashboards/operations.html',
        'technical': 'dashboard/technical.html',
    }
    ROLE_TITLES = {
        'marketing': 'داشبورد بازاریابی',
        'sales': 'داشبورد فروش',
        'operations': 'داشبورد عملیات',
        'technical': 'داشبورد فنی',
    }

    if role in ROLE_TEMPLATES:
        try:
            ctx = build_lead_fleet_context(request.user)
        except Exception:
            ctx = {
                'stats': {
                    'total': 0, 'needs_contact': 0, 'in_technical': 0, 'crm_transferred': 0,
                    'overdue': 0, 'in_marketing': 0, 'in_sales_qualify': 0, 'in_negotiation': 0,
                    'done': 0, 'hold': 0, 'closed': 0, 'unassigned_sales': 0, 'incomplete': 0,
                    'offers_ready': 0, 'high_priority': 0, 'forwarded': 0, 'sales_open': 0,
                    'missing_map': 0, 'missing_bill': 0, 'new_leads': 0,
                },
                'fleet_stats': {'plants': 0, 'alerts': 0, 'hot_cells': 0, 'online': 0, 'offline': 0, 'warn_cells': 0},
                'by_source': [], 'by_campaign': [], 'by_province': [], 'by_assignee': [],
                'map_points': [], 'fleet_alerts': [], 'ops_critical': [], 'recent_requests': [],
                'marketing_queue': [], 'sales_queue': [], 'technical_queue': [], 'closed_recent': [],
                'module_grid': None, 'selected_plant': None, 'avg_proposal_hours': None,
                'sla_hours': 72, 'dashboard_role': role, 'hide_customer_identity': role == 'technical',
            }
        title = ROLE_TITLES[role]
        ctx.update({'title': title, 'page_title': title, 'dashboard_role': role})
        return render(request, ROLE_TEMPLATES[role], ctx)

    User = get_user_model()
    # Everyone who is not a customer belongs on a staff dashboard.
    #
    # This used to list the staff roles and let everything else fall through to
    # the customer portal, which put any role the list forgot — `operator`,
    # `analyst`, and `owner`, which is the *model default* and so lands on
    # every account created without an explicit role — in front of a page about
    # "my power plant". Only `customer` is a customer; the rest manage.
    if role != User.Role.CUSTOMER:
        try:
            ctx = build_lead_fleet_context(request.user)
        except Exception:
            ctx = {
                'stats': {
                    'total': 0, 'needs_contact': 0, 'in_technical': 0, 'crm_transferred': 0,
                    'overdue': 0, 'in_marketing': 0, 'in_sales_qualify': 0, 'in_negotiation': 0,
                    'done': 0, 'hold': 0, 'closed': 0, 'unassigned_sales': 0, 'incomplete': 0,
                    'offers_ready': 0, 'high_priority': 0, 'forwarded': 0, 'sales_open': 0,
                    'missing_map': 0, 'missing_bill': 0, 'new_leads': 0,
                },
                'fleet_stats': {'plants': 0, 'alerts': 0, 'hot_cells': 0, 'online': 0, 'offline': 0, 'warn_cells': 0},
                'by_source': [], 'by_campaign': [], 'map_points': [], 'fleet_alerts': [],
                'ops_critical': [], 'recent_requests': [], 'module_grid': None, 'selected_plant': None,
                'avg_proposal_hours': None, 'sla_hours': 72, 'dashboard_role': 'admin',
            }
        latest_health = ServerHealthMetric.objects.first()
        system_health_percent = None
        if latest_health:
            avg_usage = (float(latest_health.cpu_percent) + float(latest_health.memory_percent) + float(latest_health.disk_percent)) / 3
            system_health_percent = max(0, round(100 - avg_usage, 1))
        # Trends, ratios and the SLA table live apart from the shared KPI
        # payload so the other role dashboards do not run these queries.
        try:
            ctx.update(build_executive_metrics(request.user))
            ctx['nav_counts'] = build_nav_counts(request.user)
        except Exception:
            logger.exception('executive metrics failed; rendering without them')
        # Same page, honest name: finance reaches it too, and calling their
        # screen "مدیرکل" would misdescribe both the data and the authority.
        heading = 'داشبورد مالی' if role == User.Role.FINANCIAL else 'داشبورد مدیرکل'
        ctx.update({
            'title': heading,
            'page_title': heading,
            # The header dates itself in whichever calendar the user picked.
            'today': timezone.localdate(),
            'system_health_percent': system_health_percent,
            'users_count': User.objects.count(),
            'equipment_online_count': Equipment.objects.filter(online=True).count(),
            'plants_count': (ctx.get('fleet_stats') or {}).get('plants', Plant.objects.count()),
            'hot_cells': (ctx.get('fleet_stats') or {}).get('hot_cells', 0),
        })
        return render(request, 'dashboard/executive.html', ctx)

    plants_qs = _plant_scope_for_user(request.user)
    from apps.plants.layout import module_grid_payload, plant_map_points
    from apps.plants.models import PVModule
    # The dashboard only reads: it must never scaffold module rows as a side
    # effect of a page view. A plant's layout is created when the plant is
    # created (or explicitly from the plant page), so an empty grid here
    # genuinely means "no modules registered yet".
    plants = plants_qs.select_related('owner').prefetch_related(
        'inverters', 'sensors', 'meters', 'equipment', 'gateways', 'modules')
    selected = None
    if request.GET.get('plant', '').isdigit():
        selected = plants.filter(pk=request.GET['plant']).first()
    if selected is None:
        selected = plants.order_by('-created_at').first()
    module_payload = module_grid_payload(selected) if selected else None
    latest_telemetry = RealtimeMeasurement.objects.filter(
        plant__in=plants, parameter='power').select_related('plant', 'equipment').order_by('-timestamp').first()
    my_requests = []
    try:
        from apps.requests.models import Request as LeadRequest
        from apps.requests.services.lifecycle import link_session_requests
        link_session_requests(request)
        my_requests = list(LeadRequest.objects.filter(user=request.user).order_by('-updated_at')[:5])
    except Exception:
        my_requests = []
    power_kw = float(latest_telemetry.value) if latest_telemetry else 0
    last_seen = None
    if selected:
        tel = selected.telemetry.order_by('-created_at').first()
        if tel:
            power_kw = float(tel.power_kw or 0)
            last_seen = tel.created_at
    # One plain sentence on top: is the plant working, and is data arriving?
    if selected is None:
        plant_state = None
    elif last_seen is None:
        plant_state = 'waiting'
    elif timezone.now() - last_seen > timedelta(minutes=30):
        plant_state = 'stale'
    elif selected.connection_status == 'online':
        plant_state = 'ok'
    else:
        plant_state = 'down'
    from apps.core.templatetags.ux_tags import energy_tariff_rial
    from apps.plants.revenue import build_revenue
    revenue = build_revenue(selected) if selected else None
    active_request = next((r for r in my_requests if not r.plant_id and r.status not in ('closed', 'cancelled')), None)
    context = {
        'title': 'داشبورد مالک',
        'plants': plants,
        'plant_count': plants.count(),
        'alerts_count': AlertEvent.objects.filter(rule__plant__in=plants, acknowledged=False).count(),
        'hot_cells': PVModule.objects.filter(plant__in=plants, status=PVModule.Status.HOT).count(),
        'warn_cells': PVModule.objects.filter(plant__in=plants, status=PVModule.Status.WARN).count(),
        'latest_telemetry': latest_telemetry,
        'buyer_power_kw': power_kw,
        'report_plant': selected,
        'selected_plant': selected,
        'module_grid': module_payload,
        'map_points': plant_map_points(plants),
        'recent_alerts': AlertEvent.objects.filter(rule__plant__in=plants).select_related('rule', 'rule__plant').order_by('-created_at')[:8],
        'recent_notifications': Notification.objects.filter(user=request.user).order_by('-created_at')[:6],
        'recent_environmental': EnvironmentalReading.objects.filter(plant__in=plants).select_related('plant').order_by('-created_at')[:6],
        'recent_rules': AlertRule.objects.filter(plant__in=plants).select_related('plant').order_by('-id')[:6],
        'membership_count': PlantMembership.objects.filter(user=request.user, active=True).count(),
        'my_requests': my_requests,
        'active_request': active_request,
        'plant_state': plant_state,
        'last_seen': last_seen,
        'has_tariff': energy_tariff_rial() is not None,
        'revenue': revenue if revenue and revenue['has_rate'] else None,
        'latest_bill': selected.bills.first() if selected else None,
        'portal_tab': 'dashboard',
    }
    return render(request, 'dashboard/owner.html', context)


def _build_chart_series_from_measurements(queryset, hours=12):
    def _query_series(start, end):
        # Hourly averages grouped in Python: TruncHour needs time-zone tables
        # the production database does not have (see apps.core.localtime).
        sums = {}
        for ts, value in queryset.filter(timestamp__gte=start, timestamp__lte=end).values_list('timestamp', 'value'):
            bucket = sums.setdefault(local_hour(ts), [0.0, 0])
            bucket[0] += float(value or 0)
            bucket[1] += 1
        return [{'hour': h, 'avg_power': s / n} for h, (s, n) in sorted(sums.items())]

    end = timezone.now()
    start = end - timedelta(hours=hours)
    series = _query_series(start, end)

    if not series:
        latest_measurement = queryset.order_by('-timestamp').first()
        if latest_measurement:
            end = latest_measurement.timestamp
            start = end - timedelta(hours=hours)
            series = _query_series(start, end)

    local_tz = timezone.get_current_timezone()
    labels = []
    values = []
    series_map = {}
    for item in series:
        item_hour = item.get('hour')
        if not item_hour:
            continue
        if timezone.is_aware(item_hour):
            item_hour = item_hour.astimezone(local_tz)
        series_map[item_hour] = float(item['avg_power'] or 0)

    current = timezone.localtime(start, local_tz).replace(minute=0, second=0, microsecond=0)
    while current <= end:
        labels.append(current.strftime('%H:%M'))
        values.append(series_map.get(current, 0))
        current += timedelta(hours=1)

    if not labels:
        now = timezone.now().replace(minute=0, second=0, microsecond=0)
        for offset in range(hours, -1, -1):
            point = now - timedelta(hours=offset)
            labels.append(point.strftime('%H:%M'))
            values.append(0)
    return labels, values


# compatibility alias for legacy admin dashboard calls
_build_chart_series = _build_chart_series_from_measurements

@login_required
def admin_dashboard_data(request):
    role = getattr(request.user, 'role', 'owner')
    if role != 'admin' and not request.user.is_superuser:
        raise PermissionDenied

    latest_health = ServerHealthMetric.objects.first()
    labels, production = _build_chart_series_from_measurements(
        RealtimeMeasurement.objects.filter(parameter='power'), hours=12
    )
    total_capacity = Plant.objects.aggregate(total=Sum('capacity_kw'))['total'] or 0
    efficiency = []
    for value in production:
        if total_capacity:
            efficiency.append(min(100, round((value / float(total_capacity)) * 100, 2)))
        else:
            efficiency.append(0)

    alert_events = AlertEvent.objects.select_related('rule', 'rule__plant').order_by('-created_at')[:6]
    alerts_payload = [
        {
            'type': event.rule.name,
            'plant': event.rule.plant.name,
            'message': event.message,
            'severity': event.severity,
            'acknowledged': event.acknowledged,
        }
        for event in alert_events
    ]

    data = {
        'plants_count': Plant.objects.count(),
        'equipment_online_count': Equipment.objects.filter(online=True).count(),
        'alerts_count': AlertEvent.objects.filter(acknowledged=False).count(),
        'users_count': get_user_model().objects.count(),
        'system_health_percent': None,
        'server_health': {
            'cpu': float(latest_health.cpu_percent) if latest_health else 0,
            'memory': float(latest_health.memory_percent) if latest_health else 0,
            'disk': float(latest_health.disk_percent) if latest_health else 0,
            'queue': float(latest_health.queue_depth) if latest_health else 0,
        },
        'chart': {
            'labels': labels,
            'production': production,
            'efficiency': efficiency,
        },
        'alerts': alerts_payload,
    }
    if latest_health:
        avg_usage = (float(latest_health.cpu_percent) + float(latest_health.memory_percent) + float(latest_health.disk_percent)) / 3
        data['system_health_percent'] = max(0, round(100 - avg_usage, 1))
    return JsonResponse(data)


@login_required
def owner_dashboard_data(request):
    plants = _plant_scope_for_user(request.user)
    total_capacity = plants.aggregate(total=Sum('capacity_kw'))['total'] or 0
    current_power = 0
    for plant in plants:
        # Get latest power measurement for the plant
        latest_power = RealtimeMeasurement.objects.filter(
            plant=plant, parameter='power'
        ).order_by('-timestamp').first()
        if latest_power:
            current_power += float(latest_power.value)
    
    latest_telemetry = (
        RealtimeMeasurement.objects.filter(plant__in=plants, parameter='power')
        .select_related('plant', 'equipment')
        .order_by('-timestamp')
        .first()
    )
    
    # Build chart series from realtime measurements
    labels, production = _build_chart_series_from_measurements(
        RealtimeMeasurement.objects.filter(plant__in=plants, parameter='power'), hours=24
    )
    
    today = timezone.localdate()
    today_energy = (
        RealtimeMeasurement.objects.filter(
            plant__in=plants,
            parameter='energy',
            **on_or_after('timestamp', today),
        ).aggregate(total=Sum('value')).get('total') or 0
    )
    
    efficiency = 0
    if total_capacity:
        efficiency = min(100, round((current_power / float(total_capacity)) * 100, 2))
    
    # Savings use the tariff set in System Parameters; without one, none is shown.
    from apps.core.templatetags.ux_tags import energy_tariff_rial
    tariff = energy_tariff_rial()
    revenue = float(today_energy) * tariff if tariff else 0
    month_energy = (
        RealtimeMeasurement.objects.filter(
            plant__in=plants, parameter='energy',
            **on_or_after('timestamp', today - timedelta(days=29)),
        ).aggregate(total=Sum('value')).get('total') or 0
    )

    # Get equipment status (inverters, etc.)
    equipment = Equipment.objects.filter(plant__in=plants).select_related('plant')[:6]
    equipment_payload = []
    for eq in equipment:
        latest_power = RealtimeMeasurement.objects.filter(
            equipment=eq, parameter='power'
        ).order_by('-timestamp').first()
        equipment_payload.append({
            'name': eq.name,
            'status': _('فعال') if eq.online else _('قطع ارتباط'),
            'status_level': 'ok' if eq.online else 'bad',
            'power_kw': float(latest_power.value) if latest_power else 0,
        })

    # Recent alerts
    recent_alerts = AlertEvent.objects.filter(rule__plant__in=plants).select_related('rule').order_by('-created_at')[:4]
    alerts_payload = [
        {
            'type': alert.rule.name,
            'message': alert.message,
            'time': alert.created_at.strftime('%H:%M'),
        }
        for alert in recent_alerts
    ]

    data = {
        'plant_count': plants.count(),
        'latest_power_kw': float(latest_telemetry.value) if latest_telemetry else 0,
        'today_energy_kwh': float(today_energy),
        'efficiency': efficiency,
        'today_revenue': revenue,
        'today_saving_toman': round(revenue / 10) if tariff else None,
        'month_energy_kwh': round(float(month_energy)),
        'chart': {
            'labels': labels,
            'production': production,
        },
        'inverters': equipment_payload,  # Changed from inverters to equipment
        'alerts': alerts_payload,
    }
    return JsonResponse(data)


def set_calendar(request):
    """Persist the user's calendar choice (jalali/gregorian) in the session."""
    calendar = request.POST.get('calendar') or request.GET.get('calendar')
    if calendar in ('jalali', 'gregorian'):
        request.session['calendar'] = calendar
    nxt = request.POST.get('next') or request.META.get('HTTP_REFERER') or '/'
    if not url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        nxt = '/'
    return redirect(nxt)


def reverse_geocode(request):
    """Turn a map pin into a Persian address, keeping the map.ir key server-side.

    The browser never sees the credential: it sends coordinates here and gets
    back an address. A lookup failure is not an error for the caller — the
    coordinates are what matter, the address is a convenience.

    Open to anonymous callers on purpose: the public evaluation form and the
    exhibition lead form both have a map and neither has a signed-in user. That
    makes this a free proxy to a metered third-party API, so it is rate limited
    per client — generous enough that dragging a pin never trips it.
    """
    client = request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip()         or request.META.get('REMOTE_ADDR', 'unknown')
    bucket = f'geocode:{client}'
    hits = cache.get(bucket, 0)
    if hits >= GEOCODE_RATE_PER_MINUTE:
        return JsonResponse({'ok': False, 'error': 'rate limited'}, status=429)
    # Not atomic, and it does not need to be: this throttles casual abuse, it is
    # not a quota ledger.
    cache.set(bucket, hits + 1, 60)

    try:
        lat = float(request.GET.get('lat', ''))
        lng = float(request.GET.get('lng', ''))
    except (TypeError, ValueError):
        return JsonResponse({'ok': False, 'error': 'bad coordinates'}, status=400)
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return JsonResponse({'ok': False, 'error': 'out of range'}, status=400)

    try:
        return JsonResponse({'ok': True, **geocoding.reverse(lat, lng)})
    except geocoding.GeocodingError as exc:
        return JsonResponse({'ok': False, 'error': str(exc)})


def csrf_failure(request, reason=''):
    """Render the Persian expiry page instead of Django's bare English 403.

    A CSRF failure here almost never means an attack: it means a form sat open
    past its token's life, or the app process restarted under it. Telling the
    visitor that, and giving them the button that fixes it, is the difference
    between a reload and a support call.
    """
    logger.info('CSRF failure on %s: %s', request.path, reason)
    return render(request, '403_csrf.html', status=403)


@cache_control(public=True, max_age=60 * 60 * 24 * 30)
def map_tile(request, z, x, y):
    """Serve one map tile from our own domain.

    The browser never contacts a tile service directly, so whichever of them is
    blocked from Iranian consumer networks this week stops mattering — only
    this server has to reach one of them. Tiles are immutable, so a fetched
    tile is written to disk and afterwards served from there.
    """
    z, x, y = int(z), int(x), int(y)
    if not (0 <= z <= 19 and 0 <= x < 2 ** z and 0 <= y < 2 ** z):
        return HttpResponseNotFound('bad tile')

    # A dark UI over a bright white map is the one combination that looks
    # broken, so the tile style follows the theme. The value is whitelisted
    # because it becomes part of a cache path.
    theme = request.GET.get('theme', '')
    if theme not in ('dark', 'light', 'satellite'):
        theme = ''
    # Satellite tiles are JPEGs; say so, so caches and browsers do not guess.
    cached_type = 'image/jpeg' if theme == 'satellite' else 'image/png'

    path = tiles.cached_tile_path(z, x, y, theme)
    if path.exists():
        return HttpResponse(path.read_bytes(), content_type=cached_type)

    body, content_type = tiles.fetch_tile(z, x, y, theme)
    if body is None:
        # A transparent 1x1 keeps the map usable (markers, zoom, the pin the
        # customer came to drop) instead of filling it with broken images.
        return HttpResponse(_BLANK_TILE, content_type='image/png')

    # When every satellite source is down the server falls back to a plain
    # street tile (PNG). Serve it, but never store it as a satellite tile, so
    # imagery returns by itself once a satellite source is back.
    if theme == 'satellite' and body[:2] != b'\xff\xd8':
        return HttpResponse(body, content_type=content_type)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    except OSError:
        logger.warning('Could not cache tile %s/%s/%s', z, x, y, exc_info=True)
    return HttpResponse(body, content_type=content_type)
