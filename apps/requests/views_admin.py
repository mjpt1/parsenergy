"""Admin pages for the requests module.

These live inside the existing admin panel: every view extends base.html and is
gated by the same RBAC the rest of the panel uses (superuser / admin role /
`requests.manage` permission).
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.translation import gettext_lazy as _
from django.views.generic import CreateView, DetailView, ListView, UpdateView, View

from apps.core.services import write_audit_log
from apps.leads.forms import LeadInternalForm

from . import repositories
from .forms import ContractSettingsForm, ContractTemplateForm, LeadForm, TicketForm, TicketReplyForm
from .models import (
    ContractSettings,
    ContractTemplate,
    Request,
    RequestContract,
    RequestMessageLog,
    RequestOffer,
    RequestPayment,
    RequestStageNote,
    Ticket,
    TicketMessage,
)
from .services import contracts as contract_service
from .services import delivery as delivery_service
from .services import lifecycle
from .services import offers as offer_service
from .services import project as project_service

# Map Persian/Arabic-Indic digits to ASCII so amounts typed in any locale parse.
_DIGIT_MAP = {ord(p): str(i) for i, p in enumerate('۰۱۲۳۴۵۶۷۸۹')}
_DIGIT_MAP.update({ord(p): str(i) for i, p in enumerate('٠١٢٣٤٥٦٧٨٩')})


def _clean_number(raw) -> str:
    """Normalise a user-entered amount: ASCII digits, strip thousands separators."""
    s = str(raw or '').translate(_DIGIT_MAP)
    for sep in (',', '،', '٬', ' ', '‌', '٬'):
        s = s.replace(sep, '')
    return s.strip()


def _awaiting_marketing(user, target) -> bool:
    """True when this user may look at the lead but not act on it yet.

    The pipeline is marketing → sales → technical. Sales sees a lead from the
    moment it lands so nothing sits unnoticed, but while it is still in the
    marketing queue it belongs to marketing: until marketing refers it on,
    sales looks and does not touch.

    Most sales actions are already gated on `department == SALES`, but three
    were not — cancelling, unlocking customer edits, and closing a lead as
    lost (`close_lost` deliberately accepts marketing-stage requests so that
    *marketing* can drop a junk lead). This is the one guard they share.
    """
    if target.department != Request.Department.MARKETING:
        return False
    return not (repositories.is_marketing(user)
                or repositories.is_management(user)
                or repositories.is_operations(user))


def _blocked_reason(user, target):
    """Why this user may not act on this request, or None if they may.

    `is_request_manager` is a wide door — it lets marketing, sales, operations
    and finance reach the commercial pages. Two of the actions behind that
    door (cancelling, and unlocking customer edits) are not for everyone who
    can see the page, so the narrowing happens here instead.
    """
    if repositories.is_financial(user) and not repositories.is_management(user):
        return _('نقش مالی دسترسی خواندنی دارد و نمی‌تواند وضعیت درخواست را تغییر دهد.')
    if _awaiting_marketing(user, target):
        return _('این لید هنوز در صف بازاریابی است؛ تا ارجاع بازاریابی امکان اقدام روی آن نیست.')
    return None


class RequestManagerRequiredMixin(UserPassesTestMixin):
    """Commercial pages: management, sales, marketing, ops, or requests.manage."""
    def test_func(self):
        user = getattr(self.request, 'user', None)
        return bool(user and repositories.is_request_manager(user))


class RequestStaffRequiredMixin(UserPassesTestMixin):
    """Any staff that may see requests including technical."""
    def test_func(self):
        user = getattr(self.request, 'user', None)
        return bool(user and repositories.is_request_staff(user))


class ManagementRequiredMixin(UserPassesTestMixin):
    """Tracking/oversight pages: management or operations."""
    def test_func(self):
        user = getattr(self.request, 'user', None)
        return bool(user and (
            repositories.is_management(user) or repositories.is_operations(user)))


def _parse_date(value):
    from apps.core.dates import parse_user_date
    return parse_user_date(value)


_LIST_FILTER_KEYS = (
    'status', 'province', 'city', 'department', 'funnel_stage', 'sales_phase', 'priority',
    'request_type', 'partnership_type', 'install_location', 'lead_source',
    'campaign_name', 'sales_assignee', 'technical_status', 'crm_transferred',
    'date_from', 'date_to', 'updated_from', 'updated_to', 'q',
)


#: Filters where several values can be ticked at once.
_MULTI_FILTER_KEYS = (
    'status', 'province', 'department', 'funnel_stage', 'priority', 'request_type', 'partnership_type',
    'install_location', 'lead_source', 'campaign_name', 'sales_assignee',
    'city', 'technical_status', 'crm_transferred',
)


class RequestAdminListView(LoginRequiredMixin, RequestStaffRequiredMixin, ListView):
    template_name = 'requests/admin/list.html'
    paginate_by = 25
    context_object_name = 'requests'

    def get_queryset(self):
        g = self.request.GET
        user = self.request.user
        qs = repositories.filter_requests(
            status=[v for v in g.getlist('status') if v] or None,
            province=[v for v in g.getlist('province') if v] or None,
            city=[v for v in g.getlist('city') if v] or None,
            department=[v for v in g.getlist('department') if v] or None,
            funnel_stage=[v for v in g.getlist('funnel_stage') if v] or None,
            sales_phase=g.get('sales_phase') or None,
            priority=[v for v in g.getlist('priority') if v] or None,
            request_type=[v for v in g.getlist('request_type') if v] or None,
            partnership_type=[v for v in g.getlist('partnership_type') if v] or None,
            install_location=[v for v in g.getlist('install_location') if v] or None,
            lead_source=[v for v in g.getlist('lead_source') if v] or None,
            campaign_name=[v for v in g.getlist('campaign_name') if v] or None,
            sales_assignee=[v for v in g.getlist('sales_assignee') if v] or None,
            technical_status=[v for v in g.getlist('technical_status') if v] or None,
            crm_transferred=[v for v in g.getlist('crm_transferred') if v] or None,
            date_from=_parse_date(g.get('date_from')),
            date_to=_parse_date(g.get('date_to')),
            updated_from=_parse_date(g.get('updated_from')),
            updated_to=_parse_date(g.get('updated_to')),
            q=g.get('q') or None,
            identity_search=repositories.can_search_identity(user),
        )
        qs = repositories.scope_requests_by_department(user, qs)
        if not [v for v in g.getlist('status') if v] and not g.get('q'):
            qs = qs.exclude(status__in=(Request.Status.CLOSED, Request.Status.CANCELLED))
        from django.db.models import Case, IntegerField, Value, When
        prio = Case(
            When(priority='urgent', then=Value(0)),
            When(priority='high', then=Value(1)),
            When(priority='normal', then=Value(2)),
            When(priority='low', then=Value(3)),
            default=Value(2), output_field=IntegerField())
        return qs.annotate(_prio=prio).order_by('_prio', '-created_at')

    def render_to_response(self, context, **kwargs):
        """`?export=excel` hands back the same rows the screen is showing.

        It exports the full filtered queryset, not just the current page — the
        point of an export is the whole result, and `object_list` here is
        already paginated.
        """
        if self.request.GET.get('export') != 'excel':
            return super().render_to_response(context, **kwargs)

        from apps.leads import exports
        payload = exports.build_sheet(
            'درخواست‌ها', exports.REQUEST_HEADERS,
            exports.request_rows(
                self.get_queryset(),
                hide_identity=repositories.is_identity_restricted(self.request.user)))
        response = HttpResponse(
            payload,
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = 'attachment; filename="requests.xlsx"'
        return response

    def get_template_names(self):
        if self.request.GET.get('print'):
            return ['requests/admin/list_print.html']
        return [self.template_name]

    def get_paginate_by(self, queryset):
        # The PDF/print page is a report of every filtered request, not just
        # the 25 on the current screen.
        if self.request.GET.get('print'):
            return None
        return super().get_paginate_by(queryset)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        ctx['generated_at'] = timezone.now()
        if repositories.is_technical(user) and not repositories.is_management(user):
            ctx['page_title'] = 'صف فنی'
        elif repositories.is_sales(user) and not repositories.is_management(user):
            ctx['page_title'] = 'صف فروش'
        elif repositories.is_marketing(user) and not repositories.is_management(user):
            ctx['page_title'] = 'صف بازاریابی'
        elif repositories.is_operations(user) and not repositories.is_management(user):
            ctx['page_title'] = 'نظارت عملیات'
        else:
            ctx['page_title'] = 'مدیریت درخواست‌ها'
        # Sales sees marketing-stage leads but cannot act on them yet; the rows
        # say so rather than leaving the user to discover it by clicking.
        ctx['sales_readonly_marketing'] = (
            repositories.is_sales(user)
            and not repositories.is_management(user)
            and not repositories.is_marketing(user))
        ctx['status_choices'] = Request.Status.choices
        ctx['department_choices'] = Request.Department.choices
        ctx['funnel_choices'] = Request.FunnelStage.choices
        ctx['can_create_lead'] = repositories.can_create_lead(user)
        ctx['priority_choices'] = Request.Priority.choices
        ctx['request_type_choices'] = Request.RequestType.choices
        ctx['partnership_type_choices'] = Request.PartnershipType.choices
        ctx['install_location_choices'] = Request.InstallLocation.choices
        ctx['sales_phase_choices'] = Request.SalesPhase.choices
        ctx['can_filter_department'] = (
            repositories.is_management(user) or repositories.is_operations(user))
        ctx['can_search_identity'] = repositories.can_search_identity(user)
        from django.contrib.auth import get_user_model
        User = get_user_model()
        ctx['sales_users'] = User.objects.filter(role='sales').order_by('username')
        ctx['provinces'] = (
            Request.objects.order_by('province')
            .values_list('province', flat=True)
            .distinct()
        )
        ctx['lead_sources'] = (
            Request.objects.exclude(lead_source='')
            .order_by('lead_source').values_list('lead_source', flat=True).distinct()
        )
        ctx['cities'] = (
            Request.objects.exclude(city='')
            .order_by('city').values_list('city', flat=True).distinct()
        )
        ctx['campaigns'] = (
            Request.objects.exclude(campaign_name='')
            .order_by('campaign_name').values_list('campaign_name', flat=True).distinct()
        )
        ctx['current'] = {key: self.request.GET.get(key, '') for key in _LIST_FILTER_KEYS}
        # Ticked boxes of the multi-choice filters, as lists.
        ctx['current_multi'] = {key: self.request.GET.getlist(key) for key in _MULTI_FILTER_KEYS}
        ctx['hide_customer_identity'] = repositories.is_identity_restricted(user)
        return ctx


class RequestAdminDetailView(LoginRequiredMixin, RequestStaffRequiredMixin, DetailView):
    model = Request
    template_name = 'requests/admin/detail.html'
    context_object_name = 'req'

    def get_queryset(self):
        # Staff may only open requests inside the queue(s) they can see.
        return repositories.scope_requests_by_department(
            self.request.user, Request.objects.all())

    def get(self, request, *args, **kwargs):
        pk = kwargs.get('pk')
        if not self.get_queryset().filter(pk=pk).exists():
            other = Request.objects.filter(pk=pk).first()
            if other is not None:
                messages.info(request, _(
                    'این درخواست در صف شما نیست — به بخش «%(dept)s» منتقل شده است.'
                ) % {'dept': other.get_department_display()})
                return redirect('requests:admin-list')
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        req = self.object
        user = self.request.user
        offer_count = req.offers.count()
        status = Request.Status
        dept = Request.Department
        contract = RequestContract.objects.filter(request=req).first()
        contract_open = contract is None or contract.status != RequestContract.Status.APPROVED
        is_mgmt = repositories.is_management(user)
        is_ops = repositories.is_operations(user)
        is_tech = repositories.is_technical(user)
        is_sales = repositories.is_sales(user)
        is_mkt = repositories.is_marketing(user)
        sp = Request.SalesPhase
        # Marketing review (no customer contact).
        can_refer_marketing = (
            (is_mkt or is_mgmt or is_ops) and req.department == dept.MARKETING
            and req.status not in (status.HOLD, status.CLOSED, status.CANCELLED))
        # Sales qualification → technical / hold / closed.
        sales_qualify = (
            (is_sales or is_mgmt) and req.department == dept.SALES
            and req.sales_phase != sp.NEGOTIATION
            and req.status not in (status.CLOSED, status.CANCELLED))
        can_refer_to_technical = sales_qualify
        can_hold = sales_qualify and req.status != status.HOLD
        can_close_lost = sales_qualify or (
            (is_sales or is_mgmt) and req.department == dept.SALES
            and req.status not in (status.PAID, status.CLOSED, status.CANCELLED))
        # Technical owns pricing.
        tech_stage = (is_tech or is_mgmt) and req.department == dept.TECHNICAL
        funnel = Request.FunnelStage
        case_open = req.status not in (status.CLOSED, status.CANCELLED)
        can_add_offer = (tech_stage and offer_count < offer_service.MAX_OFFERS_PER_REQUEST
                         and (req.status in (status.NEW, status.OFFERED, status.HOLD)
                              or (req.funnel_stage == funnel.COMMERCIAL_OFFER and case_open)))
        can_refer_to_sales = tech_stage and offer_count > 0
        # Sales negotiation owns the contract.
        sales_negotiate = (
            (is_sales or is_mgmt) and req.department == dept.SALES
            and req.sales_phase == sp.NEGOTIATION)
        can_issue_contract = (sales_negotiate
                              and req.status in (status.OFFERED, status.CONTRACT_GENERATED)
                              and contract_open)
        can_close_sales = sales_negotiate
        can_set_price = sales_negotiate and case_open
        can_start_commercial = (sales_negotiate and case_open and not contract_open
                                and req.funnel_stage == funnel.FIRST_CONTRACT)
        can_start_operation = ((is_tech or is_mgmt or is_ops) and case_open and bool(req.plant_id)
                               and req.funnel_stage == funnel.EXECUTION)
        hide_identity = repositories.is_identity_restricted(user)
        # Sales can open a lead that is still marketing's. Every action flag
        # above already comes out False for it; this says *why*, so the empty
        # action bar reads as "not yet" rather than "broken".
        awaiting_marketing = _awaiting_marketing(user, req)
        # The marketer's own read of an exhibition lead, editable in place.
        lead = getattr(req, 'exhibition', None)
        can_write_lead_note = _can_write_lead_note(user, req)
        current = funnel.values.index(req.funnel_stage)
        history = req.stage_notes.select_related('created_by')
        if hide_identity:
            history = history.filter(Q(stage__in=lifecycle.TECHNICAL_STAGES) | Q(created_by=user))
        ctx.update(project_service.staff_context(user, req))
        ctx.update(delivery_service.staff_context(user, req))
        ctx.update({
            'funnel_steps': [
                {'label': label, 'state': 'done' if i < current else 'now' if i == current and case_open
                 else 'stopped' if i == current else ''}
                for i, (_value, label) in enumerate(funnel.choices)],
            'stage_history': history[:100],
            'case_open': case_open,
            'can_start_commercial': can_start_commercial,
            'can_start_operation': can_start_operation,
            'can_manage_stage': (is_mgmt or is_ops) and case_open,
            'funnel_choices': funnel.choices,
            'stop_reasons': Request.StopReason.choices,
            'can_stop': (repositories.owns_current_stage(user, req) and not _blocked_reason(user, req)
                         and req.status not in (status.PAID, status.CANCELLED, status.CLOSED)),
            'can_edit_lead': repositories.can_edit_lead(user, req) and case_open,
            'approved_offer_id': contract.offer_id if contract and not contract_open else None,
            'page_title': f'درخواست #{req.id}',
            'awaiting_marketing': awaiting_marketing,
            'can_write_lead_note': can_write_lead_note,
            'lead_note_form': LeadInternalForm(instance=lead) if can_write_lead_note else None,
            'offers': req.offers.all(),
            'offer_count': offer_count,
            'max_offers': offer_service.MAX_OFFERS_PER_REQUEST,
            'contract': None if hide_identity else contract,
            'payments': [] if hide_identity else req.payments.select_related('offer').all(),
            'sms_logs': [] if hide_identity else req.message_logs.all(),
            'priority_choices': Request.Priority.choices,
            'can_refer_marketing': can_refer_marketing,
            'can_refer_to_technical': can_refer_to_technical,
            'can_hold': can_hold,
            'can_close_lost': can_close_lost,
            'can_add_offer': can_add_offer,
            'can_set_price': can_set_price,
            'can_enter_offer_price': is_mgmt,
            'can_refer_to_sales': can_refer_to_sales,
            'can_manage_offers': tech_stage,
            'can_issue_contract': can_issue_contract,
            'can_close_sales': can_close_sales,
            'can_commission_plant': (is_tech or is_mgmt),
            'can_cancel': (is_mgmt or is_ops) and req.status not in (
                status.PAID, status.CANCELLED, status.CLOSED),
            'can_delete': is_mgmt,
            'has_paid_payment': req.payments.filter(
                status=RequestPayment.Status.PAID).exists(),
            'can_toggle_edit':repositories.is_request_manager(user) and not is_tech,
            'edit_unlocked': req.edit_unlocked,
            'hide_customer_identity': hide_identity,
        })
        return ctx


class RequestMarketingReferView(LoginRequiredMixin, RequestStaffRequiredMixin, View):
    """Marketing reviews lead quality and sends to sales qualification."""
    def post(self, request, pk):
        target = get_object_or_404(Request, pk=pk)
        user = request.user
        if not (repositories.is_marketing(user) or repositories.is_management(user)
                or repositories.is_operations(user)):
            messages.error(request, _('شما اجازهٔ این کار را ندارید.'))
            return redirect('requests:admin-detail', pk=pk)
        try:
            lifecycle.refer_marketing_to_sales(target, actor=user)
            messages.success(request, _('لید به صف صلاحیت‌سنجی فروش ارجاع شد.'))
        except lifecycle.DepartmentError as exc:
            messages.error(request, str(exc))
        return redirect('requests:admin-detail', pk=pk)


class RequestReferToTechnicalView(LoginRequiredMixin, RequestStaffRequiredMixin, View):
    """Sales qualification → technical evaluation."""
    def post(self, request, pk):
        target = get_object_or_404(Request, pk=pk)
        user = request.user
        if not (repositories.is_sales(user) or repositories.is_management(user)):
            messages.error(request, _('شما اجازهٔ این کار را ندارید.'))
            return redirect('requests:admin-detail', pk=pk)
        try:
            lifecycle.refer_sales_to_technical(
                target, actor=user, priority=request.POST.get('priority'))
            messages.success(request, _('درخواست با اولویت تعیین‌شده به بخش فنی ارسال شد.'))
        except lifecycle.DepartmentError as exc:
            messages.error(request, str(exc))
        return redirect('requests:admin-detail', pk=pk)


class RequestHoldView(LoginRequiredMixin, RequestStaffRequiredMixin, View):
    def post(self, request, pk):
        target = get_object_or_404(Request, pk=pk)
        user = request.user
        if not (repositories.is_sales(user) or repositories.is_management(user)):
            messages.error(request, _('شما اجازهٔ این کار را ندارید.'))
            return redirect('requests:admin-detail', pk=pk)
        try:
            lifecycle.hold_request(target, actor=user)
            messages.success(request, _('درخواست معلق شد.'))
        except (lifecycle.DepartmentError, lifecycle.TransitionError) as exc:
            messages.error(request, str(exc))
        return redirect('requests:admin-detail', pk=pk)


class RequestCloseLostView(LoginRequiredMixin, RequestStaffRequiredMixin, View):
    def post(self, request, pk):
        return _stop_case(request, pk, Request.Status.CLOSED)


class RequestTriageView(RequestReferToTechnicalView):
    """Back-compat URL alias for sales → technical."""
    pass


class RequestReferToSalesView(LoginRequiredMixin, RequestStaffRequiredMixin, View):
    """Technical finishes pricing (offers) and refers the request to sales."""
    def post(self, request, pk):
        target = get_object_or_404(Request, pk=pk)
        user = request.user
        if not (repositories.is_technical(user) or repositories.is_management(user)):
            messages.error(request, _('شما اجازهٔ این کار را ندارید.'))
            return redirect('requests:admin-detail', pk=pk)
        try:
            lifecycle.refer_to_sales(
                target, actor=user, note=request.POST.get('technical_note', '').strip())
            messages.success(request, _('درخواست برای بستن قرارداد به فروش ارجاع شد.'))
        except lifecycle.DepartmentError as exc:
            messages.error(request, str(exc))
            return redirect('requests:admin-detail', pk=pk)
        if repositories.is_management(user):
            return redirect('requests:admin-detail', pk=pk)
        return redirect('requests:admin-list')


class RequestCloseSalesView(LoginRequiredMixin, RequestManagerRequiredMixin, View):
    """Sales closes the deal (after the contract); request reaches its final state."""
    def post(self, request, pk):
        target = get_object_or_404(Request, pk=pk)
        try:
            lifecycle.close_by_sales(target, actor=request.user)
            messages.success(request, _('فروش تکمیل شد؛ پرونده به CRM منتقل شد.'))
        except lifecycle.DepartmentError as exc:
            messages.error(request, str(exc))
        return redirect('requests:admin-detail', pk=pk)


def _can_write_lead_note(user, req) -> bool:
    """Who may record the marketing read of an exhibition lead.

    The marketer who captured it — at any stage, including after they have
    handed it to sales, because what they learned at the stand stays useful —
    plus management and operations. Sales and technical read it on the detail
    page but do not write it; it is the capturing marketer's account.
    """
    lead = getattr(req, 'exhibition', None)
    if lead is None:
        return False
    if repositories.is_management(user) or repositories.is_operations(user):
        return True
    return repositories.is_marketing(user) and lead.marketer_id == user.pk


class RequestLeadNoteView(LoginRequiredMixin, RequestStaffRequiredMixin, View):
    """Save the marketer's own read of a lead: quality, next step, impression.

    These fields have existed on the Lead model since the exhibition form was
    built, and the form class with them was written at the same time — but
    when exhibition leads were folded into the ordinary request pipeline the
    screen that rendered it went away and was never replaced, so the fields
    became write-only-by-nobody. This is that screen's replacement.
    """

    def post(self, request, pk):
        target = get_object_or_404(
            repositories.scope_requests_by_department(request.user, Request.objects.all()),
            pk=pk)
        lead = getattr(target, 'exhibition', None)
        if lead is None:
            messages.error(request, _('این درخواست از فرم نمایشگاهی ثبت نشده است.'))
            return redirect('requests:admin-detail', pk=pk)
        if not _can_write_lead_note(request.user, target):
            messages.error(request, _('تنها بازاریاب ثبت‌کنندهٔ این سرنخ یا مدیریت می‌تواند تحلیل را ویرایش کند.'))
            return redirect('requests:admin-detail', pk=pk)

        form = LeadInternalForm(request.POST, instance=lead)
        if form.is_valid():
            form.save()
            write_audit_log(
                actor=request.user, action='lead.note_updated',
                target_type='request', target_id=str(target.id),
                metadata={'lead_code': lead.lead_code})
            messages.success(request, _('تحلیل سرنخ ذخیره شد.'))
        else:
            messages.error(request, _('ثبت تحلیل انجام نشد؛ مقادیر واردشده را بررسی کنید.'))
        return redirect('requests:admin-detail', pk=pk)


class RequestToggleEditView(LoginRequiredMixin, RequestManagerRequiredMixin, View):
    """Sales/management grants or revokes the customer's edit access (unlimited)."""
    def post(self, request, pk):
        target = get_object_or_404(Request, pk=pk)
        blocked = _blocked_reason(request.user, target)
        if blocked:
            messages.error(request, blocked)
            return redirect('requests:admin-detail', pk=pk)
        target.edit_unlocked = not target.edit_unlocked
        target.save(update_fields=['edit_unlocked', 'updated_at'])
        from apps.core.services import write_audit_log
        write_audit_log(actor=request.user, action='request.edit_unlock_toggled',
                        target_type='request', target_id=str(target.id),
                        metadata={'unlocked': target.edit_unlocked})
        messages.success(request, _('دسترسی ویرایش برای مشتری باز شد.') if target.edit_unlocked
                         else _('دسترسی ویرایش برای مشتری بسته شد.'))
        return redirect('requests:admin-detail', pk=pk)


