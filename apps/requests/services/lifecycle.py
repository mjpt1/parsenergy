"""Request lifecycle and the status / department state machines.

Website lead pipeline:
  submit → MARKETING → SALES(qualification) → TECHNICAL
         → SALES(negotiation) → DONE (+ CRM handoff)

`transition()` remains the entry point for commercial `status` changes.
Department moves go through the named helpers below.
"""
from __future__ import annotations

from typing import Optional

from django.utils import timezone

from apps.core.services import write_audit_log

from ..models import ProjectContract, Request, RequestContract, RequestMessageLog, RequestPayment, RequestStageNote
from . import sms as sms_service

S = Request.Status
D = Request.Department
SP = Request.SalesPhase
F = Request.FunnelStage

# Allowed commercial status moves.
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    S.NEW: {S.OFFERED, S.HOLD, S.CLOSED, S.CANCELLED},
    S.OFFERED: {S.CONTRACT_GENERATED, S.HOLD, S.CLOSED, S.CANCELLED},
    S.CONTRACT_GENERATED: {S.CONTRACT_APPROVED, S.HOLD, S.CLOSED, S.CANCELLED},
    S.CONTRACT_APPROVED: {S.AWAITING_PAYMENT, S.HOLD, S.CLOSED, S.CANCELLED},
    S.AWAITING_PAYMENT: {S.PAID, S.HOLD, S.CLOSED, S.CANCELLED},
    S.PAID: set(),
    S.HOLD: {S.NEW, S.OFFERED, S.CLOSED, S.CANCELLED},
    S.CLOSED: set(),
    S.CANCELLED: set(),
}

# Soft SLA for operations dashboard (hours in current department stage).
STAGE_SLA_HOURS = 72


# Which team and sales phase own each funnel stage.
FUNNEL_ROUTE = {
    F.LEAD: (D.MARKETING, ''),
    F.QUALIFICATION: (D.SALES, SP.QUALIFICATION),
    F.INITIAL_DESIGN: (D.TECHNICAL, ''),
    F.FIRST_CONTRACT: (D.SALES, SP.NEGOTIATION),
    F.COMMERCIAL_OFFER: (D.TECHNICAL, ''),
    F.SECOND_CONTRACT: (D.SALES, SP.NEGOTIATION),
    F.EXECUTION: (D.DONE, ''),
    F.OPERATION: (D.DONE, ''),
}
#: Stages whose history the technical team may read; the others hold commercial talk.
TECHNICAL_STAGES = (F.INITIAL_DESIGN, F.COMMERCIAL_OFFER, F.EXECUTION, F.OPERATION)


def stage_for_department(department, sales_phase='') -> str:
    if department == D.TECHNICAL:
        return F.INITIAL_DESIGN
    if department == D.SALES:
        return F.FIRST_CONTRACT if sales_phase == SP.NEGOTIATION else F.QUALIFICATION
    return F.EXECUTION if department == D.DONE else F.LEAD


class TransitionError(Exception):
    """Raised when an illegal status transition is attempted."""


class DepartmentError(Exception):
    """Raised when an illegal department move is attempted."""


def create_request(*, full_name, mobile, province, city='', description='', user=None,
                   **extra_fields) -> Request:
    now = timezone.now()
    extra_fields.setdefault('department', D.MARKETING)
    extra_fields.setdefault('stage_entered_at', now)
    extra_fields.setdefault('funnel_stage', stage_for_department(
        extra_fields['department'], extra_fields.get('sales_phase', '')))
    request = Request.objects.create(
        full_name=full_name,
        mobile=mobile,
        province=province,
        city=city,
        description=description,
        user=user,
        **extra_fields,
    )
    write_audit_log(
        actor=user,
        action='request.created',
        target_type='request',
        target_id=str(request.id),
        metadata={'mobile': mobile, 'province': province, 'department': request.department},
    )
    return request


CUSTOMER_ROLES = ('customer', 'owner')
SESSION_MOBILE = 'verified_mobile'


def is_customer_account(user) -> bool:
    """A customer's own account — never staff, whatever number they sign in with."""
    return bool(user and user.is_authenticated and not user.is_superuser and not user.is_staff
                and getattr(user, 'role', '') in CUSTOMER_ROLES)


def link_requests(user, mobile) -> int:
    """Give `user` every unowned request made with `mobile`.

    Only call this with a mobile the user proved by SMS code: matching on an
    unverified number would hand a stranger's request to whoever typed it.
    """
    if not (mobile and is_customer_account(user)):
        return 0
    return Request.objects.filter(mobile=mobile, user__isnull=True).update(user=user)


