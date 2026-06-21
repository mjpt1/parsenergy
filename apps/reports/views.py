from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.db.models import Sum

from apps.alerts.models import AlertEvent
from apps.plants.models import TelemetryReading
from .services import build_pdf_report, build_excel_report


from apps.plants.scoping import plant_scope_for_user as _plant_scope_for_user


@login_required
def report_center(request):
    plants = _plant_scope_for_user(request.user)
    rows = [(plant.name, f'{plant.capacity_kw} kW') for plant in plants]
    return render(request, 'reports/index.html', {'plants': plants, 'rows': rows})


@login_required
def export_pdf(request, plant_id):
    plants = _plant_scope_for_user(request.user)
    plant = get_object_or_404(plants, id=plant_id)
    telemetry = TelemetryReading.objects.filter(plant=plant).aggregate(
        total_energy=Sum('energy_kwh'),
        total_power=Sum('power_kw'),
    )
    alerts_count = AlertEvent.objects.filter(rule__plant=plant, acknowledged=False).count()
    rows = [
        ('Name', plant.name),
        ('Capacity (kW)', str(plant.capacity_kw)),
        ('Location', plant.location_name),
        ('Status', plant.connection_status),
        ('Active Alerts', str(alerts_count)),
        ('Total Energy (kWh)', str(telemetry.get('total_energy') or 0)),
        ('Total Power (kW)', str(telemetry.get('total_power') or 0)),
    ]
    content = build_pdf_report(f'Report - {plant.name}', rows)
    response = HttpResponse(content, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{plant.name}.pdf"'
    return response


@login_required
def export_excel(request, plant_id):
    plants = _plant_scope_for_user(request.user)
    plant = get_object_or_404(plants, id=plant_id)
    telemetry = TelemetryReading.objects.filter(plant=plant).aggregate(
        total_energy=Sum('energy_kwh'),
        total_power=Sum('power_kw'),
    )
    alerts_count = AlertEvent.objects.filter(rule__plant=plant, acknowledged=False).count()
    rows = [
        ('Name', plant.name),
        ('Capacity (kW)', str(plant.capacity_kw)),
        ('Location', plant.location_name),
        ('Status', plant.connection_status),
        ('Active Alerts', str(alerts_count)),
        ('Total Energy (kWh)', str(telemetry.get('total_energy') or 0)),
        ('Total Power (kW)', str(telemetry.get('total_power') or 0)),
    ]
    content = build_excel_report(f'Report {plant.name}', rows)
    response = HttpResponse(content, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = f'attachment; filename="{plant.name}.xlsx"'
    return response
