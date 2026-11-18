import logging

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

# Calendar preference is stored in the session; defaults follow the active
# language (Persian users -> Jalali, English users -> Gregorian).
CALENDAR_SESSION_KEY = 'calendar'
VALID_CALENDARS = ('jalali', 'gregorian')


def get_calendar(request) -> str:
    value = request.session.get(CALENDAR_SESSION_KEY)
    if value in VALID_CALENDARS:
        return value
    return 'gregorian' if getattr(request, 'LANGUAGE_CODE', 'fa').startswith('en') else 'jalali'


def global_settings(request):
    return {
        'APP_NAME': 'SolarOps',
        'DEBUG_MODE': settings.DEBUG,
    }


def ai_flags(request):
    """Whether to show the customer chat bubble (cached; never breaks a page)."""
    flag = cache.get('ai:chat-enabled')
    if flag is None:
        try:
            from apps.analytics.ai_views import chat_enabled
            flag = chat_enabled()
        except Exception:
            logger.exception('ai flag failed')
            flag = False
        cache.set('ai:chat-enabled', flag, 60)
    return {'AI_CHAT_ENABLED': flag}


def calendar_settings(request):
    return {'CALENDAR': get_calendar(request)}


#: Sidebar badges are glanceable, not a live feed. One minute of staleness is
#: invisible to a human and keeps seven counting queries off every page view.
NAV_COUNTS_TTL = 60


def nav_counts(request):
    """Badge numbers next to the sidebar links, on every page.

    The dashboard view computes these itself from fresh data; everywhere else
    they come from here, cached per user. Any failure returns an empty dict —
    a missing badge is a cosmetic loss and must never take a page down.
    """
    user = getattr(request, 'user', None)
    if user is None or not user.is_authenticated or getattr(user, 'role', '') in ('customer', 'contractor'):
        return {}
    key = f'nav:counts:{user.pk}'
    cached = cache.get(key)
    if cached is not None:
        return {'nav_counts': cached}
    try:
        from apps.requests.executive_metrics import build_nav_counts
        counts = build_nav_counts(user)
    except Exception:
        logger.exception('nav counts failed')
        return {}
    cache.set(key, counts, NAV_COUNTS_TTL)
    return {'nav_counts': counts}
