"""Project delivery records: contractors, insurance policies and the equipment list."""
from __future__ import annotations

from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from apps.core.services import write_audit_log

from .. import repositories
from ..models import ContractorAssignment, ProjectInsurance, Request, RequestMessageLog, RequestStageNote
from . import lifecycle, project
from . import sms as sms_service

EXPIRY_WARNING_DAYS = 30


def in_scope(user, req) -> bool:
    return repositories.scope_requests_by_department(user, Request.objects.filter(pk=req.pk)).exists()


def can_manage_equipment(user, req) -> bool:
    return ((repositories.is_technical(user) or repositories.is_operations(user)
             or repositories.is_management(user)) and in_scope(user, req))


def can_manage_insurance(user, req) -> bool:
    return ((repositories.is_operations(user) or repositories.is_financial(user)
             or repositories.is_management(user)) and in_scope(user, req))


def can_assign(user, req) -> bool:
    return user.can_manage_contractors and in_scope(user, req)


def can_share_contact(user) -> bool:
    return repositories.is_management(user) or repositories.is_operations(user)


def can_see_equipment(user, req) -> bool:
    return project.is_owner(user, req) or (repositories.is_request_staff(user) and in_scope(user, req))


def equipment_for(user, req):
    rows = req.equipment_items.all()
    return rows.filter(visible_to_customer=True) if project.is_owner(user, req) else rows


def can_read_insurance(user, policy) -> bool:
    req = policy.request
    if project.is_owner(user, req):
        return policy.visible_to_customer
    return project.can_see_money(user, req)


def active_assignment(user, req):
    return ContractorAssignment.objects.filter(
        request=req, contractor=user, status=ContractorAssignment.Status.ACTIVE).first()


def assign_contractor(req, *, form, actor) -> ContractorAssignment:
    assignment = form.save(commit=False)
    assignment.request, assignment.assigned_by = req, actor
    if not can_share_contact(actor):
        assignment.share_contact = False
    assignment.save()
    name = assignment.contractor.get_full_name() or assignment.contractor.username
    write_audit_log(actor=actor, action='request.contractor_assigned', target_type='request', target_id=str(req.id),
                    metadata={'contractor': assignment.contractor_id})
    lifecycle.add_note(req, f'پیمانکار به پرونده وصل شد: {name} — {assignment.scope}', actor=actor,
                       kind=RequestStageNote.Kind.EDIT)
    mobile = assignment.contractor.phone_number
    if mobile:
        label = 'ارجاع پروژه به شما'
        sms_service.send_message(request=req, user=assignment.contractor, mobile=mobile, body=f'درخواست #{req.id}: {label}',
                                 message_type=RequestMessageLog.MessageType.STATUS_CHANGE,
                                 pattern=(sms_service.STATUS_PATTERN, [req.id, label]))
    return assignment


def finish_assignment(assignment, *, status, rating, note, actor) -> ContractorAssignment:
    Status = ContractorAssignment.Status
    if assignment.status != Status.ACTIVE:
        raise project.ProjectError('این همکاری قبلاً بسته شده است.')
    if status not in (Status.DONE, Status.CANCELLED):
        raise project.ProjectError('نتیجهٔ همکاری معتبر نیست.')
    if status == Status.DONE and rating not in (1, 2, 3, 4, 5):
        raise project.ProjectError('برای پایان کار، امتیاز ۱ تا ۵ را انتخاب کنید.')
    if status == Status.CANCELLED and not note:
        raise project.ProjectError('دلیل لغو همکاری را بنویسید.')
    assignment.status, assignment.rating, assignment.review_note = status, rating if status == Status.DONE else None, note[:2000]
    assignment.finished_at = timezone.now()
    assignment.save()
    write_audit_log(actor=actor, action='request.contractor_finished', target_type='request',
                    target_id=str(assignment.request_id), metadata={'assignment': assignment.id, 'status': status})
    lifecycle.add_note(assignment.request, f'همکاری پیمانکار: {assignment.get_status_display()}', actor=actor,
                       kind=RequestStageNote.Kind.EDIT)
    return assignment


def expiring_policies():
    return ProjectInsurance.objects.filter(
        end_date__lte=timezone.localdate() + timedelta(days=EXPIRY_WARNING_DAYS),
    ).exclude(request__status__in=(Request.Status.CLOSED, Request.Status.CANCELLED))


def insurance_gap(req) -> str:
    """The phase the case is in when it has no policy in force for that phase."""
    F, Phase = Request.FunnelStage, ProjectInsurance.Phase
    phase = {F.EXECUTION: Phase.EXECUTION, F.OPERATION: Phase.OPERATION}.get(req.funnel_stage)
    if phase is None or req.status in (Request.Status.CLOSED, Request.Status.CANCELLED):
        return ''
    covered = req.insurances.filter(phase=phase, end_date__gte=timezone.localdate()).exists()
    return '' if covered else phase.label


def staff_context(user, req) -> dict:
    see_money = project.can_see_money(user, req)
    return {
        'equipment_items': req.equipment_items.all(),
        'can_manage_equipment': can_manage_equipment(user, req),
        'insurances': req.insurances.all() if see_money else [],
        'can_see_insurance': see_money,
        'can_manage_insurance': can_manage_insurance(user, req),
        'insurance_gap': insurance_gap(req) if see_money else '',
        'contractor_assignments': req.contractor_assignments.select_related('contractor', 'contractor__contractor_profile'),
        'can_assign_contractor': can_assign(user, req),
        'rating_choices': range(1, 6),
    }


def customer_context(req) -> dict:
    return {
        'equipment_items': req.equipment_items.filter(visible_to_customer=True),
        'insurances': req.insurances.filter(visible_to_customer=True),
    }


def contractor_documents(user, req):
    return req.documents.filter(Q(visible_to_contractor=True) | Q(uploaded_by=user))