class RequestDeleteView(LoginRequiredMixin, ManagementRequiredMixin, View):
    """Admin / super-admin permanently deletes a request.

    Offers, contract, payments, SMS logs, OTPs and the exhibition lead detail
    go with it (CASCADE). A request with a successful payment is kept: it is
    a financial record and should be cancelled instead.
    """
    def post(self, request, pk):
        if not repositories.is_management(request.user):
            messages.error(request, _('فقط مدیریت می‌تواند درخواست را حذف کند.'))
            return redirect('requests:admin-detail', pk=pk)
        target = get_object_or_404(Request, pk=pk)
        if target.payments.filter(status=RequestPayment.Status.PAID).exists():
            messages.error(request, _('این درخواست پرداخت موفق دارد و قابل حذف نیست؛ به‌جای حذف آن را لغو کنید.'))
            return redirect('requests:admin-detail', pk=pk)
        write_audit_log(
            actor=request.user, action='request.deleted',
            target_type='request', target_id=str(target.id),
            metadata={'full_name': target.full_name, 'mobile': target.mobile,
                      'status': target.status, 'department': target.department},
        )
        target_id = target.id
        from django.db import transaction
        with transaction.atomic():
            # Contract and payments point at the offers with PROTECT, so Django
            # refuses to cascade through them; remove them before the request.
            RequestContract.objects.filter(request=target).delete()
            target.payments.all().delete()
            target.delete()
        messages.success(request, _('درخواست #%(id)s حذف شد.') % {'id': target_id})
        return redirect('requests:admin-list')


