"""Exhibition capture, and the QR codes behind it.

There is no separate lead list any more. A capture creates an ordinary
`Request` in the marketing queue, so it shows up wherever every other lead
shows up and moves through the same marketing → sales → technical pipeline,
with the same privacy rules. The only screen here is the QR admin.

The visitor at the stand is anonymous and reaches the form only through a QR
link. The token in the URL is the whole authorisation — there is no listing,
no index, and no way to walk from one lead to another.
"""
from __future__ import annotations

import logging
import re
import time
from datetime import date, timedelta
from functools import wraps
from io import BytesIO

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.safestring import mark_safe
from django.views.decorators.http import require_http_methods

from apps.requests.iran_locations import CITIES
from apps.requests.models import Request, RequestMessageLog
from apps.requests.services import lifecycle
from apps.requests.services import sms as sms_service

from . import exports, performance
from .forms import LeadStageOneForm, LeadStageTwoForm
from .models import Lead, LeadSource

logger = logging.getLogger(__name__)


#: Same visitor, same stand, inside this window = the same lead.
DUPLICATE_WINDOW = timedelta(minutes=30)


def noindex(view):
    """Keep a capture page out of search results.

    robots.txt asks politely and only covers crawlers that read it; this header
    is the instruction a crawler has to act on even if it arrived at the URL
    some other way — a shared screenshot, a pasted link, a browser extension.
    """
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        response = view(request, *args, **kwargs)
        response['X-Robots-Tag'] = 'noindex, nofollow, noarchive'
        return response
    return wrapper


def _is_management(user) -> bool:
    return bool(user.is_superuser or getattr(user, 'role', '') in ('admin', 'operations'))


# --------------------------------------------------------------------------- #
# Public capture — reachable only with a token
# --------------------------------------------------------------------------- #

@noindex
@require_http_methods(['GET', 'POST'])
def capture(request, token):
    """Stage 1. The QR code lands here; the token says who gets the credit."""
    source = LeadSource.objects.filter(token=token, is_active=True).first()
    if source is None:
        raise Http404

    if request.method == 'POST':
        form = LeadStageOneForm(request.POST)
        if form.is_valid():
            cd = form.cleaned_data
            who = source.marketer
            # A second tap, a retry after a slow SMS, or the back button must
            # not make a second request: reuse the one this visitor just made.
            recent = Lead.objects.filter(
                source=source, request__mobile=cd['mobile'],
                created_at__gte=timezone.now() - DUPLICATE_WINDOW,
            ).order_by('-created_at').first()
            if recent is not None:
                return redirect('leads:captured', token=recent.resume_token)
            # Two taps can arrive together; only the first one gets through.
            lock = f'lead-capture:{source.pk}:{cd["mobile"]}'
            if not cache.add(lock, 1, 30):
                # The browser shows the last response, so wait for the first
                # tap to finish and send this one to the same page.
                for _ in range(20):
                    time.sleep(0.5)
                    recent = Lead.objects.filter(
                        source=source, request__mobile=cd['mobile'],
                        created_at__gte=timezone.now() - DUPLICATE_WINDOW,
                    ).order_by('-created_at').first()
                    if recent is not None:
                        return redirect('leads:captured', token=recent.resume_token)
                return redirect('leads:capture', token=token)
            # An ordinary request in the marketing queue — same pipeline, same
            # filters, same privacy rules as a lead that arrived from the site.
            lead_request = lifecycle.create_request(
                full_name=cd['full_name'],
                mobile=cd['mobile'],
                province=cd.get('province', ''),
                city=cd.get('city', ''),
                how_heard=Request.HowHeard.EXHIBITION,
                lead_source=(source.event_name or source.name)[:64],
                campaign_name=source.event_name[:128],
                contact_method=cd.get('contact_method', ''),
                # No Shahkar at a stand: a visitor gives a name and a number,
                # and identity is verified later in the normal flow.
                identity_verified=False,
            )
            # Attribution is taken from the link, never asked and never trusted
            # from the form — the visitor should not know the marketer's name.
            lead = Lead.objects.create(
                request=lead_request,
                source=source,
                marketer=who,
                event_name=source.event_name,
                company=cd.get('company', ''),
                job_title=cd.get('job_title', ''),
                business_field=cd.get('business_field', ''),
                goals=cd.get('goals', []),
                timeline=cd.get('timeline', ''),
                country=cd.get('country', ''),
            )
            # The visitor gets an SMS the moment they register — a receipt and
            # the stage-2 link in one, so "finish later" works even if they
            # never tap the resume button.
            _notify(lead, _welcome_text(lead, _resume_url(request, lead)), None, None, request,
                    pattern=_link_pattern(lead))
            cache.delete(lock)
            return redirect('leads:captured', token=lead.resume_token)
    else:
        form = LeadStageOneForm()

    return render(request, 'leads/capture.html', {
        'form': form,
        'source': source,
        'cities': CITIES,
        'page_title': 'ثبت اطلاعات',
    })


