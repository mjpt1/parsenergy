"""Exhibition lead capture.

A lead captured at a stand is not a different kind of thing from a lead
captured on the website — it is the same request, arriving by a different
door. So the capture form creates an ordinary `Request`, which drops it into
the queue the sales pipeline already runs: marketing reviews it, refers it to
sales, sales refers it to technical, and technical never sees the customer's
name or phone number. None of that had to be rebuilt.

What *is* specific to an exhibition hangs off the request here: who was
standing at the stand, which event it was, the qualification questions that
only make sense face to face, and the marketer's private read of the visitor.

The two-stage flow exists because a stand has seconds, not minutes. Stage one
captures a name and a mobile number and nothing else is required; stage two
asks for project detail and may never be filled in. Both write to the *same*
request — the resume link carries a token, never a "create another" path.

Nothing is reachable without a link. `LeadSource` holds the unguessable token
behind each marketer's QR code, which is also how a lead gets attributed
without ever asking the visitor who they just spoke to.
"""
from __future__ import annotations

import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.requests.models import Request


def _token() -> str:
    """URL-safe, unguessable, and short enough to sit inside a QR code."""
    return secrets.token_urlsafe(16)


class LeadSource(models.Model):
    """One QR code: a marketer's own, or the public one for brochures."""

    token = models.CharField(max_length=64, unique=True, default=_token, db_index=True)
    name = models.CharField(_('عنوان'), max_length=120,
                            help_text=_('مثلاً «نمایشگاه برق تهران — غرفهٔ A»'))
    marketer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='lead_sources',
        help_text=_('خالی بگذارید تا این QR عمومی باشد (کارت ویزیت، بروشور).'),
    )
    event_name = models.CharField(_('رویداد'), max_length=120, blank=True)
    is_active = models.BooleanField(_('فعال'), default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-created_at',)
        verbose_name = _('منبع سرنخ (QR)')
        verbose_name_plural = _('منابع سرنخ (QR)')

    def __str__(self):
        who = self.marketer.get_full_name() or self.marketer.username if self.marketer else _('عمومی')
        return f'{self.name} — {who}'

    @property
    def is_public(self) -> bool:
        return self.marketer_id is None


class Lead(models.Model):
    """The exhibition-specific half of a request captured at a stand.

    Everything a normal request already holds — name, mobile, province, map
    pin, install location, area, bill id — lives on `request`, not here, so
    the pipeline, the filters and the privacy rules all keep working with no
    special cases.
    """

    class Goal(models.TextChoices):
        SELL_POWER = 'sell_power', _('فروش برق')
        CUT_COST = 'cut_cost', _('کاهش هزینه انرژی')
        ONSITE_USE = 'onsite_use', _('مصرف برق در محل')
        INVESTMENT = 'investment', _('سرمایه‌گذاری')
        MONETISE_SPACE = 'monetise_space', _('استفادهٔ اقتصادی از سقف / زمین')
        PARTNERSHIP = 'partnership', _('بررسی مشارکت')
        INFORMATION = 'information', _('دریافت اطلاعات')

    class Timeline(models.TextChoices):
        LT_1M = 'lt_1m', _('کمتر از ۱ ماه')
        M1_3 = 'm1_3', _('۱ تا ۳ ماه')
        M3_6 = 'm3_6', _('۳ تا ۶ ماه')
        GT_6M = 'gt_6m', _('بیش از ۶ ماه')
        EXPLORING = 'exploring', _('فعلاً در حال بررسی')

    class DemandPower(models.TextChoices):
        UNDER_1MW = 'under_1mw', _('زیر یک مگاوات')
        OVER_1MW = 'over_1mw', _('بیشتر از یک مگاوات')
        UNKNOWN = 'unknown', _('نمی‌دانم')

    class Temperature(models.TextChoices):
        HOT = 'hot', _('سرنخ داغ')
        WARM = 'warm', _('سرنخ گرم')
        COLD = 'cold', _('سرنخ سرد')
        UNQUALIFIED = 'unqualified', _('فاقد شرایط')

    request = models.OneToOneField(
        Request, on_delete=models.CASCADE, related_name='exhibition',
        null=True, blank=True, verbose_name=_('درخواست'),
    )

    lead_code = models.CharField(_('شناسهٔ سرنخ'), max_length=20, unique=True, blank=True)
    resume_token = models.CharField(max_length=64, unique=True, default=_token, db_index=True)

    # --- who the visitor represents ---------------------------------------- #
    company = models.CharField(_('نام شرکت / مجموعه'), max_length=150, blank=True)
    job_title = models.CharField(_('سمت'), max_length=100, blank=True)
    business_field = models.CharField(_('حوزهٔ فعالیت'), max_length=150, blank=True)
    goals = models.JSONField(_('هدف اصلی'), default=list, blank=True)
    timeline = models.CharField(_('زمان احتمالی تصمیم‌گیری یا شروع پروژه'), max_length=16,
                                choices=Timeline.choices, blank=True)

    # --- attribution, never typed by the visitor --------------------------- #
    source = models.ForeignKey(LeadSource, on_delete=models.SET_NULL, null=True, blank=True,
                               related_name='leads', verbose_name=_('منبع'))
    marketer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                 null=True, blank=True, related_name='leads',
                                 verbose_name=_('بازاریاب'))
    event_name = models.CharField(_('رویداد'), max_length=120, blank=True)
    country = models.CharField(_('کشور'), max_length=64, blank=True, default='ایران')

    # --- follow-up of leads that stopped after stage 1 --------------------- #
    reminder_count = models.PositiveSmallIntegerField(_('تعداد یادآوری'), default=0)
    last_reminder_at = models.DateTimeField(_('آخرین یادآوری'), null=True, blank=True)

    # --- stage 2 extras the request has no column for ---------------------- #
    stage2_completed = models.BooleanField(_('مرحلهٔ ۲ تکمیل شد'), default=False)
    stage2_completed_at = models.DateTimeField(null=True, blank=True)
    install_location_note = models.CharField(_('توضیح محل نصب'), max_length=200, blank=True)
    area_note = models.CharField(_('مساحت دقیق‌تر'), max_length=120, blank=True)
    demand_power = models.CharField(_('توان مورد تقاضا'), max_length=16,
                                    choices=DemandPower.choices, blank=True)
    shading_note = models.TextField(_('موانع موجود'), blank=True)
    bill_file = models.FileField(_('فایل قبض'), upload_to='leads/bills/%Y/%m/',
                                 null=True, blank=True)

    # --- internal: Pars Energy only, never shown to the visitor ------------ #
    temperature = models.CharField(_('کیفیت سرنخ'), max_length=16,
                                   choices=Temperature.choices, blank=True)
    next_action = models.CharField(_('اقدام بعدی'), max_length=255, blank=True)
    marketer_impression = models.TextField(_('برداشت بازاریاب از نیاز مشتری'), blank=True)
    decision_role = models.CharField(_('نقش مخاطب در تصمیم‌گیری'), max_length=150, blank=True)
    notes = models.TextField(_('یادداشت'), blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('-created_at',)
        verbose_name = _('جزئیات سرنخ نمایشگاهی')
        verbose_name_plural = _('جزئیات سرنخ‌های نمایشگاهی')
        indexes = [
            models.Index(fields=['marketer', '-created_at']),
            models.Index(fields=['stage2_completed']),
        ]

    def __str__(self):
        name = self.request.full_name if self.request_id else '—'
        return f'{self.lead_code} — {name}'

    def save(self, *args, **kwargs):
        if not self.lead_code:
            # Readable at a stand and over the phone; the token stays the secret.
            self.lead_code = f'L{timezone.now():%y%m}-{secrets.randbelow(900000) + 100000}'
        super().save(*args, **kwargs)

    @property
    def goal_labels(self) -> list[str]:
        labels = dict(self.Goal.choices)
        return [str(labels[g]) for g in (self.goals or []) if g in labels]