class RequestCommissionPlantView(LoginRequiredMixin, RequestStaffRequiredMixin, View):
    """Technical action: create a Plant for this request and open it for setup."""
    def post(self, request, pk):
        from apps.plants.models import Plant
        target = get_object_or_404(Request, pk=pk)
        user = request.user
        if not (repositories.is_technical(user) or repositories.is_management(user)):
            messages.error(request, _('شما اجازهٔ این کار را ندارید.'))
            return redirect('requests:admin-detail', pk=pk)
        if target.plant_id:
            messages.info(request, _('برای این درخواست قبلاً نیروگاه ساخته شده است.'))
            return redirect('plants:edit', pk=target.plant_id)
        # The plant is the customer's, never the technician's. A request made
        # without signing in (exhibition, phone) gets the SMS-login account for
        # its mobile, created now; the customer sees the plant on first login.
        owner = (target.user if lifecycle.is_customer_account(target.user)
                 else lifecycle.customer_account_for(target.mobile, create=True))
        if owner is None:
            messages.error(request, _(
                'حسابی با رمز عبور با موبایل %(m)s وجود دارد و نمی‌توان مطمئن بود مال همین مشتری است. '
                'ابتدا مشتری با کد پیامکی وارد شود، سپس نیروگاه را بسازید.') % {'m': target.mobile})
            return redirect('requests:admin-detail', pk=pk)
        location_name = (
            target.install_address or f'{target.province} {target.city}'
        ).strip() or target.province
        # Do not embed customer name — technical staff must not leak identity
        # into the plant record; Request ID + site location is enough.
        plant = Plant.objects.create(
            name=f'درخواست #{target.id}',
            owner=owner,
            external_code=f'REQ-{target.id}',
            location_name=location_name,
            latitude=float(target.latitude or 0),
            longitude=float(target.longitude or 0),
            capacity_kw=0,
        )
        target.plant = plant
        target.user = owner
        target.save(update_fields=['plant', 'user', 'updated_at'])
        from apps.core.services import write_audit_log
        write_audit_log(actor=user, action='request.plant_commissioned',
                        target_type='request', target_id=str(target.id),
                        metadata={'plant_id': plant.id})
        messages.success(request, _('نیروگاه ساخته شد. اطلاعات فنی را کامل کنید.'))
        return redirect('plants:edit', pk=plant.id)


