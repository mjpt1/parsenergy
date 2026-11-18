"""Day and hour maths in the site's time zone, done in Python.

The production MariaDB has no time-zone tables, so Django's CONVERT_TZ-based
lookups (`__date`, `TruncDate`, `TruncHour` in Asia/Tehran) come back NULL
there: date filters match nothing and charts fail with "Database returned an
invalid datetime value". Filter with plain datetime ranges and group in Python.
"""
from datetime import datetime, time, timedelta

from django.utils import timezone


def day_start(day):
    """Local midnight of `day` as an aware datetime."""
    return timezone.make_aware(datetime.combine(day, time.min), timezone.get_current_timezone())


def on_or_after(field, day):
    return {f'{field}__gte': day_start(day)}


def before_end_of(field, day):
    return {f'{field}__lt': day_start(day + timedelta(days=1))}


def local_hour(dt):
    return timezone.localtime(dt).replace(minute=0, second=0, microsecond=0)


def local_day(dt):
    return timezone.localtime(dt).date()
