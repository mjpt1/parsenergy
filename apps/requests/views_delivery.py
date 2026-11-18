"""Contractors, the contractor's own panel, project insurance and the equipment list."""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Avg, Count, Q
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.leads import exports

from . import repositories
from .forms import ContractorAssignmentForm, ContractorProfileForm, ProjectEquipmentForm, ProjectInsuranceForm
from .models import ContractorAssignment, ContractorProfile, ProjectEquipment, ProjectInsurance, Request, RequestDocument
from .services import delivery, lifecycle, project

User = get_user_model()


def _detail(pk):
    return redirect('requests:admin-detail', pk=pk)


def _item_form(request, form, title, req):
    return render(request, 'requests/admin/project_item_form.html',
                  {'form': form, 'page_title': title, 'req': req})


# ------------------------------------------------------------------ equipment
@login_required
def equipment_edit(request, req_pk=None, pk=None):
    item = get_object_or_404(ProjectEquipment.objects.select_related('request'), pk=pk) if pk else None
    req = item.request if item else get_object_or_404(Request, pk=req_pk)
    if not delivery.can_manage_equipment(request.user, req):
        raise PermissionDenied
    form = ProjectEquipmentForm(request.POST or None, instance=item)
    if request.method == 'POST' and form.is_valid():
        saved = form.save(commit=False)
        saved.request = req
        saved.created_by = saved.created_by or request.user
        saved.save()
        lifecycle.add_note(req, f'فهرست تجهیزات: {saved.name}', actor=request.user, kind='edit')
        messages.success(request, 'تجهیز ذخیره شد.')
        return _detail(req.pk)
    return _item_form(request, form, 'ویرایش تجهیز' if item else 'افزودن تجهیز', req)


@login_required
@require_POST
def equipment_delete(request, pk):
    item = get_object_or_404(ProjectEquipment.objects.select_related('request'), pk=pk)
    if not delivery.can_manage_equipment(request.user, item.request):
        raise PermissionDenied
    req_id = item.request_id
    lifecycle.add_note(item.request, f'تجهیز حذف شد: {item.name}', actor=request.user, kind='edit')
    item.delete()
    messages.success(request, 'تجهیز حذف شد.')
    return _detail(req_id)


