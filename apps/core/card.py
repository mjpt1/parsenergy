"""The company's online business card: one page, one QR, one .vcf.

The QR on the card carries the vCard itself rather than a link, so a phone
camera offers "Add contact" straight away — no network, no page load. The
"save contact" button serves the same vCard as a .vcf file, with the logo.

Details are those published on pars-energy.com/contact-us; change them here
and the page, the QR and the .vcf all follow.
"""
from __future__ import annotations

import base64
import re
from io import BytesIO
from pathlib import Path

from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import render
from django.utils.safestring import mark_safe
from django.views.decorators.cache import cache_page

COMPANY = {
    'name': 'پارس انرژی تیدا',
    'name_en': 'Pars Energy Tida',
    'tagline': 'طراحی، اجرا و بهره‌برداری نیروگاه‌های خورشیدی',
    'phone': '021-22222922',
    'phone_e164': '+982122222922',
    'address': 'تهران، بلوار میرداماد، خیابان نیک رای، پلاک ۳',
    'website': 'https://pars-energy.com',
    # Sales expert: the same number on Bale, Telegram and for calls.
    'sales_phone': '0919 833 3303',
    'sales_phone_e164': '+989198333303',
    # Telegram opens a chat straight from a phone number.
    'telegram': 'https://t.me/+989198333303',
    # Bale links need the account's username (https://ble.ir/<username>);
    # while it is empty the Bale button copies the number instead.
    'bale': '',
    'maps': 'https://www.google.com/maps/search/?api=1&query='
            '%D9%BE%D8%A7%D8%B1%D8%B3+%D8%A7%D9%86%D8%B1%DA%98%DB%8C+%D9%85%DB%8C%D8%B1%D8%AF%D8%A7%D9%85%D8%A7%D8%AF+%D9%86%DB%8C%DA%A9+%D8%B1%D8%A7%DB%8C',
    'services': [
        'نیروگاه خورشیدی اختصاصی',
        'نیروگاه خورشیدی مشارکتی',
        'پایش هوشمند و بهره‌برداری',
    ],
}


CRLF = chr(13) + chr(10)  # vCard line ending


def _esc(value: str) -> str:
    """vCard 3.0 text escaping."""
    return re.sub(r'([,;\\])', r'\\\1', value).replace('\n', '\\n')


def vcard(*, with_photo: bool = False, compact: bool = False) -> str:
    """`compact` is for the QR: every extra field makes the code denser and
    harder to scan from a printed card, so it carries only what a contact needs."""
    c = COMPANY
    lines = [
        'BEGIN:VCARD',
        'VERSION:3.0',
        f'N:;{_esc(c["name"])};;;',
        f'FN:{_esc(c["name"])}',
        f'ORG:{_esc(c["name"])}',
        *([] if compact else [f'TITLE:{_esc(c["tagline"])}']),
        f'TEL;TYPE=WORK,VOICE:{c["phone_e164"]}',
        f'TEL;TYPE=CELL:{c["sales_phone_e164"]}',
        f'ADR;TYPE=WORK:;;{_esc(c["address"])};;;;',
        f'URL:{c["website"]}',
    ]
    if compact:
        lines.append('END:VCARD')
        return CRLF.join(lines) + CRLF
    lines.append(f'X-SOCIALPROFILE;TYPE=telegram:{c["telegram"]}')
    if c['bale']:
        lines.append(f'X-SOCIALPROFILE;TYPE=bale:{c["bale"]}')
    if with_photo:
        photo = _logo_jpeg_b64()
        if photo:
            lines.append(f'PHOTO;ENCODING=b;TYPE=JPEG:{photo}')
    lines.append('END:VCARD')
    return CRLF.join(lines) + CRLF


def _logo_jpeg_b64() -> str:
    """The logo as JPEG — contact apps do not read WebP."""
    try:
        from PIL import Image
    except ImportError:
        return ''
    for root in [Path(settings.BASE_DIR) / 'static', *map(Path, getattr(settings, 'STATICFILES_DIRS', []))]:
        path = root / 'img' / 'pars-logo.webp'
        if path.exists():
            img = Image.open(path).convert('RGBA')
            canvas = Image.new('RGB', img.size, 'white')
            canvas.paste(img, mask=img.split()[3])
            canvas.thumbnail((300, 300))
            out = BytesIO()
            canvas.save(out, 'JPEG', quality=85)
            return base64.b64encode(out.getvalue()).decode('ascii')
    return ''


def _qr_svg(data: str) -> str:
    import qrcode
    import qrcode.image.svg

    code = qrcode.QRCode(border=0, error_correction=qrcode.constants.ERROR_CORRECT_M)
    code.add_data(data.encode('utf-8'))
    code.make(fit=True)
    img = code.make_image(image_factory=qrcode.image.svg.SvgPathImage)
    buffer = BytesIO()
    img.save(buffer)
    svg = buffer.getvalue().decode('utf-8').split('?>', 1)[-1].strip()
    svg = re.sub(r'(<svg[^>]*?)\s+width="[^"]*"\s+height="[^"]*"', r'\1', svg, count=1)
    return svg.replace('<svg', '<svg role="img" aria-label="QR"', 1)


@cache_page(60 * 60)
def card(request):
    return render(request, 'core/card.html', {
        'c': COMPANY,
        'qr_svg': mark_safe(_qr_svg(vcard(compact=True))),  # noqa: S308 - our own SVG
        'page_url': request.build_absolute_uri(request.path),
    })


#: Where the QR-only page sends people. Fixed so the code is the same on every
#: print, whatever host or proxy served the page.
CARD_URL = 'https://pars-tida.ir/card/'


@cache_page(60 * 60)
def card_qr(request):
    """A page with nothing but a QR code that opens the business card."""
    return render(request, 'core/card_qr.html', {
        'qr_svg': mark_safe(_qr_svg(CARD_URL)),  # noqa: S308 - our own SVG
    })


@cache_page(60 * 60)
def card_vcf(request):
    response = HttpResponse(vcard(with_photo=True), content_type='text/vcard; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="pars-energy.vcf"'
    return response
