from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib import messages
from django.db.models import OuterRef, Subquery, Sum
from apps.core.localtime import local_day, on_or_after
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.generic import ListView, CreateView, UpdateView, DeleteView, TemplateView
from apps.alerts.models import AlertEvent
from .models import Plant, PlantGroup, PlantGroupMembership, Inverter, Sensor, Meter, Equipment, Transformer, Gateway, PVModule, CloudAccount
from .models import TelemetryReading
from .forms import (
    PlantForm, PlantGroupForm, PlantGroupMembershipForm,
    InverterForm, SensorForm, MeterForm, EquipmentForm,
    TransformerForm, GatewayForm, CloudAccountForm,
)
from .layout import ensure_module_grid, module_grid_payload, plant_map_points, sync_module_grid


from apps.plants.scoping import plant_scope_for_user as _plant_scope_for_user


class PlantEditorRequiredMixin(UserPassesTestMixin):
    """Customers watch their plant; registering and changing it is staff work."""
    def test_func(self):
        return self.request.user.can_edit_plants


class PlantDashboardView(LoginRequiredMixin, TemplateView):
    """Technical monitoring dashboard: every plant's live production, faults,
    address, map location and module heat-map at a glance."""
    template_name = 'plants/dashboard.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        plants = (_plant_scope_for_user(self.request.user)
                  .select_related('owner').prefetch_related('inverters', 'modules').order_by('name'))
        rows, points, charts = [], [], []
        total_power = total_energy = total_cap = Decimal('0')
        online = total_alerts = hot_cells = 0
        since = timezone.now() - timedelta(days=14)
        selected_id = self.request.GET.get('plant')
        selected_plant = None
        for p in plants:
            latest = p.telemetry.order_by('-created_at').first()
            power = latest.power_kw if latest else Decimal('0')
            energy = latest.energy_kwh if latest else Decimal('0')
            tstatus = latest.status if latest else '—'
            invs = list(p.inverters.all())
            inv_online = sum(1 for i in invs if i.online)
            alerts = list(AlertEvent.objects.filter(rule__plant=p, acknowledged=False)
                          .select_related('rule').order_by('-created_at')[:6])
            alert_count = AlertEvent.objects.filter(rule__plant=p, acknowledged=False).count()
            module_hot = p.modules.filter(status=PVModule.Status.HOT).count()
            module_warn = p.modules.filter(status=PVModule.Status.WARN).count()
            is_online = (p.connection_status == Plant.ConnectionStatus.ONLINE)
            online += 1 if is_online else 0
            total_power += power or 0
            total_energy += energy or 0
            total_cap += p.capacity_kw or 0
            total_alerts += alert_count
            hot_cells += module_hot
            rows.append({
                'plant': p, 'power': power, 'energy': energy, 'tstatus': tstatus,
                'inv_total': len(invs), 'inv_online': inv_online,
                'alerts': alerts, 'alert_count': alert_count, 'is_online': is_online,
                'last_seen': latest.created_at if latest else None,
                'module_hot': module_hot, 'module_warn': module_warn,
                'module_total': p.modules.count(),
            })
            p._alert_count = alert_count
            p._hot_count = module_hot
            if selected_id and str(p.id) == str(selected_id):
                selected_plant = p
            # Daily production over the last 14 days (sum of energy per day).
            # Grouped in Python: TruncDate needs DB time-zone tables (apps.core.localtime).
            per_day = {}
            for ts, kwh in p.telemetry.filter(created_at__gte=since).values_list('created_at', 'energy_kwh'):
                day = local_day(ts)
                per_day[day] = per_day.get(day, 0.0) + float(kwh or 0)
            labels = [d.strftime('%m/%d') for d in sorted(per_day)]
            values = [per_day[d] for d in sorted(per_day)]
            rows[-1]['has_chart'] = bool(values)
            charts.append({'id': p.id, 'labels': labels, 'values': values})
        points = plant_map_points(plants)
        if selected_plant is None and plants:
            selected_plant = plants[0]
        module_payload = None
        if selected_plant is not None:
            # Read-only: never scaffold modules from a dashboard page view — an
            # empty grid means the plant genuinely has no modules registered.
            module_payload = module_grid_payload(selected_plant)
        ctx.update({
            'page_title': 'داشبورد فنی نیروگاه‌ها',
            'rows': rows, 'map_points': points, 'chart_data': charts,
            'plant_count': len(rows), 'online': online, 'offline': len(rows) - online,
            'total_power': total_power, 'total_energy': total_energy,
            'total_cap': total_cap, 'total_alerts': total_alerts,
            'hot_cells': hot_cells,
            'selected_plant': selected_plant,
            'module_grid': module_payload,
        })
        return ctx


