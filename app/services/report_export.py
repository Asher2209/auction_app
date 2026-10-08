"""Formatting and the two export renderers (PDF via ReportLab, Excel via openpyxl) for report_service reports.

Security notes
* Excel: any text that starts with = + - @ (or a control character) could be run as a formula when the
  file is opened ("formula injection"). Such cells are stored as plain strings, never as formulas.
* PDF: text is made safe for the built-in Latin-1 fonts and escaped, because Paragraph reads XML-like markup.
"""
import io
from datetime import date, datetime
from decimal import Decimal

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .. import timeutil
from .invoice_service import _t  # Latin-1 safe + XML-escaped text

FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r", "\n")
INK, MUTED, ACCENT, LINE = colors.HexColor("#212529"), colors.HexColor("#6c757d"), colors.HexColor("#0d6efd"), colors.HexColor("#dee2e6")


def fmt(kind, value):
    """Display text for one value (HTML table and PDF)."""
    if value is None or value == "":
        return "-"
    if kind == "int":
        return f"{int(value):,}"
    if kind == "money":
        return f"{float(value):,.2f}"
    if kind == "eth":
        return f"{float(value):,.6f}".rstrip("0").rstrip(".") if float(value) else "0"
    if kind == "datetime":
        return timeutil.to_local(value).strftime("%Y-%m-%d %H:%M") if isinstance(value, datetime) else str(value)
    if kind == "date":
        return value.isoformat() if isinstance(value, (date, datetime)) else str(value)
    if kind == "rating":
        return f"{float(value):.1f}"
    if kind == "pct":
        return f"{float(value):.1f}%"
    return str(value)


def describe_params(report, params):
    """One line describing the filters in force, for the page header and exports."""
    parts = []
    if report.filter == "day":
        parts.append(f"Day: {params.day.isoformat()}")
    elif report.filter == "range":
        label = f" ({report.filter_label})" if report.filter_label else ""
        if params.start or params.end:
            a = params.first_day.isoformat() if params.start else "the beginning"
            b = params.last_day.isoformat() if params.end else "today"
            parts.append(f"Period: {a} to {b}{label}")
        else:
            parts.append(f"Period: all time{label}")
    else:
        parts.append("Snapshot of current data")
    if report.statuses and params.status != "all":
        parts.append(f"Status: {params.status}")
    return " | ".join(parts)


def _generated(now):
    return f"{timeutil.to_local(now).strftime('%Y-%m-%d %H:%M')} {timeutil.tz_name()}"


def filename(report, ext, now):
    return f"chainbid-{report.key}-{timeutil.to_local(now).strftime('%Y%m%d')}.{ext}"


# ---- Excel ------------------------------------------------------------------------------------------------------
NUMBER_FORMATS = {"int": "#,##0", "money": "#,##0.00", "eth": "0.000000", "datetime": "yyyy-mm-dd hh:mm", "date": "yyyy-mm-dd",
                  "rating": "0.0", "pct": '0.0"%"'}


def _put(cell, kind, value):
    if value is None:
        return
    if isinstance(value, Decimal):
        value = float(value)
    if kind == "datetime" and isinstance(value, datetime):
        value = timeutil.to_local(value)  # the sheet holds site-zone times, as its header says
    cell.value = value
    if isinstance(value, str):
        if value.startswith(FORMULA_STARTS):
            cell.data_type = "s"  # keep it text: never evaluate it as a formula
    if kind in NUMBER_FORMATS and not isinstance(value, str):
        cell.number_format = NUMBER_FORMATS[kind]


