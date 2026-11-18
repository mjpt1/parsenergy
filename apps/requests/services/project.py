"""The second contract, its three instalments, finance approval and project files."""
from __future__ import annotations

import os

from django.utils import timezone

from apps.core.services import write_audit_log

from .. import repositories
from ..models import (ContractInstallment, ContractorAssignment, ProjectContract, Request, RequestDocument, RequestPayment,
                      RequestStageNote)
from . import lifecycle

_OFFICE_OLD = (b'\xd0\xcf\x11\xe0',)
_ZIP = (b'PK\x03\x04',)
SIGNATURES = {
    '.pdf': (b'%PDF',), '.jpg': (b'\xff\xd8\xff',), '.jpeg': (b'\xff\xd8\xff',), '.png': (b'\x89PNG',),
    '.doc': _OFFICE_OLD, '.xls': _OFFICE_OLD, '.docx': _ZIP, '.xlsx': _ZIP, '.zip': _ZIP, '.dwg': (b'AC10',),
}
RECEIPT_TYPES = ('.pdf', '.jpg', '.jpeg', '.png')
CONTRACT_TYPES = ('.pdf', '.jpg', '.jpeg', '.png', '.doc', '.docx')
MAX_RECEIPT_BYTES = 5 * 1024 * 1024
MAX_DOCUMENT_BYTES = 20 * 1024 * 1024
TECHNICAL_KINDS = (RequestDocument.Kind.TECHNICAL, RequestDocument.Kind.PROPOSAL)


class ProjectError(Exception):
    """A rule of the contract or payment flow was not met."""


def check_upload(upload, *, allowed=tuple(SIGNATURES), max_bytes=MAX_DOCUMENT_BYTES):
    """Accept a file only if its size, extension and first bytes agree."""
    if upload is None:
        raise ProjectError('فایل را انتخاب کنید.')
    extension = os.path.splitext(upload.name)[1].lower()
    if extension not in allowed:
        raise ProjectError('نوع فایل مجاز نیست. نوع‌های مجاز: ' + '، '.join(e[1:] for e in allowed))
    if upload.size > max_bytes:
        raise ProjectError(f'حجم فایل باید کمتر از {max_bytes // (1024 * 1024)} مگابایت باشد.')
    head = upload.read(8)
    upload.seek(0)
    if not any(head.startswith(mark) for mark in SIGNATURES[extension]):
        raise ProjectError('محتوای فایل با پسوند آن یکی نیست.')
    return upload


def _in_scope(user, req) -> bool:
    return repositories.scope_requests_by_department(user, Request.objects.filter(pk=req.pk)).exists()


def is_owner(user, req) -> bool:
    return bool(req.user_id and req.user_id == user.pk)


def can_review(user) -> bool:
    return repositories.is_financial(user) or repositories.is_management(user)


def can_see_money(user, req) -> bool:
    if is_owner(user, req):
        return True
    return repositories.is_request_staff(user) and not repositories.is_identity_restricted(user) and _in_scope(user, req)


def can_manage_contract(user, req) -> bool:
    return ((repositories.is_sales(user) or repositories.is_management(user))
            and req.funnel_stage == Request.FunnelStage.SECOND_CONTRACT
            and req.department == Request.Department.SALES
            and req.status not in (Request.Status.CLOSED, Request.Status.CANCELLED))


def can_submit_receipt(user, req) -> bool:
    if is_owner(user, req):
        return True
    return ((repositories.is_sales(user) or repositories.is_financial(user) or repositories.is_management(user)
             or repositories.is_operations(user)) and _in_scope(user, req))


def can_upload_document(user, req) -> bool:
    return repositories.is_request_staff(user) and _in_scope(user, req)


def visible_documents(user, req):
    documents = req.documents.select_related('uploaded_by')
    if repositories.is_identity_restricted(user):
        return documents.filter(kind__in=TECHNICAL_KINDS)
    return documents


def can_read_document(user, document) -> bool:
    req = document.request
    if is_owner(user, req):
        return document.visible_to_customer
    if user.role == 'contractor':
        return ((document.visible_to_contractor or document.uploaded_by_id == user.pk)
                and ContractorAssignment.objects.filter(
                    request=req, contractor=user, status=ContractorAssignment.Status.ACTIVE).exists())
    if not (repositories.is_request_staff(user) and _in_scope(user, req)):
        return False
    return not repositories.is_identity_restricted(user) or document.kind in TECHNICAL_KINDS