class OfferAddView(LoginRequiredMixin, RequestStaffRequiredMixin, View):
    """Pricing is the technical team's job (and management)."""
    def post(self, request, pk):
        if not (repositories.is_technical(request.user) or repositories.is_management(request.user)):
            messages.error(request, _('ثبت پیشنهاد فنی برعهدهٔ بخش فنی است.'))
            return redirect('requests:admin-detail', pk=pk)
        target = get_object_or_404(Request, pk=pk)
        try:
            amount = Decimal(_clean_number(request.POST.get('amount', '0')) or '0')
        except InvalidOperation:
            messages.error(request, _('مبلغ نامعتبر است.'))
            return redirect('requests:admin-detail', pk=pk)
        # The technical team proposes the solution; sales sets the price.
        if not repositories.is_management(request.user):
            amount = Decimal('0')

        try:
            vat_percent = int(str(request.POST.get('vat_percent', '10')).strip() or '10')
        except ValueError:
            vat_percent = 10

        valid_until = None
        raw = request.POST.get('valid_until')
        if raw:
            # Typed as a Jalali day (۱۴۰۵/۰۸/۳۰): valid to the end of that day.
            from datetime import datetime, time as dtime
            from apps.core.dates import parse_user_date
            day = parse_user_date(raw)
            parsed = (datetime.combine(day, dtime(23, 59)) if day else parse_datetime(raw))
            if parsed and timezone.is_naive(parsed):
                parsed = timezone.make_aware(parsed)
            valid_until = parsed

        try:
            offer_service.add_offer(
                request=target,
                title=request.POST.get('title', '').strip() or 'پیشنهاد',
                amount=amount,
                vat_percent=vat_percent,
                description=request.POST.get('description', '').strip(),
                valid_until=valid_until,
                created_by=request.user,
            )
            messages.success(request, _('پیشنهاد ثبت شد.'))
        except offer_service.OfferError as exc:
            messages.error(request, str(exc))
        return redirect('requests:admin-detail', pk=pk)


