from __future__ import annotations

import re
from datetime import date

DATE_PATTERN = re.compile(r"^\d{4}-(?:0[1-9]|1[0-2])(?:-(?:0[1-9]|[12]\d|3[01]))?$")
MONTHS_EN = (
    "",
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)


def validate_date_string(value: str) -> bool:
    if not isinstance(value, str) or not DATE_PATTERN.fullmatch(value):
        return False
    try:
        parts = [int(part) for part in value.split("-")]
        if len(parts) == 2:
            date(parts[0], parts[1], 1)
        else:
            date(parts[0], parts[1], parts[2])
    except ValueError:
        return False
    return True


def date_key(value: str | int | None, *, present_high: bool = False) -> tuple[int, int, int]:
    if not value or str(value).lower() == "present":
        return (9999, 12, 31) if present_high else (0, 0, 0)
    parts = [int(part) for part in str(value).split("-")]
    if len(parts) == 1:
        return (parts[0], 1, 1)
    return (parts[0], parts[1], parts[2] if len(parts) == 3 else 1)


def format_date(value: str | None, language: str = "en") -> str:
    if not value or str(value).lower() == "present":
        return "至今" if language == "zh" else "Present"
    if not validate_date_string(value):
        return str(value)
    parts = [int(part) for part in value.split("-")]
    year, month = parts[0], parts[1]
    if language == "zh":
        return f"{year}年{month}月"
    return f"{MONTHS_EN[month]} {year}"


def format_date_range(
    start: str | None,
    end: str | None,
    *,
    language: str = "en",
    ongoing: bool = False,
) -> str:
    left = format_date(start, language)
    right = format_date(None if ongoing else end, language)
    if not left:
        return right
    if not right:
        return left
    separator = " - "
    return f"{left}{separator}{right}"
