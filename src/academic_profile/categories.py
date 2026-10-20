"""Editable, versioned category and form-field registry."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
import uuid
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from .ui_fields import CATEGORIES, FIELD_DEFINITIONS, READY_REQUIRED


_CATEGORY_ID = re.compile(r"^[a-z][a-z0-9_]{1,62}$")
_FIELD_KEY = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_FIELD_TYPES = {"text", "textarea", "date", "number", "list", "bool", "url", "map"}
_FIELD_TYPES_WITH_OPTIONS = {"select", "multiselect"}


def _builtins() -> list[dict[str, Any]]:
    result = []
    for order, category in enumerate(CATEGORIES):
        fields = []
        for field_order, definition in enumerate(FIELD_DEFINITIONS[category["id"]]):
            key, label, field_type, advanced = definition
            if key in {"cv_bullets", "cv_bullets_zh"}:
                label = "经历要点"
            options: list[str] | None = None
            if field_type.startswith("select:"):
                field_type, raw = "select", field_type.split(":", 1)[1]
                options = [item.strip() for item in raw.split(",") if item.strip()]
            fields.append({
                "key": key, "label": label, "type": field_type,
                "options": options or [], "required": field_type != "date" and key in READY_REQUIRED[category["id"]],
                "advanced": bool(advanced), "active": True, "order": field_order,
            })
        result.append({
            **category, "order": order, "archived": False, "builtin": True,
            "fields": fields,
        })
    return result


def default_registry() -> dict[str, Any]:
    return {"version": 1, "categories": _builtins()}


def registry_path(home: Path) -> Path:
    return Path(home) / "data" / "categories.yaml"


def registry_revision(home: Path) -> str:
    path = registry_path(home)
    if not path.exists():
        return "defaults-v1"
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_registry(home: Path) -> dict[str, Any]:
    path = registry_path(home)
    if not path.exists():
        return default_registry()
    try:
        return deepcopy(_parse_registry(path.read_bytes()))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError("分类配置无法读取，请恢复本机备份或检查 data/categories.yaml。") from exc


@lru_cache(maxsize=16)
def _parse_registry(payload: bytes) -> dict[str, Any]:
    """Parse unchanged settings once; callers always receive an isolated copy."""
    value = yaml.safe_load(payload.decode("utf-8"))
    if not isinstance(value, dict) or value.get("version") != 1 or not isinstance(value.get("categories"), list):
        raise ValueError("分类配置格式不正确，请恢复本机备份或检查 data/categories.yaml。")
    normalized = {"version": 1, "categories": value["categories"]}
    for category in normalized["categories"]:
        if isinstance(category, dict):
            for field in category.get("fields", []):
                if isinstance(field, dict) and field.get("key") in {"cv_bullets", "cv_bullets_zh"}:
                    field["label"] = "经历要点"
                if isinstance(field, dict) and field.get("type") == "date":
                    field["required"] = False
    _validate_registry(normalized)
    return normalized


def ordered_categories(home: Path, *, include_archived: bool = False) -> list[dict[str, Any]]:
    items = load_registry(home)["categories"]
    selected = [item for item in items if include_archived or not item.get("archived", False)]
    return sorted(selected, key=lambda item: (int(item.get("order", 0)), str(item.get("label", ""))))


def category_map(home: Path, *, include_archived: bool = False) -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in ordered_categories(home, include_archived=include_archived)}


def field_definitions(home: Path, category: str, *, include_inactive: bool = False) -> list[dict[str, Any]]:
    item = category_map(home, include_archived=True).get(category)
    if item is None:
        return []
    fields = [field for field in item.get("fields", []) if include_inactive or (field.get("active", True) and not field.get("deleted"))]
    return sorted(fields, key=lambda field: (int(field.get("order", 0)), str(field.get("label", ""))))


def registry_for_api(home: Path) -> dict[str, Any]:
    all_categories = ordered_categories(home, include_archived=True)
    categories = [item for item in all_categories if not item.get("archived")]
    return {
        "categories": [
            {
                **category,
                "preview_field_keys": [
                    field["key"] for field in sorted(
                        category["fields"], key=lambda item: (item.get("order", 0), item["label"])
                    )
                    if field.get("active", True) and not field.get("deleted")
                    and not field["key"].endswith("_en") and "英文" not in field["label"]
                ][:5],
            }
            for category in categories
        ],
        "all_categories": all_categories,
        "fields": {
            category["id"]: [
                {
                    **field,
                    "required_for_ready": bool(field.get("required", False)),
                    "type": (f"select:{','.join(field.get('options', []))}" if field.get("type") == "select" else field.get("type")),
                }
                for field in sorted(category["fields"], key=lambda item: (item.get("order", 0), item["label"]))
                if field.get("active", True) and not field.get("deleted") and not field["key"].endswith("_en") and "英文" not in field["label"]
            ]
            for category in categories
        },
        "revision": registry_revision(home),
    }


def apply_category_settings(category: dict[str, Any], payload: dict[str, Any], records: list[dict[str, Any]]) -> None:
    """Validate an entire edit before the caller atomically writes the registry.

    Deleted fields become tombstones: historical values and stable keys survive.
    Omitted fields (including hidden English fields) remain unchanged.
    """
    for key in ("label", "order", "archived"):
        if key in payload:
            category[key] = payload[key]
    changes = payload.get("fields", [])
    if not isinstance(changes, list):
        raise ValueError("表单设置格式不正确。")
    known = {field["key"]: field for field in category["fields"]}
    seen = set()
    for change in changes:
        if not isinstance(change, dict):
            raise ValueError("字段设置格式不正确。")
        for flag in ("required", "active", "advanced", "deleted"):
            if flag in change and not isinstance(change[flag], bool):
                raise ValueError("字段设置中的开关格式不正确。")
        key = change.get("key")
        if key is not None and (not isinstance(key, str) or key not in known or key in seen):
            raise ValueError("字段编号无效或重复，请刷新配置后重试。")
        if key is None:
            key = f"field_{uuid.uuid4().hex[:16]}"
            field = {"key": key, "label": "", "type": "text", "options": [], "active": True, "required": False, "advanced": False, "order": len(known)}
            category["fields"].append(field)
            known[key] = field
        else:
            field = known[key]
        seen.add(key)
        if change.get("deleted"):
            if key == category.get("title_field"):
                raise ValueError("请保留记录名称字段；可以修改它的名称。")
            field.update(deleted=True, active=False, required=False)
            continue
        next_type = change.get("type", field["type"])
        if next_type != field["type"]:
            if next_type not in _FIELD_TYPES | _FIELD_TYPES_WITH_OPTIONS:
                raise ValueError("不能新增自定义跨分类关联。")
            if any(record.get(key) not in (None, "", []) for record in records):
                raise ValueError(f"“{field['label']}”已有记录内容，不能直接更改类型。")
        required = change.get("required", field.get("required", False)) and next_type != "date"
        active = change.get("active", field.get("active", True))
        if active and required and (not field.get("required") or not field.get("active", True)):
            if any(record.get("record_state", "ready") == "ready" and record.get(key) in (None, "", []) for record in records):
                raise ValueError(f"已有整理完成的记录缺少“{change.get('label', field['label'])}”，请先补全或改为待完善。")
        if next_type in _FIELD_TYPES_WITH_OPTIONS and "options" in change:
            options = change["options"]
            if not isinstance(options, list) or any(not isinstance(item, str) for item in options):
                raise ValueError("选项格式不正确。")
            for record in records:
                value = record.get(key)
                if value not in (None, "", []) and any(item not in options for item in (value if isinstance(value, list) else [value])):
                    raise ValueError("已有记录使用了这些选项，不能移除或更名。")
        for attr in ("label", "type", "options", "active", "advanced", "order"):
            if attr in change:
                field[attr] = change[attr]
        field["required"] = required
        if key == category.get("title_field"):
            field["required"] = True
        field.pop("deleted", None)


def save_registry(home: Path, registry: dict[str, Any]) -> str:
    _validate_registry(registry)
    path = registry_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = yaml.safe_dump(registry, sort_keys=False, allow_unicode=True, width=100).encode("utf-8")
    descriptor, temporary = tempfile.mkstemp(prefix="categories-", suffix=".tmp", dir=path.parent)
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
    return hashlib.sha256(payload).hexdigest()


def make_category(label: str, order: int) -> dict[str, Any]:
    category_id = f"custom_{uuid.uuid4().hex[:20]}"
    return {
        "id": category_id, "label": label, "icon": label[:1] or "类",
        "title_field": "title", "order": order, "archived": False, "builtin": False,
        "fields": [
            {"key": "title", "label": "名称", "type": "text", "options": [], "required": True, "advanced": False, "active": True, "order": 0},
            {"key": "date", "label": "日期", "type": "date", "options": [], "required": False, "advanced": False, "active": True, "order": 1},
            {"key": "details", "label": "详细内容", "type": "textarea", "options": [], "required": False, "advanced": False, "active": True, "order": 2},
            {"key": "highlights", "label": "经历要点", "type": "list", "options": [], "required": False, "advanced": False, "active": True, "order": 3},
        ],
    }


def _validate_registry(registry: dict[str, Any]) -> None:
    categories = registry.get("categories")
    if not isinstance(categories, list):
        raise ValueError("至少需要保留一个分类。")
    ids: set[str] = set()
    for category in categories:
        if not isinstance(category, dict):
            raise ValueError("分类配置格式不正确。")
        category_id = category.get("id")
        label = category.get("label")
        if not isinstance(category_id, str) or not _CATEGORY_ID.fullmatch(category_id) or category_id in ids:
            raise ValueError("分类编号无效或重复。")
        if not isinstance(label, str) or not label.strip() or len(label.strip()) > 40:
            raise ValueError("分类名称需为 1 至 40 个字符。")
        if "archived" in category and not isinstance(category["archived"], bool):
            raise ValueError("分类归档状态格式不正确。")
        if isinstance(category.get("order", 0), bool) or not isinstance(category.get("order", 0), int):
            raise ValueError("分类顺序必须是整数。")
        ids.add(category_id)
        fields = category.get("fields")
        if not isinstance(fields, list) or not fields:
            raise ValueError("每个分类至少需要一个有效字段。")
        field_keys: set[str] = set()
        active_fields = []
        for field in fields:
            if not isinstance(field, dict):
                raise ValueError("表单字段格式不正确。")
            key, field_label, kind = field.get("key"), field.get("label"), field.get("type")
            if not isinstance(key, str) or not _FIELD_KEY.fullmatch(key) or key in field_keys:
                raise ValueError("字段编号无效或重复。")
            if not isinstance(field_label, str) or not field_label.strip() or len(field_label.strip()) > 40:
                raise ValueError("字段名称需为 1 至 40 个字符。")
            if isinstance(field.get("order", 0), bool) or not isinstance(field.get("order", 0), int):
                raise ValueError("字段顺序必须是整数。")
            for flag in ("active", "required", "advanced"):
                if flag in field and not isinstance(field[flag], bool):
                    raise ValueError("字段启用、必填与扩展状态必须是布尔值。")
            options = field.get("options", [])
            valid_kind = kind in _FIELD_TYPES or kind in _FIELD_TYPES_WITH_OPTIONS
            if not valid_kind:
                # Legacy select and relation fields remain readable; custom fields
                # may not introduce arbitrary relation syntax.
                valid_kind = isinstance(kind, str) and kind.startswith(("relation:", "relation_one:", "select:"))
            if not valid_kind:
                raise ValueError(f"字段“{field_label}”的类型不受支持。")
            if not category.get("builtin", False) and isinstance(kind, str) and kind.startswith(("relation:", "relation_one:")):
                raise ValueError("自定义分类不能新增跨分类关联字段。")
            if kind in _FIELD_TYPES_WITH_OPTIONS and (not isinstance(options, list) or not options or len(options) > 50 or any(not isinstance(item, str) or not item.strip() for item in options)):
                raise ValueError("单选或多选字段需要至少一个有效选项。")
            field_keys.add(key)
            if field.get("active", True):
                active_fields.append(field)
        title_field = category.get("title_field", "title")
        title_definition = next((field for field in active_fields if field.get("key") == title_field), None)
        if title_definition is None:
            raise ValueError("请保留可用的记录名称字段。")
        valid_title_types = {"text", "textarea"} if not category.get("builtin", False) else {"text", "textarea", "select"}
        if title_definition.get("type") not in valid_title_types:
            raise ValueError("记录名称字段必须是短文本或长文本。")
