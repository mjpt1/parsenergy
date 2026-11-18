from django import forms
from typing import Any, cast
from apps.plants.forms import as_select
from apps.plants.scoping import plant_scope_for_user
from .models import AlertRule, Notification, AlertEvent

# The keys are what apps.monitoring.services passes to evaluate_alert_rules.
METRIC_CHOICES = [
    ('power_kw', 'توان (کیلووات)'), ('voltage_v', 'ولتاژ (ولت)'), ('current_a', 'جریان (آمپر)'),
    ('frequency_hz', 'فرکانس (هرتز)'), ('energy_kwh', 'انرژی (کیلووات‌ساعت)'),
]
COMPARATOR_CHOICES = [('>', 'بیشتر از'), ('>=', 'بیشتر یا مساوی'), ('<', 'کمتر از'),
                      ('<=', 'کمتر یا مساوی'), ('==', 'برابر با')]
SEVERITY_CHOICES = [('low', 'کم'), ('medium', 'متوسط'), ('high', 'زیاد'), ('critical', 'بحرانی')]


class AlertRuleForm(forms.ModelForm):
    channels = forms.MultipleChoiceField(
        label='روش اطلاع‌رسانی', required=True, choices=Notification.Channel.choices,
        widget=forms.CheckboxSelectMultiple)

    class Meta:
        model = AlertRule
        fields = ['plant', 'name', 'metric', 'comparator', 'threshold_value', 'severity', 'channels', 'enabled']

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        as_select(self, 'metric', METRIC_CHOICES)
        as_select(self, 'comparator', COMPARATOR_CHOICES)
        as_select(self, 'severity', SEVERITY_CHOICES)
        stored = self.instance.channels if self.instance.pk else AlertRule._meta.get_field('channels').default
        self.initial['channels'] = [c.strip() for c in stored.split(',') if c.strip()]
        if user is not None and not (user.is_superuser or getattr(user, 'role', '') == 'admin'):
            # Technical and operations staff work on customers' plants.
            cast(Any, self.fields['plant']).queryset = plant_scope_for_user(user)

    def clean_channels(self):
        return ','.join(self.cleaned_data['channels'])


class NotificationForm(forms.ModelForm):
    class Meta:
        model = Notification
        fields = ['user', 'channel', 'title', 'body', 'sent', 'delivery_status', 'provider_message_id', 'delivered_at']


class AlertEventForm(forms.ModelForm):
    class Meta:
        model = AlertEvent
        fields = ['rule', 'message', 'severity', 'acknowledged', 'acknowledged_by']

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if user is not None and not (user.is_superuser or getattr(user, 'role', '') == 'admin'):
            rule_field = cast(Any, self.fields['rule'])
            rule_field.queryset = rule_field.queryset.filter(plant__in=plant_scope_for_user(user))
