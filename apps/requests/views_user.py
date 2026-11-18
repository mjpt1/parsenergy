"""User-panel pages for the requests module ("درخواست‌های من").

Entry flow for a visitor: submit a request -> verify mobile via OTP
(register or login) -> the request lands in "my requests".
All pages use the existing user-panel layout (base.html).
"""
from __future__ import annotations

import re

from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Prefetch, Q
from django.http import HttpResponse
from datetime import timedelta

from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.generic import DetailView, ListView, UpdateView

from .forms import (ProfileCompletionForm, RequestEditForm, RequestSubmitForm,
                    TicketForm, TicketReplyForm)
from .iran_locations import CITIES, PROVINCES
from .models import (
    ContractSettings,
    OtpVerification,
    Request,
    RequestContract,
    RequestFormField,
    RequestFormStep,
    RequestOffer,
    RequestPayment,
    Ticket,
    TicketMessage,
    UserProfileCompletion,
)
from .services import contracts as contract_service
from .services import delivery as delivery_service
from .services import identity as identity_service
from .services import lifecycle
from .services import offers as offer_service
from .services import otp as otp_service
from .services import payments as payment_service
from .services import project as project_service

User = get_user_model()
_AUTH_BACKEND = 'django.contrib.auth.backends.ModelBackend'


def _capture_lead_attribution(request, cd: dict) -> dict:
    """Build lead-source / UTM fields from form + querystring + headers."""
    get = request.GET
    extra = {}
    for key in (
        'utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term',
        'campaign_name', 'medium', 'landing_page', 'referrer', 'device_type',
    ):
        # Cut to the column's own length: MariaDB strict mode rejects longer values.
        limit = Request._meta.get_field(key).max_length
        extra[key] = (cd.get(key) or get.get(key) or '').strip()[:limit]

    if not extra['landing_page']:
        extra['landing_page'] = (request.build_absolute_uri(request.path) or '')[:512]
    if not extra['referrer']:
        extra['referrer'] = (request.META.get('HTTP_REFERER') or '')[:512]

    ua = (request.META.get('HTTP_USER_AGENT') or '').lower()
    if not extra['device_type']:
        if 'mobile' in ua or 'android' in ua or 'iphone' in ua:
            extra['device_type'] = 'mobile'
        elif 'tablet' in ua or 'ipad' in ua:
            extra['device_type'] = 'tablet'
        else:
            extra['device_type'] = 'desktop'

    raw_visit = (cd.get('first_visit_at') or get.get('first_visit_at') or '').strip()
    first_visit = None
    if raw_visit:
        from django.utils.dateparse import parse_datetime
        first_visit = parse_datetime(raw_visit)
        if first_visit and timezone.is_naive(first_visit):
            first_visit = timezone.make_aware(first_visit)
    extra['first_visit_at'] = first_visit

    # Derive lead_source from UTM / how_heard fallback.
    how_heard = (cd.get('how_heard') or '').strip()
    extra['how_heard'] = how_heard
    source = (extra.get('utm_source') or extra.get('campaign_name') or '').strip()
    if source:
        extra['lead_source'] = source[:64]
    elif how_heard:
        extra['lead_source'] = how_heard[:64]
    elif extra.get('referrer'):
        extra['lead_source'] = 'referral'
    else:
        extra['lead_source'] = 'direct'

    if not extra['campaign_name'] and extra.get('utm_campaign'):
        extra['campaign_name'] = extra['utm_campaign'][:128]
    if not extra['medium'] and extra.get('utm_medium'):
        extra['medium'] = extra['utm_medium'][:64]

    # Persist attribution in session for later submits in the same visit.
    attr = {k: (v.isoformat() if hasattr(v, 'isoformat') else v)
            for k, v in extra.items() if v}
    request.session['lead_attribution'] = attr
    return extra


