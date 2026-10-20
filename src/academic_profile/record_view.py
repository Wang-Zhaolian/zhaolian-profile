"""Shared title search, numeric/date sort metadata, and stable record sorting."""

from __future__ import annotations

import re
from datetime import date
from typing import Any


_NUMBER = re.compile(
    r"^\s*([+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s*(%|分|学分|小时|分钟|天|月|年|次|人|项|篇|个|名|米|公里|元|kg|GB|MB)?\s*$",
    re.IGNORECASE,
)
_DATE = re.compile(r"^(\d{4})(?:[-/](\d{1,2})(?:[-/](\d{1,2}))?)?$")


def visible_fields(category: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted(
        (
            field for field in category.get("fields", [])
            if field.get("active", True) and not field.get("deleted")
            and not str(field.get("key", "")).endswith("_en")
            and "英文" not in str(field.get("label", ""))
        ),
        key=lambda field: (int(field.get("order", 0)), str(field.get("label", ""))),
    )


def _numeric(value: Any) -> float | None:
    if isinstance(value, bool) or value in (None, "", []):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = _NUMBER.fullmatch(str(value))
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", ""))
    except ValueError:
        return None


def _date(value: Any) -> date | None:
    if value in (None, "", []):
        return None
    match = _DATE.fullmatch(str(value).strip())
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2) or 1), int(match.group(3) or 1))
    except ValueError:
        return None


def sort_fields(category: dict[str, Any], records: list[dict[str, Any]]) -> list[dict[str, str]]:
    fields = visible_fields(category)
    result: list[dict[str, str]] = []
    for field in fields:
        kind = field.get("type", "text")
        if kind == "number":
            result.append({"key": field["key"], "label": field["label"], "type": "number"})
        elif kind == "date":
            result.append({"key": field["key"], "label": field["label"], "type": "date"})
        elif kind == "text" and any(_numeric(record.get(field["key"])) is not None for record in records):
            result.append({"key": field["key"], "label": field["label"], "type": "number"})
    return result


def filter_and_sort_records(
    records: list[dict[str, Any]], title_key: str, query: str,
    sort_type: str = "", direction: str = "asc", sort_key: str = "",
) -> list[dict[str, Any]]:
    query = query.strip().casefold()
    filtered = [record for record in records if not query or query in str(record.get(title_key) or "").casefold()]
    if not sort_key or sort_type not in {"number", "date"}:
        return filtered

    parse = _numeric if sort_type == "number" else _date
    valid: list[tuple[Any, dict[str, Any]]] = []
    missing: list[dict[str, Any]] = []
    for record in filtered:
        value = parse(record.get(sort_key))
        (valid if value is not None else missing).append((value, record) if value is not None else record)
    valid.sort(key=lambda pair: pair[0], reverse=direction == "desc")
    return [record for _, record in valid] + missing
