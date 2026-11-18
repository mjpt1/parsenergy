"""One way to call a language model, with fallback between providers.

Three OpenAI-compatible providers can be configured from the AI settings page:

* ``primary`` — the original setting (any OpenAI-compatible endpoint),
* ``gapgpt``  — GapGPT, an Iranian gateway (https://api.gapgpt.app/v1),
* ``avalai``  — AvalAI, an Iranian gateway (https://api.avalai.ir/v1).

`chat()` tries them in order and returns the first answer. The Iranian
gateways keep the AI features working when international internet is cut.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass

from apps.core.models import SystemParameter

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 40


@dataclass(frozen=True)
class Provider:
    name: str
    label: str
    base_url: str
    api_key: str
    model: str
    auth_header: str = 'Authorization'
    auth_prefix: str = 'Bearer'


@dataclass(frozen=True)
class AIResult:
    text: str
    provider: str


class AIError(Exception):
    """No configured provider produced an answer."""


#: name -> (label, default base URL, default model)
BUILTIN = {
    'gapgpt': ('GapGPT (گپ جی‌پی‌تی)', 'https://api.gapgpt.app/v1', 'gpt-4o-mini'),
    'avalai': ('AvalAI (اول‌ای‌آی)', 'https://api.avalai.ir/v1', 'gpt-4o-mini'),
}
ORDER_CHOICES = {
    'primary': ('primary', 'gapgpt', 'avalai'),
    'gapgpt': ('gapgpt', 'avalai', 'primary'),
    'avalai': ('avalai', 'gapgpt', 'primary'),
}


def _param(key: str, default: str = '') -> str:
    p = SystemParameter.objects.filter(key=key).first()
    return (p.value if p else default) or default


def providers() -> list[Provider]:
    """Configured, enabled providers in the order they should be tried."""
    found = {}
    if _param('ai_enabled', 'false') == 'true':
        base, key, model = _param('ai_base_url').strip(), _param('ai_api_key').strip(), _param('ai_model').strip()
        if base and key and model:
            found['primary'] = Provider(
                'primary', 'اصلی', base, key, model,
                _param('ai_auth_header', 'Authorization').strip() or 'Authorization',
                _param('ai_auth_prefix', 'Bearer').strip())
    for name, (label, default_base, default_model) in BUILTIN.items():
        key = _param(f'ai_{name}_key').strip()
        if key and _param(f'ai_{name}_enabled', 'true') == 'true':
            found[name] = Provider(name, label, _param(f'ai_{name}_base_url', default_base).strip(),
                                   key, _param(f'ai_{name}_model', default_model).strip())
    order = ORDER_CHOICES.get(_param('ai_order', 'primary'), ORDER_CHOICES['primary'])
    return [found[n] for n in order if n in found]


def is_available() -> bool:
    return bool(providers())


def _call(p: Provider, messages: list[dict], temperature: float, max_tokens: int) -> str:
    endpoint = p.base_url.rstrip('/')
    if not endpoint.endswith('/chat/completions'):
        endpoint += '/chat/completions'
    payload = {'model': p.model, 'messages': messages, 'temperature': temperature,
               'max_tokens': max_tokens}
    auth = f'{p.auth_prefix} {p.api_key}'.strip() if p.auth_prefix else p.api_key
    req = urllib.request.Request(
        endpoint, data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
        headers={'Content-Type': 'application/json', p.auth_header: auth})
    with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
        data = json.loads(resp.read().decode('utf-8'))
    text = ((data.get('choices') or [{}])[0].get('message') or {}).get('content') or ''
    if not text.strip():
        raise AIError('empty answer')
    return text.strip()


def chat(messages: list[dict], *, temperature: float = 0.3, max_tokens: int = 900) -> AIResult:
    """Ask the first provider that answers. Raises AIError if none do."""
    tried = []
    for p in providers():
        try:
            return AIResult(_call(p, messages, temperature, max_tokens), p.label)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode('utf-8', 'ignore')[:200] if hasattr(exc, 'read') else ''
            logger.warning('AI provider %s HTTP %s %s', p.name, exc.code, detail)
            tried.append(f'{p.label}: HTTP {exc.code}')
        except Exception as exc:  # noqa: BLE001 - try the next provider
            logger.warning('AI provider %s failed: %s', p.name, exc)
            tried.append(f'{p.label}: {str(exc)[:80]}')
    if not tried:
        raise AIError('هیچ سرویس هوش مصنوعی فعالی تنظیم نشده است.')
    raise AIError('پاسخی از سرویس‌های هوش مصنوعی دریافت نشد (' + ' — '.join(tried) + ')')


def ask(system: str, user: str, **kwargs) -> AIResult:
    return chat([{'role': 'system', 'content': system}, {'role': 'user', 'content': user}], **kwargs)