def submit_request(request):
    if request.method == 'POST':
        form = RequestSubmitForm(request.POST)
        if form.is_valid():
            cd = form.cleaned_data
            mobile = cd['mobile']
            # Identity is checked when the customer reaches the contract; the
            # public form only confirms the mobile with a texted code.
            extra = {k: cd.get(k) for k in (
                'request_type', 'user_type', 'needs_financial_consult', 'install_address',
                'partnership_type', 'investment_range', 'area_range', 'shade_status',
                'install_location', 'building_type', 'contact_method',
                'grid_distance_m', 'storage_interest', 'bill_id', 'accepted_terms',
                'latitude', 'longitude',
            )}
            # Backward-compat boolean + system/lead capture.
            extra['needs_financial_consult'] = bool(cd.get('needs_financial_consult'))
            extra['has_shading'] = cd.get('shade_status') == Request.ShadeStatus.YES
            extra.update(_capture_lead_attribution(request, cd))
            extra['ip_address'] = request.META.get('REMOTE_ADDR') or None
            # Values for fields an admin added through the form builder
            # (RequestFormField, is_system=False) — stored as JSON, never as
            # real columns, so they can't collide with the system fields above.
            extra['custom_fields'] = {
                key: cd.get(key) for key in getattr(form, 'custom_field_keys', [])
            }
            # A repeated tap or a back-and-resubmit reuses the request
            # this person made a moment ago instead of adding another.
            req = Request.objects.filter(
                mobile=mobile,
                created_at__gte=timezone.now() - timedelta(minutes=30),
            ).order_by('-created_at').first() or lifecycle.create_request(
                full_name=cd['full_name'],
                mobile=mobile,
                province=cd['province'],
                city=cd.get('city', ''),
                description=cd.get('description', ''),
                user=request.user if request.user.is_authenticated else None,
                **extra,
            )
            if request.user.is_authenticated:
                messages.success(request, _('درخواست شما ثبت شد.'))
                return redirect('requests:my-detail', pk=req.id)

            purpose = (
                OtpVerification.Purpose.LOGIN
                if User.objects.filter(username=mobile).exists()
                else OtpVerification.Purpose.REGISTER
            )
            otp_service.issue(mobile=mobile, purpose=purpose, request=req)
            request.session['pending_request_id'] = req.id
            request.session['otp_mobile'] = mobile
            request.session['otp_purpose'] = purpose
            return redirect('requests:verify')
    else:
        initial = {}
        # Prefill attribution from querystring or prior session visit.
        session_attr = request.session.get('lead_attribution') or {}
        for key in (
            'utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term',
            'campaign_name', 'medium', 'landing_page', 'referrer', 'device_type',
            'first_visit_at',
        ):
            initial[key] = request.GET.get(key) or session_attr.get(key) or ''
        if not initial.get('landing_page'):
            initial['landing_page'] = request.build_absolute_uri(request.path)
        if not initial.get('referrer'):
            initial['referrer'] = request.META.get('HTTP_REFERER') or ''
        if not initial.get('first_visit_at'):
            initial['first_visit_at'] = timezone.now().isoformat()
            request.session.setdefault('lead_first_visit_at', initial['first_visit_at'])
        else:
            initial['first_visit_at'] = (
                request.session.get('lead_first_visit_at') or initial['first_visit_at'])
        form = RequestSubmitForm(initial=initial)
    steps = RequestFormStep.objects.filter(is_active=True).prefetch_related(
        Prefetch('fields', queryset=RequestFormField.objects.filter(is_active=True))
    )
    return render(request, 'requests/user/submit.html', {
        'form': form,
        'page_title': 'فرم ارزیابی',
        'provinces': PROVINCES,
        'cities': CITIES,
        'steps': steps,
        # The wizard owns the whole viewport: no hero, no tabs, no sidebar —
        # nothing to distract from filling the form in.
        'portal_bare': True,
    })