@noindex
def captured(request, token):
    """The fork: carry on now, or get the link and finish later."""
    lead = get_object_or_404(Lead.objects.select_related('request'), resume_token=token)
    return render(request, 'leads/captured.html', {
        'lead': lead,
        'continue_url': reverse('leads:detail-form', kwargs={'token': token}),
        'page_title': 'ثبت شد',
    })


@noindex
@require_http_methods(['POST'])
def send_resume_link(request, token):
    """Text the visitor their own stage-2 link so they can finish later."""
    lead = get_object_or_404(Lead.objects.select_related('request'), resume_token=token)
    _notify(lead, f'تکمیل اطلاعات پروژه ({lead.lead_code}): {_resume_url(request, lead)}',
            'لینک تکمیل اطلاعات برای شما پیامک شد.',
            'ارسال پیامک ناموفق بود. می‌توانید همین حالا ادامه دهید.', request,
            pattern=_link_pattern(lead))
    return redirect('leads:captured', token=token)


def _resume_url(request, lead) -> str:
    return request.build_absolute_uri(
        reverse('leads:detail-form', kwargs={'token': lead.resume_token}))


def _welcome_text(lead, url) -> str:
    return (f'{lead.request.full_name} عزیز، ثبت‌نام شما در پارس انرژی انجام شد '
            f'(کد پیگیری {lead.lead_code}).\nتکمیل اطلاعات پروژه: {url}')


def _reminder_text(lead, url) -> str:
    return (f'{lead.request.full_name} عزیز، اطلاعات پروژهٔ شما هنوز کامل نشده است. '
            f'برای دریافت مشاورهٔ دقیق‌تر لطفاً فرم را تکمیل کنید:\n{url}\nپارس انرژی')


def _link_pattern(lead):
    """Pattern 564762: "{0} عزیز، ... pars-tida.ir/leads/f/{1}" — name, token."""
    name = lead.request.full_name if lead.request_id else ''
    return (sms_service.LEAD_LINK_PATTERN, [name, lead.resume_token])


def _notify(lead, body, ok_message, fail_message, request, pattern=None) -> bool:
    """Send one SMS, and never let a failed send cost us the lead.

    A provider rejection comes back as a FAILED log rather than an exception,
    so both count as failure here — the caller's message has to tell the truth.
    """
    ok = False
    try:
        log = sms_service.send_message(
            request=lead.request, user=None,
            mobile=lead.request.mobile if lead.request_id else '',
            body=body, message_type=RequestMessageLog.MessageType.LEAD, pattern=pattern)
        ok = log.status == RequestMessageLog.Status.SENT
        if not ok:
            logger.warning('Lead SMS rejected for %s: %s', lead.lead_code, log.provider_message_id)
    except Exception:  # noqa: BLE001 - delivery is best effort
        logger.warning('Lead SMS failed for %s', lead.lead_code, exc_info=True)
    if ok and ok_message:
        messages.success(request, ok_message)
    elif not ok and fail_message:
        messages.error(request, fail_message)
    return ok


@noindex
@require_http_methods(['GET', 'POST'])
def detail_form(request, token):
    """Stage 2. Always completes the *same* request — never creates another."""
    lead = get_object_or_404(Lead.objects.select_related('request'), resume_token=token)
    target = lead.request

    if request.method == 'POST':
        form = LeadStageTwoForm(request.POST, request.FILES)
        if form.is_valid():
            cd = form.cleaned_data
            if target is not None:
                for field in ('latitude', 'longitude', 'install_address',
                              'install_location', 'area_range', 'shade_status', 'bill_id'):
                    value = cd.get(field)
                    if value not in (None, ''):
                        setattr(target, field, value)
                target.save()

            lead.install_location_note = cd.get('install_location_note', '')
            lead.area_note = cd.get('area_note', '')
            lead.demand_power = cd.get('demand_power', '')
            lead.shading_note = cd.get('shading_note', '')
            if cd.get('bill_file'):
                lead.bill_file = cd['bill_file']
            lead.stage2_completed = True
            lead.stage2_completed_at = timezone.now()
            lead.save()
            _notify(lead,
                    f'{lead.request.full_name} عزیز، اطلاعات شما دریافت شد '
                    f'(کد پیگیری {lead.lead_code}). همکاران ما با شما در ارتباط خواهند بود.',
                    None, None, request,
                    pattern=(sms_service.RECEIVED_PATTERN, [lead.request.full_name, lead.lead_code]))
            return redirect('leads:done', token=token)
    else:
        initial = {}
        if target is not None:
            initial = {f: getattr(target, f) for f in (
                'latitude', 'longitude', 'install_address', 'install_location',
                'area_range', 'shade_status', 'bill_id')}
        initial['demand_power'] = lead.demand_power
        form = LeadStageTwoForm(initial=initial)

    return render(request, 'leads/detail_form.html', {
        'form': form,
        'lead': lead,
        'page_title': 'اطلاعات پروژه',
    })


