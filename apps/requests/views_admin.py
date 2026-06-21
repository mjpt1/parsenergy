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
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.translation import gettext_lazy as _
from django.views.generic import CreateView, DetailView, ListView, UpdateView, View

from . import repositories
from .forms import ContractSettingsForm, ContractTemplateForm, TicketReplyForm
from .models import (
    ContractSettings,
    ContractTemplate,
    Request,
    RequestContract,
    RequestMessageLog,
    RequestOffer,
    RequestPayment,
    Ticket,
    TicketMessage,
)
from .services import contracts as contract_service
from .services import lifecycle
from .services import offers as offer_service


class RequestManagerRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        user = getattr(self.request, 'user', None)
        return bool(user and repositories.is_request_manager(user))


def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except ValueError:
        return None


class RequestAdminListView(LoginRequiredMixin, RequestManagerRequiredMixin, ListView):
    template_name = 'requests/admin/list.html'
    paginate_by = 25
    context_object_name = 'requests'

    def get_queryset(self):
        return repositories.filter_requests(
            status=self.request.GET.get('status') or None,
            province=self.request.GET.get('province') or None,
            date_from=_parse_date(self.request.GET.get('date_from')),
            date_to=_parse_date(self.request.GET.get('date_to')),
        ).order_by('-created_at')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['page_title'] = 'مدیریت درخواست‌ها'
        ctx['status_choices'] = Request.Status.choices
        ctx['provinces'] = (
            Request.objects.order_by('province')
            .values_list('province', flat=True)
            .distinct()
        )
        ctx['current'] = {
            key: self.request.GET.get(key, '')
            for key in ('status', 'province', 'date_from', 'date_to')
        }
        return ctx


class RequestAdminDetailView(LoginRequiredMixin, RequestManagerRequiredMixin, DetailView):
    model = Request
    template_name = 'requests/admin/detail.html'
    context_object_name = 'req'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        req = self.object
        offer_count = req.offers.count()
        status = Request.Status
        contract = RequestContract.objects.filter(request=req).first()
        contract_open = contract is None or contract.status != RequestContract.Status.APPROVED
        ctx.update({
            'page_title': f'درخواست #{req.id}',
            'offers': req.offers.all(),
            'offer_count': offer_count,
            'max_offers': offer_service.MAX_OFFERS_PER_REQUEST,
            'contract': contract,
            'payments': req.payments.select_related('offer').all(),
            'sms_logs': req.message_logs.all(),
            'can_add_offer': offer_count < offer_service.MAX_OFFERS_PER_REQUEST
            and req.status in (status.NEW, status.OFFERED),
            # An admin can issue the contract from a chosen offer until one is approved.
            'can_issue_contract': req.status in (status.OFFERED, status.CONTRACT_GENERATED) and contract_open,
            # Admins may only cancel from here; forward workflow states are reached
            # through the customer/payment flow so manual jumps can't leave the
            # request inconsistent (e.g. "contract" status without a contract).
            'can_cancel': req.status not in (status.PAID, status.CANCELLED),
        })
        return ctx


class OfferAddView(LoginRequiredMixin, RequestManagerRequiredMixin, View):
    def post(self, request, pk):
        target = get_object_or_404(Request, pk=pk)
        try:
            amount = Decimal(str(request.POST.get('amount', '0')).strip() or '0')
        except InvalidOperation:
            messages.error(request, _('مبلغ نامعتبر است.'))
            return redirect('requests:admin-detail', pk=pk)

        try:
            vat_percent = int(str(request.POST.get('vat_percent', '10')).strip() or '10')
        except ValueError:
            vat_percent = 10

        valid_until = None
        raw = request.POST.get('valid_until')
        if raw:
            parsed = parse_datetime(raw)
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


class OfferToggleView(LoginRequiredMixin, RequestManagerRequiredMixin, View):
    def post(self, request, pk):
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


