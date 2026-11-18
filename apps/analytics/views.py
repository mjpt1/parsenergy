import json
from urllib import request as url_request

from django.contrib.auth.decorators import login_required
from django.db.models import Avg, Sum
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone

from apps.alerts.models import AlertEvent
from apps.core.models import SystemParameter
from apps.plants.models import Inverter, TelemetryReading
from .services import calculate_kpis, economic_analysis


@login_required
def analytics_dashboard(request, plant_id=None):
    plants = _plant_scope_for_user(request.user)
    plant = None
    if plant_id is not None:
        plant = plants.filter(id=plant_id).first()
    if plant is None:
        plant = plants.first()
    context = {'plant': plant, 'kpis': {}, 'economics': None, 'comparison': {}, 'forecast': {}}
    if plant:
        kpis = calculate_kpis(plant)
        economics = economic_analysis(plant, tariff_per_kwh=1.0, cost=1000.0)
        context['kpis'] = kpis
        context['economics'] = {
            'revenue': economics.revenue,
            'roi': economics.roi,
            'profit': economics.profit,
            'forecast_revenue': economics.forecast_revenue,
        }
        context['comparison'] = {
            'plant_capacity': plant.capacity_kw,
            'peer_index': 0.92,
        }
        context['forecast'] = {
            'next_day_production_kwh': float(kpis['total_power']) * 1.05 if kpis.get('total_power') else 0,
        }
    return render(request, 'dashboard/analytics.html', context)


def _get_param(key, default=''):
    param = SystemParameter.objects.filter(key=key).first()
    return param.value if param else default


from apps.plants.scoping import plant_scope_for_user as _plant_scope_for_user


def _build_ai_context(user):
    plants = _plant_scope_for_user(user)
    telemetry = TelemetryReading.objects.filter(plant__in=plants)
    last_reading = telemetry.order_by('-created_at').first()
    aggregates = telemetry.aggregate(
        total_power_sum=Sum('power_kw'),
        total_energy_sum=Sum('energy_kwh'),
        avg_voltage=Avg('voltage_v'),
        avg_frequency=Avg('frequency_hz'),
    )
    alerts_active = AlertEvent.objects.filter(rule__plant__in=plants, acknowledged=False).count()
    recent_alerts = list(
        AlertEvent.objects.filter(rule__plant__in=plants)
        .select_related('rule')
        .order_by('-created_at')[:5]
        .values('rule__name', 'message', 'severity')
    )
    return {
        'timestamp': timezone.now().isoformat(),
        'plants_count': plants.count(),
        'inverters_count': Inverter.objects.filter(plant__in=plants).count(),
        'alerts_active': alerts_active,
        'telemetry': {
            'total_power_sum': float(aggregates.get('total_power_sum') or 0),
            'total_energy_sum': float(aggregates.get('total_energy_sum') or 0),
            'avg_voltage': float(aggregates.get('avg_voltage') or 0),
            'avg_frequency': float(aggregates.get('avg_frequency') or 0),
            'last_power_kw': float(last_reading.power_kw) if last_reading else 0,
            'last_voltage_v': float(last_reading.voltage_v) if last_reading else 0,
            'last_frequency_hz': float(last_reading.frequency_hz) if last_reading else 0,
        },
        'recent_alerts': recent_alerts,
    }


@login_required
def ai_analysis(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'invalid_method'}, status=405)

    from apps.core import ai, ai_limits
    if not ai.is_available():
        return JsonResponse({'error': 'ai_not_configured'}, status=400)
    blocked = ai_limits.check(request.user, 'plant')
    if blocked:
        return JsonResponse({'error': blocked}, status=403)
    system_prompt = _get_param('ai_system_prompt', '').strip()
    if not system_prompt:
        system_prompt = 'شما تحلیلگر ارشد نیروگاه خورشیدی هستید. خروجی را خلاصه، دقیق و عملیاتی ارائه بده.'

    context = _build_ai_context(request.user)
    user_prompt = f"با توجه به داده‌های زیر، تحلیل عملکرد، ریسک‌ها و پیشنهادهای عملی ارائه بده:\n{json.dumps(context, ensure_ascii=False)}"

    try:
        result = ai.ask(system_prompt, user_prompt)
        ai_limits.consume(request.user, 'plant')
        return JsonResponse({'analysis': result.text, 'provider': result.provider})
    except ai.AIError as exc:
        return JsonResponse({'error': str(exc)}, status=502)