def _resolve_otp_user(mobile):
    """The existing account this mobile belongs to, or None.

    Customers are keyed by `username` (their mobile is their username). Staff
    accounts have a real username, so they are found by `phone_number` — the
    field the staff form now requires. Checking only `username`, as this used
    to, meant an employee's number looked unknown and a fresh customer account
    was created for them.
    """
    return (User.objects.filter(username=mobile).first()
            or User.objects.filter(phone_number=mobile).order_by('pk').first())


def otp_login(request):
    """Mobile + OTP login *or* registration: a new mobile is registered on verify."""
    if request.method == 'POST':
        mobile = request.POST.get('mobile', '').strip()
        if not re.fullmatch(r'09\d{9}', mobile):
            messages.error(request, _('شمارهٔ موبایل را درست وارد کنید (مثل ۰۹۱۲۳۴۵۶۷۸۹).'))
            return render(request, 'requests/user/login.html', {'mobile': mobile})
        # Staff sign in here too, with their own mobile — which is why the
        # number is mandatory on a staff account. Matching on `phone_number`
        # as well as `username` is what stops a second, customer account being
        # created beside their real one; `_resolve_otp_user` then signs them
        # into the account they already have.
        purpose = (
            OtpVerification.Purpose.LOGIN
            if _resolve_otp_user(mobile) is not None
            else OtpVerification.Purpose.REGISTER
        )
        otp_service.issue(mobile=mobile, purpose=purpose)
        request.session['otp_mobile'] = mobile
        request.session['otp_purpose'] = purpose
        return redirect('requests:verify')
    return render(request, 'requests/user/login.html', {})


def verify(request):
    mobile = request.session.get('otp_mobile')
    purpose = request.session.get('otp_purpose')
    if not mobile or not purpose:
        return redirect('requests:otp-login')

    if request.method == 'POST':
        code = request.POST.get('code', '').strip()
        try:
            otp_service.verify(mobile=mobile, code=code, purpose=purpose)
        except otp_service.OtpError as exc:
            messages.error(request, str(exc))
            return render(request, 'requests/user/verify.html', {'mobile': mobile})

        user = _resolve_otp_user(mobile)
        if user is None:
            user = User(username=mobile, phone_number=mobile, role=User.Role.CUSTOMER)
            user.set_unusable_password()
            user.save()
        login(request, user, backend=_AUTH_BACKEND)

        # Attach any anonymous requests submitted with this mobile — but only
        # for an actual customer. A staff member signing in with their own
        # number must not silently become the owner of a customer's requests.
        if lifecycle.is_customer_account(user):
            request.session[lifecycle.SESSION_MOBILE] = mobile
            lifecycle.link_requests(user, mobile)
            # Seed the customer's profile from the form they just filled.
            UserProfileCompletion.ensure_for(user)
        pending = request.session.pop('pending_request_id', None)
        request.session.pop('otp_mobile', None)
        request.session.pop('otp_purpose', None)
        messages.success(request, _('ورود با موفقیت انجام شد.'))
        if pending:
            return redirect('requests:my-detail', pk=pending)
        # Staff who came through the customer door still belong on their own
        # dashboard. This branch used to look only at plant ownership, so a
        # sales or marketing account that signed in here landed in the customer
        # request list and looked, reasonably, like the whole app was broken.
        if getattr(user, 'role', '') != User.Role.CUSTOMER:
            return redirect('dashboard')
        # Once a plant has been commissioned, monitoring it is what the customer
        # comes back for — send them to the dashboard rather than the request
        # list they no longer need to chase.
        if _user_has_plant(user):
            return redirect('dashboard')
        return redirect('requests:my-list')

    return render(request, 'requests/user/verify.html', {'mobile': mobile})


def resend_otp(request):
    mobile = request.session.get('otp_mobile')
    purpose = request.session.get('otp_purpose')
    if mobile and purpose:
        otp_service.issue(mobile=mobile, purpose=purpose)
        messages.success(request, _('کد دوباره ارسال شد.'))
    return redirect('requests:verify')


