"""The "where do visitors come from" report and the tracking pixel."""
from __future__ import annotations

import base64
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count
from apps.core.localtime import local_day
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt

from apps.requests import repositories
from apps.requests.models import Request

from . import traffic
from .models import Visit

PERIODS = (7, 30, 90)
#: 1x1 transparent GIF.
PIXEL = base64.b64decode('R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7')

PATH_LABELS = (
    ('/card/', 'کارت ویزیت'),
    ('/leads/go/', 'فرم نمایشگاه (QR)'),
    ('/leads/f/', 'تکمیل فرم نمایشگاه'),
    ('/requests/submit/', 'فرم ارزیابی'),
    ('/requests/login/', 'ورود مشتری'),
)


def can_view_traffic(user) -> bool:
    return bool(user.is_authenticated and (
        repositories.is_management(user) or repositories.is_sales(user)))


def _page_label(host: str, path: str) -> str:
    if host in traffic.MAIN_SITE_HOSTS:
        return f'pars-energy.com{path}'
    if path == '/':
        return 'صفحهٔ اصلی'
    for prefix, label in PATH_LABELS:
        if path.startswith(prefix):
            return label
    return path


def build_report(days: int) -> dict:
    since = timezone.now() - timedelta(days=days)
    visits = Visit.objects.filter(created_at__gte=since)
    total = visits.count()
    visitors = visits.values('visitor_id').distinct().count()
    requests_qs = Request.objects.filter(created_at__gte=since)
    requests_count = requests_qs.count()
    labels = dict(Visit.Source.choices)

    by_source = list(visits.values('source').annotate(
        n=Count('id'), people=Count('visitor_id', distinct=True)).order_by('-n'))
    for row in by_source:
        row['label'] = str(labels.get(row['source'], row['source']))
        row['pct'] = round(100 * row['n'] / total) if total else 0

    # Grouped in Python: TruncDate needs DB time-zone tables (apps.core.localtime).
    per_day = {}
    for ts in visits.values_list('created_at', flat=True):
        day = local_day(ts)
        per_day[day] = per_day.get(day, 0) + 1
    daily = [{'day': d, 'n': per_day[d]} for d in sorted(per_day)]
    peak = max((d['n'] for d in daily), default=0)
    for d in daily:
        d['h'] = round(100 * d['n'] / peak) if peak else 0

    pages = {}
    for row in visits.values('host', 'path').annotate(n=Count('id')):
        label = _page_label(row['host'], row['path'])
        pages[label] = pages.get(label, 0) + row['n']
    top_pages = sorted(pages.items(), key=lambda kv: -kv[1])[:10]

    referrers = list(visits.exclude(referrer_host='').values('referrer_host')
                     .annotate(n=Count('id')).order_by('-n')[:10])
    devices = list(visits.values('device').annotate(n=Count('id')).order_by('-n'))
    campaigns = list(visits.exclude(utm_campaign='').values('utm_source', 'utm_campaign')
                     .annotate(n=Count('id')).order_by('-n')[:10])
    lead_sources = list(requests_qs.values('lead_source').annotate(n=Count('id')).order_by('-n'))
    how_heard = dict(Request.HowHeard.choices)
    for row in lead_sources:
        key = row['lead_source'] or 'direct'
        row['label'] = str(how_heard.get(key) or {'direct': 'مستقیم', 'referral': 'سایت معرّف'}.get(key, key))

    return {
        'days': days, 'total': total, 'visitors': visitors,
        'new_visitors': visits.filter(is_new_visitor=True).count(),
        'requests_count': requests_count,
        'conversion': round(100 * requests_count / visitors, 1) if visitors else 0,
        'by_source': by_source, 'daily': daily, 'top_pages': top_pages,
        'referrers': referrers, 'devices': devices, 'campaigns': campaigns,
        'lead_sources': lead_sources,
    }


@login_required
def traffic_report(request):
    if not can_view_traffic(request.user):
        raise PermissionDenied
    try:
        days = int(request.GET.get('days', 30))
    except ValueError:
        days = 30
    if days not in PERIODS:
        days = 30
    context = build_report(days)
    context.update({'periods': PERIODS, 'page_title': 'منبع ورود بازدیدکنندگان'})
    return render(request, 'analytics/traffic.html', context)


@csrf_exempt
@never_cache
def pixel(request):
    """1x1 image for pars-energy.com pages to report a visit.

    Embed on the main site:
    <img src="https://pars-tida.ir/analytics/t.gif?p=PATH&r=REFERRER" width="1" height="1" alt="">
    (the snippet in the report page fills PATH/REFERRER with JavaScript).
    """
    response = HttpResponse(PIXEL, content_type='image/gif')
    ua = request.META.get('HTTP_USER_AGENT', '')
    if traffic.is_bot(ua):
        return response
    visitor_id = request.COOKIES.get(traffic.VISITOR_COOKIE, '')
    is_new = not (len(visitor_id) == 32 and visitor_id.isalnum())
    if is_new:
        visitor_id = traffic.new_visitor_id()
        response.set_cookie(traffic.VISITOR_COOKIE, visitor_id, max_age=traffic.VISITOR_COOKIE_AGE,
                            samesite='None', secure=True, httponly=True)
    page = request.GET.get('p', '/')
    query = {k: request.GET.get(k, '') for k in ('utm_source', 'utm_medium', 'utm_campaign')}
    try:
        traffic.record(visitor_id=visitor_id, is_new=is_new, host='pars-energy.com',
                       path=page.split('?')[0], referrer=request.GET.get('r', ''),
                       query=query, user_agent=ua)
    except Exception:  # noqa: BLE001 - never break the main site's page
        pass
    return response
