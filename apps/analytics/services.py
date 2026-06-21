from dataclasses import dataclass
from django.db.models import Avg, Sum
from apps.plants.models import Plant, TelemetryReading


@dataclass
class EconomicResult:
    revenue: float
    roi: float
    profit: float
    forecast_revenue: float


def calculate_kpis(plant: Plant):
    readings = TelemetryReading.objects.filter(plant=plant)
    aggregates = readings.aggregate(
        total_power=Sum('power_kw'),
        total_energy=Sum('energy_kwh'),
        avg_voltage=Avg('voltage_v'),
        avg_current=Avg('current_a'),
    )
    return {
        'total_power': aggregates['total_power'] or 0,
        'total_energy': aggregates['total_energy'] or 0,
        'avg_voltage': aggregates['avg_voltage'] or 0,
        'avg_current': aggregates['avg_current'] or 0,
    }


def economic_analysis(plant: Plant, tariff_per_kwh: float = 1.0, cost: float = 0.0) -> EconomicResult:
    total_energy = float(TelemetryReading.objects.filter(plant=plant).aggregate(total=Sum('energy_kwh'))['total'] or 0)
    revenue = total_energy * tariff_per_kwh
    profit = revenue - cost
    roi = (profit / cost * 100.0) if cost else 0.0
    forecast_revenue = revenue * 1.08
    return EconomicResult(revenue=revenue, roi=roi, profit=profit, forecast_revenue=forecast_revenue)
