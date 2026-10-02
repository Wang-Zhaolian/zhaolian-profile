from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .constants import DATA_CATEGORIES, PUBLICATION_STATUSES
from .loader import load_master_data
from .validation import ValidationIssue

MISSPELLINGS = {
    "teh": "the",
    "recieve": "receive",
    "seperate": "separate",
    "occured": "occurred",
}


def _label(record: dict[str, Any], category: str, index: int) -> str:
    return f"{category}[{record.get('id', index)}]"


def lint_repository(data_dir: Path, max_bullet_length: int = 220) -> list[ValidationIssue]:
    data = load_master_data(data_dir)
    issues: list[ValidationIssue] = []
    seen_titles: dict[tuple[str, str], str] = {}

    for category in DATA_CATEGORIES:
        for index, record in enumerate(data[category]):
            if record.get("record_state", "ready") == "draft":
                continue
            location = _label(record, category, index)
            title = next(
                (
                    record.get(field)
                    for field in ("title_en", "title", "name_en", "name", "course_name_en", "course_name")
                    if record.get(field)
                ),
                None,
            )
            if title:
                normalized = re.sub(r"\W+", "", str(title).lower())
                key = (category, normalized)
                if key in seen_titles:
                    issues.append(
                        ValidationIssue("warning", "possible_duplicate", location, f"Similar title already appears at {seen_titles[key]}")
                    )
                seen_titles[key] = location

            for field in ("cv_bullets", "cv_bullets_en", "cv_bullets_zh"):
                bullets = record.get(field, [])
                if isinstance(bullets, str):
                    bullets = [bullets]
                for bullet_index, bullet in enumerate(bullets):
                    text = str(bullet)
                    if len(text) > max_bullet_length:
                        issues.append(
                            ValidationIssue(
                                "warning", "long_bullet", f"{location}.{field}[{bullet_index}]",
                                f"Bullet has {len(text)} characters; recommended maximum is {max_bullet_length}",
                            )
                        )
                    if "  " in text:
                        issues.append(
                            ValidationIssue("warning", "double_space", f"{location}.{field}[{bullet_index}]", "Contains repeated spaces")
                        )
                    words = set(re.findall(r"[A-Za-z]+", text.lower()))
                    for wrong, right in MISSPELLINGS.items():
                        if wrong in words:
                            issues.append(
                                ValidationIssue("warning", "spelling", f"{location}.{field}[{bullet_index}]", f"Possible spelling error: {wrong!r}; consider {right!r}")
                            )

            if category == "research":
                if not record.get("my_contribution") and not record.get("cv_bullets") and not record.get("cv_bullets_en"):
                    issues.append(
                        ValidationIssue("warning", "missing_contribution", location, "Research entry has no personal contribution or CV bullets")
                    )
                if not record.get("institution"):
                    issues.append(
                        ValidationIssue("warning", "missing_institution", location, "Research entry has no institution")
                    )
            if category in {"education", "coursework"} and not record.get("institution"):
                issues.append(
                    ValidationIssue("warning", "missing_institution", location, f"{category.title()} entry has no institution")
                )
            if category == "publications" and record.get("status") not in PUBLICATION_STATUSES:
                issues.append(
                    ValidationIssue("warning", "publication_status", location, "Publication status is not allowed")
                )

    return issues