class RequestStatusChangeView(LoginRequiredMixin, RequestManagerRequiredMixin, View):
    def post(self, request, pk):
        target = get_object_or_404(Request, pk=pk)
        # Only cancellation is allowed manually; advancing the workflow happens
        # through offer selection / OTP approval / payment.
        if request.POST.get('status', '') != Request.Status.CANCELLED:
            messages.error(request, _('از این بخش تنها امکان لغو درخواست وجود دارد.'))
            return redirect('requests:admin-detail', pk=pk)
        try:
            lifecycle.transition(target, Request.Status.CANCELLED, actor=request.user)
            messages.success(request, _('درخواست لغو شد.'))
        except lifecycle.TransitionError as exc:
            messages.error(request, str(exc))
        return redirect('requests:admin-detail', pk=pk)


class OfferAdminListView(LoginRequiredMixin, RequestManagerRequiredMixin, ListView):
    template_name = 'requests/admin/offers.html'
    paginate_by = 25
    context_object_name = 'offers'
    extra_context = {'page_title': 'پیشنهادهای قیمت'}

    def get_queryset(self):
        return RequestOffer.objects.select_related('request', 'created_by').order_by('-created_at')


class PaymentAdminListView(LoginRequiredMixin, RequestManagerRequiredMixin, ListView):
    template_name = 'requests/admin/payments.html'
    paginate_by = 25
    context_object_name = 'payments'
    extra_context = {'page_title': 'پرداخت‌ها'}

    def get_queryset(self):
        return RequestPayment.objects.select_related('request', 'offer').order_by('-created_at')


class ContractAdminListView(LoginRequiredMixin, RequestManagerRequiredMixin, ListView):
    template_name = 'requests/admin/contracts.html'
    paginate_by = 25
    context_object_name = 'contracts'
    extra_context = {'page_title': 'قراردادها'}

    def get_queryset(self):
        return RequestContract.objects.select_related('request', 'offer').order_by('-created_at')


class SmsLogAdminListView(LoginRequiredMixin, RequestManagerRequiredMixin, ListView):
    template_name = 'requests/admin/sms_logs.html'
    paginate_by = 25
    context_object_name = 'logs'
    extra_context = {'page_title': 'لاگ پیامک‌ها'}

    def get_queryset(self):
        return RequestMessageLog.objects.select_related('request').order_by('-created_at')


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

class TicketAdminListView(LoginRequiredMixin, RequestManagerRequiredMixin, ListView):
    template_name = 'requests/admin/ticket_list.html'
    paginate_by = 25
    context_object_name = 'tickets'
    extra_context = {'page_title': 'تیکت‌ها'}

    def get_queryset(self):
        qs = Ticket.objects.select_related('user', 'request').order_by('-updated_at')
        status = self.request.GET.get('status')
        if status:
            qs = qs.filter(status=status)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['status_choices'] = Ticket.Status.choices
        ctx['current_status'] = self.request.GET.get('status', '')
        return ctx


class TicketAdminDetailView(LoginRequiredMixin, RequestManagerRequiredMixin, DetailView):
    model = Ticket
    template_name = 'requests/admin/ticket_detail.html'
    context_object_name = 'ticket'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['thread'] = self.object.ticket_messages.select_related('author').all()
        ctx['reply_form'] = TicketReplyForm()
        ctx['status_choices'] = Ticket.Status.choices
        ctx['page_title'] = f'تیکت #{self.object.id}'
        return ctx


class TicketAdminReplyView(LoginRequiredMixin, RequestManagerRequiredMixin, View):
    def post(self, request, pk):
        ticket = get_object_or_404(Ticket, pk=pk)
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


class TicketAdminStatusView(LoginRequiredMixin, RequestManagerRequiredMixin, View):
    def post(self, request, pk):
        ticket = get_object_or_404(Ticket, pk=pk)
        new_status = request.POST.get('status')
        if new_status in Ticket.Status.values:
            ticket.status = new_status
            ticket.save(update_fields=['status', 'updated_at'])
            messages.success(request, _('وضعیت تیکت به‌روزرسانی شد.'))
        return redirect('requests:admin-ticket-detail', pk=pk)
