"""Private AI source notes and reviewable, fact-grounded record proposals.

This module deliberately does not use a document-export context: that context
contains private contact information and omits drafts. The only note admitted
to an AI request is the new note passed explicitly to ``build_context``.
"""

from __future__ import annotations

import json
import hashlib
import os
import re
import shutil
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from .dates import validate_date_string
from .file_inputs import save_attachments
from .loader import load_master_data
from .categories import category_map, field_definitions


MAX_NOTE_CHARS = 20_000
MAX_PROPOSAL_JSON_CHARS = 250_000
DEFAULT_CONTEXT_CHARS = 60_000
_NOTE_ID = re.compile(r"^[0-9a-f]{32}$")
_EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}(?![\w.-])")
_PHONE = re.compile(r"(?<!\d)(?:\+?86[-\s]?)?1[3-9]\d[-\s]?\d{4}[-\s]?\d{4}(?!\d)")
_WINDOWS_PATH = re.compile(r"(?<![\w])(?:[A-Za-z]:[\\/]|\\\\)[^\s\"'<>，；,;]+")
_UNIX_PATH = re.compile(r"(?<![\w:])/(?:Users|home|mnt|Volumes|tmp|var|etc)/[^\s\"'<>，；,;]+")
_FILE_URI = re.compile(r"file://[^\s\"'<>，；,;]+", re.IGNORECASE)
_RELATION_PREFIXES = ("relation:", "relation_one:")
_EXCLUDED_FIELDS = {"evidence"}
_REDACTION = "[已隐藏私人信息]"
_NOTE_LOCKS: dict[str, threading.RLock] = {}
_NOTE_LOCKS_GUARD = threading.Lock()


def _note_lock(note_id: str) -> threading.RLock:
    with _NOTE_LOCKS_GUARD:
        return _NOTE_LOCKS.setdefault(note_id, threading.RLock())


def _note_directory(home: Path) -> Path:
    return Path(home) / "private" / "ai_notes"


def _note_path(home: Path, note_id: str) -> Path:
    if not isinstance(note_id, str) or not _NOTE_ID.fullmatch(note_id):
        raise ValueError("笔记编号无效。")
    return _note_directory(home) / f"{note_id}.json"