@noindex
def done(request, token):
    lead = get_object_or_404(Lead, resume_token=token)
    return render(request, 'leads/done.html', {'lead': lead, 'page_title': 'تکمیل شد'})


# --------------------------------------------------------------------------- #
# QR administration — management only
# --------------------------------------------------------------------------- #

def _qr_svg(url: str) -> str:
    """Draw the QR on the server, as inline SVG.

    It used to be drawn in the browser from a CDN script, which is exactly the
    dependency that broke the maps: a script that never loads leaves an empty
    canvas and no error anyone would notice. Rendering here means the QR is in
    the HTML itself — it prints, it survives a screenshot, and it needs nothing
    from outside this server.
    """
    import qrcode
    import qrcode.image.svg

    code = qrcode.QRCode(box_size=10, border=2,
                         error_correction=qrcode.constants.ERROR_CORRECT_M)
    code.add_data(url)
    code.make(fit=True)
    img = code.make_image(image_factory=qrcode.image.svg.SvgPathImage)
    buffer = BytesIO()
    img.save(buffer)
    svg = buffer.getvalue().decode('utf-8')
    # Drop the XML prolog so the SVG can be embedded straight into the page,
    # and let CSS size it instead of the library's millimetre defaults.
    svg = svg.split('?>', 1)[-1].strip()
    return re.sub(r'(<svg[^>]*?)\s+width="[^"]*"\s+height="[^"]*"', r'\1', svg, count=1)


@login_required
def source_list(request):
    """The QR codes: management sees all, a marketer only their own.

    A link is what credits a lead to someone, so a marketer never sees another
    person's code or the public one.
    """
    manager = _is_management(request.user)
    if not manager and getattr(request.user, 'role', '') != 'marketing':
        raise PermissionDenied
    sources = LeadSource.objects.select_related('marketer').all()
    if not manager:
        sources = sources.filter(marketer=request.user, is_active=True)
    for source in sources:
        source.public_url = request.build_absolute_uri(
            reverse('leads:capture', kwargs={'token': source.token}))
        source.qr_svg = mark_safe(_qr_svg(source.public_url))  # noqa: S308 - our own SVG
    return render(request, 'leads/panel_sources.html', {
        'sources': sources,
        'can_manage': manager,
        'page_title': 'QR بازاریاب‌ها' if manager else 'QR من',
    })


# --------------------------------------------------------------------------- #
# Follow-up: leads that stopped after stage 1
# --------------------------------------------------------------------------- #

def _can_follow_up(user) -> bool:
    return _is_management(user) or getattr(user, 'role', '') in ('marketing', 'sales')


def _sees_all_leads(user) -> bool:
    """Management and sales work every lead; a marketer only their own QR's."""
    return _is_management(user) or getattr(user, 'role', '') == 'sales'


def _date_param(value):
    from apps.core.dates import parse_user_date
    return parse_user_date(value)


def _scoped_leads(request):
    """Management sees every lead; a marketer only the ones their QR brought."""
    qs = performance.leads_in(*performance.window(
        _date_param(request.GET.get('date_from')), _date_param(request.GET.get('date_to'))))
    if not _sees_all_leads(request.user):
        return qs.filter(marketer=request.user)
    who = request.GET.get('marketer', '')
    if who == 'public':
        qs = qs.filter(marketer__isnull=True)
    elif who.isdigit():
        qs = qs.filter(marketer_id=int(who))
    return qs


