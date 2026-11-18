from django.conf import settings
from django.db import models


class SystemParameter(models.Model):
    key = models.CharField(max_length=128, unique=True, verbose_name='کلید')
    value = models.TextField(verbose_name='مقدار')
    description = models.CharField(max_length=255, blank=True, verbose_name='توضیح')
    is_secret = models.BooleanField(default=False, verbose_name='محرمانه است')
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.key


class SecuritySetting(models.Model):
    require_mfa = models.BooleanField(default=True, verbose_name='ورود دومرحله‌ای الزامی باشد')
    session_timeout_minutes = models.PositiveIntegerField(default=30, verbose_name='مدت نشست (دقیقه)')
    password_rotation_days = models.PositiveIntegerField(default=90, verbose_name='دورهٔ تغییر رمز (روز)')
    lockout_threshold = models.PositiveIntegerField(default=5, verbose_name='تعداد تلاش ناموفق تا قفل حساب')
    ip_allowlist = models.TextField(blank=True, verbose_name='فهرست IPهای مجاز')
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'تنظیمات امنیتی {self.pk}'


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
        PENDING = 'pending', 'در انتظار'
        SUCCESS = 'success', 'موفق'
        FAILED = 'failed', 'ناموفق'

    file_path = models.CharField(max_length=1024, verbose_name='مسیر فایل')
    file_size_bytes = models.BigIntegerField(default=0, verbose_name='حجم (بایت)')
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING, verbose_name='وضعیت')
    notes = models.TextField(blank=True, verbose_name='یادداشت')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.file_path


class APIConnection(models.Model):
    class AuthType(models.TextChoices):
        NONE = 'none', 'بدون احراز هویت'
        TOKEN = 'token', 'Token'
        BASIC = 'basic', 'Basic'

    name = models.CharField(max_length=128, verbose_name='نام')
    base_url = models.URLField(verbose_name='آدرس پایه')
    auth_type = models.CharField(max_length=16, choices=AuthType.choices, default=AuthType.TOKEN, verbose_name='نوع احراز هویت')
    token = models.CharField(max_length=512, blank=True, verbose_name='توکن')
    is_active = models.BooleanField(default=True, verbose_name='فعال')
    last_success_at = models.DateTimeField(null=True, blank=True, verbose_name='آخرین اتصال موفق')

    def __str__(self):
        return self.name


class ProtocolAdapter(models.Model):
    class Protocol(models.TextChoices):
        MODBUS = 'modbus', 'Modbus'
        MQTT = 'mqtt', 'MQTT'
        OPCUA = 'opcua', 'OPC-UA'
        HTTP = 'http', 'HTTP'

    name = models.CharField(max_length=128, verbose_name='نام')
    protocol = models.CharField(max_length=16, choices=Protocol.choices, verbose_name='پروتکل')
    endpoint = models.CharField(max_length=255, verbose_name='آدرس اتصال')
    config = models.JSONField(default=dict, blank=True, verbose_name='تنظیمات (JSON)')
    enabled = models.BooleanField(default=True, verbose_name='فعال')
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class SettingChangeRequest(models.Model):
    """SMS, Shahkar or payment settings a technical user wants changed.

    Nothing reaches the live settings until an administrator approves it.
    `changes` is {key: {'value': str, 'secret': bool}}; secret values are wiped
    as soon as the request is decided.
    """

    class Status(models.TextChoices):
        PENDING = 'pending', 'در انتظار تأیید'
        APPROVED = 'approved', 'تأیید شد'
        REJECTED = 'rejected', 'رد شد'

    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL,
                                     related_name='setting_change_requests', verbose_name='درخواست‌دهنده')
    changes = models.JSONField(default=dict, verbose_name='تغییرات')
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING,
                              db_index=True, verbose_name='وضعیت')
    created_at = models.DateTimeField(auto_now_add=True)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name='decided_setting_changes', verbose_name='تصمیم‌گیرنده')
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ('-id',)

    def __str__(self):
        return f'تغییر تنظیمات {self.pk}'
