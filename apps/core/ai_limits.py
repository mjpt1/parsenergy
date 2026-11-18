"""Per-feature limits for the AI helpers, set from Settings > AI.

Each staff feature has: on/off, the roles allowed to use it, and a daily cap
per person (0 = no cap). The customer chat has a per-visitor and a total
hourly cap. Everything is stored as SystemParameter rows so it can change
without a deploy.
"""
from __future__ import annotations

from django.core.cache import cache
from django.utils import timezone

from apps.core.models import SystemParameter

ROLES = (
    ('admin', 'مدیریت'),
    ('sales', 'فروش'),
    ('marketing', 'بازاریابی'),
    ('technical', 'فنی'),
    ('operations', 'عملیات'),
    ('financial', 'مالی'),
    ('customer', 'مشتری / مالک نیروگاه'),
)
#: Account roles that count as "customer" here.
CUSTOMER_ROLES = ('owner', 'customer', 'operator', 'analyst')

#: feature -> (label, default roles, default daily cap per person)
FEATURES = {
    'lead': ('تحلیل هوشمند سرنخ', ('admin', 'sales', 'marketing', 'technical', 'operations'), 50),
    'ticket': ('پیش‌نویس پاسخ تیکت', ('admin', 'sales', 'marketing', 'technical', 'operations'), 50),
    'traffic': ('خلاصهٔ مدیریتی بازدید', ('admin', 'sales'), 20),
    'plant': ('تحلیل نیروگاه', ('admin', 'technical', 'operations', 'customer'), 20),
}

CHAT_DEFAULTS = {'ai_chat_per_visitor': 25, 'ai_chat_total': 300}


def _param(key: str, default: str = '') -> str:
    p = SystemParameter.objects.filter(key=key).first()
    return p.value if p is not None else default


def _int(key: str, default: int) -> int:
    try:
        return max(0, int(_param(key, str(default))))
    except (TypeError, ValueError):
        return default


def settings_for(feature: str) -> dict:
    label, roles, daily = FEATURES[feature]
    raw_roles = _param(f'ai_feat_{feature}_roles', ','.join(roles))
    return {
        'label': label,
        'enabled': _param(f'ai_feat_{feature}_enabled', 'true') == 'true',
        'roles': [r for r in raw_roles.split(',') if r],
        'daily': _int(f'ai_feat_{feature}_daily', daily),
    }


def chat_limits() -> tuple[int, int]:
    return (_int('ai_chat_per_visitor', CHAT_DEFAULTS['ai_chat_per_visitor']),
            _int('ai_chat_total', CHAT_DEFAULTS['ai_chat_total']))


def user_role(user) -> str:
    if getattr(user, 'is_superuser', False):
        return 'admin'
    role = getattr(user, 'role', '') or ''
    return 'customer' if role in CUSTOMER_ROLES else role


def _usage_key(feature: str, user) -> str:
    return f'ai-use:{feature}:{user.pk}:{timezone.localdate():%Y%m%d}'


def check(user, feature: str) -> str | None:
    """Why this user may not use `feature` now, or None if they may."""
    cfg = settings_for(feature)
    if not cfg['enabled']:
        return f'«{cfg["label"]}» از تنظیمات خاموش شده است.'
    if user_role(user) not in cfg['roles']:
        return f'نقش شما اجازهٔ استفاده از «{cfg["label"]}» را ندارد.'
    if cfg['daily'] and cache.get(_usage_key(feature, user), 0) >= cfg['daily']:
        return f'سقف روزانهٔ «{cfg["label"]}» ({cfg["daily"]} بار) پر شده است. فردا دوباره امتحان کنید.'
    return None


def consume(user, feature: str) -> None:
    key = _usage_key(feature, user)
    cache.set(key, cache.get(key, 0) + 1, 26 * 3600)


def used_today(user, feature: str) -> int:
    return cache.get(_usage_key(feature, user), 0)
