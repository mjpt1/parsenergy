from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import ListView, CreateView, UpdateView, DeleteView
from django.urls import reverse_lazy
from django.contrib import messages
from django.utils.translation import gettext_lazy as _
from .models import AlertRule, AlertEvent, Notification
from .forms import AlertRuleForm


from apps.plants.scoping import plant_scope_for_user as _plant_scope_for_user


class AlertRuleListView(LoginRequiredMixin, ListView):
    model = AlertRule
    template_name = 'alerts/list.html'

    def get_queryset(self):
        plants = _plant_scope_for_user(self.request.user)
        return AlertRule.objects.select_related('plant').filter(plant__in=plants).order_by('-id')


class AlertRuleCreateView(LoginRequiredMixin, CreateView):
    model = AlertRule
    form_class = AlertRuleForm
    template_name = 'crud/form.html'
    success_url = reverse_lazy('alerts:list')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        messages.success(self.request, _('قانون هشدار با موفقیت ایجاد شد.'))
        return super().form_valid(form)


class AlertRuleUpdateView(LoginRequiredMixin, UpdateView):
    model = AlertRule
    form_class = AlertRuleForm
    template_name = 'crud/form.html'
    success_url = reverse_lazy('alerts:list')

    def get_queryset(self):
        plants = _plant_scope_for_user(self.request.user)
        return AlertRule.objects.filter(plant__in=plants)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs


class AlertRuleDeleteView(LoginRequiredMixin, DeleteView):
    model = AlertRule
    template_name = 'crud/confirm_delete.html'
    success_url = reverse_lazy('alerts:list')

    def get_queryset(self):
        plants = _plant_scope_for_user(self.request.user)
        return AlertRule.objects.filter(plant__in=plants)


class AlertEventListView(LoginRequiredMixin, ListView):
    model = AlertEvent
    template_name = 'alerts/events.html'

    def get_queryset(self):
        plants = _plant_scope_for_user(self.request.user)
        return AlertEvent.objects.select_related('rule', 'rule__plant').filter(rule__plant__in=plants).order_by('-created_at')


class NotificationListView(LoginRequiredMixin, ListView):
    model = Notification
    template_name = 'alerts/notifications.html'

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser or getattr(user, 'role', '') == 'admin':
            return Notification.objects.select_related('user').all().order_by('-created_at')
        return Notification.objects.filter(user=user).order_by('-created_at')
