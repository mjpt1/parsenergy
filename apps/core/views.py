from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.db.models import Avg, Count, Sum
from django.db.models.functions import TruncHour
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _

from apps.plants.models import (EnvironmentalReading, Equipment, Inverter, Plant,
                                PlantMembership, RealtimeMeasurement)
from apps.alerts.models import AlertEvent, Notification, AlertRule
from apps.core.models import (APIConnection, AuditLog, DatabaseBackup,
                              ProtocolAdapter, ServerHealthMetric)


from apps.plants.scoping import plant_scope_for_user as _plant_scope_for_user


@login_required
def dashboard_router(request):
    role = getattr(request.user, 'role', 'owner')
    template = 'dashboard/admin.html' if role == 'admin' else 'dashboard/owner.html'
    User = get_user_model()
    if role == 'admin':
        latest_health = ServerHealthMetric.objects.first()
        system_health_percent = None
        if latest_health:
            avg_usage = (float(latest_health.cpu_percent) + float(latest_health.memory_percent) + float(latest_health.disk_percent)) / 3
            system_health_percent = max(0, round(100 - avg_usage, 1))
        report_plant = Plant.objects.order_by('-created_at').first()
        context = {
            'title': 'داشبورد مدیریت',
            'plants_count': Plant.objects.count(),
            'inverters_count': Inverter.objects.count(),
            'equipment_online_count': Equipment.objects.filter(online=True).count(),
            'alerts_count': AlertEvent.objects.filter(acknowledged=False).count(),
            'users_count': User.objects.count(),
            'latest_health': latest_health,
            'system_health_percent': system_health_percent,
            'report_plant': report_plant,
            'latest_logs': AuditLog.objects.select_related('actor')[:10],
            'recent_plants': Plant.objects.select_related('owner').annotate(
                inverter_count=Count('inverters'),
                alert_count=Count('alert_rules', distinct=True),
            )[:6],
            'recent_health_metrics': ServerHealthMetric.objects.order_by('-checked_at')[:5],
            'active_backups': DatabaseBackup.objects.order_by('-created_at')[:5],
            'api_connections': APIConnection.objects.order_by('-id')[:5],
            'protocol_adapters': ProtocolAdapter.objects.order_by('-updated_at')[:5],
            'recent_alert_events': AlertEvent.objects.select_related('rule', 'rule__plant').order_by('-created_at')[:6],
        }
    else:
        plants = _plant_scope_for_user(request.user)
        latest_telemetry = RealtimeMeasurement.objects.filter(plant__in=plants, parameter='power').select_related('plant', 'equipment').order_by('-timestamp').first()
        context = {
            'title': 'داشبورد مالک',
            'plants': plants.select_related('owner').prefetch_related('inverters', 'sensors', 'meters', 'equipment'),
            'plant_count': plants.count(),
            'alerts_count': AlertEvent.objects.filter(rule__plant__in=plants, acknowledged=False).count(),
            'latest_telemetry': latest_telemetry,
            'report_plant': plants.order_by('-created_at').first(),
            'recent_alerts': AlertEvent.objects.filter(rule__plant__in=plants).select_related('rule', 'rule__plant').order_by('-created_at')[:8],
            'recent_notifications': Notification.objects.filter(user=request.user).order_by('-created_at')[:6],
            'recent_environmental': EnvironmentalReading.objects.filter(plant__in=plants).select_related('plant').order_by('-created_at')[:6],
            'recent_rules': AlertRule.objects.filter(plant__in=plants).select_related('plant').order_by('-id')[:6],
            'membership_count': PlantMembership.objects.filter(user=request.user, active=True).count(),
        }
    return render(request, template, {
        **context,
    })


def _build_chart_series_from_measurements(queryset, hours=12):
    def _query_series(start, end):
        return (
            queryset.filter(timestamp__gte=start, timestamp__lte=end)
            .annotate(hour=TruncHour('timestamp'))
            .values('hour')
            .annotate(avg_power=Avg('value'))
            .order_by('hour')
        )

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
        return HttpResponseForbidden('forbidden')

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
            timestamp__date=today
        ).aggregate(total=Sum('value')).get('total') or 0
    )
    
    efficiency = 0
    if total_capacity:
        efficiency = min(100, round((current_power / float(total_capacity)) * 100, 2))
    
    tariff_per_kwh = 1000  # Could be configurable
    revenue = float(today_energy) * tariff_per_kwh

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