def render_xlsx(report, data, params, now):
    wb = Workbook()
    ws = wb.active
    ws.title = "Report"[:31]
    ws["A1"] = report.title
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = describe_params(report, params)
    ws["A3"] = f"Generated {_generated(now)}. Amounts in INR unless stated."
    ws["A2"].font = ws["A3"].font = Font(color="6C757D", size=9)
    header_row = 5
    head_fill = PatternFill("solid", fgColor="212529")
    thin = Side(style="thin", color="DEE2E6")
    for i, col in enumerate(report.columns, 1):
        c = ws.cell(header_row, i, col.display_label)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = head_fill
        c.alignment = Alignment(vertical="center", wrap_text=True, horizontal="left" if col.kind in ("text", "mono") else "right")
    for r, row in enumerate(data.rows, header_row + 1):
        for i, (col, value) in enumerate(zip(report.columns, row), 1):
            cell = ws.cell(r, i)
            _put(cell, col.kind, value)
            cell.border = Border(bottom=thin)
            if col.kind == "mono":
                cell.font = Font(name="Consolas", size=9)
    ws.freeze_panes = ws.cell(header_row + 1, 1)
    if data.rows:
        ws.auto_filter.ref = f"A{header_row}:{get_column_letter(len(report.columns))}{header_row + len(data.rows)}"
    for i, col in enumerate(report.columns, 1):
        longest = max([len(col.display_label)] + [len(fmt(col.kind, row[i - 1])) for row in data.rows[:300]])
        ws.column_dimensions[get_column_letter(i)].width = min(max(10, longest + 2), 70)

    summary = wb.create_sheet("Summary")
    summary["A1"], summary["B1"] = "Measure", "Value"
    summary["A1"].font = summary["B1"].font = Font(bold=True)
    for r, (label, value, kind) in enumerate(data.summary, 2):
        summary.cell(r, 1, label)
        _put(summary.cell(r, 2), kind, value)
    notes = [("Report", report.title), ("Filters", describe_params(report, params)), ("Rows", len(data.rows)),
             ("Complete?", "No: only the first rows were exported" if data.truncated else "Yes")]
    base = len(data.summary) + 3
    for k, (label, value) in enumerate(notes):
        summary.cell(base + k, 1, label).font = Font(color="6C757D")
        _put(summary.cell(base + k, 2), "text", value)
    summary.column_dimensions["A"].width, summary.column_dimensions["B"].width = 28, 60

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---- PDF ---------------------------------------------------------------------------------------------------------------
class _NumberedCanvas(canvas.Canvas):
    """Draws 'Page x of y' on every page (the total is only known at the end)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved = []

    def showPage(self):
        self._saved.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved)
        for state in self._saved:
            self.__dict__.update(state)
            self.setFont("Helvetica", 7.5)
            self.setFillColor(MUTED)
            self.drawRightString(self._pagesize[0] - 12 * mm, 8 * mm, f"Page {self._pageNumber} of {total}")
            super().showPage()
        super().save()


def render_pdf(report, data, params, now):
    cols = [(i, c) for i, c in enumerate(report.columns) if c.key not in report.pdf_skip]
    page = landscape(A4)
    width = page[0] - 24 * mm
    base = getSampleStyleSheet()["Normal"]
    cell = ParagraphStyle("cell", parent=base, fontSize=7, leading=8.6)
    mono = ParagraphStyle("mono", parent=cell, fontName="Courier", fontSize=6.3, leading=7.6)
    head = ParagraphStyle("head", parent=cell, fontName="Helvetica-Bold", textColor=colors.white)
    right = {"int", "money", "eth", "rating", "pct"}

    def style_for(col, name):
        s = {"mono": mono}.get(col.kind, cell)
        return ParagraphStyle(name, parent=s, alignment=2) if col.kind in right else s

    total_weight = sum(c.weight for _, c in cols)
    # proportional widths, but never narrower than the longest header word (so "Payment" never breaks mid-word)
    widths = [max(width * c.weight / total_weight, 4.6 * max(len(w) for w in c.display_label.split()) + 8) for _, c in cols]
    if sum(widths) > width:
        widths = [w * width / sum(widths) for w in widths]
    table_rows = [[Paragraph(_t(c.display_label), ParagraphStyle("h", parent=head, alignment=2 if c.kind in right else 0)) for _, c in cols]]
    for row in data.rows:
        table_rows.append([Paragraph(_t(fmt(c.kind, row[i])), style_for(c, "c")) for i, c in cols])
    if not data.rows:
        table_rows.append([Paragraph("No data for these filters.", cell)] + [""] * (len(cols) - 1))

    table = Table(table_rows, colWidths=widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), INK), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f6f7f8")]),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, LINE), ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3)]))

    title = ParagraphStyle("title", parent=base, fontName="Helvetica-Bold", fontSize=16, leading=19, textColor=INK)
    sub = ParagraphStyle("sub", parent=base, fontSize=8.5, leading=11, textColor=MUTED)
    story = [Paragraph(_t(report.title), title), Paragraph(_t(describe_params(report, params)), sub),
             Paragraph(_t(f"Generated {_generated(now)} by ChainBid. Amounts in INR unless stated."), sub), Spacer(1, 4 * mm)]
    if data.summary:
        cells = [[Paragraph(f'<font size=6.5 color="#6c757d">{_t(label).upper()}</font><br/><font size=11><b>{_t(fmt(kind, value))}</b></font>', base)
                  for label, value, kind in data.summary]]
        box = Table(cells, colWidths=[width / len(data.summary)] * len(data.summary))
        box.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.5, LINE), ("INNERGRID", (0, 0), (-1, -1), 0.25, LINE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                 ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
        story += [box, Spacer(1, 4 * mm)]
    story.append(table)
    notes = []
    if report.pdf_skip:
        notes.append("Some columns are left out of this PDF to fit the page; the Excel export has every column.")
    if data.truncated:
        notes.append(f"Only the first {len(data.rows):,} rows are shown.")
    if notes:
        story += [Spacer(1, 3 * mm), Paragraph(_t(" ".join(notes)), sub)]

    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=page, leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm, bottomMargin=14 * mm,
                      title=report.title, author="ChainBid").build(story, canvasmaker=_NumberedCanvas)
    return buf.getvalue()