def link_session_requests(http_request) -> int:
    """Pick up requests made since sign-in (exhibition QR, a second form)."""
    return link_requests(http_request.user, http_request.session.get(SESSION_MOBILE))


def customer_account_for(mobile, *, create=False):
    """The SMS-login account for `mobile`, made on demand for a new customer.

    Only password-less accounts named by the mobile qualify: those are the
    ones the SMS door creates, so whoever signs in to one has proved the
    number. A password account with that name could be anyone's, so it is
    never chosen (returns None) and never overwritten.
    """
    from django.contrib.auth import get_user_model
    User = get_user_model()
    user = User.objects.filter(username=mobile).first()
    if user is not None:
        ok = is_customer_account(user) and not user.has_usable_password()
        return user if ok else None
    if not create:
        return None
    user = User(username=mobile, phone_number=mobile, role=User.Role.CUSTOMER)
    user.set_unusable_password()
    user.save()
    return user


def attach_user(request: Request, user) -> Request:
    """Link a request to its owner after OTP registration/login."""
    if request.user_id is None:
        request.user = user
        request.save(update_fields=['user', 'updated_at'])
        write_audit_log(
            actor=user,
            action='request.attached_user',
            target_type='request',
            target_id=str(request.id),
        )
    return request


def _send_status_sms(request: Request, label) -> None:
    if not request.mobile:
        return
    label = str(label)
    sms_service.send_message(
        request=request,
        user=request.user,
        mobile=request.mobile,
        message_type=RequestMessageLog.MessageType.STATUS_CHANGE,
        body=f'وضعیت درخواست #{request.id}: {label}',
        pattern=(sms_service.STATUS_PATTERN, [request.id, label]),
    )


def notify_customer(request: Request, label) -> None:
    _send_status_sms(request, label)


def _record_status_sms(request: Request) -> None:
    _send_status_sms(request, request.get_status_display())


def add_note(request: Request, body: str, *, actor=None, kind=RequestStageNote.Kind.NOTE) -> RequestStageNote:
    return RequestStageNote.objects.create(
        request=request, stage=request.funnel_stage, kind=kind, body=body, created_by=actor)


def _enter_stage(request: Request, department: str, *, sales_phase: str = '', stage=None) -> None:
    request.department = department
    request.sales_phase = sales_phase
    request.stage_entered_at = timezone.now()
    if stage:
        request.funnel_stage = stage


def _announce_stage(request: Request, *, actor=None, note: str = '', notify: bool = True) -> None:
    """Write the move into the case history and tell the customer."""
    label = request.get_funnel_stage_display()
    add_note(request, f'ورود به مرحلهٔ «{label}»' + (f': {note}' if note else ''),
             actor=actor, kind=RequestStageNote.Kind.MOVE)
    if notify:
        _send_status_sms(request, label)


def set_funnel_stage(request: Request, stage: str, *, actor=None, note: str = '', notify: bool = True) -> Request:
    """Management correction: put a case on any stage, with the reason on record."""
    if stage not in FUNNEL_ROUTE:
        raise DepartmentError('مرحلهٔ انتخاب‌شده معتبر نیست.')
    if stage == request.funnel_stage:
        raise DepartmentError('پرونده هم‌اکنون در همین مرحله است.')
    if request.status in (S.CLOSED, S.CANCELLED):
        raise DepartmentError('مرحلهٔ پروندهٔ بسته یا لغوشده قابل تغییر نیست.')
    department, phase = FUNNEL_ROUTE[stage]
    _enter_stage(request, department, sales_phase=phase, stage=stage)
    request.save(update_fields=['department', 'sales_phase', 'stage_entered_at', 'funnel_stage', 'updated_at'])
    write_audit_log(actor=actor, action='request.funnel_stage_set', target_type='request',
                    target_id=str(request.id), metadata={'stage': str(stage)})
    _announce_stage(request, actor=actor, note=note, notify=notify)
    return request