class OfferPriceView(LoginRequiredMixin, RequestManagerRequiredMixin, View):
    """Sales (or management) prices an offer during negotiation."""
    def post(self, request, pk):
        offer = get_object_or_404(RequestOffer.objects.select_related('request'), pk=pk)
        target = offer.request
        allowed = (repositories.is_sales(request.user) or repositories.is_management(request.user))
        in_negotiation = (target.department == Request.Department.SALES
                          and target.sales_phase == Request.SalesPhase.NEGOTIATION)
        if not (allowed and in_negotiation):
            messages.error(request, _('تعیین مبلغ در مرحلهٔ مذاکره و برعهدهٔ بخش فروش است.'))
            return redirect('requests:admin-detail', pk=target.pk)
        try:
            amount = Decimal(_clean_number(request.POST.get('amount', '')) or '0')
            offer_service.set_price(offer=offer, amount=amount, actor=request.user)
            messages.success(request, _('مبلغ پیشنهاد ثبت شد.'))
        except InvalidOperation:
            messages.error(request, _('مبلغ نامعتبر است.'))
        except (offer_service.OfferError, contract_service.ContractError) as exc:
            messages.error(request, str(exc))
        return redirect('requests:admin-detail', pk=target.pk)


class OfferToggleView(LoginRequiredMixin, RequestStaffRequiredMixin, View):
    def post(self, request, pk):
        if not (repositories.is_technical(request.user) or repositories.is_management(request.user)):
            messages.error(request, _('شما اجازهٔ این کار را ندارید.'))
            offer = get_object_or_404(RequestOffer, pk=pk)
            return redirect('requests:admin-detail', pk=offer.request_id)
        offer = get_object_or_404(RequestOffer, pk=pk)
        offer_service.toggle_active(offer, actor=request.user)
        messages.success(request, _('وضعیت پیشنهاد تغییر کرد.'))
        return redirect('requests:admin-detail', pk=offer.request_id)


class OfferIssueContractView(LoginRequiredMixin, RequestManagerRequiredMixin, View):
    """Issue (auto-generate) the contract for a chosen offer."""
    def post(self, request, pk):
        offer = get_object_or_404(RequestOffer, pk=pk)
        try:
            contract_service.generate_contract(request=offer.request, offer=offer, actor=request.user)
            messages.success(request, _('قرارداد به‌صورت خودکار صادر شد.'))
        except contract_service.ContractError as exc:
            messages.error(request, str(exc))
        return redirect('requests:admin-detail', pk=offer.request_id)


def _stop_case(request, pk, to_status):
    """Cancel or close a case for the team that holds it, with a recorded reason."""
    target = get_object_or_404(
        repositories.scope_requests_by_department(request.user, Request.objects.all()), pk=pk)
    blocked = _blocked_reason(request.user, target)
    if blocked or not repositories.owns_current_stage(request.user, target):
        messages.error(request, blocked or _('این پرونده در اختیار بخش شما نیست.'))
        return redirect('requests:admin-detail', pk=pk)
    try:
        lifecycle.stop_request(target, to_status, actor=request.user,
                               reason=request.POST.get('reason', ''),
                               note=request.POST.get('note', '').strip()[:2000])
        messages.success(request, _('درخواست لغو شد.') if to_status == Request.Status.CANCELLED
                         else _('درخواست به‌عنوان از دست‌رفته بسته شد.'))
    except (lifecycle.DepartmentError, lifecycle.TransitionError) as exc:
        messages.error(request, str(exc))
    return redirect('requests:admin-detail', pk=pk)


class RequestStatusChangeView(LoginRequiredMixin, RequestStaffRequiredMixin, View):
    def post(self, request, pk):
        # Only stopping a case is manual; advancing happens through the workflow.
        to_status = request.POST.get('status', '')
        if to_status not in (Request.Status.CANCELLED, Request.Status.CLOSED):
            messages.error(request, _('از این بخش تنها امکان لغو یا بستن درخواست وجود دارد.'))
            return redirect('requests:admin-detail', pk=pk)
        return _stop_case(request, pk, to_status)


