import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class Request(models.Model):
    """A customer service request — the root of the workflow."""

    class Status(models.TextChoices):
        NEW = 'new', _('ثبت‌شده')
        OFFERED = 'offered', _('پیشنهاد ثبت شد')
        CONTRACT_GENERATED = 'contract_generated', _('قرارداد تولید شد')
        CONTRACT_APPROVED = 'contract_approved', _('قرارداد تأیید شد')
        AWAITING_PAYMENT = 'awaiting_payment', _('در انتظار پرداخت')
        PAID = 'paid', _('پرداخت‌شده')
        CANCELLED = 'cancelled', _('لغو شده')

    class UserType(models.TextChoices):
        INDIVIDUAL = 'individual', _('حقیقی')
        LEGAL = 'legal', _('حقوقی')

    class ProjectType(models.TextChoices):
        RESIDENTIAL = 'residential', _('مسکونی و تجاری')
        GOVERNMENT = 'government', _('ادارات و سازمان‌های دولتی')
        INDUSTRY = 'industry', _('صنایع')
        AGRICULTURE = 'agriculture', _('کشاورزی')

    class InstallLocation(models.TextChoices):
        ROOFTOP = 'rooftop', _('پشت بام')
        GROUND = 'ground', _('زمین باز')
        SHED = 'shed', _('سقف سولهٔ صنعتی')

    class BuildingType(models.TextChoices):
        VILLA = 'villa', _('ویلایی')
        APARTMENT = 'apartment', _('آپارتمانی')

    class Ownership(models.TextChoices):
        DEDICATED = 'dedicated', _('اختصاصی')
        SHARED = 'shared', _('مشارکتی')

    class StorageInterest(models.TextChoices):
        YES = 'yes', _('بله')
        NO = 'no', _('خیر')
        CONSULT = 'consult', _('نیاز به مشاوره')

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='service_requests',
    )
    full_name = models.CharField(max_length=255)
    mobile = models.CharField(max_length=20)
    province = models.CharField(max_length=64)
    city = models.CharField(max_length=64, blank=True)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.NEW)
    # Identity verification (Shahkar): national id is matched against the mobile
    # before the contract can be approved / payment can start.
    national_id = models.CharField(max_length=20, blank=True)
    identity_verified = models.BooleanField(default=False)
    identity_verified_at = models.DateTimeField(null=True, blank=True)
    # --- Evaluation form (mirrors the pars-energy.com assessment wizard) ---
    user_type = models.CharField(max_length=16, choices=UserType.choices, default=UserType.INDIVIDUAL)
    project_type = models.CharField(max_length=16, choices=ProjectType.choices, blank=True)
    needs_financial_consult = models.BooleanField(default=False)
    install_address = models.CharField(max_length=255, blank=True)
    area_m2 = models.PositiveIntegerField(null=True, blank=True)
    install_location = models.CharField(max_length=16, choices=InstallLocation.choices, blank=True)
    building_type = models.CharField(max_length=16, choices=BuildingType.choices, blank=True)
    has_shading = models.BooleanField(default=False)
    ownership_type = models.CharField(max_length=16, choices=Ownership.choices, blank=True)
    grid_distance_m = models.PositiveIntegerField(null=True, blank=True)
    storage_interest = models.CharField(max_length=16, choices=StorageInterest.choices, blank=True)
    bill_id = models.CharField(max_length=32, blank=True)
    accepted_terms = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('-created_at',)
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['province']),
            models.Index(fields=['mobile']),
            models.Index(fields=['-created_at']),
        ]

    def __str__(self):
        return f'#{self.pk} - {self.full_name} ({self.get_status_display()})'