# --------------------------------------------------------------------------- #
# Authenticated "my requests" pages
# --------------------------------------------------------------------------- #

class MyRequestListView(LoginRequiredMixin, ListView):
    template_name = 'requests/user/my_list.html'
    context_object_name = 'requests'
    paginate_by = 20
    extra_context = {'page_title': 'درخواست‌های من'}

    def get_queryset(self):
        lifecycle.link_session_requests(self.request)
        return Request.objects.filter(user=self.request.user).order_by('-created_at')


class MyRequestDetailView(LoginRequiredMixin, DetailView):
    model = Request
    template_name = 'requests/user/my_detail.html'
    context_object_name = 'req'

    def get_queryset(self):
        lifecycle.link_session_requests(self.request)
        return Request.objects.filter(user=self.request.user)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        req = self.object
        contract = RequestContract.objects.filter(request=req).first()
        status = Request.Status
        ctx.update({
            'page_title': f'درخواست #{req.id}',
            'offers': req.offers.filter(is_active=True),
            'contract': contract,
            'can_select': req.status in (status.OFFERED, status.CONTRACT_GENERATED)
            and (contract is None or contract.status != RequestContract.Status.APPROVED),
            'can_pay': contract is not None
            and contract.status == RequestContract.Status.APPROVED
            and contract.offer.has_price
            and req.status in (status.CONTRACT_APPROVED, status.AWAITING_PAYMENT),
            'price_missing': contract is not None and not contract.offer.has_price,
            'is_paid': req.status == status.PAID,
            'can_edit': _request_editable(req),
            **project_service.customer_context(req),
            **delivery_service.customer_context(req),
        })
        return ctx


def _user_has_plant(user) -> bool:
    """True once a plant is owned by (or shared with) this customer."""
    from apps.plants.models import Plant, PlantMembership
    return Plant.objects.filter(
        Q(owner=user)
        | Q(id__in=PlantMembership.objects.filter(
            user=user, active=True).values_list('plant_id', flat=True))
    ).exists()


@login_required
def my_plant(request):
    """Old "my plant" address: the customer dashboard now shows everything this
    page did (status, map, panels, production), so it forwards there and old
    links and SMS messages keep working."""
    from django.urls import reverse
    pid = request.GET.get('plant', '')
    return redirect(reverse('dashboard') + (f'?plant={pid}' if pid.isdigit() else ''))


def _request_editable(req) -> bool:
    """Customers may edit only while sales/management has unlocked the request
    and the deal is not yet finalised."""
    s = Request.Status
    return bool(req.edit_unlocked) and req.status not in (
        s.PAID, s.CANCELLED, s.CONTRACT_APPROVED, s.AWAITING_PAYMENT)


class MyRequestEditView(LoginRequiredMixin, UpdateView):
    model = Request
    form_class = RequestEditForm
    template_name = 'requests/user/my_edit.html'
    context_object_name = 'req'

    def get_queryset(self):
        return Request.objects.filter(user=self.request.user)

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            obj = self.get_queryset().filter(pk=kwargs.get('pk')).first()
            if obj is not None and not _request_editable(obj):
                messages.info(request, _('این درخواست در مرحله‌ای است که دیگر قابل ویرایش نیست.'))
                return redirect('requests:my-detail', pk=obj.pk)
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['page_title'] = f'ویرایش درخواست #{self.object.id}'
        ctx['provinces'] = PROVINCES
        ctx['cities'] = CITIES
        return ctx

    def get_success_url(self):
        messages.success(self.request, _('درخواست به‌روزرسانی شد.'))
        return reverse('requests:my-detail', kwargs={'pk': self.object.pk})


@login_required
def select_offer(request, pk):
    req = get_object_or_404(Request, pk=pk, user=request.user)
    offer = get_object_or_404(RequestOffer, pk=request.POST.get('offer_id'), request=req)
    try:
        offer_service.select_offer(request=req, offer=offer, actor=request.user)
        messages.success(request, _('پیشنهاد انتخاب شد و قرارداد تولید گردید.'))
        return redirect('requests:contract', pk=req.id)
    except offer_service.OfferError as exc:
        messages.error(request, str(exc))
        return redirect('requests:my-detail', pk=req.id)


