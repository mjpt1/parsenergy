"""Excel exports for the lead and request lists.

Why only Excel here, and PDF through the browser's print dialog:

reportlab draws text glyph by glyph in the order it is given. Persian needs the
opposite — letters joined by context and the line laid out right to left — which
takes a shaping library, a bidi pass and an embedded Persian TTF. The browser
already does all three, perfectly, and every machine in the office has one. So
the PDF route is a print-styled page (`?print=1`) and Ctrl+P → Save as PDF,
while the spreadsheet, where Unicode just works, is built here.
"""
from __future__ import annotations

from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

HEADER_FILL = PatternFill('solid', fgColor='1F6F3D')
HEADER_FONT = Font(color='FFFFFF', bold=True)


def build_sheet(title: str, headers: list[str], rows: list[list]) -> bytes:
    """A single formatted sheet: styled header, frozen top row, sane widths."""
    wb = Workbook()
    ws = wb.active
    ws.title = title[:31] or 'Sheet1'
    ws.sheet_view.rightToLeft = True

    ws.append(headers)
    for cell in ws[1]:
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal='center', vertical='center')

    for row in rows:
        ws.append(row)

    for index, header in enumerate(headers, start=1):
        longest = max([len(str(header))] + [len(str(r[index - 1])) for r in rows] or [0])
        ws.column_dimensions[get_column_letter(index)].width = min(max(longest + 4, 12), 46)

    ws.freeze_panes = 'A2'
    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


LEAD_HEADERS = [
    'شناسه', 'نام', 'موبایل', 'شرکت', 'سمت', 'حوزه فعالیت', 'استان', 'شهر',
    'هدف', 'زمان اقدام', 'روش تماس', 'بازاریاب', 'رویداد', 'کیفیت',
    'مرحله ۲', 'نوع محل', 'مساحت', 'سایه‌اندازی', 'شناسه قبض', 'آدرس',
    'اقدام بعدی', 'نقش در تصمیم', 'یادداشت', 'تاریخ ثبت',
]


def lead_rows(leads) -> list[list]:
    rows = []
    for lead in leads:
        rows.append([
            lead.lead_code,
            lead.full_name,
            lead.mobile,
            lead.company,
            lead.job_title,
            lead.business_field,
            lead.province,
            lead.city,
            '، '.join(lead.goal_labels),
            lead.get_timeline_display() or '',
            lead.get_contact_method_display() or '',
            (lead.marketer.get_full_name() or lead.marketer.username) if lead.marketer else 'عمومی',
            lead.event_name,
            lead.get_temperature_display() or '',
            'تکمیل' if lead.stage2_completed else 'ناقص',
            lead.get_install_location_display() or '',
            lead.get_area_range_display() or '',
            lead.get_shading_display() or '',
            lead.bill_id,
            lead.location_address,
            lead.next_action,
            lead.decision_role,
            lead.notes,
            lead.created_at.strftime('%Y-%m-%d %H:%M'),
        ])
    return rows


REQUEST_HEADERS = [
    'شناسه', 'نام', 'شرکت', 'موبایل', 'استان', 'شهر', 'وضعیت', 'بخش',
    'نوع درخواست', 'منبع', 'احراز هویت', 'توضیحات', 'تاریخ ثبت',
]


def _company(req) -> str:
    """Company from the marketer's lead form; site requests have none."""
    try:
        return req.exhibition.company or ''
    except Exception:  # no lead attached to this request
        return ''


def request_rows(requests, *, hide_identity: bool = False) -> list[list]:
    """Rows for the request list.

    `hide_identity` mirrors the panel's own rule for technical staff: the name
    and the mobile number simply are not written, rather than written and
    hidden somewhere downstream.
    """
    rows = []
    for req in requests:
        rows.append([
            req.id,
            '—' if hide_identity else req.full_name,
            _company(req),
            '—' if hide_identity else req.mobile,
            req.province,
            req.city,
            req.get_status_display(),
            req.get_department_display() if hasattr(req, 'get_department_display') else '',
            req.get_request_type_display() if req.request_type else '',
            req.lead_source,
            'بله' if req.identity_verified else 'خیر',
            (req.description or '')[:300],
            req.created_at.strftime('%Y-%m-%d %H:%M'),
        ])
    return rows