class PlantListView(LoginRequiredMixin, ListView):
    model = Plant
    template_name = 'plants/list.html'

    def get_queryset(self):
        user = self.request.user
        return _plant_scope_for_user(user).select_related('owner').order_by('-created_at')


class PlantCreateView(LoginRequiredMixin, PlantEditorRequiredMixin, CreateView):
    model = Plant
    form_class = PlantForm
    template_name = 'crud/form.html'
    success_url = reverse_lazy('plants:list')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        if not form.instance.owner_id:
            form.instance.owner = self.request.user
        messages.success(self.request, _('نیروگاه با موفقیت ایجاد شد.'))
        response = super().form_valid(form)
        ensure_module_grid(self.object)
        return response


class PlantUpdateView(LoginRequiredMixin, PlantEditorRequiredMixin, UpdateView):
    model = Plant
    form_class = PlantForm
    template_name = 'plants/plant_form.html'
    success_url = reverse_lazy('plants:list')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['inverters'] = self.object.inverters.order_by('id')
        return ctx

    def get_queryset(self):
        return _plant_scope_for_user(self.request.user)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        """Keep the panel layout in step with the row/column figures.

        A plant commissioned from a request starts with no panels at all, and
        editing the layout previously did nothing to them — so the schematic
        stayed empty however the technical team filled the form in. Syncing
        here is the moment the operator states the real size of the array.
        """
        response = super().form_valid(form)
        created, removed = sync_module_grid(self.object)
        if created or removed:
            parts = []
            if created:
                parts.append(_('%(n)s پنل جدید ثبت شد') % {'n': created})
            if removed:
                parts.append(_('%(n)s پنل خارج از چیدمان حذف شد') % {'n': removed})
            messages.info(self.request, ' · '.join(str(p) for p in parts))
        return response


class PlantDeleteView(LoginRequiredMixin, PlantEditorRequiredMixin, DeleteView):
    model = Plant
    template_name = 'crud/confirm_delete.html'
    success_url = reverse_lazy('plants:list')

    def get_queryset(self):
        return _plant_scope_for_user(self.request.user)


class PlantGroupListView(LoginRequiredMixin, ListView):
    model = PlantGroup
    template_name = 'plants/groups_list.html'

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser or getattr(user, 'role', '') == 'admin':
            return PlantGroup.objects.select_related('owner').order_by('-created_at')
        return PlantGroup.objects.filter(owner=user).order_by('-created_at')


class PlantGroupCreateView(LoginRequiredMixin, CreateView):
    model = PlantGroup
    form_class = PlantGroupForm
    template_name = 'crud/form.html'
    success_url = reverse_lazy('plants:groups')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        if not form.instance.owner_id:
            form.instance.owner = self.request.user
        messages.success(self.request, _('گروه نیروگاه با موفقیت ایجاد شد.'))
        return super().form_valid(form)


class PlantGroupUpdateView(LoginRequiredMixin, UpdateView):
    model = PlantGroup
    form_class = PlantGroupForm
    template_name = 'crud/form.html'
    success_url = reverse_lazy('plants:groups')

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser or getattr(user, 'role', '') == 'admin':
            return PlantGroup.objects.all()
        return PlantGroup.objects.filter(owner=user)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs


class PlantGroupDeleteView(LoginRequiredMixin, DeleteView):
    model = PlantGroup
    template_name = 'crud/confirm_delete.html'
    success_url = reverse_lazy('plants:groups')

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser or getattr(user, 'role', '') == 'admin':
            return PlantGroup.objects.all()
        return PlantGroup.objects.filter(owner=user)


class PlantGroupMembershipView(LoginRequiredMixin, CreateView):
    model = PlantGroupMembership
    form_class = PlantGroupMembershipForm
    template_name = 'plants/group_membership.html'
    success_url = reverse_lazy('plants:groups')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs


LIVE_DATA_MAX_AGE = timedelta(minutes=30)   # the cloud sync runs every 5 minutes


