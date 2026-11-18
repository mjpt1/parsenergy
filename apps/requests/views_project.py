"""Second contract, instalment receipts, finance approval and protected project files."""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.core.dates import parse_user_date

from . import repositories
from .forms import ProjectContractForm
from .models import ContractInstallment, ProjectContract, Request, RequestDocument, RequestPayment
from .services import project


def _back(user, req):
    return redirect('requests:my-detail', pk=req.pk) if project.is_owner(user, req) else redirect(
        'requests:admin-detail', pk=req.pk)


def _download(field, name):
    if not field:
        raise Http404
    response = FileResponse(field.open('rb'), as_attachment=True, filename=name or field.name.rsplit('/', 1)[-1])
    response['X-Content-Type-Options'] = 'nosniff'
    return response


@login_required
def contract_form(request, pk):
    req = get_object_or_404(Request, pk=pk)
    if not project.can_manage_contract(request.user, req):
        raise PermissionDenied
    contract = ProjectContract.objects.filter(request=req).first()
    if contract is not None and project.contract_locked(contract):
        messages.error(request, 'برای این قرارداد پرداخت ثبت شده و دیگر قابل تغییر نیست.')
        return redirect('requests:admin-detail', pk=pk)
    form = ProjectContractForm(request.POST or None, request.FILES or None, contract=contract)
    if request.method == 'POST' and form.is_valid():
        try:
            project.save_contract(req, form.cleaned_data, actor=request.user)
            messages.success(request, 'قرارداد دوم و برنامهٔ پرداخت ثبت شد.')
            return redirect('requests:admin-detail', pk=pk)
        except project.ProjectError as exc:
            form.add_error(None, str(exc))
    return render(request, 'requests/admin/project_contract_form.html', {
        'form': form, 'req': req, 'page_title': 'قرارداد دوم',
        'rows': [(n, form[f'title_{n}'], form[f'amount_{n}'], form[f'due_{n}']) for n in (1, 2, 3)]})


@login_required
def contract_file(request, pk):
    contract = get_object_or_404(ProjectContract.objects.select_related('request'), pk=pk)
    if not project.can_see_money(request.user, contract.request):
        raise PermissionDenied
    return _download(contract.file, contract.file_name)


@login_required
@require_POST
def document_add(request, pk):
    req = get_object_or_404(Request, pk=pk)
    if not project.can_upload_document(request.user, req):
        raise PermissionDenied
    try:
        project.add_document(req, upload=request.FILES.get('file'), title=request.POST.get('title', '').strip(),
                             kind=request.POST.get('kind', ''), actor=request.user,
                             visible_to_customer=bool(request.POST.get('visible_to_customer')),
                             visible_to_contractor=bool(request.POST.get('visible_to_contractor')))
        messages.success(request, 'مستند ثبت شد.')
    except project.ProjectError as exc:
        messages.error(request, str(exc))
    return redirect('requests:admin-detail', pk=pk)


@login_required
def document_file(request, pk):
    document = get_object_or_404(RequestDocument.objects.select_related('request'), pk=pk)
    if not project.can_read_document(request.user, document):
        raise PermissionDenied
    return _download(document.file, document.original_name)


@login_required
@require_POST
def document_delete(request, pk):
    document = get_object_or_404(RequestDocument.objects.select_related('request'), pk=pk)
    user = request.user
    if not (project.can_read_document(user, document) and not project.is_owner(user, document.request)
            and (document.uploaded_by_id == user.pk or repositories.is_management(user))):
        raise PermissionDenied
    req_id = document.request_id
    document.delete()
    messages.success(request, 'مستند حذف شد.')
    return redirect('requests:admin-detail', pk=req_id)


def _installment(pk):
    return get_object_or_404(ContractInstallment.objects.select_related('contract__request'), pk=pk)


@login_required
@require_POST
def receipt_submit(request, pk):
    installment = _installment(pk)
    req = installment.contract.request
    if not project.can_submit_receipt(request.user, req):
        raise PermissionDenied
    try:
        project.submit_receipt(installment, upload=request.FILES.get('receipt'),
                               paid_on=parse_user_date(request.POST.get('paid_on')),
                               reference=request.POST.get('reference', '').strip(), actor=request.user)
        messages.success(request, 'رسید ثبت شد و برای تأیید به واحد مالی رفت.')
    except project.ProjectError as exc:
        messages.error(request, str(exc))
    return _back(request.user, req)


@login_required
def receipt_file(request, pk):
    installment = _installment(pk)
    if not project.can_see_money(request.user, installment.contract.request):
        raise PermissionDenied
    return _download(installment.receipt, installment.receipt_name)


def _next(request, req):
    return redirect('requests:admin-payments') if request.POST.get('next') == 'payments' else redirect(
        'requests:admin-detail', pk=req.pk)


@login_required
@require_POST
def installment_review(request, pk):
    if not project.can_review(request.user):
        raise PermissionDenied
    installment = _installment(pk)
    req = installment.contract.request
    try:
        project.review_installment(installment, decision=request.POST.get('decision', ''),
                                   note=request.POST.get('note', '').strip(), actor=request.user)
        messages.success(request, 'نتیجهٔ بررسی مالی ثبت شد.')
    except project.ProjectError as exc:
        messages.error(request, str(exc))
    return _next(request, req)


@login_required
@require_POST
def payment_review(request, pk):
    if not project.can_review(request.user):
        raise PermissionDenied
    payment = get_object_or_404(RequestPayment.objects.select_related('request'), pk=pk)
    try:
        project.review_payment(payment, decision=request.POST.get('decision', ''),
                               note=request.POST.get('note', '').strip(), actor=request.user)
        messages.success(request, 'نتیجهٔ بررسی مالی ثبت شد.')
    except project.ProjectError as exc:
        messages.error(request, str(exc))
    return _next(request, payment.request)
