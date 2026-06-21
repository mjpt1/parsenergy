from django.conf import settings
from django.db import models


class SystemParameter(models.Model):
    key = models.CharField(max_length=128, unique=True)
    value = models.TextField()
    description = models.CharField(max_length=255, blank=True)
    is_secret = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.key


class SecuritySetting(models.Model):
    require_mfa = models.BooleanField(default=True)
    session_timeout_minutes = models.PositiveIntegerField(default=30)
    password_rotation_days = models.PositiveIntegerField(default=90)
    lockout_threshold = models.PositiveIntegerField(default=5)
    ip_allowlist = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)


class AuditLog(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=128)
    target_type = models.CharField(max_length=128)
    target_id = models.CharField(max_length=64, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-created_at',)


class ServerHealthMetric(models.Model):
    hostname = models.CharField(max_length=255)
    cpu_percent = models.DecimalField(max_digits=5, decimal_places=2)
    memory_percent = models.DecimalField(max_digits=5, decimal_places=2)
    disk_percent = models.DecimalField(max_digits=5, decimal_places=2)
    queue_depth = models.PositiveIntegerField(default=0)
    checked_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-checked_at',)


class DatabaseBackup(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        SUCCESS = 'success', 'Success'
        FAILED = 'failed', 'Failed'

    file_path = models.CharField(max_length=1024)
    file_size_bytes = models.BigIntegerField(default=0)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class APIConnection(models.Model):
    class AuthType(models.TextChoices):
        NONE = 'none', 'None'
        TOKEN = 'token', 'Token'
        BASIC = 'basic', 'Basic'

    name = models.CharField(max_length=128)
    base_url = models.URLField()
    auth_type = models.CharField(max_length=16, choices=AuthType.choices, default=AuthType.TOKEN)
    token = models.CharField(max_length=512, blank=True)
    is_active = models.BooleanField(default=True)
    last_success_at = models.DateTimeField(null=True, blank=True)


class ProtocolAdapter(models.Model):
    class Protocol(models.TextChoices):
        MODBUS = 'modbus', 'Modbus'
        MQTT = 'mqtt', 'MQTT'
        OPCUA = 'opcua', 'OPC-UA'
        HTTP = 'http', 'HTTP'

    name = models.CharField(max_length=128)
    protocol = models.CharField(max_length=16, choices=Protocol.choices)
    endpoint = models.CharField(max_length=255)
    config = models.JSONField(default=dict, blank=True)
    enabled = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)
