from __future__ import annotations

from copy import deepcopy
from typing import Any

from .dates import date_key


def _is_archived(record: dict[str, Any]) -> bool:
    return (
        record.get("record_state", "ready") != "ready"
        or bool(record.get("archived"))
        or record.get("status") == "archived"
    )


def _priority(record: dict[str, Any]) -> int:
    value = record.get("priority", 999)
    return value if isinstance(value, int) else 999


def _eligible(
    record: dict[str, Any],
    profile_name: str,
    section: dict[str, Any],
    defaults: dict[str, Any],
) -> bool:
    if _is_archived(record):
        return False

    override = record.get("include_for", {}).get(profile_name)
    if override is False:
        return False
    if override is True:
        return True

    if not record.get("cv_eligible", False):
        return False

    max_priority = section.get(
        "max_priority", defaults.get("max_priority", 3)
    )
    if _priority(record) > max_priority:
        return False

    tags = set(record.get("tags", []))
    required_any = set(section.get("include_tags_any", []))
    excluded = set(defaults.get("exclude_tags", [])) | set(
        section.get("exclude_tags", [])
    )
    if required_any and not tags.intersection(required_any):
        return False
    if tags.intersection(excluded):
        return False
    return True


def _sort_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records = sorted(
        records,
        key=lambda item: date_key(
            item.get("end_date") or item.get("date") or item.get("year"),
            present_high=True,
        ),
        reverse=True,
    )
    return sorted(records, key=_priority)


def select_profile(
    data: dict[str, Any], profile: dict[str, Any]
) -> list[dict[str, Any]]:
    """Select records in display order without mutating the master data."""
    profile_name = profile["profile"]
    defaults = profile.get("selection", {})
    selected_sections: list[dict[str, Any]] = []

    for section in profile.get("sections", []):
        section_id = section["id"]
        if section_id == "research_interests":
            interests = data.get("basics", {}).get("research_interests", [])
            if interests:
                selected_sections.append(
                    {**deepcopy(section), "items": list(interests)}
                )
            continue

        categories = section.get("categories", [section_id])
        candidates: list[dict[str, Any]] = []
        for category in categories:
            for original in data.get(category, []):
                record = deepcopy(original)
                record["_category"] = category
                if _eligible(record, profile_name, section, defaults):
                    candidates.append(record)

        candidates = _sort_records(candidates)
        max_items = section.get("max_items")
        if isinstance(max_items, int) and max_items >= 0:
            candidates = candidates[:max_items]
        if candidates:
            selected_sections.append({**deepcopy(section), "items": candidates})

    return selected_sections
