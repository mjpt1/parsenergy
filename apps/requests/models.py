import os
import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.storage import PrivateStorage


class Request(models.Model):
    """A customer service request — the root of the workflow."""

    class Status(models.TextChoices):
        NEW = 'new', _('ثبت‌شده')
        OFFERED = 'offered', _('پیشنهاد ثبت شد')
        CONTRACT_GENERATED = 'contract_generated', _('قرارداد تولید شد')
        CONTRACT_APPROVED = 'contract_approved', _('قرارداد تأیید شد')
        AWAITING_PAYMENT = 'awaiting_payment', _('در انتظار پرداخت')
        PAID = 'paid', _('پرداخت‌شده')
        HOLD = 'hold', _('معلق')
        CLOSED = 'closed', _('بسته / از دست‌رفته')
        CANCELLED = 'cancelled', _('لغو شده')

    class Department(models.TextChoices):
        """Which team currently owns the request in the website lead pipeline.

        Flow: submit → MARKETING review → SALES qualification → TECHNICAL
        evaluation → SALES negotiation → DONE (+ CRM handoff).
        """
        MARKETING = 'marketing', _('بازاریابی')
        TECHNICAL = 'technical', _('فنی')
        SALES = 'sales', _('فروش')
        DONE = 'done', _('تکمیل‌شده')

    class SalesPhase(models.TextChoices):
        QUALIFICATION = 'qualification', _('صلاحیت‌سنجی')
        NEGOTIATION = 'negotiation', _('مذاکره تجاری')

    class FunnelStage(models.TextChoices):
        """The sales funnel as the company runs it, from first contact to operation."""
        LEAD = 'lead', _('ورودی لید')
        QUALIFICATION = 'qualification', _('صلاحیت‌سنجی لید')
        INITIAL_DESIGN = 'initial_design', _('ارزیابی فنی و ارائه طرح اولیه')
        FIRST_CONTRACT = 'first_contract', _('مذاکره و قرارداد اول')
        COMMERCIAL_OFFER = 'commercial_offer', _('ارزیابی فنی و پیشنهاد فنی و تجاری')
        SECOND_CONTRACT = 'second_contract', _('مذاکره و عقد قرارداد دوم')
        EXECUTION = 'execution', _('مدیریت و اجرای پروژه')
        OPERATION = 'operation', _('بهره‌برداری و نگهداری نیروگاه')

    class StopReason(models.TextChoices):
        CUSTOMER_WITHDREW = 'customer_withdrew', _('انصراف مشتری')
        NO_RESPONSE = 'no_response', _('عدم پاسخگویی مشتری')
        BUDGET = 'budget', _('نبود بودجه یا توان مالی')
        NOT_FEASIBLE = 'not_feasible', _('عدم امکان فنی یا نبود فضای مناسب')
        COMPETITOR = 'competitor', _('انتخاب رقیب')
        PRICE = 'price', _('قیمت یا شرایط قرارداد')
        DUPLICATE = 'duplicate', _('پروندهٔ تکراری یا نامعتبر')
        OTHER = 'other', _('سایر')

    class HowHeard(models.TextChoices):
        GOOGLE = 'google', _('Google')
        INSTAGRAM = 'instagram', _('Instagram')
        LINKEDIN = 'linkedin', _('LinkedIn')
        REFERRAL = 'referral', _('معرفی')
        EXHIBITION = 'exhibition', _('نمایشگاه')
        SMS = 'sms', _('پیامک')
        PHONE = 'phone', _('تماس تلفنی')
        OTHER = 'other', _('سایر')

    class Priority(models.TextChoices):
        LOW = 'low', _('کم')
        NORMAL = 'normal', _('عادی')
        HIGH = 'high', _('زیاد')
        URGENT = 'urgent', _('فوری')

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
        PARKING = 'parking', _('پارکینگ')
        OTHER = 'other', _('سایر')

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

    # --- New multi-step evaluation form (smart conditional wizard) ----------
    class RequestType(models.TextChoices):
        DEDICATED = 'dedicated', _('نیروگاه اختصاصی')
        PARTNERSHIP = 'partnership', _('نیروگاه مشارکتی')
        CONSULTATION = 'consultation', _('نیاز به مشاوره دارم')

    class PartnershipType(models.TextChoices):
        INVESTMENT = 'investment', _('سرمایه‌گذاری')
        SPACE = 'space', _('در اختیار گذاشتن فضای نصب')

    class InvestmentRange(models.TextChoices):
        UNDER_500M = 'under_500m', _('کمتر از ۵۰۰ میلیون تومان')
        R_500M_2B = '500m_2b', _('۵۰۰ میلیون تا ۲ میلیارد تومان')
        R_2B_5B = '2b_5b', _('۲ تا ۵ میلیارد تومان')
        OVER_5B = 'over_5b', _('بیش از ۵ میلیارد تومان')
        CONSULT = 'consult', _('نیاز به مشاوره دارم')

    class AreaRange(models.TextChoices):
        UNDER_100 = 'under_100', _('کمتر از ۱۰۰ متر مربع')
        R_100_500 = '100_500', _('۱۰۰ تا ۵۰۰ متر مربع')
        R_500_2000 = '500_2000', _('۵۰۰ تا ۲٬۰۰۰ متر مربع')
        OVER_2000 = 'over_2000', _('بیش از ۲٬۰۰۰ متر مربع')
        UNKNOWN = 'unknown', _('نمی‌دانم')

    class ShadeStatus(models.TextChoices):
        YES = 'yes', _('بله، سایه دارد')
        NO = 'no', _('خیر، سایه ندارد')
        UNKNOWN = 'unknown', _('نمی‌دانم')

    class ContactMethod(models.TextChoices):
        CALL = 'call', _('تماس تلفنی')
        WHATSAPP = 'whatsapp', _('واتساپ')
        TELEGRAM = 'telegram', _('تلگرام')
        BALE = 'bale', _('بله')
        ANY = 'any', _('فرقی ندارد')

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
    # --- Website lead pipeline ------------------------------------------------
    # `status` is the commercial sub-state; `department` is which team owns the
    # request right now. New leads start in marketing; sales appears twice
    # (qualification then negotiation) distinguished by `sales_phase`.
    department = models.CharField(
        max_length=16, choices=Department.choices, default=Department.MARKETING, db_index=True)
    sales_phase = models.CharField(
        max_length=16, choices=SalesPhase.choices, blank=True, db_index=True)
    funnel_stage = models.CharField(
        max_length=20, choices=FunnelStage.choices, default=FunnelStage.LEAD, db_index=True)
    stop_reason = models.CharField(max_length=20, choices=StopReason.choices, blank=True)
    stop_note = models.TextField(blank=True)
    priority = models.CharField(
        max_length=16, choices=Priority.choices, default=Priority.NORMAL, db_index=True)
    stage_entered_at = models.DateTimeField(null=True, blank=True, db_index=True)
    # Marketing review → sales qualification
    marketing_reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='marketing_reviewed_requests')
    marketing_reviewed_at = models.DateTimeField(null=True, blank=True)
    # Legacy triage fields kept for historical rows / admin display
    triaged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='triaged_requests')
    triaged_at = models.DateTimeField(null=True, blank=True)
    sales_assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='sales_assigned_requests')
    sales_completed_at = models.DateTimeField(null=True, blank=True)
    sales_completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='sales_completed_requests')
    technical_assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='technical_assigned_requests')
    technical_completed_at = models.DateTimeField(null=True, blank=True)
    technical_completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='technical_completed_requests')
    technical_note = models.TextField(blank=True)
    # Customers can only edit their request while sales/management has unlocked
    # it (after the first submission editing is locked by default).
    edit_unlocked = models.BooleanField(default=False)
    # The plant commissioned by the technical team for this request (if any).
    plant = models.OneToOneField(
        'plants.Plant', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='source_request')
    # CRM handoff (website responsibility ends after successful contract close)
    crm_transferred = models.BooleanField(default=False, db_index=True)
    crm_transferred_at = models.DateTimeField(null=True, blank=True)
    crm_transferred_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='crm_transferred_requests')
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
    # Values for admin-added custom fields (RequestFormField with is_system=False).
    # System fields always keep using their real columns above; this is only a
    # bucket for fields the admin defines later through the form builder.
    custom_fields = models.JSONField(default=dict, blank=True)
    # --- New smart-wizard fields (conditional, all optional) ----------------
    request_type = models.CharField(max_length=16, choices=RequestType.choices, blank=True)
    partnership_type = models.CharField(max_length=16, choices=PartnershipType.choices, blank=True)
    investment_range = models.CharField(max_length=16, choices=InvestmentRange.choices, blank=True)
    area_range = models.CharField(max_length=16, choices=AreaRange.choices, blank=True)
    shade_status = models.CharField(max_length=16, choices=ShadeStatus.choices, blank=True)
    contact_method = models.CharField(max_length=16, choices=ContactMethod.choices, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    # System / lead attribution (captured automatically + optional how_heard)
    lead_source = models.CharField(max_length=64, blank=True, db_index=True)
    campaign_name = models.CharField(max_length=128, blank=True, db_index=True)
    medium = models.CharField(max_length=64, blank=True)
    landing_page = models.CharField(max_length=512, blank=True)
    referrer = models.CharField(max_length=512, blank=True)
    utm_source = models.CharField(max_length=128, blank=True)
    utm_medium = models.CharField(max_length=128, blank=True)
    utm_campaign = models.CharField(max_length=128, blank=True)
    utm_content = models.CharField(max_length=128, blank=True)
    utm_term = models.CharField(max_length=128, blank=True)
    first_visit_at = models.DateTimeField(null=True, blank=True)
    device_type = models.CharField(max_length=32, blank=True)
    how_heard = models.CharField(max_length=32, choices=HowHeard.choices, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('-created_at',)
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['province']),
            models.Index(fields=['mobile']),
            models.Index(fields=['-created_at']),
            models.Index(fields=['department', 'sales_phase']),
        ]

    def __str__(self):
        return f'#{self.pk} - {self.full_name} ({self.get_status_display()})'