def start_commercial_offer(request: Request, *, actor=None) -> Request:
    """After the first contract: back to technical for the full offer."""
    if request.department != D.SALES or request.funnel_stage != F.FIRST_CONTRACT:
        raise DepartmentError('این پرونده در مرحلهٔ قرارداد اول نیست.')
    contract = RequestContract.objects.filter(request=request).first()
    if contract is None or contract.status != RequestContract.Status.APPROVED:
        raise DepartmentError('ابتدا قرارداد اول باید تأیید شود.')
    if request.payments.filter(status=RequestPayment.Status.PAID).exclude(
            finance_status=RequestPayment.Finance.APPROVED).exists():
        raise DepartmentError('پرداخت قرارداد اول هنوز تأیید مالی نشده است.')
    department, phase = FUNNEL_ROUTE[F.COMMERCIAL_OFFER]
    _enter_stage(request, department, sales_phase=phase, stage=F.COMMERCIAL_OFFER)
    request.save(update_fields=['department', 'sales_phase', 'stage_entered_at', 'funnel_stage', 'updated_at'])
    write_audit_log(actor=actor, action='request.commercial_offer_started',
                    target_type='request', target_id=str(request.id))
    _announce_stage(request, actor=actor)
    return request


def start_operation(request: Request, *, actor=None) -> Request:
    if request.funnel_stage != F.EXECUTION:
        raise DepartmentError('این پرونده در مرحلهٔ اجرا نیست.')
    if not request.plant_id:
        raise DepartmentError('ابتدا نیروگاه این پرونده را راه‌اندازی کنید.')
    _enter_stage(request, D.DONE, stage=F.OPERATION)
    request.save(update_fields=['department', 'sales_phase', 'stage_entered_at', 'funnel_stage', 'updated_at'])
    write_audit_log(actor=actor, action='request.operation_started',
                    target_type='request', target_id=str(request.id))
    _announce_stage(request, actor=actor)
    return request


def refer_marketing_to_sales(request: Request, *, actor=None) -> Request:
    """Marketing finishes lead quality review (no customer contact) → sales."""
    if request.department != D.MARKETING:
        raise DepartmentError('این درخواست در صف بازاریابی نیست.')
    _enter_stage(request, D.SALES, sales_phase=SP.QUALIFICATION, stage=F.QUALIFICATION)
    request.marketing_reviewed_by = actor
    request.marketing_reviewed_at = timezone.now()
    request.save(update_fields=[
        'department', 'sales_phase', 'stage_entered_at', 'funnel_stage',
        'marketing_reviewed_by', 'marketing_reviewed_at', 'updated_at',
    ])
    write_audit_log(
        actor=actor, action='request.marketing_to_sales',
        target_type='request', target_id=str(request.id),
        metadata={'to_department': D.SALES, 'sales_phase': SP.QUALIFICATION},
    )
    _announce_stage(request, actor=actor)
    return request


def triage_to_technical(request: Request, *, actor=None, priority=None) -> Request:
    """Compatibility wrapper: sales qualification → technical."""
    return refer_sales_to_technical(request, actor=actor, priority=priority)


def refer_sales_to_technical(request: Request, *, actor=None, priority=None) -> Request:
    """Sales qualification: set priority and send to technical evaluation."""
    if request.department != D.SALES:
        raise DepartmentError('این درخواست در صف فروش نیست.')
    if request.sales_phase == SP.NEGOTIATION:
        raise DepartmentError('این درخواست در مذاکره است، نه صلاحیت‌سنجی.')
    if priority in dict(Request.Priority.choices):
        request.priority = priority
    if actor and not request.sales_assignee_id:
        request.sales_assignee = actor
    _enter_stage(request, D.TECHNICAL, sales_phase='', stage=F.INITIAL_DESIGN)
    request.triaged_by = actor
    request.triaged_at = timezone.now()
    request.save(update_fields=[
        'department', 'sales_phase', 'stage_entered_at', 'funnel_stage', 'priority',
        'sales_assignee', 'triaged_by', 'triaged_at', 'updated_at',
    ])
    write_audit_log(
        actor=actor, action='request.referred_to_technical',
        target_type='request', target_id=str(request.id),
        metadata={'priority': request.priority, 'to_department': D.TECHNICAL},
    )
    _announce_stage(request, actor=actor)
    return request


def hold_request(request: Request, *, actor=None) -> Request:
    """Sales puts a lead on hold during qualification."""
    if request.department != D.SALES:
        raise DepartmentError('فقط از صف فروش می‌توان درخواست را معلق کرد.')
    return transition(request, S.HOLD, actor=actor, notify=True)


def close_lost(request: Request, *, actor=None) -> Request:
    """Sales marks the lead as closed / lost."""
    if request.department not in (D.SALES, D.MARKETING, D.TECHNICAL):
        raise DepartmentError('بستن درخواست در این مرحله مجاز نیست.')
    request = transition(request, S.CLOSED, actor=actor, notify=True)
    _enter_stage(request, D.DONE, sales_phase='')
    request.save(update_fields=['department', 'sales_phase', 'stage_entered_at', 'updated_at'])
    write_audit_log(
        actor=actor, action='request.closed_lost',
        target_type='request', target_id=str(request.id),
    )
    return request


