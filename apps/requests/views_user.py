"""User-panel pages for the requests module ("درخواست‌های من").

Entry flow for a visitor: submit a request -> verify mobile via OTP
(register or login) -> the request lands in "my requests".
All pages use the existing user-panel layout (base.html).
"""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.generic import DetailView, ListView

from .forms import ProfileCompletionForm, RequestSubmitForm, TicketForm, TicketReplyForm
from .iran_locations import CITIES, PROVINCES
from .models import (
    ContractSettings,
    OtpVerification,
    Request,
    RequestContract,
    RequestOffer,
    RequestPayment,
    Ticket,
    TicketMessage,
    UserProfileCompletion,
)
from .services import contracts as contract_service
from .services import identity as identity_service
from .services import lifecycle
from .services import offers as offer_service
from .services import otp as otp_service
from .services import payments as payment_service

User = get_user_model()
_AUTH_BACKEND = 'django.contrib.auth.backends.ModelBackend'


# --------------------------------------------------------------------------- #
# Submit + OTP register/login
# --------------------------------------------------------------------------- #

def submit_request(request):
    if request.method == 'POST':
        form = RequestSubmitForm(request.POST)
        if form.is_valid():
            cd = form.cleaned_data
            mobile = cd['mobile']
            national_id = cd['national_id']
            # Automatic Shahkar identity check on submit: the mobile must belong
            # to the national id before the request is accepted.
            try:
                verified, _detail = identity_service.verify_identity(mobile, national_id)
            except identity_service.IdentityError as exc:
                verified = False
                form.add_error(None, str(exc))

            if not verified:
                if not form.errors:
                    form.add_error('national_id', _('احراز هویت ناموفق بود: کد ملی با شمارهٔ موبایل مطابقت ندارد.'))
            else:
                extra = {k: cd[k] for k in (
                    'user_type', 'project_type', 'needs_financial_consult', 'install_address',
                    'area_m2', 'install_location', 'building_type', 'has_shading',
                    'ownership_type', 'grid_distance_m', 'storage_interest', 'bill_id',
                    'accepted_terms',
                )}
                req = lifecycle.create_request(
                    full_name=cd['full_name'],
                    mobile=mobile,
                    province=cd['province'],
                    city=cd.get('city', ''),
                    description=cd.get('description', ''),
                    user=request.user if request.user.is_authenticated else None,
                    national_id=national_id,
                    identity_verified=True,
                    identity_verified_at=timezone.now(),
                    **extra,
                )
                if request.user.is_authenticated:
                    messages.success(request, _('درخواست شما ثبت و احراز هویت شد.'))
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
        form = RequestSubmitForm()
    return render(request, 'requests/user/submit.html', {
        'form': form,
        'page_title': 'فرم ارزیابی',
        'provinces': PROVINCES,
        'cities': CITIES,
    })


def otp_login(request):
    if request.method == 'POST':
        mobile = request.POST.get('mobile', '').strip()
        if not User.objects.filter(username=mobile).exists():
            messages.error(request, _('کاربری با این شماره یافت نشد. لطفاً ابتدا درخواست ثبت کنید.'))
            return render(request, 'requests/user/login.html', {'mobile': mobile})
        otp_service.issue(mobile=mobile, purpose=OtpVerification.Purpose.LOGIN)
        request.session['otp_mobile'] = mobile
        request.session['otp_purpose'] = OtpVerification.Purpose.LOGIN
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

        user = User.objects.filter(username=mobile).first()
        if user is None:
            user = User(username=mobile, phone_number=mobile)
            user.set_unusable_password()
            user.save()
        login(request, user, backend=_AUTH_BACKEND)

        # Attach any anonymous requests submitted with this mobile.
        Request.objects.filter(mobile=mobile, user__isnull=True).update(user=user)
        pending = request.session.pop('pending_request_id', None)
        request.session.pop('otp_mobile', None)
        request.session.pop('otp_purpose', None)
        messages.success(request, _('ورود با موفقیت انجام شد.'))
        if pending:
            return redirect('requests:my-detail', pk=pending)
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
        return Request.objects.filter(user=self.request.user).order_by('-created_at')


class MyRequestDetailView(LoginRequiredMixin, DetailView):
    model = Request
    template_name = 'requests/user/my_detail.html'
    context_object_name = 'req'

    def get_queryset(self):
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
            and req.status in (status.CONTRACT_APPROVED, status.AWAITING_PAYMENT),
            'is_paid': req.status == status.PAID,
        })
        return ctx


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
        national_id = (request.POST.get('national_id') or '').strip()
        if not (national_id.isdigit() and len(national_id) == 10):
            messages.error(request, _('کد ملی باید ۱۰ رقم باشد.'))
            return redirect('requests:contract', pk=pk)
        try:
            matched, _detail = identity_service.verify_identity(req.mobile, national_id)
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
    return render(request, 'requests/user/ticket_form.html', {'form': form, 'page_title': 'تیکت جدید'})


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


@login_required
def pay_callback(request, token):
    payment = get_object_or_404(RequestPayment, token=token)
    if payment.request.user_id != request.user.id:
        messages.error(request, _('دسترسی مجاز نیست.'))
        return redirect('requests:my-list')
    result = request.POST.get('result') if request.method == 'POST' else request.GET.get('result', 'success')
    try:
        payment = payment_service.handle_callback(token=token, data={'result': result, 'ref': f'INT-{token}'})
    except payment_service.PaymentError as exc:
        messages.error(request, str(exc))
        return redirect('requests:my-list')
    if payment.status == RequestPayment.Status.PAID:
        messages.success(request, _('پرداخت با موفقیت انجام شد.'))
    else:
        messages.error(request, _('پرداخت انجام نشد.'))
    return redirect('requests:my-detail', pk=payment.request_id)
