"""Build the committed Word style template used by the generator."""

from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "templates" / "docx" / "academic_cv_template.docx"


def set_font(style, name: str, size: float, *, bold: bool = False) -> None:
    style.font.name = name
    style.font.size = Pt(size)
    style.font.bold = bold
    style.font.color.rgb = RGBColor(0, 0, 0)
    style._element.get_or_add_rPr().rFonts.set(qn("w:ascii"), name)
    style._element.get_or_add_rPr().rFonts.set(qn("w:hAnsi"), name)
    style._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")


def main() -> None:
    document = Document()
    section = document.sections[0]
    section.orientation = WD_ORIENT.PORTRAIT
    section.page_width = Inches(8.5)
    section.page_height = Inches(11)
    section.top_margin = Inches(0.58)
    section.bottom_margin = Inches(0.58)
    section.left_margin = Inches(0.68)
    section.right_margin = Inches(0.68)

    styles = document.styles
    set_font(styles["Normal"], "Arial", 9.5)
    styles["Normal"].paragraph_format.space_after = Pt(2)
    styles["Normal"].paragraph_format.line_spacing = 1.02

    set_font(styles["Title"], "Arial", 18, bold=True)
    styles["Title"].paragraph_format.space_after = Pt(3)
    styles["Title"].paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER

    set_font(styles["Subtitle"], "Arial", 10)
    styles["Subtitle"].paragraph_format.space_after = Pt(2)
    styles["Subtitle"].paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER

    set_font(styles["Heading 1"], "Arial", 11.5, bold=True)
    styles["Heading 1"].paragraph_format.space_before = Pt(7)
    styles["Heading 1"].paragraph_format.space_after = Pt(3)
    styles["Heading 1"].paragraph_format.keep_with_next = True

    custom = {
        "CV Contact": (9.2, 0, 4),
        "CV Entry": (10.3, 4, 0),
        "CV Detail": (9.5, 0, 1),
        "CV Bullet": (9.5, 0, 1.5),
    }
    for name, (size, before, after) in custom.items():
        style = styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
        set_font(style, "Arial", size)
        style.paragraph_format.space_before = Pt(before)
        style.paragraph_format.space_after = Pt(after)
        style.paragraph_format.line_spacing = 1.02
    styles["CV Contact"].paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
    styles["CV Entry"].paragraph_format.keep_with_next = True
    styles["CV Detail"].paragraph_format.keep_with_next = True
    styles["CV Bullet"].paragraph_format.left_indent = Inches(0.18)
    styles["CV Bullet"].paragraph_format.first_line_indent = Inches(-0.14)

    document.core_properties.title = "Academic CV Template"
    document.core_properties.subject = "ATS-friendly single-column academic CV"
    document.core_properties.author = "academic-profile"
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    document.save(OUTPUT)
    print(OUTPUT)


if __name__ == "__main__":
    main()

