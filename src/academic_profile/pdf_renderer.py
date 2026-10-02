"""Create a compact, selectable-text PDF from the shared CV view model."""

from __future__ import annotations

from html import escape
import os
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def _register_pdf_fonts() -> tuple[str, str]:
    """Embed subsets of the local Windows CJK font when available.

    System fonts are read at runtime and never bundled or redistributed. On
    non-Windows hosts ReportLab's built-in Simplified Chinese CID font is used.
    """
    windows_dir = Path(os.environ.get("WINDIR", r"C:\Windows"))
    fonts_dir = windows_dir / "Fonts"
    regular_candidates = (
        fonts_dir / "msyh.ttc",
        fonts_dir / "simsun.ttc",
        fonts_dir / "simsunb.ttf",
    )
    for candidate in regular_candidates:
        if not candidate.exists():
            continue
        try:
            pdfmetrics.registerFont(TTFont("AcademicCJK", str(candidate), subfontIndex=0))
            bold_file = fonts_dir / "msyhbd.ttc"
            if bold_file.exists():
                pdfmetrics.registerFont(TTFont("AcademicCJKBold", str(bold_file), subfontIndex=0))
            else:
                pdfmetrics.registerFont(TTFont("AcademicCJKBold", str(candidate), subfontIndex=0))
            return "AcademicCJK", "AcademicCJKBold"
        except Exception:
            continue
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    return "STSong-Light", "STSong-Light"


PDF_FONT, PDF_BOLD_FONT = _register_pdf_fonts()


def _safe(value: Any) -> str:
    return escape(str(value)).replace("\n", "<br/>")


def render_pdf(context: dict[str, Any], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=LETTER,
        rightMargin=0.68 * inch,
        leftMargin=0.68 * inch,
        topMargin=0.62 * inch,
        bottomMargin=0.62 * inch,
        title=f"{context['name']} Academic CV",
        author=context["name"],
    )
    styles = getSampleStyleSheet()
    name_style = ParagraphStyle(
        "CVName", parent=styles["Title"], fontName=PDF_BOLD_FONT, fontSize=18,
        leading=22, textColor=colors.HexColor("#172538"), alignment=TA_CENTER,
        spaceAfter=4, wordWrap="CJK",
    )
    headline_style = ParagraphStyle(
        "CVHeadline", parent=styles["Normal"], fontName=PDF_FONT, fontSize=9.5,
        leading=13, textColor=colors.HexColor("#4b5d70"), alignment=TA_CENTER,
        spaceAfter=3, wordWrap="CJK",
    )
    contact_style = ParagraphStyle(
        "CVContact", parent=headline_style, fontSize=8.5, leading=11, spaceAfter=11,
    )
    section_style = ParagraphStyle(
        "CVSection", parent=styles["Heading2"], fontName=PDF_BOLD_FONT,
        fontSize=11, leading=14, textColor=colors.HexColor("#172538"),
        spaceBefore=9, spaceAfter=4, keepWithNext=True, wordWrap="CJK",
    )
    entry_style = ParagraphStyle(
        "CVEntry", parent=styles["Normal"], fontName=PDF_BOLD_FONT, fontSize=9.5,
        leading=13, textColor=colors.black, spaceBefore=4, spaceAfter=1,
        keepWithNext=True, wordWrap="CJK",
    )
    sub_style = ParagraphStyle(
        "CVSub", parent=styles["Normal"], fontName=PDF_FONT, fontSize=8.8,
        leading=12, textColor=colors.HexColor("#4b5d70"), spaceAfter=2,
        keepWithNext=True, wordWrap="CJK",
    )
    body_style = ParagraphStyle(
        "CVBody", parent=styles["Normal"], fontName=PDF_FONT, fontSize=9,
        leading=12, textColor=colors.black, spaceAfter=2, wordWrap="CJK",
    )
    bullet_style = ParagraphStyle(
        "CVBullet", parent=body_style, leftIndent=12, firstLineIndent=-8,
        bulletIndent=0, spaceAfter=2,
    )

    story: list[Any] = [Paragraph(_safe(context["name"]), name_style)]
    if context.get("headline"):
        story.append(Paragraph(_safe(context["headline"]), headline_style))
    if context.get("contact"):
        story.append(
            Paragraph(" &nbsp; | &nbsp; ".join(_safe(item["value"]) for item in context["contact"]), contact_style)
        )
    else:
        story.append(Spacer(1, 6))

    for section in context.get("sections", []):
        story.append(Paragraph(_safe(section["title"]), section_style))
        if section["id"] == "research_interests":
            story.append(Paragraph(_safe(", ".join(section["items"])), body_style))
            continue
        for item in section.get("items", []):
            date_text = _safe(item.get("date", ""))
            title_text = _safe(item.get("title", ""))
            row = Table(
                [[Paragraph(title_text, entry_style), Paragraph(date_text, ParagraphStyle("CVDate", parent=entry_style, alignment=TA_RIGHT, fontName=PDF_FONT, fontSize=8.5))]],
                colWidths=[doc.width * 0.72, doc.width * 0.28],
                hAlign="LEFT",
            )
            row.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]))
            story.append(row)
            if item.get("subtitle"):
                story.append(Paragraph(_safe(item["subtitle"]), sub_style))
            for metadata in item.get("metadata", []):
                story.append(Paragraph(_safe(metadata), body_style))
            for bullet in item.get("bullets", []):
                story.append(Paragraph(f"&#8226; &nbsp;{_safe(bullet)}", bullet_style))

    def draw_page(canvas: Any, document: Any) -> None:
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#d7dee7"))
        canvas.setLineWidth(0.4)
        canvas.line(doc.leftMargin, 0.43 * inch, LETTER[0] - doc.rightMargin, 0.43 * inch)
        canvas.setFillColor(colors.HexColor("#738195"))
        canvas.setFont(PDF_FONT, 8)
        canvas.drawRightString(LETTER[0] - doc.rightMargin, 0.27 * inch, str(document.page))
        canvas.restoreState()

    doc.build(story, onFirstPage=draw_page, onLaterPages=draw_page)
    return output_path