class RequestFunnelView(LoginRequiredMixin, RequestStaffRequiredMixin, ListView):
    """The funnel board: open cases per stage, as far as this role may see."""
    template_name = 'requests/admin/funnel.html'
    context_object_name = 'columns'

    def get_queryset(self):
        status = Request.Status
        base = repositories.scope_requests_by_department(self.request.user, Request.objects.all())
        self.stopped = base.filter(status__in=(status.CLOSED, status.CANCELLED)).count()
        rows = base.exclude(status__in=(status.CLOSED, status.CANCELLED))
        counts = dict(rows.order_by().values_list('funnel_stage').annotate(n=Count('id')))
        self.total = sum(counts.values())
        columns = []
        for value, label in Request.FunnelStage.choices:
            count = counts.get(value, 0)
            columns.append({
                'value': value, 'label': label, 'count': count,
                'pct': round(count * 100 / self.total) if self.total else 0,
                'items': rows.filter(funnel_stage=value).order_by('stage_entered_at')[:6],
            })
        return columns

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        ctx.update({'page_title': 'قیف فروش', 'total': self.total, 'stopped': self.stopped,
                    'can_create_lead': repositories.can_create_lead(user),
                    'hide_customer_identity': repositories.is_identity_restricted(user)})
        return ctx


class LeadCreatorRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        return repositories.can_create_lead(self.request.user)


class LeadCreateView(LoginRequiredMixin, LeadCreatorRequiredMixin, CreateView):
    model = Request
    form_class = LeadForm
    template_name = 'requests/admin/lead_form.html'
    extra_context = {'page_title': 'ثبت دستی لید'}

    def form_valid(self, form):
        user = self.request.user
        values = dict(form.cleaned_data)
        values['lead_source'] = values.get('how_heard') or 'manual'
        if repositories.is_sales(user):
            # A lead sales found itself goes straight to its own qualification.
            values.update(department=Request.Department.SALES,
                          sales_phase=Request.SalesPhase.QUALIFICATION, sales_assignee=user)
        lead = lifecycle.create_request(**values)
        write_audit_log(actor=user, action='request.manual_lead', target_type='request', target_id=str(lead.id))
        lifecycle.add_note(lead, 'لید به‌صورت دستی ثبت شد.', actor=user, kind=RequestStageNote.Kind.EDIT)
        others = list(Request.objects.filter(mobile=lead.mobile).exclude(pk=lead.pk).exclude(
            status__in=(Request.Status.CLOSED, Request.Status.CANCELLED)).values_list('pk', flat=True)[:5])
        messages.success(self.request, _('لید ثبت شد.'))
        if others:
            messages.warning(self.request, _('برای این موبایل پروندهٔ باز دیگری هم هست: %(ids)s') % {
                'ids': '، '.join(f'#{pk}' for pk in others)})
        return redirect('requests:admin-detail', pk=lead.pk)


class LeadUpdateView(LoginRequiredMixin, UserPassesTestMixin, UpdateView):
    model = Request
    form_class = LeadForm
    template_name = 'requests/admin/lead_form.html'

    def get_queryset(self):
        return repositories.scope_requests_by_department(self.request.user, Request.objects.all())

    def test_func(self):
        target = self.get_object()
        return (repositories.can_edit_lead(self.request.user, target)
                and target.status not in (Request.Status.CLOSED, Request.Status.CANCELLED))

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs, page_title=f'ویرایش لید #{self.object.pk}')

    def form_valid(self, form):
        lead = form.save()
        if form.changed_data:
            labels = '، '.join(str(form.fields[name].label) for name in form.changed_data)
            write_audit_log(actor=self.request.user, action='request.lead_edited', target_type='request',
                            target_id=str(lead.id), metadata={'fields': form.changed_data})
            lifecycle.add_note(lead, f'ویرایش اطلاعات: {labels}', actor=self.request.user,
                               kind=RequestStageNote.Kind.EDIT)
        messages.success(self.request, _('اطلاعات لید ذخیره شد.'))
        return redirect('requests:admin-detail', pk=lead.pk)


class RequestNoteAddView(LoginRequiredMixin, RequestStaffRequiredMixin, View):
    def post(self, request, pk):
        target = get_object_or_404(
            repositories.scope_requests_by_department(request.user, Request.objects.all()), pk=pk)
        body = request.POST.get('body', '').strip()[:2000]
        if body:
            lifecycle.add_note(target, body, actor=request.user)
            messages.success(request, _('یادداشت ثبت شد.'))
        else:
            messages.error(request, _('متن یادداشت را وارد کنید.'))
        return redirect('requests:admin-detail', pk=pk)


class RequestFunnelAdvanceView(LoginRequiredMixin, RequestStaffRequiredMixin, View):
    def post(self, request, pk):
        user = request.user
        target = get_object_or_404(repositories.scope_requests_by_department(user, Request.objects.all()), pk=pk)
        action = request.POST.get('action')
        if action == 'commercial' and (repositories.is_sales(user) or repositories.is_management(user)):
            mover = lifecycle.start_commercial_offer
        elif action == 'operation' and (repositories.is_technical(user) or repositories.is_management(user)
                                        or repositories.is_operations(user)):
            mover = lifecycle.start_operation
        else:
            messages.error(request, _('شما اجازهٔ این کار را ندارید.'))
            return redirect('requests:admin-detail', pk=pk)
        try:
            mover(target, actor=user)
            messages.success(request, _('پرونده به مرحلهٔ بعد رفت.'))
        except lifecycle.DepartmentError as exc:
            messages.error(request, str(exc))
        return redirect('requests:admin-detail', pk=pk)


class RequestFunnelSetView(LoginRequiredMixin, ManagementRequiredMixin, View):
    def post(self, request, pk):
        target = get_object_or_404(Request, pk=pk)
        note = request.POST.get('note', '').strip()[:2000]
        if not note:
            messages.error(request, _('دلیل تغییر مرحله را بنویسید.'))
            return redirect('requests:admin-detail', pk=pk)
        try:
            lifecycle.set_funnel_stage(target, request.POST.get('stage', ''), actor=request.user, note=note,
                                       notify=bool(request.POST.get('notify')))
            messages.success(request, _('مرحلهٔ پرونده تغییر کرد.'))
        except lifecycle.DepartmentError as exc:
            messages.error(request, str(exc))
        return redirect('requests:admin-detail', pk=pk)


