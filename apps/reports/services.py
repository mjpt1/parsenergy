from io import BytesIO
from openpyxl import Workbook


def build_excel_report(sheet_name: str, rows: list[tuple[str, str]]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name
    ws.append(['Key', 'Value'])
    for key, value in rows:
        ws.append([key, value])
    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
