from __future__ import annotations

from typing import Any

from .dates import format_date, format_date_range


def localized(record: dict[str, Any], field: str, language: str) -> Any:
    if language == "zh":
        return record.get(f"{field}_zh") or record.get(f"{field}_en") or record.get(field)
    return record.get(f"{field}_en") or record.get(field) or record.get(f"{field}_zh")


def _join_nonempty(parts: list[Any], separator: str = ", ") -> str:
    return separator.join(str(part) for part in parts if part not in (None, "", []))


def normalize_entry(record: dict[str, Any], language: str = "en") -> dict[str, Any]:
    category = record.get("_category", "")
    title_field = {
        "education": "degree",
        "research": "title",
        "publications": "title",
        "projects": "name",
        "awards": "name",
        "competitions": "name",
        "coursework": "course_name",
        "skills": "category",
        "presentations": "title",
        "english": "test",
        "activities": "name",
        "links": "label",
    }.get(category, "title")

    title = localized(record, title_field, language) or record.get("id", "Untitled")
    if category == "education":
        major = localized(record, "major", language)
        title = _join_nonempty([title, major], " in ")

    subtitle_parts: list[Any] = []
    if category == "education":
        subtitle_parts = [
            localized(record, "institution", language),
            localized(record, "school", language),
            localized(record, "location", language),
        ]
    elif category == "research":
        advisor = localized(record, "advisor", language)
        subtitle_parts = [
            localized(record, "institution", language),
            f"Advisor: {advisor}" if advisor else None,
        ]
    elif category == "publications":
        subtitle_parts = [
            _join_nonempty(record.get("authors", [])),
            localized(record, "venue", language),
            str(record.get("status", "")).replace("_", " ").title(),
        ]
    elif category == "projects":
        subtitle_parts = [localized(record, "type", language), record.get("repository")]
    elif category in {"awards", "competitions"}:
        subtitle_parts = [
            localized(record, "organizer", language),
            localized(record, "level", language),
            localized(record, "result", language),
        ]
    elif category == "coursework":
        subtitle_parts = [
            localized(record, "institution", language),
            localized(record, "semester", language),
            f"Grade: {record.get('grade')}" if record.get("grade") else None,
        ]
    elif category == "presentations":
        subtitle_parts = [
            localized(record, "event", language),
            localized(record, "location", language),
        ]
    elif category == "english":
        subtitle_parts = [
            f"Score: {record.get('score')}" if record.get("score") is not None else None,
            localized(record, "institution", language),
        ]
    elif category == "activities":
        subtitle_parts = [
            localized(record, "organization", language),
            localized(record, "role", language),
        ]
    elif category == "links":
        subtitle_parts = [record.get("url")]

    if record.get("start_date"):
        end = record.get("end_date") or record.get("expected_graduation")
        ongoing = record.get("status") == "active" or not end
        date_text = format_date_range(
            record.get("start_date"), end, language=language, ongoing=ongoing
        )
    elif record.get("date"):
        date_text = format_date(record.get("date"), language)
    elif record.get("year"):
        date_text = str(record.get("year"))
    else:
        date_text = ""

    bullets = localized(record, "cv_bullets", language) or []
    if isinstance(bullets, str):
        bullets = [bullets]

    metadata: list[str] = []
    if category == "education":
        if record.get("gpa") is not None:
            metadata.append(f"GPA: {record['gpa']}/{record.get('gpa_scale', '')}".rstrip("/"))
        if record.get("rank") is not None and record.get("rank_total") is not None:
            metadata.append(f"Rank: {record['rank']}/{record['rank_total']}")
        metadata.extend(record.get("honors", []))
    elif category == "skills":
        values = record.get("items", [])
        metadata.append(_join_nonempty(values))
    elif category == "publications":
        for label, field in (("DOI", "doi"), ("arXiv", "arxiv")):
            if record.get(field):
                metadata.append(f"{label}: {record[field]}")
    elif category == "projects":
        stack = record.get("tech_stack", [])
        if stack:
            metadata.append(f"Tools: {_join_nonempty(stack)}")

    return {
        "id": record.get("id", ""),
        "category": category,
        "title": str(title),
        "subtitle": _join_nonempty(subtitle_parts, " | "),
        "date": date_text,
        "bullets": [str(item) for item in bullets if str(item).strip()],
        "metadata": metadata,
        "url": record.get("url") or record.get("repository") or record.get("doi"),
        "raw": record,
    }


def build_document_context(
    data: dict[str, Any],
    profile: dict[str, Any],
    selected_sections: list[dict[str, Any]],
    contact: dict[str, Any],
) -> dict[str, Any]:
    language = profile.get("language", "en")
    basics = data.get("basics", {})
    name = localized(basics, "name", language) or "Name Required"
    normalized_sections: list[dict[str, Any]] = []
    for section in selected_sections:
        if section["id"] == "research_interests":
            items = [str(item) for item in section["items"]]
        else:
            items = [normalize_entry(item, language) for item in section["items"]]
        normalized_sections.append(
            {
                "id": section["id"],
                "title": section.get("title", section["id"].replace("_", " ").title()),
                "items": items,
            }
        )

    contact_items = []
    for key, label in (
        ("email", "Email"),
        ("website", "Website"),
        ("github", "GitHub"),
        ("location", "Location"),
    ):
        value = contact.get(key)
        if value:
            contact_items.append({"label": label, "value": str(value)})

    return {
        "name": name,
        "headline": localized(basics, "headline", language) or "",
        "contact": contact_items,
        "sections": normalized_sections,
        "profile": profile["profile"],
        "language": language,
    }