class RequestStageNote(models.Model):
    """The case history: staff notes and every funnel move, tied to a stage."""

    class Kind(models.TextChoices):
        NOTE = 'note', _('یادداشت')
        MOVE = 'move', _('تغییر مرحله')
        STOP = 'stop', _('لغو یا بستن')
        EDIT = 'edit', _('ویرایش اطلاعات')

    request = models.ForeignKey(Request, on_delete=models.CASCADE, related_name='stage_notes')
    stage = models.CharField(max_length=20, choices=Request.FunnelStage.choices)
    kind = models.CharField(max_length=8, choices=Kind.choices, default=Kind.NOTE)
    body = models.TextField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='request_stage_notes')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-created_at', '-id')
        indexes = [models.Index(fields=['request', '-created_at'])]

    def __str__(self):
        return f'#{self.request_id} {self.get_kind_display()}'


class RequestOffer(models.Model):
    """A price offer made by an admin against a request (max 3 per request)."""

    request = models.ForeignKey(Request, on_delete=models.CASCADE, related_name='offers')
    title = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=14, decimal_places=0, default=Decimal('0'))
    currency = models.CharField(max_length=8, default='تومان')
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
    def has_price(self) -> bool:
        return self.amount > 0

    @property
    def is_payable(self) -> bool:
        return self.is_active and not self.is_expired and self.has_price

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

    class Finance(models.TextChoices):
        PENDING = 'pending', _('منتظر تأیید مالی')
        APPROVED = 'approved', _('تأیید مالی شد')
        REJECTED = 'rejected', _('رد شد')

    request = models.ForeignKey(Request, on_delete=models.CASCADE, related_name='payments')
    offer = models.ForeignKey(RequestOffer, on_delete=models.PROTECT, related_name='payments')
    amount = models.DecimalField(max_digits=14, decimal_places=0, default=Decimal('0'))
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    # The gateway's pre-payment handle (Zarinpal calls it Authority). Issued when
    # the payment is opened and needed again to verify it, so it must survive the
    # round-trip to the gateway. `gateway_ref` holds the *post*-payment receipt id.
    authority = models.CharField(max_length=64, blank=True, db_index=True)
    gateway_ref = models.CharField(max_length=128, blank=True)
    # Payments are one-per-offer today; instalments (deposit / equipment /
    # balance) will number them without reshaping the table.
    installment_no = models.PositiveSmallIntegerField(default=1)
    paid_at = models.DateTimeField(null=True, blank=True)
    finance_status = models.CharField(max_length=10, choices=Finance.choices, default=Finance.PENDING, db_index=True)
    finance_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='reviewed_payments')
    finance_at = models.DateTimeField(null=True, blank=True)
    finance_note = models.TextField(blank=True)
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


