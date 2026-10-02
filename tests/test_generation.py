from __future__ import annotations

from pathlib import Path

from docx import Document

from academic_profile.constants import PROFILE_NAMES
from academic_profile.generator import generate_profile

ROOT = Path(__file__).resolve().parents[1]


def _generate(profile: str, output: Path, formats: tuple[str, ...], data_dir: Path):
    return generate_profile(
        profile,
        data_dir=data_dir,
        profile_dir=ROOT / "profiles",
        schema_dir=ROOT / "schemas",
        template_dir=ROOT / "templates",
        output_root=output,
        contact_path=None,
        formats=formats,
    )


def test_latex_generation_for_all_profiles(tmp_path: Path, example_data_dir: Path) -> None:
    for profile in PROFILE_NAMES:
        result = _generate(profile, tmp_path, ("latex",), example_data_dir)
        tex = tmp_path / profile / "cv.tex"
        assert tex in result.outputs
        text = tex.read_text(encoding="utf-8")
        assert "Example Student" in text
        assert "\\documentclass" in text


def test_docx_generation(tmp_path: Path, example_data_dir: Path) -> None:
    result = _generate("phd", tmp_path, ("docx",), example_data_dir)
    path = tmp_path / "phd" / "cv.docx"
    assert path in result.outputs
    document = Document(path)
    visible = "\n".join(paragraph.text for paragraph in document.paragraphs)
    assert "Example Student" in visible
    assert "Research Experience" in visible
    assert "Robust Evaluation" in visible