def stop_request(request: Request, to_status: str, *, reason: str, note: str = '', actor=None) -> Request:
    """Cancel a case or mark it lost, always with the reason on record."""
    if reason not in Request.StopReason.values:
        raise DepartmentError('دلیل لغو یا بستن پرونده را انتخاب کنید.')
    if reason == Request.StopReason.OTHER and not note:
        raise DepartmentError('برای گزینهٔ «سایر»، توضیح دلیل لازم است.')
    if to_status == S.CLOSED:
        close_lost(request, actor=actor)
    elif to_status == S.CANCELLED:
        transition(request, S.CANCELLED, actor=actor, metadata={'reason': reason})
    else:
        raise TransitionError('این تغییر وضعیت مجاز نیست.')
    request.stop_reason, request.stop_note = reason, note
    request.save(update_fields=['stop_reason', 'stop_note', 'updated_at'])
    body = f'{request.get_status_display()}: {request.get_stop_reason_display()}' + (f' — {note}' if note else '')
    add_note(request, body, actor=actor, kind=RequestStageNote.Kind.STOP)
    return request


def refer_to_sales(request: Request, *, actor=None, note: str = '') -> Request:
    """Technical finishes pricing (offers) and refers back to sales negotiation."""
    if request.department != D.TECHNICAL:
        raise DepartmentError('این درخواست در صف فنی نیست.')
    if not request.offers.exists():
        raise DepartmentError('قبل از ارجاع به فروش، حداقل یک پیشنهاد فنی ثبت کنید.')
    stage = F.SECOND_CONTRACT if request.funnel_stage == F.COMMERCIAL_OFFER else F.FIRST_CONTRACT
    _enter_stage(request, D.SALES, sales_phase=SP.NEGOTIATION, stage=stage)
    request.technical_completed_by = actor
    request.technical_completed_at = timezone.now()
    if note:
        request.technical_note = note
    request.save(update_fields=[
        'department', 'sales_phase', 'stage_entered_at', 'funnel_stage',
        'technical_completed_by', 'technical_completed_at',
        'technical_note', 'updated_at',
    ])
    write_audit_log(
        actor=actor, action='request.referred_to_sales',
        target_type='request', target_id=str(request.id),
        metadata={'to_department': D.SALES, 'sales_phase': SP.NEGOTIATION},
    )
    _announce_stage(request, actor=actor, note=note)
    return request


def close_by_sales(request: Request, *, actor=None) -> Request:
    """Sales closes a successful deal and hands the project off to CRM."""
    if request.department != D.SALES:
        raise DepartmentError('این درخواست در صف فروش نیست.')
    if request.funnel_stage == F.SECOND_CONTRACT and not ProjectContract.objects.filter(request=request).exists():
        raise DepartmentError('ابتدا قرارداد دوم و برنامهٔ پرداخت را ثبت کنید.')
    _enter_stage(request, D.DONE, sales_phase='', stage=F.EXECUTION)
    request.sales_completed_by = actor
    request.sales_completed_at = timezone.now()
    request.crm_transferred = True
    request.crm_transferred_at = timezone.now()
    request.crm_transferred_by = actor
    request.save(update_fields=[
        'department', 'sales_phase', 'stage_entered_at', 'funnel_stage',
        'sales_completed_by', 'sales_completed_at',
        'crm_transferred', 'crm_transferred_at', 'crm_transferred_by',
        'updated_at',
    ])
    write_audit_log(
        actor=actor, action='request.closed_by_sales',
        target_type='request', target_id=str(request.id),
        metadata={'to_department': D.DONE, 'crm_transferred': True},
    )
    _announce_stage(request, actor=actor)
    return request


def transition(request: Request, to_status: str, *, actor=None, notify: bool = True,
               metadata: Optional[dict] = None) -> Request:
    allowed = ALLOWED_TRANSITIONS.get(request.status, set())
    if to_status not in allowed:
        raise TransitionError(f'گذار نامعتبر وضعیت: {request.status} → {to_status}')

    previous = request.status
    request.status = to_status
    request.save(update_fields=['status', 'updated_at'])

    write_audit_log(
        actor=actor,
        action='request.status_changed',
        target_type='request',
        target_id=str(request.id),
        metadata={'from': previous, 'to': to_status, **(metadata or {})},
    )
    if notify:
        _record_status_sms(request)
    return request
