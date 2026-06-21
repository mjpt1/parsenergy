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

    base_url = _get_param('ai_base_url', '').strip()
    model = _get_param('ai_model', '').strip()
    api_key = _get_param('ai_api_key', '').strip()
    auth_header = _get_param('ai_auth_header', 'Authorization').strip() or 'Authorization'
    auth_prefix = _get_param('ai_auth_prefix', 'Bearer').strip()
    enabled = _get_param('ai_enabled', 'false') == 'true'
    system_prompt = _get_param('ai_system_prompt', '').strip()

    if not enabled or not base_url or not model or not api_key:
        return JsonResponse({'error': 'ai_not_configured'}, status=400)

    endpoint = base_url.rstrip('/')
    if not endpoint.endswith('/chat/completions'):
        endpoint = f"{endpoint}/chat/completions"

    if not system_prompt:
        system_prompt = 'شما تحلیلگر ارشد نیروگاه خورشیدی هستید. خروجی را خلاصه، دقیق و عملیاتی ارائه بده.'

    context = _build_ai_context(request.user)
    user_prompt = f"با توجه به داده‌های زیر، تحلیل عملکرد، ریسک‌ها و پیشنهادهای عملی ارائه بده:\n{json.dumps(context, ensure_ascii=False)}"

    payload = {
        'model': model,
        'messages': [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': user_prompt},
        ],
        'temperature': 0.3,
    }

    headers = {
        'Content-Type': 'application/json',
    }
    if api_key:
        auth_value = f"{auth_prefix} {api_key}".strip() if auth_prefix else api_key
        headers[auth_header] = auth_value

    try:
        req = url_request.Request(endpoint, data=json.dumps(payload).encode('utf-8'), headers=headers)
        with url_request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode('utf-8'))
        content = result.get('choices', [{}])[0].get('message', {}).get('content', '')
        return JsonResponse({'analysis': content or 'پاسخی دریافت نشد.'})
    except Exception as exc:
        return JsonResponse({'error': str(exc)}, status=500)