def _live_state(inverter, now):
    """(css tone, label) for how this inverter is reporting right now."""
    if inverter.last_sync_error:
        return 'danger', _('خطا در دریافت')
    if inverter.live_at is None:
        return '', _('بدون داده')
    if now - inverter.live_at > LIVE_DATA_MAX_AGE:
        return 'warning', _('داده قدیمی')
    return ('success', _('متصل')) if inverter.online else ('danger', _('قطع'))


class InverterListView(LoginRequiredMixin, ListView):
    model = Inverter
    template_name = 'plants/list_inverter.html'

    def get_queryset(self):
        plants = _plant_scope_for_user(self.request.user)
        latest = TelemetryReading.objects.filter(inverter=OuterRef('pk')).order_by('-created_at')
        return (Inverter.objects.select_related('plant').filter(plant__in=plants)
                .annotate(live_power=Subquery(latest.values('power_kw')[:1]),
                          live_at=Subquery(latest.values('created_at')[:1]))
                .order_by('-id'))

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        inverters = list(ctx['object_list'])
        today = dict(
            TelemetryReading.objects
            .filter(inverter__in=inverters, **on_or_after('created_at', timezone.localdate()))
            .order_by().values_list('inverter').annotate(total=Sum('energy_kwh')))
        now = timezone.now()
        for inverter in inverters:
            inverter.state_tone, inverter.state_label = _live_state(inverter, now)
            inverter.is_fresh = inverter.state_tone in ('success', 'danger') and inverter.live_at is not None \
                and now - inverter.live_at <= LIVE_DATA_MAX_AGE
            inverter.today_kwh = today.get(inverter.pk)
        ctx['object_list'] = inverters
        ctx['can_manage_cloud'] = _can_manage_cloud(self.request.user)
        return ctx



INVERTER_SECTIONS = [
    ('مشخصات اینورتر', 'شماره سریال باید دقیقاً با پنل سازنده یکی باشد.',
     ['plant', 'serial_number', 'model_name', 'manufacturer', 'rated_power_kw', 'firmware_version']),
    ('اتصال به داده‌های زنده', 'با اتصال به سولاکس، توان، تولید و وضعیت خودکار در داشبورد و گزارش‌ها می‌آید.',
     ['data_source', 'cloud_account', 'registration_no']),
    ('وضعیت', '', ['status', 'online']),
]


class InverterFormContextMixin:
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['sections'] = INVERTER_SECTIONS
        ctx['can_manage_cloud'] = _can_manage_cloud(self.request.user)
        return ctx


class InverterCreateView(InverterFormContextMixin, LoginRequiredMixin, PlantEditorRequiredMixin, CreateView):
    model = Inverter
    form_class = InverterForm
    template_name = 'plants/inverter_form.html'
    success_url = reverse_lazy('plants:inverters')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def get_initial(self):
        # Opened from a plant's page: that plant is already chosen.
        return {**super().get_initial(), 'plant': self.request.GET.get('plant')}

    def get_success_url(self):
        # Back to the plant being set up, so the next inverter is one click away.
        if self.request.GET.get('plant'):
            return reverse('plants:edit', args=[self.object.plant_id])
        return super().get_success_url()


class InverterUpdateView(InverterFormContextMixin, LoginRequiredMixin, PlantEditorRequiredMixin, UpdateView):
    model = Inverter
    form_class = InverterForm
    template_name = 'plants/inverter_form.html'
    success_url = reverse_lazy('plants:inverters')

    def get_queryset(self):
        plants = _plant_scope_for_user(self.request.user)
        return Inverter.objects.filter(plant__in=plants)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def get_success_url(self):
        if self.request.GET.get('plant'):
            return reverse('plants:edit', args=[self.object.plant_id])
        return super().get_success_url()


def _can_manage_cloud(user):
    return user.is_superuser or getattr(user, 'role', '') in ('admin', 'technical', 'operations')


class CloudAccessMixin(LoginRequiredMixin):
    """Cloud API accounts are for admins, the technical team and operations."""
    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not _can_manage_cloud(request.user):
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


class CloudAccountListView(CloudAccessMixin, ListView):
    model = CloudAccount
    template_name = 'plants/cloud_accounts.html'

    def get_queryset(self):
        from django.db.models import Count
        return CloudAccount.objects.annotate(n=Count('inverters')).order_by('name')


class CloudAccountCreateView(CloudAccessMixin, CreateView):
    model = CloudAccount
    form_class = CloudAccountForm
    template_name = 'crud/form.html'
    success_url = reverse_lazy('plants:cloud-accounts')