def add_document(req, *, upload, title, kind, visible_to_customer, actor,
                 visible_to_contractor=False) -> RequestDocument:
    check_upload(upload)
    if kind not in RequestDocument.Kind.values:
        raise ProjectError('نوع مستند معتبر نیست.')
    restricted = repositories.is_identity_restricted(actor)
    if restricted and kind not in TECHNICAL_KINDS:
        raise ProjectError('بخش فنی فقط مستند فنی ثبت می‌کند.')
    document = RequestDocument.objects.create(
        request=req, stage=req.funnel_stage, kind=kind, title=(title or upload.name)[:200], file=upload,
        original_name=os.path.basename(upload.name)[:255], size=upload.size,
        visible_to_customer=visible_to_customer and not restricted,
        visible_to_contractor=visible_to_contractor, uploaded_by=actor)
    write_audit_log(actor=actor, action='request.document_added', target_type='request', target_id=str(req.id),
                    metadata={'document': document.id, 'kind': kind})
    lifecycle.add_note(req, f'مستند ثبت شد: {document.title}', actor=actor, kind=RequestStageNote.Kind.EDIT)
    return document


def contract_locked(contract) -> bool:
    return contract.installments.exclude(status=ContractInstallment.Status.PENDING).exists()


def save_contract(req, data, *, actor) -> ProjectContract:
    contract = ProjectContract.objects.filter(request=req).first()
    if contract is not None and contract_locked(contract):
        raise ProjectError('برای این قرارداد پرداخت ثبت شده و دیگر قابل تغییر نیست.')
    created = contract is None
    contract = contract or ProjectContract(request=req, created_by=actor)
    contract.contract_number = data['contract_number']
    contract.signed_on = data['signed_on']
    contract.total_amount = data['total_amount']
    contract.description = data.get('description', '')
    upload = data.get('file')
    if upload:
        if contract.file:
            contract.file.delete(save=False)
        contract.file = upload
        contract.file_name = os.path.basename(upload.name)[:255]
    contract.save()
    for number in (1, 2, 3):
        ContractInstallment.objects.update_or_create(contract=contract, number=number, defaults={
            'title': data[f'title_{number}'], 'amount': data[f'amount_{number}'], 'due_date': data[f'due_{number}']})
    write_audit_log(actor=actor, action='request.project_contract_saved', target_type='request',
                    target_id=str(req.id), metadata={'contract': contract.id, 'created': created})
    lifecycle.add_note(req, f'قرارداد دوم {"ثبت" if created else "ویرایش"} شد: {contract.contract_number}',
                       actor=actor, kind=RequestStageNote.Kind.EDIT)
    if created:
        lifecycle.notify_customer(req, 'قرارداد دوم و برنامهٔ پرداخت ثبت شد')
    return contract


def submit_receipt(installment, *, upload, paid_on, reference, actor) -> ContractInstallment:
    Status = ContractInstallment.Status
    if installment.status not in (Status.PENDING, Status.REJECTED):
        raise ProjectError('رسید این قسط قبلاً ثبت شده است.')
    if paid_on is None:
        raise ProjectError('تاریخ پرداخت را درست وارد کنید.')
    if paid_on > timezone.localdate():
        raise ProjectError('تاریخ پرداخت نمی‌تواند بعد از امروز باشد.')
    check_upload(upload, allowed=RECEIPT_TYPES, max_bytes=MAX_RECEIPT_BYTES)
    if installment.receipt:
        installment.receipt.delete(save=False)
    installment.receipt = upload
    installment.receipt_name = os.path.basename(upload.name)[:255]
    installment.paid_on, installment.reference = paid_on, reference[:100]
    installment.status = Status.SUBMITTED
    installment.submitted_by, installment.submitted_at = actor, timezone.now()
    installment.finance_by, installment.finance_at, installment.finance_note = None, None, ''
    installment.save()
    req = installment.contract.request
    write_audit_log(actor=actor, action='installment.receipt_submitted', target_type='contract_installment',
                    target_id=str(installment.id))
    lifecycle.add_note(req, f'رسید قسط {installment.number} برای تأیید مالی ثبت شد.', actor=actor,
                       kind=RequestStageNote.Kind.EDIT)
    return installment