@login_required
def contract_view(request, pk):
    req = get_object_or_404(Request, pk=pk, user=request.user)
    contract = RequestContract.objects.filter(request=req).first()
    return render(request, 'requests/user/contract.html', {
        'req': req,
        'contract': contract,
        'settings': ContractSettings.load(),
        'page_title': f'قرارداد درخواست #{req.id}',
    })


@login_required
def send_contract_otp(request, pk):
    """Identity step: verify the national id against the mobile via Shahkar, then
    (on a match) send the contract-approval OTP. Required before approval/payment."""
    req = get_object_or_404(Request, pk=pk, user=request.user)
    contract = RequestContract.objects.filter(request=req).first()
    if contract is None:
        messages.error(request, _('قراردادی برای این درخواست موجود نیست.'))
        return redirect('requests:contract', pk=pk)

    # Identity is normally verified already on the evaluation form; only run the
    # Shahkar check here as a fallback when it hasn't been done yet.
    if not req.identity_verified:
        from apps.core.dates import latin_digits
        national_id = latin_digits(request.POST.get('national_id'))
        is_company_id = (req.user_type == Request.UserType.LEGAL
                         and national_id.isdigit() and len(national_id) == 11)
        if not is_company_id and not (national_id.isdigit() and len(national_id) == 10):
            messages.error(request, _('شناسهٔ ملی شرکت باید ۱۱ رقم و کد ملی ۱۰ رقم باشد.')
                           if req.user_type == Request.UserType.LEGAL
                           else _('کد ملی باید ۱۰ رقم باشد.'))
            return redirect('requests:contract', pk=pk)
        # Shahkar matches a mobile to a person, so it cannot check a company ID;
        # the contract is still confirmed with a code sent to the mobile.
        try:
            matched = is_company_id or identity_service.verify_identity(req.mobile, national_id)[0]
        except identity_service.IdentityError as exc:
            messages.error(request, str(exc))
            return redirect('requests:contract', pk=pk)
        if not matched:
            messages.error(request, _('احراز هویت ناموفق بود: کد ملی با شمارهٔ موبایل مطابقت ندارد.'))
            return redirect('requests:contract', pk=pk)
        req.national_id = national_id
        req.identity_verified = True
        req.identity_verified_at = timezone.now()
        req.save(update_fields=['national_id', 'identity_verified', 'identity_verified_at', 'updated_at'])

    contract_service.request_approval_otp(contract)
    messages.success(request, _('کد تأیید قرارداد ارسال شد.'))
    return redirect('requests:contract', pk=pk)


@login_required
def approve_contract(request, pk):
    req = get_object_or_404(Request, pk=pk, user=request.user)
    contract = RequestContract.objects.filter(request=req).first()
    if contract is None:
        messages.error(request, _('قراردادی برای این درخواست موجود نیست.'))
        return redirect('requests:my-detail', pk=pk)
    if not req.identity_verified:
        messages.error(request, _('ابتدا باید احراز هویت انجام شود.'))
        return redirect('requests:contract', pk=pk)
    code = request.POST.get('code', '').strip()
    try:
        contract_service.approve_with_otp(contract=contract, code=code, actor=request.user)
        messages.success(request, _('قرارداد با موفقیت تأیید شد.'))
    except (otp_service.OtpError, contract_service.ContractError) as exc:
        messages.error(request, str(exc))
    return redirect('requests:contract', pk=pk)


@login_required
def messages_view(request, pk):
    req = get_object_or_404(Request, pk=pk, user=request.user)
    return render(request, 'requests/user/messages.html', {
        'req': req,
        'logs': req.message_logs.all(),
        'page_title': f'تاریخچه پیام‌های درخواست #{req.id}',
    })


