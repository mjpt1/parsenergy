from django.db import models
from django.utils.translation import gettext_lazy as _


class Visit(models.Model):
    """One arrival on a public page from outside the site.

    Only entries are kept — a page reached by clicking around inside the site
    is the same visit, not a new one — so a row answers "where did this person
    come from", which is the question the traffic report asks.
    """

    class Source(models.TextChoices):
        GOOGLE = 'google', _('گوگل')
        BING = 'bing', _('بینگ')
        INSTAGRAM = 'instagram', _('اینستاگرام')
        TELEGRAM = 'telegram', _('تلگرام')
        WHATSAPP = 'whatsapp', _('واتساپ')
        BALE = 'bale', _('بله')
        LINKEDIN = 'linkedin', _('لینکدین')
        TWITTER = 'twitter', _('X (توییتر)')
        FACEBOOK = 'facebook', _('فیسبوک')
        YOUTUBE = 'youtube', _('یوتیوب')
        APARAT = 'aparat', _('آپارات')
        MAIN_SITE = 'main_site', _('سایت پارس انرژی')
        QR = 'qr', _('QR بازاریاب')
        SMS = 'sms', _('لینک پیامک')
        CAMPAIGN = 'campaign', _('کمپین (UTM)')
        OTHER_SITE = 'other_site', _('سایت‌های دیگر')
        DIRECT = 'direct', _('مستقیم / نامشخص')

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    visitor_id = models.CharField(max_length=32, db_index=True)
    is_new_visitor = models.BooleanField(default=False)
    host = models.CharField(max_length=100, blank=True)
    path = models.CharField(max_length=255)
    referrer = models.CharField(max_length=512, blank=True)
    referrer_host = models.CharField(max_length=255, blank=True, db_index=True)
    source = models.CharField(max_length=16, choices=Source.choices, db_index=True)
    utm_source = models.CharField(max_length=128, blank=True)
    utm_medium = models.CharField(max_length=128, blank=True)
    utm_campaign = models.CharField(max_length=128, blank=True)
    device = models.CharField(max_length=16, blank=True)

    class Meta:
        ordering = ('-created_at',)
        indexes = [models.Index(fields=['source', 'created_at'])]
        verbose_name = _('بازدید')
        verbose_name_plural = _('بازدیدها')

    def __str__(self):
        return f'{self.created_at:%Y-%m-%d %H:%M} {self.source} {self.path}'