@login_required
def equipment_document(request, pk):
    req = get_object_or_404(Request, pk=pk)
    if not delivery.can_see_equipment(request.user, req):
        raise PermissionDenied
    rows = delivery.equipment_for(request.user, req)
    if request.GET.get('format') == 'excel':
        payload = exports.build_sheet('تجهیزات', ['دسته', 'نام', 'برند / مدل', 'شماره سریال', 'تعداد', 'واحد', 'تأمین‌کننده',
                                                  'تاریخ خرید', 'پایان گارانتی', 'توضیحات'], [
            [r.get_category_display(), r.name, r.model_name, r.serial_number, float(r.quantity), r.unit, r.supplier,
             str(r.purchased_on or ''), str(r.warranty_until or ''), r.note] for r in rows])
        response = HttpResponse(payload, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = f'attachment; filename="equipment-{req.pk}.xlsx"'
        return response
    return render(request, 'requests/equipment_print.html', {
        'req': req, 'rows': rows, 'today': timezone.localdate(),
        'show_customer': not repositories.is_identity_restricted(request.user)})


# ------------------------------------------------------------------ insurance
@login_required
def insurance_edit(request, req_pk=None, pk=None):
    policy = get_object_or_404(ProjectInsurance.objects.select_related('request'), pk=pk) if pk else None
    req = policy.request if policy else get_object_or_404(Request, pk=req_pk)
    if not delivery.can_manage_insurance(request.user, req):
        raise PermissionDenied
    form = ProjectInsuranceForm(request.POST or None, request.FILES or None, instance=policy)
    if request.method == 'POST' and form.is_valid():
        saved = form.save(commit=False)
        saved.request = req
        saved.created_by = saved.created_by or request.user
        upload = request.FILES.get('file')
        if upload:
            saved.file_name = upload.name[:255]
        saved.save()
        lifecycle.add_note(req, f'بیمه ثبت شد: {saved.get_kind_display()} — {saved.policy_number}',
                           actor=request.user, kind='edit')
        messages.success(request, 'بیمه‌نامه ذخیره شد.')
        return _detail(req.pk)
    return _item_form(request, form, 'ویرایش بیمه‌نامه' if policy else 'ثبت بیمه‌نامه', req)


@login_required
@require_POST
def insurance_delete(request, pk):
    policy = get_object_or_404(ProjectInsurance.objects.select_related('request'), pk=pk)
    if not delivery.can_manage_insurance(request.user, policy.request):
        raise PermissionDenied
    req_id = policy.request_id
    policy.delete()
    messages.success(request, 'بیمه‌نامه حذف شد.')
    return _detail(req_id)


@login_required
def insurance_file(request, pk):
    policy = get_object_or_404(ProjectInsurance.objects.select_related('request'), pk=pk)
    if not delivery.can_read_insurance(request.user, policy):
        raise PermissionDenied
    if not policy.file:
        raise Http404
    response = FileResponse(policy.file.open('rb'), as_attachment=True, filename=policy.file_name or 'insurance')
    response['X-Content-Type-Options'] = 'nosniff'
    return response


# --------------------------------------------------- contractors, staff side
def _require_contractor_staff(user):
    if not user.can_manage_contractors:
        raise PermissionDenied


@login_required
def contractor_list(request):
    _require_contractor_staff(request.user)
    Status = ContractorAssignment.Status
    rows = (User.objects.filter(role=User.Role.CONTRACTOR).select_related('contractor_profile')
            .annotate(active_jobs=Count('contractor_assignments', filter=Q(contractor_assignments__status=Status.ACTIVE)),
                      done_jobs=Count('contractor_assignments', filter=Q(contractor_assignments__status=Status.DONE)),
                      avg_rating=Avg('contractor_assignments__rating')).order_by('first_name', 'username'))
    return render(request, 'requests/admin/contractors.html', {
        'contractors': rows, 'page_title': 'پیمانکاران', 'can_create': repositories.is_management(request.user)})


@login_required
def contractor_detail(request, pk):
    _require_contractor_staff(request.user)
    contractor = get_object_or_404(User, pk=pk, role=User.Role.CONTRACTOR)
    profile, _created = ContractorProfile.objects.get_or_create(user=contractor)
    can_edit = delivery.can_share_contact(request.user)
    form = ContractorProfileForm(request.POST or None, instance=profile)
    if request.method == 'POST':
        if not can_edit:
            raise PermissionDenied
        if form.is_valid():
            form.save()
            messages.success(request, 'مشخصات پیمانکار ذخیره شد.')
            return redirect('requests:contractor-detail', pk=pk)
    history = contractor.contractor_assignments.select_related('request').order_by('-created_at')
    return render(request, 'requests/admin/contractor_detail.html', {
        'contractor': contractor, 'form': form, 'can_edit': can_edit, 'history': history,
        'avg_rating': history.aggregate(v=Avg('rating'))['v'], 'page_title': 'سوابق پیمانکار'})


@login_required
def contractor_assign(request, pk):
    req = get_object_or_404(Request, pk=pk)
    if not delivery.can_assign(request.user, req):
        raise PermissionDenied
    form = ContractorAssignmentForm(request.POST or None, can_share_contact=delivery.can_share_contact(request.user))
    if request.method == 'POST' and form.is_valid():
        delivery.assign_contractor(req, form=form, actor=request.user)
        messages.success(request, 'پیمانکار به پرونده وصل شد.')
        return _detail(pk)
    return _item_form(request, form, 'اتصال پیمانکار به پرونده', req)


@login_required
@require_POST
def contractor_finish(request, pk):
    assignment = get_object_or_404(ContractorAssignment.objects.select_related('request'), pk=pk)
    if not delivery.can_assign(request.user, assignment.request):
        raise PermissionDenied
    raw = request.POST.get('rating', '')
    try:
        delivery.finish_assignment(assignment, status=request.POST.get('status', ''),
                                   rating=int(raw) if raw.isdigit() else None,
                                   note=request.POST.get('note', '').strip(), actor=request.user)
        messages.success(request, 'نتیجهٔ همکاری ثبت شد.')
    except project.ProjectError as exc:
        messages.error(request, str(exc))
    return _detail(assignment.request_id)


# ------------------------------------------------------- the contractor's panel
def _contractor_only(user):
    if user.role != User.Role.CONTRACTOR:
        raise PermissionDenied


@login_required
def contractor_home(request):
    _contractor_only(request.user)
    jobs = request.user.contractor_assignments.select_related('request').order_by('status', '-created_at')
    return render(request, 'requests/contractor/home.html', {
        'jobs': jobs, 'page_title': 'پروژه‌های من', 'portal_tab': 'contractor'})


def _active_job(user, pk):
    _contractor_only(user)
    req = get_object_or_404(Request, pk=pk)
    job = delivery.active_assignment(user, req)
    if job is None:
        raise PermissionDenied
    return req, job


@login_required
def contractor_project(request, pk):
    req, job = _active_job(request.user, pk)
    return render(request, 'requests/contractor/project.html', {
        'req': req, 'job': job, 'page_title': f'پروژه #{req.pk}', 'portal_tab': 'contractor',
        'equipment_items': req.equipment_items.all(),
        'insurances': req.insurances.filter(phase=ProjectInsurance.Phase.EXECUTION),
        'documents': delivery.contractor_documents(request.user, req),
        'reports': req.stage_notes.filter(created_by=request.user, kind='note')})


@login_required
@require_POST
def contractor_report(request, pk):
    req, _job = _active_job(request.user, pk)
    body = request.POST.get('body', '').strip()[:2000]
    upload = request.FILES.get('file')
    if not body and not upload:
        messages.error(request, 'متن گزارش یا فایل را وارد کنید.')
        return redirect('requests:contractor-project', pk=pk)
    try:
        if upload:
            document = project.add_document(req, upload=upload, title=request.POST.get('title', '').strip(),
                                            kind=RequestDocument.Kind.TECHNICAL, visible_to_customer=False,
                                            actor=request.user)
            document.visible_to_contractor = True
            document.save(update_fields=['visible_to_contractor'])
        if body:
            lifecycle.add_note(req, f'گزارش پیمانکار: {body}', actor=request.user)
        messages.success(request, 'گزارش ثبت شد.')
    except project.ProjectError as exc:
        messages.error(request, str(exc))
    return redirect('requests:contractor-project', pk=pk)
