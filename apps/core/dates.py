"""Dates typed by people: Jalali (۱۴۰۵/۰۸/۰۱) or Gregorian (2026-10-23), any digits.

Browsers' <input type="date"> only offers a Gregorian calendar, so filters and
forms take plain text and this turns it into a Gregorian `date`.
"""
import re
from datetime import date

import jdatetime
from django import forms

_DIGITS = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')


def latin_digits(value):
    return str(value or '').strip().translate(_DIGITS)


def parse_user_date(value):
    """'1405/8/1', '۱۴۰۵-۰۸-۰۱' or '2026-10-23' -> date; anything else -> None."""
    if not value:
        return None
    parts = re.split(r'[/\-.\s]+', str(value).strip().translate(_DIGITS))
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        return None
    y, m, d = (int(p) for p in parts)
    try:
        if y < 1700:   # a Jalali year
            return jdatetime.date(y, m, d).togregorian()
        return date(y, m, d)
    except ValueError:
        return None


def jalali_text(value):
    return jdatetime.date.fromgregorian(date=value).strftime('%Y/%m/%d') if value else ''


class JalaliDateInput(forms.TextInput):
    def __init__(self, attrs=None):
        super().__init__({'inputmode': 'numeric', 'placeholder': 'مثلاً ۱۴۰۵/۰۸/۰۱', 'dir': 'ltr',
                          'autocomplete': 'off', 'data-jalali': '1', **(attrs or {})})

    def format_value(self, value):
        return jalali_text(value) if isinstance(value, date) else super().format_value(value)


class JalaliDateField(forms.Field):
    """A form date the user types in the Persian calendar (Gregorian also accepted)."""
    widget = JalaliDateInput
    default_error_messages = {'invalid': 'تاریخ را به شکل ۱۴۰۵/۰۸/۰۱ وارد کنید.'}

    def to_python(self, value):
        if value in self.empty_values:
            return None
        if isinstance(value, date):
            return value
        parsed = parse_user_date(value)
        if parsed is None:
            raise forms.ValidationError(self.error_messages['invalid'], code='invalid')
        return parsed
