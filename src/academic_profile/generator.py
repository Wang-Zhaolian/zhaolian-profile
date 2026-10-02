from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .content import build_document_context
from .docx_renderer import assert_docx_structure, render_docx
from .errors import DataValidationError
from .latex_renderer import render_latex
from .loader import load_contact, load_master_data, load_profile
from .pdf_builder import build_pdf
from .selection import select_profile
from .validation import has_errors, validate_repository


@dataclass
class GenerationResult:
    profile: str
    outputs: list[Path] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)


def generate_profile(
    profile_name: str,
    *,
    data_dir: Path,
    profile_dir: Path,
    schema_dir: Path,
    template_dir: Path,
    output_root: Path,
    contact_path: Path | None = None,
    formats: tuple[str, ...] = ("latex", "docx", "pdf"),
) -> GenerationResult:
    issues = validate_repository(data_dir, profile_dir, schema_dir)
    if has_errors(issues):
        details = "\n".join(str(issue) for issue in issues if issue.severity == "error")
        raise DataValidationError(f"Data validation failed:\n{details}")

    data = load_master_data(data_dir)
    profile = load_profile(profile_dir, profile_name)
    contact = load_contact(contact_path)
    sections = select_profile(data, profile)
    context = build_document_context(data, profile, sections, contact)
    if context["name"] == "Name Required":
        raise DataValidationError(
            "data/basics.yaml must contain name or name_en before generating a CV"
        )

    result = GenerationResult(profile=profile_name)
    output_dir = output_root / profile_name
    output_dir.mkdir(parents=True, exist_ok=True)

    tex_path = output_dir / "cv.tex"
    if "latex" in formats or "pdf" in formats:
        render_latex(context, template_dir / "latex", tex_path)
        result.outputs.append(tex_path)

    if "docx" in formats:
        docx_path = output_dir / "cv.docx"
        render_docx(
            context,
            template_dir / "docx" / "academic_cv_template.docx",
            docx_path,
        )
        assert_docx_structure(docx_path)
        result.outputs.append(docx_path)

    if "pdf" in formats:
        pdf_path, message = build_pdf(tex_path)
        result.messages.append(message)
        if pdf_path:
            result.outputs.append(pdf_path)

    return result

