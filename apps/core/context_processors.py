from django.conf import settings

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


def calendar_settings(request):
    return {'CALENDAR': get_calendar(request)}
