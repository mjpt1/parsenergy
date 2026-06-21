import logging

from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from django.utils import timezone
from apps.plants.models import Plant, Inverter, TelemetryReading, EnvironmentalReading
from apps.alerts.services import evaluate_alert_rules
from apps.core.services import write_audit_log
from typing import Optional

logger = logging.getLogger(__name__)


def broadcast_telemetry(payload: dict):
    """Push a telemetry update to the plant's WebSocket group.

    This is a best-effort realtime notification: if the channel layer is
    unavailable (e.g. Redis is down) it must not break telemetry ingestion,
    so failures are logged and swallowed.
    """
    plant_id = payload.get('plant_id')
    if plant_id is None:
        return
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return
    try:
        async_to_sync(channel_layer.group_send)(
            f'telemetry_plant_{plant_id}',
            {'type': 'telemetry.update', 'data': payload},
        )
    except Exception:
        logger.warning('Telemetry broadcast failed; channel layer unavailable', exc_info=True)


def ingest_telemetry(*, plant: Plant, inverter: Optional[Inverter], payload: dict, actor=None):
    telemetry = TelemetryReading.objects.create(
        plant=plant,
        inverter=inverter,
        power_kw=payload.get('power_kw', 0),
        voltage_v=payload.get('voltage_v', 0),
        current_a=payload.get('current_a', 0),
        frequency_hz=payload.get('frequency_hz', 0),
        energy_kwh=payload.get('energy_kwh', 0),
        status=payload.get('status', 'normal'),
    )

    if payload.get('temperature_c') is not None and payload.get('irradiance_wm2') is not None:
        EnvironmentalReading.objects.create(
            plant=plant,
            temperature_c=payload.get('temperature_c', 0),
            irradiance_wm2=payload.get('irradiance_wm2', 0),
        )

    event_payload = {
        'plant_id': plant.id,
        'inverter_id': inverter.id if inverter else None,
        'power_kw': float(telemetry.power_kw),
        'voltage_v': float(telemetry.voltage_v),
        'current_a': float(telemetry.current_a),
        'frequency_hz': float(telemetry.frequency_hz),
        'energy_kwh': float(telemetry.energy_kwh),
        'status': telemetry.status,
        'timestamp': timezone.now().isoformat(),
    }
    broadcast_telemetry(event_payload)

    triggered_events = evaluate_alert_rules(
        plant=plant,
        metric_values={
            'power_kw': event_payload['power_kw'],
            'voltage_v': event_payload['voltage_v'],
            'current_a': event_payload['current_a'],
            'frequency_hz': event_payload['frequency_hz'],
            'energy_kwh': event_payload['energy_kwh'],
        },
    )

    write_audit_log(
        actor=actor,
        action='telemetry.ingested',
        target_type='plant',
        target_id=str(plant.id),
        metadata={'payload': event_payload, 'alerts': len(triggered_events)},
    )

    return telemetry, triggered_events
