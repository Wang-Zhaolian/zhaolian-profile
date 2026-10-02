from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable

import yaml

from .constants import DATA_CATEGORIES
from .loader import load_yaml

PREFIXES = {
    "education": "education",
    "research": "research",
    "publications": "paper",
    "projects": "project",
    "awards": "award",
    "competitions": "competition",
    "coursework": "course",
    "skills": "skill",
    "presentations": "presentation",
    "english": "english",
    "activities": "activity",
    "links": "link",
}

FIELDS = {
    "education": ("institution", "degree", "major", "start_date", "expected_graduation"),
    "research": ("title", "institution", "advisor", "start_date", "end_date", "status"),
    "publications": ("title", "authors (semicolon-separated)", "venue", "year", "status", "research_id"),
    "projects": ("name", "type", "start_date", "end_date", "status"),
    "awards": ("name", "level", "organizer", "date", "result"),
    "competitions": ("name", "level", "organizer", "date", "result", "project_id"),
    "coursework": ("course_name", "institution", "semester", "grade", "category", "level"),
    "skills": ("category", "items (semicolon-separated)", "last_used"),
    "presentations": ("title", "event", "date", "research_id"),
    "english": ("test", "score", "date"),
    "activities": ("name", "organization", "role", "start_date", "end_date"),
    "links": ("label", "url"),
}


def _next_id(records: list[dict[str, Any]], prefix: str) -> str:
    pattern = re.compile(rf"^{re.escape(prefix)}_(\d+)$")
    numbers = [int(match.group(1)) for item in records if (match := pattern.match(str(item.get("id", ""))))]
    return f"{prefix}_{max(numbers, default=0) + 1:03d}"


def add_record(
    category: str,
    data_dir: Path,
    *,
    input_fn: Callable[[str], str] = input,
) -> str:
    if category not in DATA_CATEGORIES:
        raise ValueError(f"Unknown category {category!r}")
    path = data_dir / f"{category}.yaml"
    document = load_yaml(path)
    records = document.setdefault("records", [])
    record: dict[str, Any] = {"id": _next_id(records, PREFIXES[category])}
    for prompt in FIELDS[category]:
        field = prompt.split(" ", 1)[0]
        value = input_fn(f"{prompt}: ").strip()
        if not value:
            continue
        if "semicolon-separated" in prompt:
            record[field] = [part.strip() for part in value.split(";") if part.strip()]
        elif field in {"year"} and value.isdigit():
            record[field] = int(value)
        elif field == "score":
            record[field] = float(value) if "." in value else int(value)
        else:
            record[field] = value
    record.setdefault("record_state", "draft")
    record.setdefault("cv_eligible", False)
    record.setdefault("priority", 3)
    record.setdefault("tags", [])
    records.append(record)
    path.write_text(
        yaml.safe_dump(document, sort_keys=False, allow_unicode=True, width=100),
        encoding="utf-8",
        newline="\n",
    )
    return record["id"]