def _decide(decision, note):
    if decision not in ('approve', 'reject'):
        raise ProjectError('تصمیم معتبر نیست.')
    if decision == 'reject' and not note:
        raise ProjectError('دلیل رد را بنویسید.')
    return decision == 'approve'


def review_installment(installment, *, decision, note, actor) -> ContractInstallment:
    if not can_review(actor):
        raise ProjectError('تأیید پرداخت برعهدهٔ واحد مالی است.')
    approved = _decide(decision, note)
    Status = ContractInstallment.Status
    if installment.status != Status.SUBMITTED:
        raise ProjectError('این قسط منتظر تأیید مالی نیست.')
    installment.status = Status.APPROVED if approved else Status.REJECTED
    installment.finance_by, installment.finance_at, installment.finance_note = actor, timezone.now(), note[:1000]
    installment.save()
    req = installment.contract.request
    label = f'قسط {installment.number}: ' + ('تأیید مالی شد' if approved else 'نیاز به اصلاح رسید')
    write_audit_log(actor=actor, action='installment.reviewed', target_type='contract_installment',
                    target_id=str(installment.id), metadata={'decision': decision})
    lifecycle.add_note(req, label + (f' — {note}' if note else ''), actor=actor, kind=RequestStageNote.Kind.EDIT)
    lifecycle.notify_customer(req, label)
    return installment


def review_payment(payment, *, decision, note, actor) -> RequestPayment:
    if not can_review(actor):
        raise ProjectError('تأیید پرداخت برعهدهٔ واحد مالی است.')
    approved = _decide(decision, note)
    if payment.status != RequestPayment.Status.PAID or payment.finance_status != RequestPayment.Finance.PENDING:
        raise ProjectError('این پرداخت منتظر تأیید مالی نیست.')
    payment.finance_status = RequestPayment.Finance.APPROVED if approved else RequestPayment.Finance.REJECTED
    payment.finance_by, payment.finance_at, payment.finance_note = actor, timezone.now(), note[:1000]
    payment.save(update_fields=['finance_status', 'finance_by', 'finance_at', 'finance_note', 'updated_at'])
    write_audit_log(actor=actor, action='payment.finance_reviewed', target_type='request_payment',
                    target_id=str(payment.id), metadata={'decision': decision})
    lifecycle.add_note(payment.request, f'پرداخت #{payment.id}: {payment.get_finance_status_display()}'
                       + (f' — {note}' if note else ''), actor=actor, kind=RequestStageNote.Kind.EDIT)
    return payment


def finance_pending_count() -> int:
    return (ContractInstallment.objects.filter(status=ContractInstallment.Status.SUBMITTED).count()
            + RequestPayment.objects.filter(status=RequestPayment.Status.PAID,
                                            finance_status=RequestPayment.Finance.PENDING).count())


def staff_context(user, req) -> dict:
    see_money = can_see_money(user, req)
    contract = ProjectContract.objects.filter(request=req).first() if see_money else None
    return {
        'project_contract': contract,
        'project_installments': list(contract.installments.all()) if contract else [],
        'can_see_project_money': see_money,
        'can_manage_project': can_manage_contract(user, req) and not (contract and contract_locked(contract)),
        'can_submit_receipt': can_submit_receipt(user, req),
        'can_review_finance': can_review(user),
        'project_documents': visible_documents(user, req),
        'document_kinds': [(k, l) for k, l in RequestDocument.Kind.choices
                           if not repositories.is_identity_restricted(user) or k in TECHNICAL_KINDS],
        'can_publish_document': not repositories.is_identity_restricted(user),
        'can_upload_document': can_upload_document(user, req),
    }


def customer_context(req) -> dict:
    contract = ProjectContract.objects.filter(request=req).first()
    return {
        'project_contract': contract,
        'project_installments': list(contract.installments.all()) if contract else [],
        'project_documents': req.documents.filter(visible_to_customer=True),
    }
