"""Create presentation PDFs from the approved DOCX briefing content."""
from html import escape
from pathlib import Path

from docx import Document
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate, Frame, KeepTogether, PageBreak, PageTemplate,
    Paragraph, Spacer, Table, TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "deliverables"
pdfmetrics.registerFont(TTFont("ArialCustom", "C:/Windows/Fonts/arial.ttf"))
pdfmetrics.registerFont(TTFont("ArialCustomBold", "C:/Windows/Fonts/arialbd.ttf"))
GREEN = colors.HexColor("#0A6952")
INK = colors.HexColor("#1E3137")
MUTED = colors.HexColor("#5B7076")

STYLES = {
    "Title": ParagraphStyle("title", fontName="ArialCustomBold", fontSize=21,
                            leading=26, textColor=colors.black, spaceAfter=10),
    "Normal": ParagraphStyle("body", fontName="ArialCustom", fontSize=9.2,
                             leading=13.5, textColor=INK, spaceAfter=8),
    "Heading 1": ParagraphStyle("heading", fontName="ArialCustomBold", fontSize=12,
                                leading=16, textColor=GREEN, spaceBefore=11,
                                spaceAfter=7, keepWithNext=True),
    "List Bullet": ParagraphStyle("bullet", fontName="ArialCustom", fontSize=9.1,
                                  leading=13, textColor=INK, leftIndent=16,
                                  firstLineIndent=-10, spaceAfter=3),
    "List Number": ParagraphStyle("number", fontName="ArialCustom", fontSize=9.1,
                                  leading=13, textColor=INK, leftIndent=16,
                                  firstLineIndent=-10, spaceAfter=3),
    "subtitle": ParagraphStyle("subtitle", fontName="ArialCustom", fontSize=9.7,
                               leading=14, textColor=MUTED, spaceAfter=13),
    "cell": ParagraphStyle("cell", fontName="ArialCustom", fontSize=8.2,
                           leading=11.1, textColor=INK),
    "cellhead": ParagraphStyle("cellhead", fontName="ArialCustomBold", fontSize=8.2,
                               leading=11.1, textColor=GREEN),
}


def decorate(canvas, doc):
    canvas.saveState()
    width, height = A4
    canvas.setFont("ArialCustomBold", 7.6)
    canvas.setFillColor(GREEN)
    canvas.drawString(0.78 * inch, height - .44 * inch,
                      "FOODBRIDGE  |  INVENTORY MANAGEMENT AND EXPIRY TRACKING")
    canvas.setFillColor(MUTED)
    canvas.setFont("ArialCustom", 7.5)
    canvas.drawRightString(width - .78 * inch, .42 * inch,
                           f"Milestone 1  |  14 October 2026  |  Page {doc.page}")
    canvas.restoreState()


def to_pdf(source):
    target = source.with_suffix(".pdf")
    doc = BaseDocTemplate(str(target), pagesize=A4,
                          leftMargin=.78 * inch, rightMargin=.78 * inch,
                          topMargin=.72 * inch, bottomMargin=.68 * inch)
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height,
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates(PageTemplate(id="main", frames=[frame], onPage=decorate))
    original = Document(source)
    blocks = []
    number = 0
    body = original.element.body
    from docx.table import Table as DocxTable
    from docx.text.paragraph import Paragraph as DocxParagraph
    for child in body.iterchildren():
        if child.tag.endswith("}p"):
            para = DocxParagraph(child, original)
            if 'w:type="page"' in para._p.xml:
                blocks.append(PageBreak())
                continue
            text = para.text.strip()
            if not text:
                continue
            style = para.style.name
            if style == "List Number":
                number += 1
                text = f"{number}.  {text}"
            elif style == "List Bullet":
                text = f"•  {text}"
            elif style == "Normal" and len(blocks) == 1:
                style = "subtitle"
            blocks.append(Paragraph(escape(text), STYLES.get(style, STYLES["Normal"])))
        elif child.tag.endswith("}tbl"):
            tbl = DocxTable(child, original)
            matrix = []
            for rowidx, row in enumerate(tbl.rows):
                cellstyle = STYLES["cellhead" if rowidx == 0 else "cell"]
                matrix.append([Paragraph(escape(c.text), cellstyle) for c in row.cells])
            report_table = Table(matrix, repeatRows=1, hAlign="LEFT",
                                 colWidths=[doc.width / len(matrix[0])] * len(matrix[0]))
            report_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EAF5EF")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1),
                 [colors.white, colors.HexColor("#F3F7F8")]),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]))
            blocks.extend([report_table, Spacer(1, 5)])
    doc.build(blocks)
    print(target)


if __name__ == "__main__":
    for source in sorted(OUT.glob("*.docx")):
        to_pdf(source)