class RequestTrackingView(LoginRequiredMixin, ManagementRequiredMixin, ListView):
    """Management oversight: which department/user has acted on each request."""
    template_name = 'requests/admin/tracking.html'
    paginate_by = 25
    context_object_name = 'requests'

    def get_queryset(self):
        qs = repositories.filter_requests(department=self.request.GET.get('department') or None)
        if self.request.GET.get('overdue'):
            return repositories.overdue_requests(qs).order_by('stage_entered_at')
        return qs.order_by('-created_at')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        dept = Request.Department
        base = Request.objects.all()
        ctx['page_title'] = 'پیگیری کارها'
        ctx['department_choices'] = dept.choices
        ctx['current_department'] = self.request.GET.get('department', '')
        ctx['overdue_only'] = bool(self.request.GET.get('overdue'))
        ctx['sla_hours'] = lifecycle.STAGE_SLA_HOURS
        ctx['stats'] = {
            'total': base.count(),
            'in_marketing': base.filter(department=dept.MARKETING).count(),
            'in_technical': base.filter(department=dept.TECHNICAL).count(),
            'in_sales': base.filter(department=dept.SALES).count(),
            'done': base.filter(department=dept.DONE).count(),
            'crm': base.filter(crm_transferred=True).count(),
        }
        ctx['sales_by_user'] = (
            base.filter(sales_completed_by__isnull=False)
            .values('sales_completed_by__username')
            .annotate(n=Count('id')).order_by('-n')
        )
        ctx['technical_by_user'] = (
            base.filter(technical_completed_by__isnull=False)
            .values('technical_completed_by__username')
            .annotate(n=Count('id')).order_by('-n')
        )
        return ctx


class LeadDashboardView(LoginRequiredMixin, RequestStaffRequiredMixin, ListView):
    """Role-based website lead dashboards (marketing / sales / ops).

    Management/admin → executive home. Technical → unified technical home.
    """
    context_object_name = 'recent_requests'
    paginate_by = 10

    def dispatch(self, request, *args, **kwargs):
        user = request.user
        if user.is_authenticated and (
            user.is_superuser or getattr(user, 'role', '') == 'admin'
            or repositories.is_management(user)
        ):
            return redirect('dashboard')
        if user.is_authenticated and repositories.is_technical(user):
            return redirect('dashboard')
        return super().dispatch(request, *args, **kwargs)

    def get_template_names(self):
        from apps.requests.dashboard_context import resolve_dashboard_role
        role = resolve_dashboard_role(self.request.user)
        mapping = {
            'marketing': 'requests/admin/dashboards/marketing.html',
            'sales': 'requests/admin/dashboards/sales.html',
            'operations': 'requests/admin/dashboards/operations.html',
        }
        return [mapping.get(role, 'requests/admin/dashboard.html')]

    def get_queryset(self):
        qs = repositories.scope_requests_by_department(
            self.request.user, Request.objects.all())
        return qs.order_by('-updated_at')

    def get_context_data(self, **kwargs):
        from apps.requests.dashboard_context import build_lead_fleet_context
        ctx = super().get_context_data(**kwargs)
        data = build_lead_fleet_context(self.request.user)
        role = data['dashboard_role']
        data.pop('recent_requests', None)
        ctx.update(data)
        ctx['page_title'] = {
            'marketing': 'داشبورد بازاریابی',
            'sales': 'داشبورد فروش',
            'operations': 'داشبورد عملیات',
        }.get(role, 'داشبورد')
        ctx['title'] = ctx['page_title']
        return ctx


class OfferAdminListView(LoginRequiredMixin, RequestStaffRequiredMixin, ListView):
    # Pricing belongs to the technical team now, so they (and management) may
    # view the offers list; the queryset is still department-scoped below.
    template_name = 'requests/admin/offers.html'
    paginate_by = 25
    context_object_name = 'offers'
    extra_context = {'page_title': 'پیشنهادها'}

    def get_queryset(self):
        qs = RequestOffer.objects.select_related('request', 'created_by').order_by('-created_at')
        return repositories.scope_related_by_department(self.request.user, qs)


class PaymentAdminListView(LoginRequiredMixin, RequestManagerRequiredMixin, ListView):
    template_name = 'requests/admin/payments.html'
    paginate_by = 25
    context_object_name = 'payments'
    extra_context = {'page_title': 'پرداخت‌ها'}

    def get_queryset(self):
        qs = RequestPayment.objects.select_related('request', 'offer').order_by('-created_at')
        return repositories.scope_related_by_department(self.request.user, qs)

    def get_context_data(self, **kwargs):
        from .models import ContractInstallment
        ctx = super().get_context_data(**kwargs)
        rows = ContractInstallment.objects.select_related('contract__request').order_by('due_date')
        rows = repositories.scope_related_by_department(self.request.user, rows, field='contract__request')
        ctx['installments_waiting'] = rows.filter(status=ContractInstallment.Status.SUBMITTED)
        ctx['installments_open'] = rows.filter(status__in=(ContractInstallment.Status.PENDING,
                                                           ContractInstallment.Status.REJECTED))[:50]
        ctx['can_review_finance'] = project_service.can_review(self.request.user)
        return ctx


class ContractAdminListView(LoginRequiredMixin, RequestManagerRequiredMixin, ListView):
    template_name = 'requests/admin/contracts.html'
    paginate_by = 25
    context_object_name = 'contracts'
    extra_context = {'page_title': 'قراردادها'}

    def get_queryset(self):
        qs = RequestContract.objects.select_related('request', 'offer').order_by('-created_at')
        return repositories.scope_related_by_department(self.request.user, qs)


class SmsLogAdminListView(LoginRequiredMixin, RequestManagerRequiredMixin, ListView):
    template_name = 'requests/admin/sms_logs.html'
    paginate_by = 25
    context_object_name = 'logs'
    extra_context = {'page_title': 'لاگ پیامک‌ها'}

    def get_queryset(self):
        qs = RequestMessageLog.objects.select_related('request').order_by('-created_at')
        return repositories.scope_related_by_department(self.request.user, qs)


# --------------------------------------------------------------------------- #
# Contract templates (multiple, named) + .txt/.docx upload
# --------------------------------------------------------------------------- #

class ContractTemplateListView(LoginRequiredMixin, RequestManagerRequiredMixin, ListView):
    template_name = 'requests/admin/template_list.html'
    context_object_name = 'templates'
    extra_context = {'page_title': 'قالب‌های قرارداد'}

    def get_queryset(self):
        return ContractTemplate.objects.order_by('-is_active', '-updated_at')


class _TemplateSaveMixin:
    """Read an uploaded .txt/.docx into the body and keep a single active template."""

    def save_template(self, form):
        obj = form.save(commit=False)
        upload = form.cleaned_data.get('upload')
        if upload:
            try:
                obj.body = contract_service.read_uploaded_template(upload)
            except Exception:  # noqa: BLE001
                messages.error(self.request, _('خواندن فایل ناموفق بود.'))
                return None
            upload.seek(0)  # reading consumed the pointer; rewind before storing
            obj.source_file = upload
        obj.save()
        if obj.is_active:
            ContractTemplate.objects.exclude(pk=obj.pk).update(is_active=False)
        return obj

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['placeholders'] = contract_service.TEMPLATE_PLACEHOLDERS
        ctx['default_template'] = contract_service.DEFAULT_CONTRACT_TEMPLATE
        return ctx


