from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def find_latex_engine() -> str | None:
    for engine in ("xelatex", "lualatex", "pdflatex"):
        if shutil.which(engine):
            return engine
    return None


def build_pdf(tex_path: Path) -> tuple[Path | None, str]:
    engine = find_latex_engine()
    if engine is None:
        return None, (
            "No LaTeX engine found. Install TeX Live or MiKTeX with XeLaTeX, "
            "then run the generate command again."
        )
    command = [
        engine,
        "-interaction=nonstopmode",
        "-halt-on-error",
        tex_path.name,
    ]
    for _ in range(2):
        completed = subprocess.run(
            command,
            cwd=tex_path.parent,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if completed.returncode != 0:
            tail = "\n".join((completed.stdout + completed.stderr).splitlines()[-30:])
            return None, f"{engine} failed:\n{tail}"
    pdf_path = tex_path.with_suffix(".pdf")
    if not pdf_path.exists() or pdf_path.stat().st_size == 0:
        return None, f"{engine} returned success but did not create {pdf_path.name}"
    return pdf_path, f"Built with {engine}"

