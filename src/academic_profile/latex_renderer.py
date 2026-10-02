from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

LATEX_REPLACEMENTS = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}
LATEX_PATTERN = re.compile("|".join(re.escape(key) for key in LATEX_REPLACEMENTS))


def latex_escape(value: Any) -> str:
    return LATEX_PATTERN.sub(lambda match: LATEX_REPLACEMENTS[match.group()], str(value))


def render_latex(context: dict[str, Any], template_dir: Path, output_path: Path) -> Path:
    environment = Environment(
        loader=FileSystemLoader(str(template_dir)),
        undefined=StrictUndefined,
        autoescape=False,
        block_start_string="((*",
        block_end_string="*))",
        variable_start_string="((=",
        variable_end_string="=))",
        comment_start_string="((#",
        comment_end_string="#))",
        trim_blocks=True,
        lstrip_blocks=True,
    )
    environment.filters["latex"] = latex_escape
    template = environment.get_template("cv.tex.j2")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(template.render(**context), encoding="utf-8", newline="\n")
    return output_path

