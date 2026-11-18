"""Plain-Persian display helpers for raw codes and durations.

Several dashboards print stored codes (priority, severity, connection state)
straight from the database, which shows staff and customers words like
"normal", "high" or "critical". `|fa` turns those codes into everyday Persian;
`|age` turns a count of hours into "۳ ساعت" or "۱۲۹ روز".
"""
from django import forms, template

register = template.Library()

_FA_DIGITS = str.maketrans('0123456789.', '۰۱۲۳۴۵۶۷۸۹٫')

LABELS = {
    # priority
    'low': 'کم', 'normal': 'عادی', 'medium': 'متوسط', 'high': 'زیاد', 'urgent': 'فوری',
    # alert severity / health
    'critical': 'بحرانی', 'warning': 'هشدار', 'warn': 'هشدار', 'info': 'اطلاع', 'healthy': 'سالم',
    # connection / device state
    'online': 'متصل', 'offline': 'قطع', 'degraded': 'ناپایدار', 'fault': 'خطا', 'ok': 'عادی',
    'hot': 'داغ', 'standby': 'آماده‌به‌کار', 'idle': 'بیکار', 'wait': 'در انتظار',
    # request flow
    'hold': 'متوقف', 'lost': 'از دست‌رفته',
}


@register.filter
def fa(value):
    """Everyday Persian for a stored code; unknown values pass through unchanged."""
    if value is None:
        return ''
    return LABELS.get(str(value).strip().lower(), value)


@register.filter
def age(hours):
    """Hours -> '۵ ساعت' up to two days, then whole days."""
    try:
        hours = float(hours)
    except (TypeError, ValueError):
        return '—'
    if hours < 1:
        return 'کمتر از یک ساعت'
    if hours < 48:
        return f'{int(hours)} ساعت'.translate(_FA_DIGITS)
    return f'{round(hours / 24)} روز'.translate(_FA_DIGITS)


@register.filter
def age_since(value):
    """A datetime -> how long ago, as `age` words ('۳ ساعت', '۱۲ روز')."""
    if not value:
        return '—'
    from django.utils import timezone
    return age((timezone.now() - value).total_seconds() / 3600.0)


@register.filter
def customer_progress(req):
    from apps.requests.progress import customer_progress as build
    return build(req)


def energy_tariff_rial():
    """Rial per kWh from System Parameters (`tariff.energy_rial_per_kwh`), or None if unset."""
    from apps.core.models import SystemParameter
    raw = SystemParameter.objects.filter(key='tariff.energy_rial_per_kwh').values_list('value', flat=True).first()
    try:
        value = float(str(raw).replace(',', '').strip())
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


# --------------------------------------------------------------------------- #
# Shared add / edit / delete pages
# --------------------------------------------------------------------------- #

MODEL_LABELS = {
    'plantsection': 'سوله', 'plant': 'نیروگاه', 'plantgroup': 'گروه نیروگاه', 'inverter': 'اینورتر', 'cloudaccount': 'حساب ابری',
    'sensor': 'سنسور', 'meter': 'کنتور', 'equipment': 'تجهیز', 'transformer': 'ترانس', 'gateway': 'گیت‌وی',
    'alertrule': 'قانون هشدار', 'alertevent': 'رویداد هشدار', 'notification': 'اعلان',
    'vpp': 'نیروگاه مجازی', 'vppmember': 'عضو نیروگاه مجازی', 'dispatchschedule': 'برنامهٔ تولید',
    'systemparameter': 'پارامتر سیستم', 'securitysetting': 'تنظیم امنیتی', 'apiconnection': 'اتصال API',
    'protocoladapter': 'پروتکل', 'databasebackup': 'بکاپ',
}

DELETE_NOTES = {
    'plant': 'همهٔ اینورترها، تجهیزات، هشدارها و داده‌های تولید این نیروگاه هم پاک می‌شوند.',
    'plantgroup': 'نیروگاه‌های گروه باقی می‌مانند و فقط از این گروه خارج می‌شوند.',
    'equipment': 'اندازه‌گیری‌های ثبت‌شدهٔ این تجهیز هم پاک می‌شوند.',
    'alertrule': 'رویدادهای ثبت‌شدهٔ این قانون هم پاک می‌شوند.',
    'vpp': 'اعضا و برنامه‌های این نیروگاه مجازی هم پاک می‌شوند.',
}


@register.simple_tag
def form_heading(form):
    """'افزودن نیروگاه' / 'ویرایش نیروگاه: یزد' from the form's own model."""
    instance = getattr(form, 'instance', None)
    label = MODEL_LABELS.get(instance._meta.model_name) if instance is not None else None
    if not label:
        return 'فرم'
    return f'ویرایش {label}: {instance}' if instance.pk else f'افزودن {label}'


@register.simple_tag
def delete_info(obj):
    name = obj._meta.model_name
    return {'kind': MODEL_LABELS.get(name, 'مورد'), 'name': str(obj), 'note': DELETE_NOTES.get(name, '')}


@register.filter
def field_kind(field):
    widget = field.field.widget
    if isinstance(widget, forms.CheckboxSelectMultiple):
        return 'multi'
    if isinstance(widget, forms.CheckboxInput):
        return 'check'
    if isinstance(widget, forms.Textarea):
        return 'area'
    return 'input'


@register.filter
def styled(field):
    """Render a bound field with the site's input classes."""
    widget = field.field.widget
    if isinstance(widget, forms.CheckboxSelectMultiple):
        return field
    if isinstance(widget, forms.CheckboxInput):
        css = 'form-check-input'
    elif isinstance(widget, forms.Select):
        css = 'form-select'
    else:
        css = 'form-control'
    existing = widget.attrs.get('class', '')
    return field.as_widget(attrs={'class': f'{existing} {css}'.strip()})


@register.simple_tag
def active_filters(request):
    """How many list filters are in use (the search box and paging do not count)."""
    return sum(1 for key, values in request.GET.lists()
               if key not in ('q', 'page') and any(v.strip() for v in values))


@register.filter
def sensitive_param(param):
    from apps.core.management_views import is_sensitive_parameter
    return is_sensitive_parameter(param)


@register.filter
def approval_param(param):
    from apps.core.management_views import needs_approval
    return needs_approval(param.key)