@login_required
@require_http_methods(['GET', 'POST'])
def followup(request):
    """Who filled form 1 and form 2 — and a reminder SMS for those who stopped."""
    if not _can_follow_up(request.user):
        raise PermissionDenied
    stage = request.GET.get('stage', 'stage1')
    qs = _scoped_leads(request)

    if request.method == 'POST':
        targets = performance.stage_one_only(qs)
        if request.POST.get('scope') != 'all':
            ids = [int(i) for i in request.POST.getlist('lead') if i.isdigit()]
            targets = targets.filter(pk__in=ids)
        now = timezone.now()
        sent = failed = skipped = 0
        for lead in targets:
            if not performance.can_remind(lead, now):
                skipped += 1
                continue
            if _notify(lead, _reminder_text(lead, _resume_url(request, lead)), None, None, request,
                       pattern=_link_pattern(lead)):
                lead.reminder_count += 1
                lead.last_reminder_at = now
                lead.save(update_fields=['reminder_count', 'last_reminder_at', 'updated_at'])
                sent += 1
            else:
                failed += 1
        if sent:
            messages.success(request, f'پیامک یادآوری برای {sent} نفر ارسال شد.')
        if skipped:
            messages.info(request, f'{skipped} نفر در ۲۴ ساعت گذشته یادآوری گرفته بودند و دوباره پیامک نگرفتند.')
        if failed:
            messages.error(request, f'ارسال برای {failed} نفر ناموفق بود — «لاگ پیامک‌ها» را ببینید.')
        if not (sent or skipped or failed):
            messages.info(request, 'درخواستی برای یادآوری انتخاب نشده بود.')
        return redirect(request.get_full_path())

    counts = {'all': qs.count(), 'stage2': qs.filter(stage2_completed=True).count()}
    counts['stage1'] = counts['all'] - counts['stage2']
    if stage == 'stage1':
        qs = performance.stage_one_only(qs)
    elif stage == 'stage2':
        qs = qs.filter(stage2_completed=True)
    leads = list(qs.order_by('-created_at')[:500])
    now = timezone.now()
    for lead in leads:
        lead.remindable = not lead.stage2_completed and performance.can_remind(lead, now)

    return render(request, 'leads/panel_followup.html', {
        'leads': leads,
        'counts': counts,
        'stage': stage,
        'is_management': _sees_all_leads(request.user),
        'marketers': get_user_model().objects.filter(role='marketing').order_by('first_name', 'username'),
        'current': {k: request.GET.get(k, '') for k in ('marketer', 'date_from', 'date_to')},
        'page_title': 'پیگیری تکمیل فرم درخواست‌ها',
    })


# --------------------------------------------------------------------------- #
# Marketer performance report — management only
# --------------------------------------------------------------------------- #

REPORT_HEADERS = ['بازاریاب', 'کل درخواست', 'فرم ۲ تکمیل', 'درصد تکمیل', 'فقط فرم ۱',
                  'داغ', 'گرم', 'سرد', 'فاقد شرایط', 'ارجاع به فروش/فنی',
                  'قرارداد/پرداخت', 'نرخ تبدیل٪', 'از دست‌رفته', 'یادآوری ارسالی']


@login_required
def marketer_report(request):
    if not _is_management(request.user):
        raise PermissionDenied
    date_from = _date_param(request.GET.get('date_from'))
    date_to = _date_param(request.GET.get('date_to'))
    rows, total = performance.marketer_rows(*performance.window(date_from, date_to))

    if request.GET.get('export') == 'excel':
        data = [[r['name'], r['total'], r['stage2'], r['stage2_pct'], r['stage1_only'],
                 r['hot'], r['warm'], r['cold'], r['unqualified'], r['referred'],
                 r['won'], r['won_pct'], r['lost'], r['reminders']] for r in rows]
        response = HttpResponse(
            exports.build_sheet('عملکرد بازاریاب‌ها', REPORT_HEADERS, data),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = 'attachment; filename="marketer-performance.xlsx"'
        return response

    return render(request, 'leads/panel_marketers.html', {
        'rows': rows,
        'total': total,
        'date_from': request.GET.get('date_from', ''),
        'date_to': request.GET.get('date_to', ''),
        'printing': bool(request.GET.get('print')),
        'generated_at': timezone.now(),
        'page_title': 'گزارش عملکرد بازاریاب‌ها',
    })


@login_required
def marketer_detail(request, pk):
    """One marketer's leads, line by line — printable the same way.

    `pk=0` is the public QR, which has no marketer behind it.
    """
    if not _is_management(request.user):
        raise PermissionDenied
    marketer = None if pk == 0 else get_object_or_404(get_user_model(), pk=pk)
    start, end = performance.window(_date_param(request.GET.get('date_from')),
                                    _date_param(request.GET.get('date_to')))
    qs = performance.leads_in(start, end).filter(marketer=marketer)
    return render(request, 'leads/panel_marketer_detail.html', {
        'marketer': marketer,
        'name': (marketer.get_full_name() or marketer.username) if marketer else 'QR عمومی',
        'leads': qs.order_by('-created_at')[:1000],
        'summary': performance.summarise(qs),
        'date_from': request.GET.get('date_from', ''),
        'date_to': request.GET.get('date_to', ''),
        'printing': bool(request.GET.get('print')),
        'generated_at': timezone.now(),
        'page_title': 'عملکرد بازاریاب',
    })