def _private_path(request_id, filename):
    return f'projects/{request_id}/{uuid.uuid4().hex}{os.path.splitext(filename)[1].lower()}'


def _document_path(instance, filename):
    return _private_path(instance.request_id, filename)


def _contract_path(instance, filename):
    return _private_path(instance.request_id, filename)


def _insurance_path(instance, filename):
    return _private_path(instance.request_id, filename)


def _receipt_path(instance, filename):
    return _private_path(instance.contract.request_id, filename)


class RequestDocument(models.Model):
    """A file attached to a case; private unless staff share it with the customer."""

    class Kind(models.TextChoices):
        TECHNICAL = 'technical', _('مستند فنی')
        PROPOSAL = 'proposal', _('پیشنهاد فنی')
        CONTRACT = 'contract', _('قرارداد')
        PAYMENT = 'payment', _('مستند پرداخت')
        OTHER = 'other', _('سایر')

    request = models.ForeignKey(Request, on_delete=models.CASCADE, related_name='documents')
    stage = models.CharField(max_length=20, choices=Request.FunnelStage.choices)
    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.TECHNICAL)
    title = models.CharField(max_length=200)
    file = models.FileField(upload_to=_document_path, storage=PrivateStorage(), max_length=255)
    original_name = models.CharField(max_length=255)
    size = models.PositiveBigIntegerField(default=0)
    visible_to_customer = models.BooleanField(default=False)
    visible_to_contractor = models.BooleanField(default=False)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='request_documents')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-created_at', '-id')

    def __str__(self):
        return self.title