class CloudAccountUpdateView(CloudAccessMixin, UpdateView):
    model = CloudAccount
    form_class = CloudAccountForm
    template_name = 'crud/form.html'
    success_url = reverse_lazy('plants:cloud-accounts')


def inverter_sync_now(request, pk):
    """Read this inverter from its cloud now and say what came back."""
    from django.shortcuts import get_object_or_404, redirect
    from . import solax
    if request.method != 'POST' or not request.user.is_authenticated or not _can_manage_cloud(request.user):
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied
    inv = get_object_or_404(Inverter.objects.select_related('cloud_account', 'plant'), pk=pk)
    back = redirect(reverse('plants:inverter-edit', args=[pk]))
    if inv.data_source != Inverter.DataSource.SOLAX or not inv.cloud_account:
        messages.error(request, _('منبع داده را «SolaX Cloud» بگذارید و حساب ابری را انتخاب کنید.'))
        return back
    try:
        row = solax.fetch_realtime(inv.cloud_account, [inv.serial_number]).get(inv.serial_number.upper())
    except solax.SolaxError as exc:
        inv.last_sync_error = str(exc)[:500]
        inv.save(update_fields=['last_sync_error'])
        messages.error(request, str(exc))
        return back
    if row is None:
        inv.last_sync_error = 'این شماره سریال در حساب سولاکس پیدا نشد.'
        inv.save(update_fields=['last_sync_error'])
        messages.error(request, inv.last_sync_error)
        return back
    solax.store_reading(inv, row)
    messages.success(request, _('اتصال برقرار است. توان فعلی %(p)s کیلووات، تولید امروز %(d)s کیلووات‌ساعت.') % {
        'p': round(float(solax.total_kw(row, inv.rated_power_kw)), 2), 'd': row.get('dailyyield', 0)})
    return back


class InverterDeleteView(LoginRequiredMixin, PlantEditorRequiredMixin, DeleteView):
    model = Inverter
    template_name = 'crud/confirm_delete.html'
    success_url = reverse_lazy('plants:inverters')

    def get_queryset(self):
        plants = _plant_scope_for_user(self.request.user)
        return Inverter.objects.filter(plant__in=plants)


class SensorCreateView(LoginRequiredMixin, PlantEditorRequiredMixin, CreateView):
    model = Sensor
    form_class = SensorForm
    template_name = 'crud/form.html'
    success_url = reverse_lazy('plants:sensors')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs


class SensorListView(LoginRequiredMixin, PlantEditorRequiredMixin, ListView):
    model = Sensor
    template_name = 'plants/list_sensor.html'

    def get_queryset(self):
        plants = _plant_scope_for_user(self.request.user)
        return Sensor.objects.select_related('plant').filter(plant__in=plants).order_by('-id')


class SensorUpdateView(LoginRequiredMixin, PlantEditorRequiredMixin, UpdateView):
    model = Sensor
    form_class = SensorForm
    template_name = 'crud/form.html'
    success_url = reverse_lazy('plants:sensors')

    def get_queryset(self):
        plants = _plant_scope_for_user(self.request.user)
        return Sensor.objects.filter(plant__in=plants)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs


class SensorDeleteView(LoginRequiredMixin, PlantEditorRequiredMixin, DeleteView):
    model = Sensor
    template_name = 'crud/confirm_delete.html'
    success_url = reverse_lazy('plants:sensors')

    def get_queryset(self):
        plants = _plant_scope_for_user(self.request.user)
        return Sensor.objects.filter(plant__in=plants)


class MeterListView(LoginRequiredMixin, PlantEditorRequiredMixin, ListView):
    model = Meter
    template_name = 'plants/list_meter.html'

    def get_queryset(self):
        plants = _plant_scope_for_user(self.request.user)
        return Meter.objects.select_related('plant').filter(plant__in=plants).order_by('-id')


class MeterCreateView(LoginRequiredMixin, PlantEditorRequiredMixin, CreateView):
    model = Meter
    form_class = MeterForm
    template_name = 'crud/form.html'
    success_url = reverse_lazy('plants:meters')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs


class MeterUpdateView(LoginRequiredMixin, PlantEditorRequiredMixin, UpdateView):
    model = Meter
    form_class = MeterForm
    template_name = 'crud/form.html'
    success_url = reverse_lazy('plants:meters')

    def get_queryset(self):
        plants = _plant_scope_for_user(self.request.user)
        return Meter.objects.filter(plant__in=plants)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs


class MeterDeleteView(LoginRequiredMixin, PlantEditorRequiredMixin, DeleteView):
    model = Meter
    template_name = 'crud/confirm_delete.html'
    success_url = reverse_lazy('plants:meters')

    def get_queryset(self):
        plants = _plant_scope_for_user(self.request.user)
        return Meter.objects.filter(plant__in=plants)


class EquipmentListView(LoginRequiredMixin, PlantEditorRequiredMixin, ListView):
    model = Equipment
    template_name = 'plants/list_equipment.html'

    def get_queryset(self):
        plants = _plant_scope_for_user(self.request.user)
        return Equipment.objects.select_related('plant').filter(plant__in=plants).order_by('-id')


class EquipmentCreateView(LoginRequiredMixin, PlantEditorRequiredMixin, CreateView):
    model = Equipment
    form_class = EquipmentForm
    template_name = 'crud/form.html'
    success_url = reverse_lazy('plants:equipment')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs


class EquipmentUpdateView(LoginRequiredMixin, PlantEditorRequiredMixin, UpdateView):
    model = Equipment
    form_class = EquipmentForm
    template_name = 'crud/form.html'
    success_url = reverse_lazy('plants:equipment')

    def get_queryset(self):
        plants = _plant_scope_for_user(self.request.user)
        return Equipment.objects.filter(plant__in=plants)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs


class EquipmentDeleteView(LoginRequiredMixin, PlantEditorRequiredMixin, DeleteView):
    model = Equipment
    template_name = 'crud/confirm_delete.html'
    success_url = reverse_lazy('plants:equipment')

    def get_queryset(self):
        plants = _plant_scope_for_user(self.request.user)
        return Equipment.objects.filter(plant__in=plants)


class TransformerListView(LoginRequiredMixin, PlantEditorRequiredMixin, ListView):
    model = Transformer
    template_name = 'plants/list_transformer.html'

    def get_queryset(self):
        plants = _plant_scope_for_user(self.request.user)
        return Transformer.objects.select_related('plant').filter(plant__in=plants).order_by('-id')


class TransformerCreateView(LoginRequiredMixin, PlantEditorRequiredMixin, CreateView):
    model = Transformer
    form_class = TransformerForm
    template_name = 'crud/form.html'
    success_url = reverse_lazy('plants:transformers')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs


class TransformerUpdateView(LoginRequiredMixin, PlantEditorRequiredMixin, UpdateView):
    model = Transformer
    form_class = TransformerForm
    template_name = 'crud/form.html'
    success_url = reverse_lazy('plants:transformers')

    def get_queryset(self):
        plants = _plant_scope_for_user(self.request.user)
        return Transformer.objects.filter(plant__in=plants)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs


class TransformerDeleteView(LoginRequiredMixin, PlantEditorRequiredMixin, DeleteView):
    model = Transformer
    template_name = 'crud/confirm_delete.html'
    success_url = reverse_lazy('plants:transformers')

    def get_queryset(self):
        plants = _plant_scope_for_user(self.request.user)
        return Transformer.objects.filter(plant__in=plants)


class GatewayListView(LoginRequiredMixin, PlantEditorRequiredMixin, ListView):
    model = Gateway
    template_name = 'plants/list_gateway.html'

    def get_queryset(self):
        plants = _plant_scope_for_user(self.request.user)
        return Gateway.objects.select_related('plant').filter(plant__in=plants).order_by('-id')


class GatewayCreateView(LoginRequiredMixin, PlantEditorRequiredMixin, CreateView):
    model = Gateway
    form_class = GatewayForm
    template_name = 'crud/form.html'
    success_url = reverse_lazy('plants:gateways')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs


class GatewayUpdateView(LoginRequiredMixin, PlantEditorRequiredMixin, UpdateView):
    model = Gateway
    form_class = GatewayForm
    template_name = 'crud/form.html'
    success_url = reverse_lazy('plants:gateways')

    def get_queryset(self):
        plants = _plant_scope_for_user(self.request.user)
        return Gateway.objects.filter(plant__in=plants)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs


class GatewayDeleteView(LoginRequiredMixin, PlantEditorRequiredMixin, DeleteView):
    model = Gateway
    template_name = 'crud/confirm_delete.html'
    success_url = reverse_lazy('plants:gateways')

    def get_queryset(self):
        plants = _plant_scope_for_user(self.request.user)
        return Gateway.objects.filter(plant__in=plants)