def _atomic_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    descriptor, temporary = tempfile.mkstemp(prefix="note-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _note_metadata(note: dict[str, Any]) -> dict[str, Any]:
    note_text = str(note["text"])
    attachments = [
        {key: attachment[key] for key in ("id", "name", "size", "mime_type", "extension") if key in attachment}
        for attachment in note.get("attachments", []) if isinstance(attachment, dict)
    ]
    return {
        "id": note["id"],
        "created_at": note["created_at"],
        "preview": note_text.replace("\n", " ").strip()[:120] or (f"包含 {len(attachments)} 个附件" if attachments else "空素材"),
        "length": len(note_text),
        "attachments": attachments,
        "completed": bool(note.get("completed", False)),
        "pending_candidates": sum(
            candidate.get("status", "pending") == "pending"
            for batch in note.get("batches", []) if isinstance(batch, dict)
            for candidate in batch.get("candidates", []) if isinstance(candidate, dict)
        ),
        "batches": [
            {"id": batch.get("id"), "created_at": batch.get("created_at"),
             "candidate_count": len(batch.get("candidates", [])),
             "pending_candidates": sum(item.get("status", "pending") == "pending" for item in batch.get("candidates", []))}
            for batch in note.get("batches", []) if isinstance(batch, dict)
        ],
    }


def save_note(home: Path, text: str, uploads: list[tuple[str, bytes]] | None = None) -> dict[str, Any]:
    """Save a raw note only under ``private/ai_notes`` and return it."""
    uploads = uploads or []
    if not isinstance(text, str) or (not text.strip() and not uploads):
        raise ValueError("请先输入文字，或添加图片、文档。")
    if len(text) > MAX_NOTE_CHARS:
        raise ValueError(f"笔记过长，请拆分为不超过 {MAX_NOTE_CHARS} 字的几段。")
    note_id = uuid.uuid4().hex
    attachments = save_attachments(home, note_id, uploads) if uploads else []
    note = {
        "id": note_id,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "text": text,
        "attachments": attachments,
        "completed": False,
        "batches": [],
    }
    try:
        _atomic_json(_note_path(home, note["id"]), note)
    except BaseException:
        shutil.rmtree(Path(home) / "private" / "ai_notes" / "attachments" / note_id, ignore_errors=True)
        raise
    return {**_note_metadata(note), "text": text}


def get_note(home: Path, note_id: str, *, include_storage: bool = False) -> dict[str, Any]:
    """Read one locally saved note; IDs cannot address any other file."""
    path = _note_path(home, note_id)
    note = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(note, dict) or note.get("id") != note_id or not isinstance(note.get("text"), str):
        raise ValueError("笔记内容损坏，请检查本机文件。")
    attachments = note.get("attachments", [])
    if not isinstance(attachments, list):
        raise ValueError("笔记附件信息损坏，请检查本机文件。")
    if include_storage:
        metadata = dict(note)
        metadata.setdefault("attachments", [])
    else:
        metadata = {**_note_metadata(note), "text": note["text"]}
    return metadata


def list_notes(home: Path) -> list[dict[str, Any]]:
    """List metadata only; old source text is never loaded into AI context."""
    directory = _note_directory(home)
    if not directory.is_dir():
        return []
    notes: list[dict[str, Any]] = []
    for path in directory.glob("*.json"):
        if not _NOTE_ID.fullmatch(path.stem):
            continue
        try:
            note = get_note(home, path.stem)
        except (OSError, ValueError, KeyError):
            continue
        if note["completed"]:
            continue
        # Read old completed batches consistently as well, without rewriting
        # the user's historical notes just to render a list.
        stored = get_note(home, path.stem, include_storage=True)
        if _fully_processed(stored):
            continue
        notes.append({key: note[key] for key in ("id", "created_at", "preview", "length", "attachments", "completed", "pending_candidates", "batches")})
    return sorted(notes, key=lambda item: (item["created_at"], item["id"]), reverse=True)


def add_proposal_batch(
    home: Path, note_id: str, candidates: list[dict[str, Any]], attachment_ids: list[str]
) -> dict[str, Any]:
    with _note_lock(note_id):
        note = get_note(home, note_id, include_storage=True)
        batch = {
            "id": uuid.uuid4().hex,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "attachment_ids": list(attachment_ids),
            "candidates": [
                {**item, "status": "pending", "operation_id": uuid.uuid4().hex}
                for item in candidates
            ],
        }
        note.setdefault("batches", []).append(batch)
        note["completed"] = False
        _atomic_json(_note_path(home, note_id), note)
        return batch


def _fully_processed(note: dict[str, Any]) -> bool:
    batches = note.get("batches", [])
    candidates = [candidate for batch in batches for candidate in batch.get("candidates", [])]
    covered = {item for batch in batches if batch.get("candidates") for item in batch.get("attachment_ids", [])}
    return bool(candidates) and all(candidate.get("status") in {"adopted", "discarded"} for candidate in candidates) and all(item["id"] in covered for item in note.get("attachments", []))


def update_candidate(
    home: Path, note_id: str, batch_id: str, operation_id: str,
    status: str, fields: dict[str, Any] | None = None, category: str | None = None,
) -> dict[str, Any]:
    if status not in {"pending", "adopted", "discarded"}:
        raise ValueError("候选处理状态不正确。")
    with _note_lock(note_id):
        note = get_note(home, note_id, include_storage=True)
        for batch in note.get("batches", []):
            if batch.get("id") != batch_id:
                continue
            for candidate in batch.get("candidates", []):
                if candidate.get("operation_id") != operation_id:
                    continue
                if candidate.get("status") == "pending":
                    if category is not None:
                        if category not in category_map(home):
                            raise ValueError("请选择当前可用的分类。")
                        candidate["category"] = category
                    candidate["status"] = status
                    if fields is not None:
                        candidate["fields"] = fields
                    candidate["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
                    if _fully_processed(note):
                        note["completed"] = True
                    _atomic_json(_note_path(home, note_id), note)
                return _note_metadata(note)
        raise ValueError("没有找到这条待处理的 AI 候选。")


def set_note_completed(home: Path, note_id: str, completed: bool) -> dict[str, Any]:
    with _note_lock(note_id):
        note = get_note(home, note_id, include_storage=True)
        note["completed"] = bool(completed)
        note["completed_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds") if completed else None
        _atomic_json(_note_path(home, note_id), note)
        return _note_metadata(note)


def _scrub_text(text: str) -> str:
    result = text
    for pattern in (_FILE_URI, _WINDOWS_PATH, _UNIX_PATH, _EMAIL, _PHONE):
        result = pattern.sub(_REDACTION, result)
    return result


def _allowed_fields(home: Path, category: str) -> dict[str, str]:
    """Derive fields from the live UI definition; never trust model field names."""
    allowed: dict[str, str] = {}
    for field in field_definitions(home, category):
        key, kind = field["key"], field["type"]
        if key.endswith("_en") or "英文" in field.get("label", ""):
            continue
        if kind == "select":
            kind = "select:" + ",".join(field.get("options", []))
        elif kind == "multiselect":
            kind = "multiselect:" + ",".join(field.get("options", []))
        if key in _EXCLUDED_FIELDS or kind.startswith(_RELATION_PREFIXES):
            continue
        # Linked profile URLs may be personal contact channels, unlike an
        # academic paper or project URL. Keep the category but not its URL.
        if category == "links" and key == "url":
            continue
        allowed[key] = kind
    return allowed


def _safe_value(value: Any) -> Any:
    if isinstance(value, str):
        return _scrub_text(value)
    if isinstance(value, bool) or value is None or isinstance(value, (int, float)):
        return value
    if isinstance(value, list):
        return [item for original in value if (item := _safe_value(original)) not in (None, "", [])]
    if isinstance(value, dict):
        return {
            _scrub_text(str(key)): item
            for key, original in value.items()
            if (item := _safe_value(original)) not in (None, "", [])
        }
    return None


def _safe_record(home: Path, category: str, record: dict[str, Any]) -> dict[str, Any]:
    allowed = _allowed_fields(home, category)
    fields = {
        key: value
        for key in allowed
        if key in record and (value := _safe_value(record[key])) not in (None, "", [])
    }
    return {
        "category": category,
        "id": str(record.get("id", "")),
        "title_field": category_map(home, include_archived=True)[category].get("title_field", "title"),
        "record_state": record.get("record_state", "ready"),
        "archived": bool(record.get("archived", False)),
        "fields": fields,
    }


def _all_records(home: Path, data: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    data = data if data is not None else load_master_data(Path(home) / "data")
    categories = category_map(home)
    return [
        _safe_record(home, category, record)
        for category in categories
        for record in data.get(category, [])
        if isinstance(record, dict)
    ]


def _safe_profile(basics: dict[str, Any]) -> dict[str, Any]:
    """Only academic basics belong in AI context; contacts live elsewhere."""
    fields = ("name_zh", "headline_zh", "research_interests")
    return {
        key: value
        for key in fields
        if key in basics and (value := _safe_value(basics[key])) not in (None, "", [])
    }


def _synopsis(record: dict[str, Any]) -> dict[str, Any]:
    fields = record["fields"]
    category = record["category"]
    title_field = record.get("title_field", "title")
    title = next(
        (fields[key] for key in (f"{title_field}_en", title_field, f"{title_field}_zh") if fields.get(key)),
        "未命名记录",
    )
    date = next((fields[key] for key in ("date", "start_date", "year", "semester") if fields.get(key)), "")
    return {
        "category": category,
        "id": record["id"],
        "record_state": record["record_state"],
        "title": str(title)[:120],
        "date": str(date)[:40],
    }


def _size(payload: dict[str, Any]) -> int:
    return len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def _relevance(record: dict[str, Any], note: str) -> float:
    summary = _synopsis(record)
    title = summary["title"].lower()
    note_lower = note.lower()
    if title and title != "未命名记录" and title in note_lower:
        return 100.0
    words = set(re.findall(r"[a-z][a-z0-9_-]{2,}|[\u4e00-\u9fff]{2,}", note_lower))
    record_words = set(re.findall(r"[a-z][a-z0-9_-]{2,}|[\u4e00-\u9fff]{2,}", title))
    return float(len(words & record_words))


def build_context(home: Path, note_text: str, *, max_chars: int = DEFAULT_CONTEXT_CHARS) -> dict[str, Any]:
    """Build private-safe context covering all categories, including drafts.

    In summary mode, every record remains in ``synopsis`` and only relevant
    records with room in the budget are repeated in full under ``records``.
    """
    if not isinstance(note_text, str) or not note_text.strip():
        raise ValueError("请先输入要整理的文字笔记。")
    if len(note_text) > MAX_NOTE_CHARS:
        raise ValueError(f"笔记过长，请拆分为不超过 {MAX_NOTE_CHARS} 字的几段。")
    if not isinstance(max_chars, int) or max_chars < 256:
        raise ValueError("AI 上下文大小设置无效。")
    cleaned_note = _scrub_text(note_text)
    data = load_master_data(Path(home) / "data")
    profile = _safe_profile(data["basics"])
    records = _all_records(home, data)
    base: dict[str, Any] = {
        "mode": "full",
        "record_count": len(records),
        "full_record_count": len(records),
        "note_text": cleaned_note,
        "profile": profile,
        "records": records,
        "synopsis": [],
    }
    if _size(base) <= max_chars:
        return base

    base.update(mode="summary", full_record_count=0, records=[], synopsis=[_synopsis(item) for item in records])
    if _size(base) > max_chars:
        raise ValueError("笔记或资料提纲超过模型输入上限，请缩短笔记或调高模型上下文容量。")
    ranked = sorted(records, key=lambda item: _relevance(item, cleaned_note), reverse=True)
    for record in ranked:
        base["records"].append(record)
        base["full_record_count"] += 1
        if _size(base) > max_chars:
            base["records"].pop()
            base["full_record_count"] -= 1
    return base


def _candidate_value(value: Any, kind: str) -> Any:
    if value is None or value == "" or value == []:
        return None
    if kind == "bool":
        return value if isinstance(value, bool) else None
    if kind == "number":
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, str) and re.fullmatch(r"\d{1,6}", value.strip()):
            return int(value.strip())
        return None
    if kind == "list":
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            return None
        return [cleaned for item in value if (cleaned := _scrub_text(item).strip())]
    if kind.startswith("multiselect:"):
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            return None
        allowed = {item.strip() for item in kind.split(":", 1)[1].split(",") if item.strip()}
        return [item.strip() for item in value if item.strip() in allowed]
    if kind == "map":
        if not isinstance(value, dict):
            return None
        return {
            _scrub_text(str(key)).strip(): _scrub_text(str(item)).strip()
            for key, item in value.items()
            if isinstance(item, (str, int, float)) and not isinstance(item, bool)
        }
    if not isinstance(value, str):
        return None
    cleaned = _scrub_text(value).strip()
    if not cleaned:
        return None
    if kind == "date" and not validate_date_string(cleaned):
        return None
    if kind.startswith("select:") and cleaned not in {item.strip() for item in kind.split(":", 1)[1].split(",")}:
        return None
    if kind == "url" and not re.fullmatch(r"https?://[^\s]+", cleaned, re.IGNORECASE):
        return None
    return cleaned


def _duplicate_hints(
    home: Path, category: str, fields: dict[str, Any], existing: list[dict[str, Any]],
    revision: str,
) -> list[dict[str, Any]]:
    title_field = category_map(home, include_archived=True)[category].get("title_field", "title")
    proposed_title = next(
        (fields.get(key) for key in (f"{title_field}_en", title_field, f"{title_field}_zh") if fields.get(key)),
        None,
    )
    if not isinstance(proposed_title, str):
        return []
    comparison_fields = {
        "education": ("institution", "major"),
        "coursework": ("institution",),
        "awards": ("organizer",),
        "competitions": ("organizer",),
    }.get(category, ())
    def fingerprint(values: dict[str, Any]) -> str:
        parts = [str(values.get(title_field) or values.get(f"{title_field}_en") or values.get(f"{title_field}_zh") or "")]
        parts.extend(str(values.get(key, "")) for key in comparison_fields)
        return re.sub(r"[^\w\u4e00-\u9fff]+", "", " ".join(parts).lower())
    proposed = fingerprint(fields)
    if not proposed:
        return []
    hints = []
    for record in existing:
        if record["category"] != category:
            continue
        title = _synopsis(record)["title"]
        current = fingerprint(record["fields"])
        if not current:
            continue
        score = SequenceMatcher(None, proposed, current).ratio()
        if score >= 0.72:
            hints.append({
                "id": record["id"], "category": category, "title": title,
                "score": round(score, 2), "revision": revision,
            })
    return sorted(hints, key=lambda item: item["score"], reverse=True)[:5]


def parse_proposals(
    home: Path,
    text: str,
    note_text: str,
    attachments: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Parse untrusted model JSON into reviewable, allowlisted candidates.

    Supported model shape: ``{"candidates": [{"category": ..., "fields": ...,
    "source_excerpt": ...}]}``, or a bare candidate array. Any model-supplied
    duplicate IDs are ignored; duplicates are recomputed from local records.
    """
    if not isinstance(text, str) or len(text) > MAX_PROPOSAL_JSON_CHARS:
        raise ValueError("AI 返回内容过长或格式不正确。")
    cleaned = text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned, re.IGNORECASE)
    if fenced:
        cleaned = fenced.group(1)
    try:
        parsed = json.loads(cleaned)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError("AI 返回内容不是有效 JSON，请重试。") from exc
    candidates = parsed.get("candidates") if isinstance(parsed, dict) else parsed
    if not isinstance(candidates, list) or len(candidates) > 50:
        raise ValueError("AI 返回的候选记录格式或数量不正确。")
    active_categories = list(category_map(home))
    try:
        revisions_before = {
            category_id: hashlib.sha256((Path(home) / "data" / f"{category_id}.yaml").read_bytes()).hexdigest()
            for category_id in active_categories
        }
        existing = _all_records(home)
        revisions_after = {
            category_id: hashlib.sha256((Path(home) / "data" / f"{category_id}.yaml").read_bytes()).hexdigest()
            for category_id in active_categories
        }
    except OSError:
        raise ValueError("履历资料正在变化或有分类文件无法读取，请刷新后重新整理。") from None
    if revisions_before != revisions_after:
        raise ValueError("AI 整理期间履历资料被其他窗口修改，请重新整理后审核。")
    output: list[dict[str, Any]] = []
    allowed_attachments = {
        str(item.get("id")): str(item.get("name", "附件"))
        for item in (attachments or []) if isinstance(item, dict) and item.get("id")
    }
    normalized_note = " ".join(_scrub_text(note_text).split()) if isinstance(note_text, str) else ""
    for raw in candidates:
        available_categories = category_map(home)
        if not isinstance(raw, dict) or raw.get("category") not in available_categories:
            continue
        category = raw["category"]
        raw_fields = raw.get("fields")
        if not isinstance(raw_fields, dict):
            continue
        allowed = _allowed_fields(home, category)
        fields: dict[str, Any] = {}
        warnings: list[str] = []
        for key, value in raw_fields.items():
            if key not in allowed:
                warnings.append(f"已忽略不可录入字段：{key}。")
                continue
            valid = _candidate_value(value, allowed[key])
            if valid is None or valid == [] or valid == {}:
                warnings.append(f"已忽略格式不正确或空白的字段：{key}。")
                continue
            fields[key] = valid
            if valid != value:
                warnings.append(f"字段 {key} 已清理或标准化，请核对。")
        if not fields:
            continue
        excerpt = raw.get("source_excerpt")
        excerpt = _scrub_text(excerpt.strip()) if isinstance(excerpt, str) else ""
        if excerpt and " ".join(excerpt.split()) not in normalized_note:
            excerpt = ""
            warnings.append("原文片段无法在本次笔记中核对，请自行检查。")
        if not excerpt:
            if normalized_note:
                warnings.append("未找到可核对的原文片段，请自行检查。")
        raw_sources = raw.get("source_references", [])
        source_references: list[dict[str, Any]] = []
        if isinstance(raw_sources, list):
            for source in raw_sources[:10]:
                if not isinstance(source, dict):
                    continue
                attachment_id = str(source.get("attachment_id", ""))
                if attachment_id not in allowed_attachments:
                    continue
                reference: dict[str, Any] = {
                    "attachment_id": attachment_id,
                    "filename": allowed_attachments[attachment_id],
                }
                page = source.get("page")
                if isinstance(page, int) and not isinstance(page, bool) and page > 0:
                    reference["page"] = page
                source_excerpt = source.get("excerpt")
                if isinstance(source_excerpt, str) and source_excerpt.strip():
                    reference["excerpt"] = _scrub_text(source_excerpt.strip())[:1000]
                source_references.append(reference)
        if source_references:
            warnings.append("附件内容由 ChatGPT 识读，尚未人工核实；请对照原始文件检查。")
        elif not excerpt and not normalized_note:
            warnings.append("未提供可核对的来源引用，请对照原始附件检查。")
        output.append({
            "category": category,
            "fields": fields,
            "source_excerpt": excerpt,
            "source_references": source_references,
            "possible_duplicates": _duplicate_hints(home, category, fields, existing, revisions_after.get(category, "")),
            "warnings": list(dict.fromkeys(warnings)),
        })
    return output
