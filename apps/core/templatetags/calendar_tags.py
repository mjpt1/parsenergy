"""Dual-calendar template filters.

Datetimes are stored in the DB as standard (Gregorian, tz-aware) values;
these filters convert to the user's chosen calendar at render time. Pass the
active calendar from the template context, e.g. ``{{ obj.created_at|smartdatetime:CALENDAR }}``.
"""
from django import template
from django.utils import timezone

import jdatetime

register = template.Library()

_FA_DIGITS = str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹')


def _localize(value):
    if hasattr(value, 'hour') and timezone.is_aware(value):
        return timezone.localtime(value)
    return value


def _to_jalali(value):
    value = _localize(value)
    if hasattr(value, 'hour'):
        return jdatetime.datetime.fromgregorian(datetime=value)
    return jdatetime.date.fromgregorian(date=value)


@register.filter
def smartdate(value, calendar='gregorian'):
    """Render a date in the chosen calendar (YYYY/MM/DD)."""
    if not value:
        return ''
    if calendar == 'jalali':
        return _to_jalali(value).strftime('%Y/%m/%d').translate(_FA_DIGITS)
    return _localize(value).strftime('%Y/%m/%d')


@register.filter
def smartdatetime(value, calendar='gregorian'):
    """Render a datetime in the chosen calendar (YYYY/MM/DD HH:MM)."""
    if not value:
        return ''
    if calendar == 'jalali':
        return _to_jalali(value).strftime('%Y/%m/%d %H:%M').translate(_FA_DIGITS)
    return _localize(value).strftime('%Y/%m/%d %H:%M')