@login_required
def complete_profile(request):
    instance = UserProfileCompletion.objects.filter(user=request.user).first()
    if request.method == 'POST':
        form = ProfileCompletionForm(request.POST, instance=instance)
        if form.is_valid():
            profile = form.save(commit=False)
            profile.user = request.user
            profile.is_completed = True
            profile.completed_at = timezone.now()
            profile.save()
            messages.success(request, _('اطلاعات پروفایل تکمیل شد.'))
            return redirect('requests:my-list')
    else:
        form = ProfileCompletionForm(instance=instance)
    return render(request, 'requests/user/profile_complete.html', {
        'form': form,
        'page_title': 'تکمیل پروفایل',
    })


# --------------------------------------------------------------------------- #
# Contract print (PDF via browser) + Word download
# --------------------------------------------------------------------------- #

@login_required
def contract_print(request, pk):
    """Clean, print-optimised contract page. Use the browser's print dialog to
    print or 'Save as PDF'. Page margins come from ContractSettings."""
    req = get_object_or_404(Request, pk=pk, user=request.user)
    contract = RequestContract.objects.filter(request=req).first()
    if contract is None:
        messages.error(request, _('قراردادی برای این درخواست موجود نیست.'))
        return redirect('requests:my-detail', pk=pk)
    return render(request, 'requests/user/contract_print.html', {
        'req': req,
        'contract': contract,
        'settings': ContractSettings.load(),
    })


@login_required
def contract_word(request, pk):
    req = get_object_or_404(Request, pk=pk, user=request.user)
    contract = RequestContract.objects.filter(request=req).first()
    if contract is None:
        messages.error(request, _('قراردادی برای این درخواست موجود نیست.'))
        return redirect('requests:my-detail', pk=pk)
    buf = contract_service.build_contract_docx(contract)
    response = HttpResponse(
        buf.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    )
    response['Content-Disposition'] = f'attachment; filename="contract-{contract.contract_number}.docx"'
    return response


# --------------------------------------------------------------------------- #
# Tickets (customer side)
# --------------------------------------------------------------------------- #

class MyTicketListView(LoginRequiredMixin, ListView):
    template_name = 'requests/user/ticket_list.html'
    context_object_name = 'tickets'
    paginate_by = 20
    extra_context = {'page_title': 'تیکت‌های من'}

    def get_queryset(self):
        return Ticket.objects.filter(user=self.request.user).order_by('-updated_at')


@login_required
def ticket_create(request):
    if request.method == 'POST':
        form = TicketForm(request.POST)
        if form.is_valid():
            ticket = Ticket.objects.create(
                user=request.user,
                department=form.cleaned_data['department'],
                subject=form.cleaned_data['subject'],
                priority=form.cleaned_data['priority'],
            )
            TicketMessage.objects.create(
                ticket=ticket, author=request.user, is_staff_reply=False,
                body=form.cleaned_data['message'],
            )
            messages.success(request, _('تیکت ثبت شد.'))
            return redirect('requests:ticket-detail', pk=ticket.id)
    else:
        form = TicketForm()
    return render(request, 'requests/user/ticket_form.html', {'form': form, 'page_title': 'تیکت'})


class MyTicketDetailView(LoginRequiredMixin, DetailView):
    model = Ticket
    template_name = 'requests/user/ticket_detail.html'
    context_object_name = 'ticket'

    def get_queryset(self):
        return Ticket.objects.filter(user=self.request.user)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['thread'] = self.object.ticket_messages.select_related('author').all()
        ctx['reply_form'] = TicketReplyForm()
        ctx['page_title'] = f'تیکت #{self.object.id}'
        return ctx


