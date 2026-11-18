from django.db.models import Avg, Sum
from .models import Plant, TelemetryReading


def plant_kpi(plant: Plant):
    latest = TelemetryReading.objects.filter(plant=plant).order_by('-created_at').first()
    daily_energy = TelemetryReading.objects.filter(plant=plant).aggregate(total=Sum('power_kw'))['total'] or 0
    avg_power = TelemetryReading.objects.filter(plant=plant).aggregate(avg=Avg('power_kw'))['avg'] or 0
    return {
        'latest': latest,
        'daily_energy': daily_energy,
        'avg_power': avg_power,
    }