class ProjectContract(models.Model):
    """The second contract: signed outside the site, recorded and followed here."""

    request = models.OneToOneField(Request, on_delete=models.CASCADE, related_name='project_contract')
    contract_number = models.CharField(max_length=64)
    signed_on = models.DateField()
    total_amount = models.DecimalField(max_digits=16, decimal_places=0)
    description = models.TextField(blank=True)
    file = models.FileField(upload_to=_contract_path, storage=PrivateStorage(), max_length=255, blank=True)
    file_name = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='project_contracts')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.contract_number


class ContractInstallment(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', _('منتظر پرداخت')
        SUBMITTED = 'submitted', _('منتظر تأیید مالی')
        APPROVED = 'approved', _('تأیید مالی شد')
        REJECTED = 'rejected', _('رد شد؛ رسید را اصلاح کنید')

    contract = models.ForeignKey(ProjectContract, on_delete=models.CASCADE, related_name='installments')
    number = models.PositiveSmallIntegerField()
    title = models.CharField(max_length=120)
    amount = models.DecimalField(max_digits=16, decimal_places=0)
    due_date = models.DateField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    paid_on = models.DateField(null=True, blank=True)
    reference = models.CharField(max_length=100, blank=True)
    receipt = models.FileField(upload_to=_receipt_path, storage=PrivateStorage(), max_length=255, blank=True)
    receipt_name = models.CharField(max_length=255, blank=True)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='submitted_installments')
    submitted_at = models.DateTimeField(null=True, blank=True)
    finance_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='reviewed_installments')
    finance_at = models.DateTimeField(null=True, blank=True)
    finance_note = models.TextField(blank=True)

    class Meta:
        ordering = ('contract_id', 'number')
        unique_together = [('contract', 'number')]

    def __str__(self):
        return f'{self.contract_id}/{self.number}'

    @property
    def can_receive_receipt(self) -> bool:
        return self.status in (self.Status.PENDING, self.Status.REJECTED)

    @property
    def is_overdue(self) -> bool:
        return self.can_receive_receipt and self.due_date < timezone.localdate()


class ContractorProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='contractor_profile')
    company_name = models.CharField(_('نام شرکت'), max_length=200, blank=True)
    expertise = models.CharField(_('تخصص'), max_length=200, blank=True)
    license_no = models.CharField(_('شمارهٔ ثبت یا پروانه'), max_length=100, blank=True)
    city = models.CharField(_('شهر فعالیت'), max_length=100, blank=True)
    notes = models.TextField(_('یادداشت داخلی'), blank=True)

    def __str__(self):
        return self.company_name or str(self.user)


class ContractorAssignment(models.Model):
    """One contractor on one project: the link that opens the case to them, and their record."""

    class Status(models.TextChoices):
        ACTIVE = 'active', _('در حال انجام')
        DONE = 'done', _('پایان‌یافته')
        CANCELLED = 'cancelled', _('لغو شده')

    request = models.ForeignKey(Request, on_delete=models.CASCADE, related_name='contractor_assignments')
    contractor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                   related_name='contractor_assignments', limit_choices_to={'role': 'contractor'})
    scope = models.CharField(_('شرح کار'), max_length=255)
    start_date = models.DateField(_('تاریخ شروع'), null=True, blank=True)
    end_date = models.DateField(_('تاریخ پایان'), null=True, blank=True)
    share_contact = models.BooleanField(_('نام و موبایل مشتری را ببیند'), default=False)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE, db_index=True)
    rating = models.PositiveSmallIntegerField(null=True, blank=True)
    review_note = models.TextField(blank=True)
    assigned_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='assigned_contractors')
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ('-created_at', '-id')

    def __str__(self):
        return f'#{self.request_id} / {self.contractor_id}'


class ProjectInsurance(models.Model):
    class Phase(models.TextChoices):
        EXECUTION = 'execution', _('دورهٔ اجرا')
        OPERATION = 'operation', _('پس از اجرا و بهره‌برداری')

    class Kind(models.TextChoices):
        LIABILITY = 'liability', _('بیمهٔ مسئولیت')
        ALL_RISK = 'all_risk', _('بیمهٔ تمام‌خطر پیمانکاران')
        WORKERS = 'workers', _('بیمهٔ حوادث کارکنان')
        FIRE = 'fire', _('بیمهٔ آتش‌سوزی')
        EQUIPMENT = 'equipment', _('بیمهٔ تجهیزات')
        OTHER = 'other', _('سایر')

    request = models.ForeignKey(Request, on_delete=models.CASCADE, related_name='insurances')
    phase = models.CharField(_('دوره'), max_length=10, choices=Phase.choices)
    kind = models.CharField(_('نوع بیمه'), max_length=10, choices=Kind.choices)
    insurer = models.CharField(_('شرکت بیمه'), max_length=150)
    policy_number = models.CharField(_('شمارهٔ بیمه‌نامه'), max_length=100)
    start_date = models.DateField(_('شروع اعتبار'))
    end_date = models.DateField(_('پایان اعتبار'), db_index=True)
    coverage_amount = models.DecimalField(_('سرمایهٔ بیمه (تومان)'), max_digits=16, decimal_places=0, null=True, blank=True)
    file = models.FileField(_('فایل بیمه‌نامه'), upload_to=_insurance_path, storage=PrivateStorage(), max_length=255, blank=True)
    file_name = models.CharField(max_length=255, blank=True)
    visible_to_customer = models.BooleanField(_('مشتری هم ببیند'), default=True)
    note = models.CharField(_('توضیح'), max_length=255, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='project_insurances')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('phase', '-end_date')

    def __str__(self):
        return self.policy_number

    @property
    def is_expired(self) -> bool:
        return self.end_date < timezone.localdate()

    @property
    def expires_soon(self) -> bool:
        return not self.is_expired and (self.end_date - timezone.localdate()).days <= 30


