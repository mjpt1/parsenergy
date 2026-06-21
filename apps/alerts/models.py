from django.conf import settings
from django.db import models


class AlertRule(models.Model):
    plant = models.ForeignKey('plants.Plant', on_delete=models.CASCADE, related_name='alert_rules')
    name = models.CharField(max_length=255)
    metric = models.CharField(max_length=64)
    threshold_value = models.DecimalField(max_digits=12, decimal_places=3)
    comparator = models.CharField(max_length=8, default='>')
    severity = models.CharField(max_length=16, default='medium')
    channels = models.CharField(max_length=64, default='email,sms,push')
    enabled = models.BooleanField(default=True)


class AlertEvent(models.Model):
    rule = models.ForeignKey(AlertRule, on_delete=models.CASCADE, related_name='events')
    message = models.TextField()
    severity = models.CharField(max_length=16, default='medium')
    acknowledged = models.BooleanField(default=False)
    acknowledged_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)


class Notification(models.Model):
    class Channel(models.TextChoices):
        EMAIL = 'email', 'Email'
        SMS = 'sms', 'SMS'
        PUSH = 'push', 'Push'

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notifications')
    channel = models.CharField(max_length=16, choices=Channel.choices)
    title = models.CharField(max_length=255)
    body = models.TextField()
    sent = models.BooleanField(default=False)
    delivery_status = models.CharField(max_length=16, default='pending')
    provider_message_id = models.CharField(max_length=128, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