class RequestOffer(models.Model):
    """A price offer made by an admin against a request (max 3 per request)."""

    request = models.ForeignKey(Request, on_delete=models.CASCADE, related_name='offers')
    title = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=14, decimal_places=0, default=Decimal('0'))
    currency = models.CharField(max_length=8, default='IRR')
    vat_percent = models.PositiveSmallIntegerField(default=10, help_text='ارزش افزوده (٪)')
    description = models.TextField(blank=True)
    valid_until = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_offers',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-created_at',)

    def __str__(self):
        return f'{self.title} - {self.amount} {self.currency}'

    @property
    def is_expired(self) -> bool:
        return self.valid_until is not None and self.valid_until < timezone.now()

    @property
    def is_payable(self) -> bool:
        return self.is_active and not self.is_expired

    @property
    def vat_amount(self) -> Decimal:
        from decimal import ROUND_HALF_UP
        return (self.amount * Decimal(self.vat_percent) / Decimal(100)).quantize(
            Decimal('1'), rounding=ROUND_HALF_UP)

    @property
    def total_amount(self) -> Decimal:
        """Amount payable including value-added tax."""
        return self.amount + self.vat_amount


class RequestContract(models.Model):
    """The contract generated for a selected offer; approved via OTP."""

    class Status(models.TextChoices):
        DRAFT = 'draft', _('پیش‌نویس')
        GENERATED = 'generated', _('تولیدشده')
        APPROVED = 'approved', _('تأییدشده')
        CANCELLED = 'cancelled', _('لغو شده')

    request = models.OneToOneField(Request, on_delete=models.CASCADE, related_name='contract')
    offer = models.ForeignKey(RequestOffer, on_delete=models.PROTECT, related_name='contracts')
    contract_number = models.CharField(max_length=32, unique=True)
    body = models.TextField(blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.GENERATED)
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-created_at',)

    def __str__(self):
        return self.contract_number


