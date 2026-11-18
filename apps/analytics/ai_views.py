"""AI helpers for each part of the panel, plus the customer chat assistant.

Every task builds a small, role-appropriate context and asks `apps.core.ai`,
which falls back across providers (main / GapGPT / AvalAI).
"""
from __future__ import annotations

import json

from django.core.cache import cache
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core import ai, ai_limits
from apps.core.card import COMPANY
from apps.requests import repositories
from apps.requests.models import Request, Ticket

from .traffic_views import build_report, can_view_traffic

STYLE = ('به فارسی روان و کوتاه جواب بده. فهرست‌وار و عملیاتی بنویس. '
         'چیزی را که در داده‌ها نیست حدس نزن و عدد نساز.')


def _err(message, status=400):
    return JsonResponse({'error': message}, status=status)


# --------------------------------------------------------------------------- #
#  Panel tasks
# --------------------------------------------------------------------------- #
def _lead_context(req: Request, hide_identity: bool) -> dict:
    lead = getattr(req, 'exhibition', None)
    days = (timezone.now() - req.stage_entered_at).days if req.stage_entered_at else None
    ctx = {
        'شماره': req.id,
        'وضعیت': req.get_status_display(),
        'مرحله': req.get_department_display(),
        'روز در این مرحله': days,
        'اولویت': req.get_priority_display(),
        'نوع درخواست': req.get_request_type_display() if req.request_type else '',
        'نوع پروژه': req.get_project_type_display() if req.project_type else '',
        'استان/شهر': f'{req.province} {req.city}'.strip(),
        'محل نصب': req.get_install_location_display() if req.install_location else '',
        'مساحت': req.get_area_range_display() if req.area_range else (req.area_m2 or ''),
        'سایه': req.get_shade_status_display() if req.shade_status else '',
        'بودجه': req.get_investment_range_display() if req.investment_range else '',
        'منبع ورود': req.lead_source,
        'توضیح مشتری': (req.description or '')[:600],
        'تعداد پیشنهاد قیمت': req.offers.count(),
        'یادداشت فنی': (req.technical_note or '')[:400],
    }
    if lead:
        ctx.update({
            'نمایشگاهی': True,
            'هدف': '، '.join(lead.goal_labels),
            'زمان تصمیم‌گیری': lead.get_timeline_display() if lead.timeline else '',
            'توان مورد تقاضا': lead.get_demand_power_display() if lead.demand_power else '',
            'مرحلهٔ ۲ تکمیل شده': lead.stage2_completed,
            'کیفیت سرنخ (بازاریاب)': lead.get_temperature_display() if lead.temperature else '',
            'برداشت بازاریاب': (lead.marketer_impression or '')[:400],
            'یادداشت': (lead.notes or '')[:400],
        })
        if not hide_identity:
            ctx.update({'شرکت': lead.company, 'سمت': lead.job_title, 'حوزه': lead.business_field})
    return {k: v for k, v in ctx.items() if v not in ('', None)}


def _task_lead(request, target):
    qs = repositories.scope_requests_by_department(request.user, Request.objects.all())
    req = qs.filter(pk=target).select_related('exhibition').first()
    if req is None:
        return _err('درخواست پیدا نشد.', 404)
    hide = repositories.is_identity_restricted(request.user)
    system = ('تو کارشناس ارشد فروش نیروگاه خورشیدی در شرکت پارس انرژی هستی. ' + STYLE)
    prompt = (
        'این سرنخ را تحلیل کن و دقیقاً این بخش‌ها را بنویس:\n'
        '۱. خلاصه در دو جمله\n'
        '۲. کیفیت سرنخ: داغ / گرم / سرد، با دلیل\n'
        '۳. اقدام بعدی پیشنهادی و زمانش\n'
        '۴. سه نکته یا سؤال برای تماس با مشتری\n'
        '۵. اطلاعات مهمی که هنوز نداریم\n\n'
        + json.dumps(_lead_context(req, hide), ensure_ascii=False))
    return ai.ask(system, prompt)


def _task_ticket(request, target):
    qs = repositories.scope_tickets_by_department(request.user, Ticket.objects.all())
    ticket = qs.filter(pk=target).first()
    if ticket is None:
        return _err('تیکت پیدا نشد.', 404)
    thread = [
        ('پشتیبانی' if m.is_staff_reply else 'مشتری') + ': ' + (m.body or '')[:800]
        for m in ticket.ticket_messages.order_by('-created_at')[:8]
    ][::-1]
    system = ('تو کارشناس پشتیبانی مؤدب شرکت پارس انرژی (نیروگاه خورشیدی) هستی. '
              'فقط متن پاسخ را بنویس، بدون مقدمه و توضیح برای همکار. '
              'قول قیمت، تاریخ یا تخفیف نده؛ اگر لازم است بگو همکاران بررسی و اطلاع می‌دهند. '
              'کوتاه، محترمانه و فارسی.')
    prompt = (f'موضوع تیکت: {ticket.subject}\nبخش: {ticket.get_department_display()}\n\n'
              'گفتگو:\n' + '\n'.join(thread) + '\n\nپیش‌نویس پاسخ بعدی پشتیبانی را بنویس.')
    return ai.ask(system, prompt, temperature=0.4, max_tokens=600)