class ProjectEquipment(models.Model):
    class Category(models.TextChoices):
        PANEL = 'panel', _('پنل خورشیدی')
        INVERTER = 'inverter', _('اینورتر')
        STRUCTURE = 'structure', _('سازه')
        CABLE = 'cable', _('کابل و اتصالات')
        PROTECTION = 'protection', _('حفاظت و تابلو')
        METER = 'meter', _('کنتور و پایش')
        OTHER = 'other', _('سایر')

    request = models.ForeignKey(Request, on_delete=models.CASCADE, related_name='equipment_items')
    category = models.CharField(_('دسته'), max_length=12, choices=Category.choices)
    name = models.CharField(_('نام تجهیز'), max_length=200)
    model_name = models.CharField(_('برند / مدل'), max_length=200, blank=True)
    serial_number = models.CharField(_('شماره سریال'), max_length=200, blank=True)
    quantity = models.DecimalField(_('تعداد'), max_digits=12, decimal_places=2, default=Decimal('1'))
    unit = models.CharField(_('واحد'), max_length=30, default='عدد')
    supplier = models.CharField(_('تأمین‌کننده'), max_length=200, blank=True)
    purchased_on = models.DateField(_('تاریخ خرید'), null=True, blank=True)
    warranty_until = models.DateField(_('پایان گارانتی'), null=True, blank=True)
    note = models.CharField(_('توضیح'), max_length=255, blank=True)
    visible_to_customer = models.BooleanField(_('به مشتری نمایش داده شود'), default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='project_equipment')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('category', 'id')

    def __str__(self):
        return self.name


@receiver(post_delete, sender=ProjectInsurance)
def _remove_insurance_file(sender, instance, **kwargs):
    if instance.file:
        instance.file.delete(save=False)


@receiver(post_delete, sender=RequestDocument)
def _remove_document_file(sender, instance, **kwargs):
    if instance.file:
        instance.file.delete(save=False)


@receiver(post_delete, sender=ProjectContract)
def _remove_contract_file(sender, instance, **kwargs):
    if instance.file:
        instance.file.delete(save=False)


@receiver(post_delete, sender=ContractInstallment)
def _remove_receipt_file(sender, instance, **kwargs):
    if instance.receipt:
        instance.receipt.delete(save=False)


class OtpVerification(models.Model):
    """One-time codes for SMS registration/login and contract approval."""

    class Purpose(models.TextChoices):
        REGISTER = 'register', _('ثبت‌نام')
        LOGIN = 'login', _('ورود')
        CONTRACT_APPROVAL = 'contract_approval', _('تأیید قرارداد')

    mobile = models.CharField(max_length=20)
    # 16: MelliPayamak's OTP service returns codes of up to 10 digits.
    code = models.CharField(max_length=16)
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
        LEAD = 'lead', _('سرنخ نمایشگاهی')

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
    full_name = models.CharField(max_length=255, blank=True)
    mobile = models.CharField(max_length=20, blank=True)
    province = models.CharField(max_length=64, blank=True)
    city = models.CharField(max_length=64, blank=True)
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

    @classmethod
    def ensure_for(cls, user):
        """Get-or-create this user's profile, seeding empty fields from their
        most recent request so the form they already filled isn't re-asked."""
        profile, _ = cls.objects.get_or_create(user=user)
        last = Request.objects.filter(user=user).order_by('-created_at').first()
        if last:
            seed = {
                'full_name': last.full_name, 'mobile': last.mobile,
                'province': last.province, 'city': last.city,
                'national_id': last.national_id,
                'address': last.install_address,
            }
            changed = False
            for field, value in seed.items():
                if value and not getattr(profile, field):
                    setattr(profile, field, value)
                    changed = True
            if changed:
                profile.save()
        return profile


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

    class Department(models.TextChoices):
        SALES = 'sales', _('فروش')
        TECHNICAL = 'technical', _('فنی')
        MARKETING = 'marketing', _('بازاریابی')
        OPERATIONS = 'operations', _('عملیات')
        MANAGEMENT = 'management', _('مدیریت')

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='tickets',
    )
    # Which team the customer addressed this ticket to.
    department = models.CharField(
        max_length=16, choices=Department.choices, default=Department.SALES, db_index=True)
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


