from django.conf import settings
from django.db import models
from django.utils import timezone


class AlertRule(models.Model):
    plant = models.ForeignKey('plants.Plant', on_delete=models.CASCADE, related_name='alert_rules', verbose_name='نیروگاه')
    name = models.CharField(max_length=255, verbose_name='نام قانون')
    metric = models.CharField(max_length=64, verbose_name='شاخص')
    threshold_value = models.DecimalField(max_digits=12, decimal_places=3, verbose_name='مقدار آستانه')
    comparator = models.CharField(max_length=8, default='>', verbose_name='شرط')
    severity = models.CharField(max_length=16, default='medium', verbose_name='شدت')
    channels = models.CharField(max_length=64, default='email,sms,push', verbose_name='روش اطلاع‌رسانی')
    enabled = models.BooleanField(default=True, verbose_name='فعال')

    def __str__(self):
        return self.name


class AlertEvent(models.Model):
    rule = models.ForeignKey(AlertRule, on_delete=models.CASCADE, related_name='events', verbose_name='قانون')
    message = models.TextField(verbose_name='پیام')
    severity = models.CharField(max_length=16, default='medium', verbose_name='شدت')
    acknowledged = models.BooleanField(default=False, verbose_name='بررسی شده')
    acknowledged_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, verbose_name='بررسی‌کننده')
    # Without this, "how long does an alert sit unhandled?" is unanswerable:
    # the flag says whether someone got to it, never when. Null on rows that
    # were acknowledged before this field existed, so averages skip them.
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        """Stamp the acknowledgement here rather than at each call site.

        An event is acknowledged from the edit form, from the API viewset and
        from Django admin. Putting the clock in `save()` means none of them can
        forget it, and clearing the flag clears the time with it.
        """
        if self.acknowledged and self.acknowledged_at is None:
            self.acknowledged_at = timezone.now()
            if kwargs.get('update_fields') is not None:
                kwargs['update_fields'] = set(kwargs['update_fields']) | {'acknowledged_at'}
        elif not self.acknowledged:
            self.acknowledged_at = None
        super().save(*args, **kwargs)

    def __str__(self):
        return self.message[:80]


class Notification(models.Model):
    class Channel(models.TextChoices):
        EMAIL = 'email', 'ایمیل'
        SMS = 'sms', 'پیامک'
        PUSH = 'push', 'اعلان'

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notifications', verbose_name='کاربر')
    channel = models.CharField(max_length=16, choices=Channel.choices, verbose_name='روش ارسال')
    title = models.CharField(max_length=255, verbose_name='عنوان')
    body = models.TextField(verbose_name='متن')
    sent = models.BooleanField(default=False, verbose_name='ارسال شده')
    delivery_status = models.CharField(max_length=16, default='pending', verbose_name='وضعیت تحویل')
    provider_message_id = models.CharField(max_length=128, blank=True, verbose_name='شناسهٔ پیام')
    delivered_at = models.DateTimeField(null=True, blank=True, verbose_name='زمان تحویل')
    created_at = models.DateTimeField(auto_now_add=True)