def _task_traffic(request, target):
    if not can_view_traffic(request.user):
        return _err('دسترسی ندارید.', 403)
    try:
        days = int(target)
    except (TypeError, ValueError):
        days = 30
    report = build_report(days if days in (7, 30, 90) else 30)
    pipeline = {
        str(label): Request.objects.filter(department=key).exclude(
            status__in=('closed', 'cancelled')).count()
        for key, label in Request.Department.choices
    }
    data = {
        'دوره (روز)': report['days'], 'ورود': report['total'], 'افراد یکتا': report['visitors'],
        'درخواست جدید': report['requests_count'], 'نرخ تبدیل٪': report['conversion'],
        'منابع ورود': {r['label']: r['n'] for r in report['by_source']},
        'منبع درخواست‌ها': {r['label']: r['n'] for r in report['lead_sources']},
        'صفحه‌های ورود': dict(report['top_pages']),
        'قیف فروش فعلی': pipeline,
    }
    system = 'تو مشاور بازاریابی و مدیر فروش یک شرکت نیروگاه خورشیدی هستی. ' + STYLE
    prompt = ('برای مدیریت یک خلاصهٔ اجرایی بنویس: ۱. وضعیت در یک پاراگراف '
              '۲. بهترین و ضعیف‌ترین منبع جذب ۳. گلوگاه قیف فروش ۴. سه اقدام پیشنهادی برای هفتهٔ آینده.\n\n'
              + json.dumps(data, ensure_ascii=False))
    return ai.ask(system, prompt)


TASKS = {'lead': _task_lead, 'ticket': _task_ticket, 'traffic': _task_traffic}


@require_POST
def ai_task(request):
    if not request.user.is_authenticated or not repositories.is_request_staff(request.user):
        return _err('دسترسی ندارید.', 403)
    handler = TASKS.get(request.POST.get('task', ''))
    if handler is None:
        return _err('کار نامعتبر.')
    if not ai.is_available():
        return _err('هوش مصنوعی تنظیم نشده است. از «تنظیمات › هوش مصنوعی» یک سرویس را فعال کنید.')
    target = (request.POST.get('target') or '').strip()
    if not target.isdigit():
        return _err('مورد پیدا نشد.', 404)
    task = request.POST.get('task', '')
    blocked = ai_limits.check(request.user, task)
    if blocked:
        return _err(blocked, 403)
    try:
        result = handler(request, int(target))
    except ai.AIError as exc:
        return _err(str(exc), 502)
    if isinstance(result, JsonResponse):
        return result
    ai_limits.consume(request.user, task)
    return JsonResponse({'text': result.text, 'provider': result.provider})


# --------------------------------------------------------------------------- #
#  Customer chat assistant
# --------------------------------------------------------------------------- #
CHAT_MAX_CHARS = 500
CHAT_MAX_TURNS = 6


def chat_enabled() -> bool:
    from apps.core.models import SystemParameter
    p = SystemParameter.objects.filter(key='ai_chat_enabled').first()
    return (p.value if p else 'true') == 'true' and ai.is_available()


def _chat_system_prompt() -> str:
    c = COMPANY
    return (
        f'تو دستیار آنلاین «{c["name"]}» هستی؛ شرکتی که {c["tagline"]} انجام می‌دهد. '
        f'خدمات: {"، ".join(c["services"])}. '
        f'تلفن: {c["phone"]}، کارشناس فروش: {c["sales_phone"]}، آدرس: {c["address"]}. '
        'به سؤال‌های عمومی دربارهٔ نیروگاه خورشیدی، مراحل همکاری و مزایا کوتاه و فارسی جواب بده. '
        'هیچ قیمت، تخفیف، زمان یا تعهد مشخصی نده؛ برای قیمت دقیق بگو فرم ارزیابی رایگان را '
        'در https://pars-tida.ir/requests/submit/ پر کنند یا با کارشناس فروش تماس بگیرند. '
        'دربارهٔ موضوعات بی‌ربط به انرژی خورشیدی و شرکت جواب نده و مؤدبانه برگرد به موضوع. '
        'اطلاعات شخصی مثل کد ملی نخواه.'
    )


def _client_ip(request) -> str:
    """The address our own proxy saw. The left of X-Forwarded-For is whatever
    the client typed, so only the right-most entry (added by our proxy) counts."""
    forwarded = [p.strip() for p in request.META.get('HTTP_X_FORWARDED_FOR', '').split(',') if p.strip()]
    return forwarded[-1] if forwarded else request.META.get('REMOTE_ADDR', '')


@require_POST
def ai_chat(request):
    if not chat_enabled():
        return _err('دستیار در دسترس نیست.', 503)
    per_visitor, all_visitors = ai_limits.chat_limits()
    key = f'ai-chat:{_client_ip(request)}'
    used = cache.get(key, 0)
    total = cache.get('ai-chat:all', 0)
    if used >= per_visitor or total >= all_visitors:
        return _err('تعداد پیام‌ها زیاد شد. لطفاً کمی بعد دوباره تلاش کنید یا با ما تماس بگیرید.', 429)
    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except ValueError:
        return _err('درخواست نامعتبر.')
    history = payload.get('messages') or []
    messages = [{'role': 'system', 'content': _chat_system_prompt()}]
    for m in history[-CHAT_MAX_TURNS:]:
        role = m.get('role')
        text = str(m.get('content') or '')[:CHAT_MAX_CHARS]
        if role in ('user', 'assistant') and text.strip():
            messages.append({'role': role, 'content': text})
    if len(messages) < 2 or messages[-1]['role'] != 'user':
        return _err('پیامی ارسال نشده.')
    cache.set(key, used + 1, 3600)
    cache.set('ai-chat:all', total + 1, 3600)
    try:
        result = ai.chat(messages, temperature=0.4, max_tokens=400)
    except ai.AIError:
        return _err('الان امکان پاسخ نیست. لطفاً با شمارهٔ کارشناس فروش تماس بگیرید.', 502)
    return JsonResponse({'text': result.text})
