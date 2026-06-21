from django import forms
from typing import Any, cast
from .models import AlertRule, Notification, AlertEvent


class AlertRuleForm(forms.ModelForm):
    class Meta:
        model = AlertRule
        fields = ['plant', 'name', 'metric', 'threshold_value', 'comparator', 'severity', 'channels', 'enabled']

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if user is not None and not (user.is_superuser or getattr(user, 'role', '') == 'admin'):
            plant_field = cast(Any, self.fields['plant'])
            plant_field.queryset = plant_field.queryset.filter(owner=user)


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
            rule_field.queryset = rule_field.queryset.filter(plant__owner=user)
