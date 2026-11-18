"""Helpers for plant geo-map points and PV module layout heat-maps."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Iterable

from django.db.models import Count, Q
from django.utils import timezone

from .models import Plant, PVModule, TelemetryReading


SECTION_LIVE_MAX_AGE = timedelta(minutes=30)   # the cloud sync runs every 5 minutes


def plant_map_points(plants: Iterable[Plant], *, telemetry_power=None) -> list[dict]:
    """Serialize plants with lat/lng for Leaflet fleet maps."""
    points = []
    for p in plants:
        if p.latitude is None or p.longitude is None:
            continue
        power = 0.0
        if telemetry_power and p.id in telemetry_power:
            power = float(telemetry_power[p.id] or 0)
        else:
            latest = p.telemetry.order_by('-created_at').first()
            power = float(latest.power_kw) if latest else 0.0
        alerts = getattr(p, '_alert_count', None)
        if alerts is None:
            from apps.alerts.models import AlertEvent
            alerts = AlertEvent.objects.filter(rule__plant=p, acknowledged=False).count()
        hot = getattr(p, '_hot_count', None)
        if hot is None:
            hot = p.modules.filter(status=PVModule.Status.HOT).count()
        points.append({
            'id': p.id,
            'name': p.name,
            'lat': float(p.latitude),
            'lng': float(p.longitude),
            'power': power,
            'online': p.connection_status == Plant.ConnectionStatus.ONLINE,
            'alerts': int(alerts or 0),
            'hot_cells': int(hot or 0),
            'location': p.location_name,
        })
    return points


def module_grid_payload(plant: Plant) -> dict:
    """JSON payload for the interactive cell/module heat-map UI."""
    sections = list(plant.sections.select_related('inverter').all())
    if sections:
        return section_grid_payload(plant, sections)
    modules = list(plant.modules.select_related('inverter').all())
    cells = []
    summary = {'total': 0, 'ok': 0, 'warn': 0, 'hot': 0, 'offline': 0, 'fault': 0}
    for m in modules:
        summary['total'] += 1
        summary[m.status] = summary.get(m.status, 0) + 1
        cells.append({
            'id': m.id,
            'row': m.row,
            'col': m.col,
            'code': m.code or f'C-R{m.row}-C{m.col}',
            'status': m.status,
            'temp': float(m.temperature_c),
            'power_pct': float(m.relative_power_pct),
            'string': m.string_code or '',
            'inverter': m.inverter.serial_number if m.inverter_id else '',
            'last_seen': m.last_seen_at.isoformat() if m.last_seen_at else None,
        })
    return {
        'plant_id': plant.id,
        'plant_name': plant.name,
        'rows': plant.layout_rows or 8,
        'cols': plant.layout_cols or 12,
        'cells': cells,
        'summary': summary,
    }


def _inverter_state(inverter, now):
    """(status, label, kW) for the panels on this inverter. Panels have no sensors
    of their own, so their state is the state of the inverter they feed."""
    if inverter is None:
        return 'pending', 'به پایش وصل نشده', None
    reading = TelemetryReading.objects.filter(inverter=inverter).order_by('-created_at').first()
    if inverter.status in ('fault', 'permanent_fault'):
        return 'fault', 'خطای اینورتر', None
    if inverter.last_sync_error or reading is None or now - reading.created_at > SECTION_LIVE_MAX_AGE:
        return 'offline', 'بدون دادهٔ تازه', None
    if inverter.online and reading.power_kw > 0:
        return 'ok', 'در حال تولید', reading.power_kw
    return 'idle', 'بدون تولید', reading.power_kw


def section_grid_payload(plant: Plant, sections) -> dict:
    """The panel layout as built: one entry per roof, coloured by its inverter."""
    now = timezone.now()
    summary = {'total': 0, 'ok': 0, 'warn': 0, 'hot': 0, 'offline': 0, 'fault': 0, 'idle': 0, 'pending': 0}
    panels_on_inverter = {}
    for section in sections:
        if section.inverter_id:
            panels_on_inverter[section.inverter_id] = (
                panels_on_inverter.get(section.inverter_id, 0) + section.panel_count)
    states = {}
    payload = []
    for section in sections:
        if section.inverter_id not in states:
            states[section.inverter_id] = _inverter_state(section.inverter, now)
        status, label, power = states[section.inverter_id]
        count = section.panel_count
        summary['total'] += count
        summary[status] += count
        average = None
        if power is not None and section.inverter_id:
            average = round(float(power) * 1000 / panels_on_inverter[section.inverter_id])
        payload.append({
            'name': section.name,
            'status': status,
            'status_label': label,
            'panels': count,
            'kwp': float(section.kwp),
            'panel_watt': float(section.panel_watt),
            'inverter': section.inverter.serial_number if section.inverter_id else '',
            'average_w': average,
            'tilt': section.tilt_text,
            'azimuth': float(section.azimuth_deg) if section.azimuth_deg is not None else None,
            'blocks': [{'cols': cols, 'rows': rows} for cols, rows in section.parsed_blocks],
        })
    return {
        'plant_id': plant.id,
        'plant_name': plant.name,
        'rows': plant.layout_rows or 8,
        'cols': plant.layout_cols or 12,
        'cells': [],
        'summary': summary,
        'sections': payload,
        'capacity_kw': float(plant.capacity_kw or 0),
        'connected_kw': float(plant.active_capacity_kw or 0),
    }


def annotate_module_counts(qs):
    return qs.annotate(
        _hot_count=Count('modules', filter=Q(modules__status=PVModule.Status.HOT), distinct=True),
        _warn_count=Count('modules', filter=Q(modules__status=PVModule.Status.WARN), distinct=True),
        _fault_count=Count('modules', filter=Q(modules__status=PVModule.Status.FAULT), distinct=True),
    )


def sync_module_grid(plant: Plant) -> tuple[int, int]:
    """Make the stored panels match the plant's declared layout.

    Creates the panels that are missing (in the honest "never reported" state)
    and removes the ones that now fall outside the grid — shrinking a layout
    from 8×12 to 4×6 would otherwise leave 72 orphan panels that still count
    towards the hot/warning totals on every dashboard.

    Returns ``(created, removed)`` so the caller can tell the operator exactly
    what changed; removal is destructive, so it should never be silent.
    """
    rows = max(1, min(int(plant.layout_rows or 8), 32))
    cols = max(1, min(int(plant.layout_cols or 12), 48))
    removed, _ = plant.modules.filter(
        Q(row__gt=rows) | Q(col__gt=cols)).delete()
    created = ensure_module_grid(plant)
    return created, removed


def ensure_module_grid(plant: Plant, *, seed_temperatures: bool = False) -> int:
    """Create missing modules for plant.layout_rows × layout_cols. Returns created count.

    By default the new modules are created in a "never reported" state
    (OFFLINE, no temperature/power, ``last_seen_at=None``) — a module only
    shows a temperature or a health status once real telemetry arrives for it.
    ``seed_temperatures=True`` fabricates a plausible mix of hot/warn/fault
    cells and exists solely for the demo seeder (``seed_demo``); never enable
    it on a customer's plant or the dashboard will report faults that aren't
    real.
    """
    rows = max(1, min(int(plant.layout_rows or 8), 32))
    cols = max(1, min(int(plant.layout_cols or 12), 48))
    plant.layout_rows = rows
    plant.layout_cols = cols
    plant.save(update_fields=['layout_rows', 'layout_cols', 'updated_at'])

    existing = {(m.row, m.col) for m in plant.modules.all()}
    inverters = list(plant.inverters.all())
    created = 0
    now = timezone.now()
    batch = []
    for r in range(1, rows + 1):
        for c in range(1, cols + 1):
            if (r, c) in existing:
                continue
            inv = inverters[(r - 1) % len(inverters)] if inverters else None
            string_code = f'S{((c - 1) % 4) + 1}'
            # Never-reported default: no telemetry has arrived for this module yet.
            temp = Decimal('0')
            status = PVModule.Status.OFFLINE
            power = Decimal('0')
            if seed_temperatures:
                n = (r * 17 + c * 13) % 47
                if n in (3, 11):
                    temp, status, power = Decimal('76'), PVModule.Status.HOT, Decimal('58')
                elif n in (7, 19, 23):
                    temp, status, power = Decimal('62'), PVModule.Status.WARN, Decimal('78')
                elif n == 29:
                    temp, status, power = Decimal('25'), PVModule.Status.OFFLINE, Decimal('0')
                elif n == 31:
                    temp, status, power = Decimal('40'), PVModule.Status.FAULT, Decimal('12')
                else:
                    temp = Decimal(40 + (n % 12))
            batch.append(PVModule(
                plant=plant,
                row=r,
                col=c,
                code=f'C-R{r}-C{c}',
                string_code=string_code,
                inverter=inv,
                status=status,
                temperature_c=temp,
                relative_power_pct=power,
                last_seen_at=now if seed_temperatures else None,
            ))
            created += 1
    if batch:
        PVModule.objects.bulk_create(batch, ignore_conflicts=True)
    return created