@login_required
def ticket_reply(request, pk):
    ticket = get_object_or_404(Ticket, pk=pk, user=request.user)
    form = TicketReplyForm(request.POST, request.FILES)
    if form.is_valid():
        TicketMessage.objects.create(
            ticket=ticket, author=request.user, is_staff_reply=False,
            body=form.cleaned_data['body'], attachment=form.cleaned_data.get('attachment'),
        )
        ticket.status = Ticket.Status.OPEN
        ticket.save(update_fields=['status', 'updated_at'])
        messages.success(request, _('پاسخ ثبت شد.'))
    else:
        messages.error(request, _('متن پاسخ را وارد کنید.'))
    return redirect('requests:ticket-detail', pk=pk)


# --------------------------------------------------------------------------- #
# Payment (internal gateway + callback)
# --------------------------------------------------------------------------- #

@login_required
def pay_start(request, pk):
    req = get_object_or_404(Request, pk=pk, user=request.user)
    contract = RequestContract.objects.filter(request=req).first()
    if contract is None or contract.status != RequestContract.Status.APPROVED:
        messages.error(request, _('ابتدا باید قرارداد تأیید شود.'))
        return redirect('requests:contract', pk=pk)
    try:
        payment, url = payment_service.create_for_offer(request=req, offer=contract.offer, actor=request.user)
    except payment_service.PaymentError as exc:
        messages.error(request, str(exc))
        return redirect('requests:my-detail', pk=pk)
    return redirect(url)


@login_required
def pay_page(request, token):
    payment = get_object_or_404(RequestPayment, token=token)
    if payment.request.user_id != request.user.id:
        messages.error(request, _('دسترسی مجاز نیست.'))
        return redirect('requests:my-list')
    return render(request, 'requests/user/pay.html', {
        'payment': payment,
        'page_title': 'پرداخت',
    })


def pay_callback(request, token):
    """Settle a payment the customer is returning from.

    Deliberately NOT `@login_required`: the customer may have been at the
    gateway long enough to lose their session, and bouncing them to the login
    page would leave money taken but the payment unrecorded. Safety does not
    come from the session — it comes from the gateway backend, which verifies
    the transaction server-to-server before anything is marked paid. The UUID4
    token in the URL is the capability; knowing it is not enough to settle an
    unpaid transaction.
    """
    payment = get_object_or_404(RequestPayment, token=token)
    user = request.user if request.user.is_authenticated else None
    if user is not None and payment.request.user_id != user.id:
        messages.error(request, _('دسترسی مجاز نیست.'))
        return redirect('requests:my-list')

    # Hand the gateway's own parameters through; never default to success — a
    # bare GET must not be able to mark a payment paid.
    source = request.POST if request.method == 'POST' else request.GET
    data = {key: source.get(key) for key in ('Authority', 'Status', 'authority', 'status')
            if source.get(key) is not None}
    # `result` belongs to the internal simulator's own CSRF-protected form. Reading
    # it from a GET would let a customer settle their own payment by opening a URL,
    # and the simulator is the production default until a real gateway is enabled.
    if request.method == 'POST' and request.POST.get('result') is not None:
        data['result'] = request.POST['result']
    if payment_service.get_backend().name == 'internal':
        data.setdefault('ref', f'INT-{token}')

    try:
        payment = payment_service.handle_callback(token=token, data=data)
    except payment_service.PaymentError as exc:
        messages.error(request, str(exc))
        return redirect('requests:my-list' if user else 'requests:otp-login')

    if payment.status == RequestPayment.Status.PAID:
        messages.success(request, _('پرداخت با موفقیت انجام شد.'))
    elif payment.status == RequestPayment.Status.CANCELLED:
        messages.error(request, _('پرداخت لغو شد. می‌توانید دوباره تلاش کنید.'))
    else:
        messages.error(request, _('پرداخت انجام نشد.'))
    if user is None:
        # Session expired at the gateway: log in again, then land on the request.
        detail = reverse('requests:my-detail', kwargs={'pk': payment.request_id})
        return redirect(f"{reverse('requests:otp-login')}?next={detail}")
    return redirect('requests:my-detail', pk=payment.request_id)