class RequestPayment(models.Model):
    """A dedicated payment tied to a specific offer (no generic product)."""

    class Status(models.TextChoices):
        PENDING = 'pending', _('در انتظار')
        PAID = 'paid', _('پرداخت‌شده')
        FAILED = 'failed', _('ناموفق')
        CANCELLED = 'cancelled', _('لغو شده')

    request = models.ForeignKey(Request, on_delete=models.CASCADE, related_name='payments')
    offer = models.ForeignKey(RequestOffer, on_delete=models.PROTECT, related_name='payments')
    amount = models.DecimalField(max_digits=14, decimal_places=0, default=Decimal('0'))
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    gateway_ref = models.CharField(max_length=128, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('-created_at',)
        indexes = [
            models.Index(fields=['token']),
            models.Index(fields=['status']),
        ]

    def __str__(self):
        return f'Payment {self.token} - {self.get_status_display()}'


class OtpVerification(models.Model):
    """One-time codes for SMS registration/login and contract approval."""

    class Purpose(models.TextChoices):
        REGISTER = 'register', _('ثبت‌نام')
        LOGIN = 'login', _('ورود')
        CONTRACT_APPROVAL = 'contract_approval', _('تأیید قرارداد')

    mobile = models.CharField(max_length=20)
    code = models.CharField(max_length=8)
    purpose = models.CharField(max_length=32, choices=Purpose.choices)
    request = models.ForeignKey(
        Request,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='otp_verifications',
    )
    attempts = models.PositiveIntegerField(default=0)
    is_used = models.BooleanField(default=False)
    expires_at = models.DateTimeField()
    verified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-created_at',)
        indexes = [
            models.Index(fields=['mobile', 'purpose']),
        ]

    def __str__(self):
        return f'OTP {self.mobile} ({self.get_purpose_display()})'

    @property
    def is_expired(self) -> bool:
        return self.expires_at < timezone.now()


class RequestMessageLog(models.Model):
    """Audit trail of every SMS the module sends."""

    class MessageType(models.TextChoices):
        OTP = 'otp', _('کد یک‌بارمصرف')
        STATUS_CHANGE = 'status_change', _('تغییر وضعیت')
        PAYMENT_SUCCESS = 'payment_success', _('پرداخت موفق')
        CONTRACT = 'contract', _('قرارداد')

    class Status(models.TextChoices):
        QUEUED = 'queued', _('در صف')
        SENT = 'sent', _('ارسال‌شده')
        FAILED = 'failed', _('ناموفق')

    request = models.ForeignKey(
        Request,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='message_logs',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='request_messages',
    )
    mobile = models.CharField(max_length=20)
    message_type = models.CharField(max_length=32, choices=MessageType.choices)
    body = models.TextField()
    provider = models.CharField(max_length=64, blank=True)
    provider_message_id = models.CharField(max_length=128, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-created_at',)
        indexes = [
            models.Index(fields=['mobile']),
            models.Index(fields=['message_type']),
        ]

    def __str__(self):
        return f'{self.get_message_type_display()} → {self.mobile}'


class UserProfileCompletion(models.Model):
    """Extended profile data collected after a successful payment."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='profile_completion',
    )
    national_id = models.CharField(max_length=20, blank=True)
    address = models.TextField(blank=True)
    postal_code = models.CharField(max_length=20, blank=True)
    company_name = models.CharField(max_length=255, blank=True)
    economic_code = models.CharField(max_length=64, blank=True)
    is_completed = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'Profile of {self.user}'


class ContractTemplate(models.Model):
    """Admin-editable contract template. The body may be typed directly or
    populated from an uploaded text/Word file. Placeholders like {{full_name}} or
    {{amount}} are substituted when a contract is generated. Several templates may
    exist; the one with ``is_active=True`` is used for new contracts."""

    name = models.CharField(max_length=128, default='قالب پیش‌فرض')
    body = models.TextField(blank=True)
    source_file = models.FileField(upload_to='contract_templates/', null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('-updated_at',)

    def __str__(self):
        return self.name


class ContractSettings(models.Model):
    """Singleton settings that shape every generated/printed contract and the
    customer-facing contract page: company header, signature and page margins."""

    company_name = models.CharField(max_length=255, blank=True, default='')
    company_address = models.TextField(blank=True, default='')
    company_phone = models.CharField(max_length=64, blank=True, default='')
    logo = models.ImageField(upload_to='contract_settings/', null=True, blank=True)
    header_note = models.TextField(blank=True, default='', help_text=_('متن بالای قرارداد'))
    footer_note = models.TextField(blank=True, default='', help_text=_('متن پایین قرارداد'))
    signature_text = models.CharField(max_length=255, blank=True, default='')
    # Print / PDF page setup, in millimetres.
    margin_top = models.PositiveSmallIntegerField(default=20)
    margin_right = models.PositiveSmallIntegerField(default=20)
    margin_bottom = models.PositiveSmallIntegerField(default=20)
    margin_left = models.PositiveSmallIntegerField(default=20)
    # Customer-facing contract page texts.
    customer_page_title = models.CharField(max_length=255, blank=True, default='')
    customer_page_intro = models.TextField(blank=True, default='')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('تنظیمات قرارداد')
        verbose_name_plural = _('تنظیمات قرارداد')

    def __str__(self):
        return self.company_name or 'Contract settings'

    @classmethod
    def load(cls):
        """Return the single settings row, creating it on first use."""
        obj = cls.objects.first()
        if obj is None:
            obj = cls.objects.create()
        return obj


class Ticket(models.Model):
    """A support ticket: a conversation thread between a customer and admins."""

    class Status(models.TextChoices):
        OPEN = 'open', _('باز')
        ANSWERED = 'answered', _('پاسخ داده‌شده')
        CLOSED = 'closed', _('بسته‌شده')

    class Priority(models.TextChoices):
        LOW = 'low', _('کم')
        NORMAL = 'normal', _('عادی')
        HIGH = 'high', _('زیاد')

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='tickets',
    )
    subject = models.CharField(max_length=255)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN)
    priority = models.CharField(max_length=16, choices=Priority.choices, default=Priority.NORMAL)
    request = models.ForeignKey(
        Request,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='tickets',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('-updated_at',)
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['-updated_at']),
        ]

    def __str__(self):
        return f'#{self.pk} - {self.subject}'


class TicketMessage(models.Model):
    """A single message inside a ticket thread (from the customer or an admin)."""

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name='ticket_messages')
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ticket_messages',
    )
    is_staff_reply = models.BooleanField(default=False)
    body = models.TextField()
    attachment = models.FileField(upload_to='ticket_attachments/', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('created_at',)

    def __str__(self):
        return f'message #{self.pk} on ticket {self.ticket_id}'
