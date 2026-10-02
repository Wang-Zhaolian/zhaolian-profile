from __future__ import annotations

from typing import Any

from .dates import format_date, format_date_range


SECTION_TITLES_ZH = {
    "education": "教育经历",
    "research_interests": "研究兴趣",
    "research": "科研经历",
    "publications": "论文与手稿",
    "projects": "项目经历",
    "coursework": "相关课程",
    "awards": "荣誉与奖项",
    "competitions": "竞赛经历",
    "skills": "技能",
    "presentations": "学术汇报",
    "english": "英语成绩",
    "activities": "活动经历",
    "links": "相关链接",
}

PUBLICATION_STATUS_ZH = {
    "published": "已发表", "accepted": "已录用", "under_review": "审稿中",
    "submitted": "已投稿", "preprint": "预印本", "manuscript": "手稿",
}
GENERAL_STATUS_ZH = {
    "planned": "计划中", "active": "进行中", "completed": "已完成",
    "archived": "已归档", "idea": "构思中", "literature": "文献调研",
    "method": "方法设计", "experiment": "实验中", "writing": "写作中",
}


def _status_label(value: Any, language: str) -> str:
    text = str(value or "")
    if language == "zh":
        return PUBLICATION_STATUS_ZH.get(text, GENERAL_STATUS_ZH.get(text, text.replace("_", " ")))
    return text.replace("_", " ").title()


def localized(record: dict[str, Any], field: str, language: str) -> Any:
    if language == "zh":
        return record.get(f"{field}_zh") or record.get(field) or record.get(f"{field}_en")
    return record.get(f"{field}_en") or record.get(field) or record.get(f"{field}_zh")


def _join_nonempty(parts: list[Any], separator: str = ", ") -> str:
    return separator.join(str(part) for part in parts if part not in (None, "", []))


def _contains_cjk(value: Any) -> bool:
    if isinstance(value, dict):
        return any(_contains_cjk(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_cjk(item) for item in value)
    return any("\u3400" <= character <= "\u9fff" for character in str(value or ""))


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
        title = _join_nonempty([title, major], " · " if language == "zh" else " in ")

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
            _status_label(record.get("status"), language),
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
            f"{'成绩' if language == 'zh' else 'Grade'}: {record.get('grade')}" if record.get("grade") else None,
        ]
    elif category == "presentations":
        subtitle_parts = [
            localized(record, "event", language),
            localized(record, "location", language),
        ]
    elif category == "english":
        subtitle_parts = [
            f"{'分数' if language == 'zh' else 'Score'}: {record.get('score')}" if record.get("score") is not None else None,
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
            metadata.append(f"{'排名' if language == 'zh' else 'Rank'}: {record['rank']}/{record['rank_total']}")
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
            metadata.append(f"{'工具' if language == 'zh' else 'Tools'}: {_join_nonempty(stack)}")

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
    *,
    language: str | None = None,
    include_phone: bool = True,
) -> dict[str, Any]:
    language = language if language in {"zh", "en"} else profile.get("language", "zh")
    basics = data.get("basics", {})
    name = localized(basics, "name", language) or "Name Required"
    warnings: list[str] = []
    normalized_sections: list[dict[str, Any]] = []
    for section in selected_sections:
        if section["id"] == "research_interests":
            preferred_key = "research_interests_en" if language == "en" else "research_interests"
            fallback_key = "research_interests" if language == "en" else "research_interests_en"
            selected_interests = basics.get(preferred_key) or basics.get(fallback_key) or section["items"]
            items = [str(item) for item in selected_interests]
            if basics.get(fallback_key) and not basics.get(preferred_key):
                warnings.append(
                    f"研究兴趣缺少{'英文' if language == 'en' else '中文'}版本，预览使用了已有文本。"
                )
            elif language == "en" and _contains_cjk(items):
                warnings.append("研究兴趣缺少英文版本，预览使用了已有文本。")
        else:
            items = [normalize_entry(item, language) for item in section["items"]]
        normalized_sections.append(
            {
                "id": section["id"],
                "title": (
                    SECTION_TITLES_ZH.get(section["id"], section.get("title", section["id"]))
                    if language == "zh"
                    else section.get("title", section["id"].replace("_", " ").title())
                ),
                "items": items,
            }
        )

    contact_items = []
    labels = (
        {"email": "邮箱", "phone": "电话", "website": "个人网站", "github": "GitHub", "location": "所在地"}
        if language == "zh"
        else {"email": "Email", "phone": "Phone", "website": "Website", "github": "GitHub", "location": "Location"}
    )
    for key in ("email", "phone", "website", "github", "location"):
        if key == "phone" and not include_phone:
            continue
        value = contact.get(key)
        if value:
            contact_items.append({"label": labels[key], "value": str(value)})

    language_suffix = f"_{language}"
    other_suffix = "_en" if language == "zh" else "_zh"
    localized_fields = {
        "education": ("institution", "school", "degree", "major", "location", "cv_bullets"),
        "research": ("title", "institution", "advisor", "research_area", "research_question", "description", "cv_bullets"),
        "publications": ("title", "venue", "citation", "cv_bullets"),
        "projects": ("name", "type", "description", "cv_bullets"),
        "awards": ("name", "level", "organizer", "result", "description", "cv_bullets"),
        "competitions": ("name", "level", "organizer", "result", "description", "cv_bullets"),
        "coursework": ("course_name", "institution", "semester", "category", "topics"),
        "skills": ("category", "level", "items"),
        "presentations": ("title", "event", "location", "cv_bullets"),
        "english": ("test", "institution"),
        "activities": ("name", "organization", "role", "description", "cv_bullets"),
        "links": ("label",),
    }
    for section in selected_sections:
        for record in section["items"]:
            category = section["id"]
            for field_name in localized_fields.get(category, ()):
                if record.get(field_name + language_suffix):
                    continue
                fallback = record.get(field_name + other_suffix) or record.get(field_name)
                if fallback and (
                    bool(record.get(field_name + other_suffix))
                    or (language == "zh" and not _contains_cjk(fallback))
                    or (language == "en" and _contains_cjk(fallback))
                ):
                    warnings.append(
                        f"{localized(record, field_name, 'zh') or localized(record, field_name, 'en')}：缺少{'中文' if language == 'zh' else '英文'}版本，预览使用了已有文本。"
                    )
    if basics.get("name_" + other_suffix[1:]) and not basics.get("name" + language_suffix):
        warnings.append("姓名缺少所选语言版本，预览使用了已有姓名。")
    headline_fallback = basics.get("headline" + other_suffix) or basics.get("headline")
    if headline_fallback and not basics.get("headline" + language_suffix) and (
        basics.get("headline" + other_suffix)
        or (language == "zh" and not _contains_cjk(headline_fallback))
        or (language == "en" and _contains_cjk(headline_fallback))
    ):
        warnings.append("个人简介缺少所选语言版本，预览使用了已有文本。")

    return {
        "name": name,
        "headline": localized(basics, "headline", language) or "",
        "contact": contact_items,
        "sections": normalized_sections,
        "profile": profile["profile"],
        "language": language,
        "warnings": list(dict.fromkeys(warnings)),
    }
