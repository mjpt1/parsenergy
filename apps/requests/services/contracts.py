"""Contract generation and OTP-based approval."""
from __future__ import annotations

import re

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.services import write_audit_log

from ..models import ContractTemplate, OtpVerification, Request, RequestContract, RequestOffer
from . import lifecycle, otp as otp_service


class ContractError(Exception):
    """Raised on contract workflow violations."""


# Built-in fallback used when no ContractTemplate has been configured in the admin.
DEFAULT_CONTRACT_TEMPLATE = (
    'قرارداد خدمات\n'
    'شماره قرارداد: {{contract_number}}\n'
    'شماره درخواست: {{request_id}}\n'
    'مشتری: {{full_name}}\n'
    'کد ملی: {{national_id}}\n'
    'موبایل: {{mobile}}\n'
    'استان: {{province}}\n'
    'عنوان پیشنهاد: {{offer_title}}\n'
    'مبلغ: {{amount}} {{currency}}\n'
    'ارزش افزوده: {{vat_percent}}٪ ({{vat_amount}} {{currency}})\n'
    'مبلغ کل قابل پرداخت: {{total_amount}} {{currency}}\n'
    'تاریخ تولید: {{date}}\n'
)

# Placeholders an admin may use in the contract template (shown on the settings page).
TEMPLATE_PLACEHOLDERS = [
    'contract_number', 'request_id', 'full_name', 'national_id', 'mobile',
    'province', 'city', 'description', 'offer_title', 'amount', 'currency',
    'vat_percent', 'vat_amount', 'total_amount', 'date',
]


def _generate_contract_number(request: Request) -> str:
    return f'C-{request.id}-{timezone.now():%Y%m%d%H%M%S}'


def get_active_template_text() -> str:
    """The active admin-configured template body, or the built-in default."""
    template = ContractTemplate.objects.filter(is_active=True).order_by('-updated_at').first()
    if template and template.body.strip():
        return template.body
    return DEFAULT_CONTRACT_TEMPLATE


def read_uploaded_template(uploaded_file) -> str:
    """Extract plain text from an uploaded template file (.txt or .docx)."""
    name = (getattr(uploaded_file, 'name', '') or '').lower()
    if name.endswith('.docx'):
        from docx import Document  # local import: only needed for Word uploads
        document = Document(uploaded_file)
        return '\n'.join(p.text for p in document.paragraphs)
    raw = uploaded_file.read()
    if isinstance(raw, bytes):
        return raw.decode('utf-8', 'replace')
    return str(raw)


def build_contract_docx(contract):
    """Render a contract (company header/footer + body) to a .docx in memory.

    Returns a BytesIO positioned at 0, ready to stream as a download.
    """
    from io import BytesIO

    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn
    from docx.shared import Pt

    from ..models import ContractSettings

    s = ContractSettings.load()
    doc = Document()

    def para(text, *, bold=False, align=WD_ALIGN_PARAGRAPH.RIGHT, size=None):
        p = doc.add_paragraph()
        p.alignment = align
        # Mark the paragraph and run right-to-left for correct Persian layout.
        p_pr = p._p.get_or_add_pPr()
        p_pr.append(p_pr.makeelement(qn('w:bidi'), {}))
        run = p.add_run(text or '')
        run.bold = bold
        if size:
            run.font.size = Pt(size)
        r_pr = run._r.get_or_add_rPr()
        r_pr.append(r_pr.makeelement(qn('w:rtl'), {}))
        return p

    if s.company_name:
        para(s.company_name, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, size=16)
    if s.company_address:
        para(s.company_address, align=WD_ALIGN_PARAGRAPH.CENTER)
    if s.company_phone:
        para(s.company_phone, align=WD_ALIGN_PARAGRAPH.CENTER)
    if s.header_note:
        para(s.header_note)
    if s.company_name or s.header_note:
        para('')

    for line in (contract.body or '').split('\n'):
        para(line)

    if s.footer_note:
        para('')
        para(s.footer_note)
    if s.signature_text:
        para('')
        para(s.signature_text)

    buf = BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf


def render_contract_body(request: Request, offer: RequestOffer, contract_number: str) -> str:
    """Fill the active template's {{placeholders}} with this request/offer's data."""
    text = get_active_template_text()
    context = {
        'contract_number': contract_number,
        'request_id': request.id,
        'full_name': request.full_name,
        'national_id': request.national_id or '',
        'mobile': request.mobile,
        'province': request.province,
        'city': request.city or '',
        'description': request.description or '',
        'offer_title': offer.title,
        'amount': offer.amount,
        'currency': offer.currency,
        'vat_percent': offer.vat_percent,
        'vat_amount': offer.vat_amount,
        'total_amount': offer.total_amount,
        'date': timezone.localtime(timezone.now()).strftime('%Y-%m-%d %H:%M'),
    }
    for key, value in context.items():
        text = re.sub(r'\{\{\s*' + re.escape(key) + r'\s*\}\}', str(value), text)
    return text


@transaction.atomic
def generate_contract(*, request: Request, offer: RequestOffer, actor=None) -> RequestContract:
    """Create (or regenerate) the contract for the selected offer."""
    contract = RequestContract.objects.filter(request=request).first()
    if contract is not None:
        if contract.status == RequestContract.Status.APPROVED:
            raise ContractError(_('قرارداد قبلاً تأیید شده و قابل تغییر نیست.'))
        contract.offer = offer
        contract.body = render_contract_body(request, offer, contract.contract_number)
        contract.status = RequestContract.Status.GENERATED
        contract.save(update_fields=['offer', 'body', 'status'])
    else:
        number = _generate_contract_number(request)
        contract = RequestContract.objects.create(
            request=request,
            offer=offer,
            contract_number=number,
            body=render_contract_body(request, offer, number),
            status=RequestContract.Status.GENERATED,
        )
    write_audit_log(
        actor=actor,
        action='contract.generated',
        target_type='request_contract',
        target_id=str(contract.id),
        metadata={'request': request.id, 'offer': offer.id},
    )
    if request.status == Request.Status.OFFERED:
        lifecycle.transition(request, Request.Status.CONTRACT_GENERATED, actor=actor)
    return contract


def request_approval_otp(contract: RequestContract) -> OtpVerification:
    """Send the OTP the customer uses to approve the contract."""
    return otp_service.issue(
        mobile=contract.request.mobile,
        purpose=OtpVerification.Purpose.CONTRACT_APPROVAL,
        request=contract.request,
    )


@transaction.atomic
def approve_with_otp(*, contract: RequestContract, code: str, actor=None) -> RequestContract:
    if contract.status == RequestContract.Status.APPROVED:
        raise ContractError(_('این قرارداد قبلاً تأیید شده است.'))
    # Raises OtpError on failure.
    otp_service.verify(
        mobile=contract.request.mobile,
        code=code,
        purpose=OtpVerification.Purpose.CONTRACT_APPROVAL,
    )
    contract.status = RequestContract.Status.APPROVED
    contract.approved_at = timezone.now()
    contract.save(update_fields=['status', 'approved_at'])
    write_audit_log(
        actor=actor,
        action='contract.approved',
        target_type='request_contract',
        target_id=str(contract.id),
    )
    if contract.request.status == Request.Status.CONTRACT_GENERATED:
        lifecycle.transition(contract.request, Request.Status.CONTRACT_APPROVED, actor=actor)
    return contract
