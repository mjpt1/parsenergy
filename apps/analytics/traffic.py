"""Where visitors come from.

Records one `Visit` per arrival on a public page and classifies its source
from, in order: UTM tags, the kind of link (QR capture, SMS resume link), and
the referring site. Staff, bots and internal navigation are ignored.

The main marketing site (pars-energy.com) runs elsewhere; it can report its own
visits through the pixel at ``/analytics/t.gif`` (see `pixel` in views).
"""
from __future__ import annotations

import secrets
from datetime import timedelta
from urllib.parse import urlparse

from django.utils import timezone

from .models import Visit

S = Visit.Source
VISITOR_COOKIE = 'pv'
VISITOR_COOKIE_AGE = 365 * 24 * 3600
#: The same person reopening the same page within this window is not a new arrival.
DEDUP_WINDOW = timedelta(minutes=30)

#: Public pages worth counting. Everything else is the panel.
PUBLIC_PREFIXES = ('/card/', '/leads/go/', '/leads/f/', '/requests/submit/', '/requests/login/')
OWN_HOSTS = ('pars-tida.ir', 'www.pars-tida.ir')
MAIN_SITE_HOSTS = ('pars-energy.com', 'www.pars-energy.com')

BOT_MARKERS = ('bot', 'crawl', 'spider', 'slurp', 'preview', 'curl', 'python', 'wget',
               'headless', 'monitor', 'facebookexternalhit', 'whatsapp/')

_REFERRER_SOURCES = (
    ('google.', S.GOOGLE), ('bing.', S.BING), ('instagram.', S.INSTAGRAM),
    ('t.me', S.TELEGRAM), ('telegram.', S.TELEGRAM), ('whatsapp.', S.WHATSAPP),
    ('wa.me', S.WHATSAPP), ('ble.ir', S.BALE), ('bale.ai', S.BALE),
    ('linkedin.', S.LINKEDIN), ('lnkd.in', S.LINKEDIN), ('twitter.', S.TWITTER),
    ('x.com', S.TWITTER), ('t.co', S.TWITTER), ('facebook.', S.FACEBOOK),
    ('youtube.', S.YOUTUBE), ('youtu.be', S.YOUTUBE), ('aparat.', S.APARAT),
)
_UTM_SOURCES = {
    'google': S.GOOGLE, 'instagram': S.INSTAGRAM, 'ig': S.INSTAGRAM,
    'telegram': S.TELEGRAM, 'whatsapp': S.WHATSAPP, 'bale': S.BALE,
    'linkedin': S.LINKEDIN, 'twitter': S.TWITTER, 'x': S.TWITTER,
    'facebook': S.FACEBOOK, 'youtube': S.YOUTUBE, 'aparat': S.APARAT,
    'sms': S.SMS, 'qr': S.QR,
}


def is_tracked_path(path: str) -> bool:
    return path == '/' or path.startswith(PUBLIC_PREFIXES)


def is_bot(user_agent: str) -> bool:
    ua = (user_agent or '').lower()
    return not ua or any(m in ua for m in BOT_MARKERS)


def device_of(user_agent: str) -> str:
    ua = (user_agent or '').lower()
    if 'ipad' in ua or 'tablet' in ua:
        return 'tablet'
    if 'mobile' in ua or 'android' in ua or 'iphone' in ua:
        return 'mobile'
    return 'desktop'


def host_of(url: str) -> str:
    try:
        return (urlparse(url).hostname or '').lower()
    except ValueError:
        return ''


def classify(path: str, referrer_host: str, utm_source: str) -> str:
    utm = (utm_source or '').strip().lower()
    if utm:
        return _UTM_SOURCES.get(utm, S.CAMPAIGN)
    if path.startswith('/leads/go/'):
        return S.QR
    if path.startswith('/leads/f/') and not referrer_host:
        return S.SMS
    if referrer_host:
        if referrer_host in MAIN_SITE_HOSTS:
            return S.MAIN_SITE
        for marker, source in _REFERRER_SOURCES:
            if marker in referrer_host:
                return source
        return S.OTHER_SITE
    return S.DIRECT


def record(*, visitor_id: str, is_new: bool, host: str, path: str, referrer: str,
           query: dict, user_agent: str) -> Visit | None:
    """Store one arrival, unless it is internal navigation or a quick repeat."""
    referrer = (referrer or '')[:512]
    ref_host = host_of(referrer)
    if ref_host in OWN_HOSTS or (host and ref_host == host.split(':')[0]):
        return None  # clicking around inside the site — same visit
    path = (path or '/')[:255]
    since = timezone.now() - DEDUP_WINDOW
    if Visit.objects.filter(visitor_id=visitor_id, path=path, created_at__gte=since).exists():
        return None
    utm_source = (query.get('utm_source') or '')[:128]
    return Visit.objects.create(
        visitor_id=visitor_id, is_new_visitor=is_new, host=(host or '')[:100], path=path,
        referrer=referrer, referrer_host=ref_host[:255],
        source=classify(path, ref_host, utm_source),
        utm_source=utm_source,
        utm_medium=(query.get('utm_medium') or '')[:128],
        utm_campaign=(query.get('utm_campaign') or '')[:128],
        device=device_of(user_agent),
    )


def new_visitor_id() -> str:
    return secrets.token_hex(16)
