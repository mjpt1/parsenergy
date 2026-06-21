from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from openpyxl import Workbook


def build_pdf_report(title: str, rows: list[tuple[str, str]]) -> bytes:
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    pdf.setTitle(title)
    pdf.drawString(50, 800, title)
    y = 770
    for key, value in rows:
        pdf.drawString(50, y, f'{key}: {value}')
        y -= 20
    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


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