class ContractTemplateCreateView(LoginRequiredMixin, RequestManagerRequiredMixin, _TemplateSaveMixin, CreateView):
    model = ContractTemplate
    form_class = ContractTemplateForm
    template_name = 'requests/admin/template_form.html'
    extra_context = {'page_title': _('قالب جدید قرارداد')}

    def form_valid(self, form):
        if self.save_template(form) is None:
            return self.form_invalid(form)
        messages.success(self.request, _('قالب قرارداد ذخیره شد.'))
        return redirect('requests:admin-templates')


class ContractTemplateEditView(LoginRequiredMixin, RequestManagerRequiredMixin, _TemplateSaveMixin, UpdateView):
    model = ContractTemplate
    form_class = ContractTemplateForm
    template_name = 'requests/admin/template_form.html'
    extra_context = {'page_title': _('ویرایش قالب قرارداد')}

    def form_valid(self, form):
        if self.save_template(form) is None:
            return self.form_invalid(form)
        messages.success(self.request, _('قالب قرارداد ذخیره شد.'))
        return redirect('requests:admin-templates')


class ContractTemplateActivateView(LoginRequiredMixin, RequestManagerRequiredMixin, View):
    def post(self, request, pk):
        tpl = get_object_or_404(ContractTemplate, pk=pk)
        ContractTemplate.objects.update(is_active=False)
        tpl.is_active = True
        tpl.save(update_fields=['is_active', 'updated_at'])
        messages.success(request, _('قالب فعال شد.'))
        return redirect('requests:admin-templates')


class ContractTemplateDeleteView(LoginRequiredMixin, RequestManagerRequiredMixin, View):
    def post(self, request, pk):
        get_object_or_404(ContractTemplate, pk=pk).delete()
        messages.success(request, _('قالب حذف شد.'))
        return redirect('requests:admin-templates')


# --------------------------------------------------------------------------- #
# Contract settings (company header / page margins / customer page)
# --------------------------------------------------------------------------- #

class ContractSettingsView(LoginRequiredMixin, RequestManagerRequiredMixin, UpdateView):
    model = ContractSettings
    form_class = ContractSettingsForm
    template_name = 'requests/admin/contract_settings.html'
    extra_context = {'page_title': 'تنظیمات قرارداد'}

    def get_object(self, queryset=None):
        return ContractSettings.load()

    def get_success_url(self):
        return reverse('requests:contract-settings')

    def form_valid(self, form):
        messages.success(self.request, _('تنظیمات قرارداد ذخیره شد.'))
        return super().form_valid(form)


# --------------------------------------------------------------------------- #
# Tickets (admin side)
# --------------------------------------------------------------------------- #

class TicketAdminListView(LoginRequiredMixin, RequestStaffRequiredMixin, ListView):
    template_name = 'requests/admin/ticket_list.html'
    paginate_by = 25
    context_object_name = 'tickets'
    extra_context = {'page_title': 'تیکت‌ها'}

    def get_queryset(self):
        qs = Ticket.objects.select_related('user', 'request').order_by('-updated_at')
        qs = repositories.scope_tickets_by_department(self.request.user, qs)
        status = self.request.GET.get('status')
        if status:
            qs = qs.filter(status=status)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['status_choices'] = Ticket.Status.choices
        ctx['current_status'] = self.request.GET.get('status', '')
        ctx['show_department'] = True
        return ctx


class TicketAdminCreateView(LoginRequiredMixin, RequestStaffRequiredMixin, View):
    """Staff opens an internal ticket to another department (or management)."""

    template_name = 'requests/admin/ticket_form.html'

    def _own_department(self, user):
        if repositories.is_marketing(user):
            return Ticket.Department.MARKETING
        if repositories.is_sales(user):
            return Ticket.Department.SALES
        if repositories.is_technical(user):
            return Ticket.Department.TECHNICAL
        if repositories.is_operations(user):
            return Ticket.Department.OPERATIONS
        if repositories.is_management(user):
            return Ticket.Department.MANAGEMENT
        return None

    def get(self, request):
        own = self._own_department(request.user)
        form = TicketForm(exclude_departments=[own] if own and not repositories.is_management(request.user) else None)
        return render(request, self.template_name, {
            'form': form,
            'page_title': 'تیکت',
        })

    def post(self, request):
        own = self._own_department(request.user)
        form = TicketForm(
            request.POST,
            exclude_departments=[own] if own and not repositories.is_management(request.user) else None,
        )
        if form.is_valid():
            ticket = Ticket.objects.create(
                user=request.user,
                department=form.cleaned_data['department'],
                subject=form.cleaned_data['subject'],
                priority=form.cleaned_data['priority'],
            )
            TicketMessage.objects.create(
                ticket=ticket,
                author=request.user,
                is_staff_reply=True,
                body=form.cleaned_data['message'],
            )
            messages.success(request, _('تیکت ثبت شد.'))
            return redirect('requests:admin-ticket-detail', pk=ticket.id)
        return render(request, self.template_name, {
            'form': form,
            'page_title': 'تیکت',
        })


class TicketAdminDetailView(LoginRequiredMixin, RequestStaffRequiredMixin, DetailView):
    model = Ticket
    template_name = 'requests/admin/ticket_detail.html'
    context_object_name = 'ticket'

    def get_queryset(self):
        return repositories.scope_tickets_by_department(
            self.request.user, Ticket.objects.all())

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['thread'] = self.object.ticket_messages.select_related('author').all()
        ctx['reply_form'] = TicketReplyForm()
        ctx['status_choices'] = Ticket.Status.choices
        ctx['page_title'] = f'تیکت #{self.object.id}'
        return ctx


class TicketAdminReplyView(LoginRequiredMixin, RequestStaffRequiredMixin, View):
    def post(self, request, pk):
        ticket = get_object_or_404(
            repositories.scope_tickets_by_department(request.user, Ticket.objects.all()),
            pk=pk)
        form = TicketReplyForm(request.POST, request.FILES)
        if form.is_valid():
            TicketMessage.objects.create(
                ticket=ticket, author=request.user, is_staff_reply=True,
                body=form.cleaned_data['body'], attachment=form.cleaned_data.get('attachment'),
            )
            ticket.status = Ticket.Status.ANSWERED
            ticket.save(update_fields=['status', 'updated_at'])
            messages.success(request, _('پاسخ ثبت شد.'))
        else:
            messages.error(request, _('متن پاسخ را وارد کنید.'))
        return redirect('requests:admin-ticket-detail', pk=pk)


class TicketAdminStatusView(LoginRequiredMixin, RequestStaffRequiredMixin, View):
    def post(self, request, pk):
        ticket = get_object_or_404(
            repositories.scope_tickets_by_department(request.user, Ticket.objects.all()),
            pk=pk)
        new_status = request.POST.get('status')
        if new_status in Ticket.Status.values:
            ticket.status = new_status
            ticket.save(update_fields=['status', 'updated_at'])
            messages.success(request, _('وضعیت تیکت به‌روزرسانی شد.'))
        return redirect('requests:admin-ticket-detail', pk=pk)