class RequestFormStep(models.Model):
    """One page/step of the customer evaluation wizard (`requests/submit/`).

    Seeded once (see the 0018 data migration) to reproduce the 6 steps that
    used to be hardcoded in the template; admins can then add/reorder/hide
    steps from the Django admin without touching code.

    `condition` is a list of AND-groups, OR'd together — a step is visible if
    ANY group matches, and a group matches only if ALL its (field, value)
    pairs match the current form state:
        [[{"field": "request_type", "value": "dedicated"}],
         [{"field": "request_type", "value": "partnership"},
          {"field": "partnership_type", "value": "space"}]]
    An empty list means "always visible" (no condition).
    """

    order = models.PositiveIntegerField(default=0)
    label = models.CharField(max_length=120)
    condition = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ('order',)
        verbose_name = _('مرحلهٔ فرم ارزیابی')
        verbose_name_plural = _('مراحل فرم ارزیابی')

    def __str__(self):
        return f'{self.order}. {self.label}'


class RequestFormField(models.Model):
    """A single field within a `RequestFormStep`.

    `key` is the form/field name. For system fields (`is_system=True`) it must
    match a real field already declared on `RequestSubmitForm` (identity,
    contact, and other business-critical fields) — those keep writing to their
    real `Request` columns exactly as before and can't be deleted or retyped
    from the admin. Custom fields an admin adds later (`is_system=False`) are
    added dynamically to the form and their submitted values are stored in
    `Request.custom_fields[key]`.
    """

    TEXT = 'text'
    TEXTAREA = 'textarea'
    NUMBER = 'number'
    SELECT = 'select'
    RADIO = 'radio'
    YESNO = 'yesno'
    DATE = 'date'
    TYPE_CHOICES = [
        (TEXT, _('متن کوتاه')),
        (TEXTAREA, _('متن بلند')),
        (NUMBER, _('عدد')),
        (SELECT, _('لیست کشویی')),
        (RADIO, _('چندگزینه‌ای')),
        (YESNO, _('بله / خیر')),
        (DATE, _('تاریخ')),
    ]

    step = models.ForeignKey(RequestFormStep, on_delete=models.CASCADE, related_name='fields')
    order = models.PositiveIntegerField(default=0)
    key = models.SlugField(max_length=64)
    field_type = models.CharField(max_length=16, choices=TYPE_CHOICES, default=TEXT)
    label = models.CharField(max_length=200)
    help_text = models.CharField(max_length=255, blank=True)
    required = models.BooleanField(default=False)
    # [{"value": "x", "label": "..."}, ...] — used by select/radio.
    choices = models.JSONField(default=list, blank=True)
    # Same AND-groups-OR'd structure as RequestFormStep.condition, evaluated
    # against sibling fields within the same step.
    condition = models.JSONField(default=list, blank=True)
    is_system = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ('step__order', 'order')
        unique_together = [('step', 'key')]
        verbose_name = _('فیلد فرم ارزیابی')
        verbose_name_plural = _('فیلدهای فرم ارزیابی')

    def __str__(self):
        return f'{self.label} ({self.key})'
