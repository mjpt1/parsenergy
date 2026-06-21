from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _
from django.views.generic import ListView, CreateView, UpdateView, DeleteView
from .models import Plant, PlantGroup, PlantGroupMembership, Inverter, Sensor, Meter, Equipment, Transformer, Gateway
from .forms import (
    PlantForm, PlantGroupForm, PlantGroupMembershipForm,
    InverterForm, SensorForm, MeterForm, EquipmentForm,
    TransformerForm, GatewayForm,
)


from apps.plants.scoping import plant_scope_for_user as _plant_scope_for_user


class PlantListView(LoginRequiredMixin, ListView):
    model = Plant
    template_name = 'plants/list.html'

    def get_queryset(self):
        user = self.request.user
        return _plant_scope_for_user(user).select_related('owner').order_by('-created_at')


class PlantCreateView(LoginRequiredMixin, CreateView):
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
        return super().form_valid(form)


class PlantUpdateView(LoginRequiredMixin, UpdateView):
    model = Plant
    form_class = PlantForm
    template_name = 'crud/form.html'
    success_url = reverse_lazy('plants:list')

    def get_queryset(self):
        return _plant_scope_for_user(self.request.user)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs


class PlantDeleteView(LoginRequiredMixin, DeleteView):
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


class InverterListView(LoginRequiredMixin, ListView):
    model = Inverter
    template_name = 'plants/list_inverter.html'

    def get_queryset(self):
        plants = _plant_scope_for_user(self.request.user)
        return Inverter.objects.select_related('plant').filter(plant__in=plants).order_by('-id')


class InverterCreateView(LoginRequiredMixin, CreateView):
    model = Inverter
    form_class = InverterForm
    template_name = 'crud/form.html'
    success_url = reverse_lazy('plants:inverters')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs


class InverterUpdateView(LoginRequiredMixin, UpdateView):
    model = Inverter
    form_class = InverterForm
    template_name = 'crud/form.html'
    success_url = reverse_lazy('plants:inverters')

    def get_queryset(self):
        plants = _plant_scope_for_user(self.request.user)
        return Inverter.objects.filter(plant__in=plants)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs


class InverterDeleteView(LoginRequiredMixin, DeleteView):
    model = Inverter
    template_name = 'crud/confirm_delete.html'
    success_url = reverse_lazy('plants:inverters')

    def get_queryset(self):
        plants = _plant_scope_for_user(self.request.user)
        return Inverter.objects.filter(plant__in=plants)


class SensorCreateView(LoginRequiredMixin, CreateView):
    model = Sensor
    form_class = SensorForm
    template_name = 'crud/form.html'
    success_url = reverse_lazy('plants:sensors')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs


class SensorListView(LoginRequiredMixin, ListView):
    model = Sensor
    template_name = 'plants/list_sensor.html'

    def get_queryset(self):
        plants = _plant_scope_for_user(self.request.user)
        return Sensor.objects.select_related('plant').filter(plant__in=plants).order_by('-id')


class SensorUpdateView(LoginRequiredMixin, UpdateView):
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


class SensorDeleteView(LoginRequiredMixin, DeleteView):
    model = Sensor
    template_name = 'crud/confirm_delete.html'
    success_url = reverse_lazy('plants:sensors')

    def get_queryset(self):
        plants = _plant_scope_for_user(self.request.user)
        return Sensor.objects.filter(plant__in=plants)


class MeterListView(LoginRequiredMixin, ListView):
    model = Meter
    template_name = 'plants/list_meter.html'

    def get_queryset(self):
        plants = _plant_scope_for_user(self.request.user)
        return Meter.objects.select_related('plant').filter(plant__in=plants).order_by('-id')


class MeterCreateView(LoginRequiredMixin, CreateView):
    model = Meter
    form_class = MeterForm
    template_name = 'crud/form.html'
    success_url = reverse_lazy('plants:meters')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs


class MeterUpdateView(LoginRequiredMixin, UpdateView):
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


class MeterDeleteView(LoginRequiredMixin, DeleteView):
    model = Meter
    template_name = 'crud/confirm_delete.html'
    success_url = reverse_lazy('plants:meters')

    def get_queryset(self):
        plants = _plant_scope_for_user(self.request.user)
        return Meter.objects.filter(plant__in=plants)


class EquipmentListView(LoginRequiredMixin, ListView):
    model = Equipment
    template_name = 'plants/list_equipment.html'

    def get_queryset(self):
        plants = _plant_scope_for_user(self.request.user)
        return Equipment.objects.select_related('plant').filter(plant__in=plants).order_by('-id')


class EquipmentCreateView(LoginRequiredMixin, CreateView):
    model = Equipment
    form_class = EquipmentForm
    template_name = 'crud/form.html'
    success_url = reverse_lazy('plants:equipment')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs


class EquipmentUpdateView(LoginRequiredMixin, UpdateView):
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


class EquipmentDeleteView(LoginRequiredMixin, DeleteView):
    model = Equipment
    template_name = 'crud/confirm_delete.html'
    success_url = reverse_lazy('plants:equipment')

    def get_queryset(self):
        plants = _plant_scope_for_user(self.request.user)
        return Equipment.objects.filter(plant__in=plants)


class TransformerListView(LoginRequiredMixin, ListView):
    model = Transformer
    template_name = 'plants/list_transformer.html'

    def get_queryset(self):
        plants = _plant_scope_for_user(self.request.user)
        return Transformer.objects.select_related('plant').filter(plant__in=plants).order_by('-id')


class TransformerCreateView(LoginRequiredMixin, CreateView):
    model = Transformer
    form_class = TransformerForm
    template_name = 'crud/form.html'
    success_url = reverse_lazy('plants:transformers')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs


class TransformerUpdateView(LoginRequiredMixin, UpdateView):
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


class TransformerDeleteView(LoginRequiredMixin, DeleteView):
    model = Transformer
    template_name = 'crud/confirm_delete.html'
    success_url = reverse_lazy('plants:transformers')

    def get_queryset(self):
        plants = _plant_scope_for_user(self.request.user)
        return Transformer.objects.filter(plant__in=plants)


class GatewayListView(LoginRequiredMixin, ListView):
    model = Gateway
    template_name = 'plants/list_gateway.html'

    def get_queryset(self):
        plants = _plant_scope_for_user(self.request.user)
        return Gateway.objects.select_related('plant').filter(plant__in=plants).order_by('-id')


class GatewayCreateView(LoginRequiredMixin, CreateView):
    model = Gateway
    form_class = GatewayForm
    template_name = 'crud/form.html'
    success_url = reverse_lazy('plants:gateways')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs


class GatewayUpdateView(LoginRequiredMixin, UpdateView):
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


class GatewayDeleteView(LoginRequiredMixin, DeleteView):
    model = Gateway
    template_name = 'crud/confirm_delete.html'
    success_url = reverse_lazy('plants:gateways')

    def get_queryset(self):
        plants = _plant_scope_for_user(self.request.user)
        return Gateway.objects.filter(plant__in=plants)
