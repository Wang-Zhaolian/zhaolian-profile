"""Loopback-only browser interface backed by the existing YAML records."""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import tempfile
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml
from flask import Flask, abort, jsonify, redirect, render_template, request, send_file
from jsonschema import Draft202012Validator

from .backup import PRIVATE_PATHS, STAGE_PATHS, backup as do_backup, status as backup_status, load_config as load_backup_config, save_config as save_backup_config
from .library import library_id
from .resources import resource_root
from . import __version__
from .ai_provider import AIServiceError, ChatGPTProvider
from .chatgpt_auth import ChatGPTAuth
from .ai_workflow import build_context as build_ai_context
from .ai_workflow import get_note as get_ai_note
from .ai_workflow import list_notes as list_ai_notes
from .ai_workflow import parse_proposals as parse_ai_proposals
from .ai_workflow import save_note as save_ai_note
from .ai_workflow import add_proposal_batch, update_candidate, set_note_completed
from .file_inputs import MAX_FILE_BYTES, attachment_path, build_attachment_content
from .constants import REFERENCE_FIELDS, REFERENCE_LIST_FIELDS
from .categories import (
    category_map, field_definitions, load_registry, make_category,
    registry_for_api, registry_revision, save_registry, apply_category_settings,
)
from .preferences import load_preferences, save_preferences
from .record_view import filter_and_sort_records, sort_fields, visible_fields
from .dates import validate_date_string
from .errors import AcademicProfileError
from .loader import load_contact, load_master_data, load_yaml
from .ui_fields import CATEGORIES


ID_PREFIXES = {
    "education": "education", "research": "research", "publications": "paper",
    "projects": "project", "awards": "award", "competitions": "competition",
    "coursework": "course", "skills": "skill", "presentations": "presentation",
    "english": "english", "activities": "activity", "links": "link",
}
TITLE_FIELDS = {item["id"]: item["title_field"] for item in CATEGORIES}
AI_BLOCKING_ERROR_CODES = {
    "subscription_sharing_user_not_eligible",
    "subscription_sharing_usage_limit_exceeded",
    "subscription_sharing_invalid_user",
    "chatpass_v2_scope_not_authorized",
}
_PATH_LOCKS: dict[Path, threading.RLock] = {}
_PATH_LOCKS_GUARD = threading.Lock()


def _path_lock(path: Path) -> threading.RLock:
    resolved = path.resolve()
    with _PATH_LOCKS_GUARD:
        return _PATH_LOCKS.setdefault(resolved, threading.RLock())


def _atomic_write(path: Path, contents: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(prefix="academic-profile-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def _yaml_bytes(document: dict[str, Any]) -> bytes:
    return yaml.safe_dump(
        document, sort_keys=False, allow_unicode=True, width=100
    ).encode("utf-8")


def _revision(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except FileNotFoundError:
        return "missing"


def _record_title(category: str, record: dict[str, Any]) -> str:
    for field in (TITLE_FIELDS.get(category, "title"), "title", "name", "degree", "course_name", "category", "test", "label"):
        value = record.get(f"{field}_zh") or record.get(field) or record.get(f"{field}_en")
        if value not in (None, "", []):
            return str(value)
    return str(record.get("id") or "未命名记录")


def _request_origin_is_local() -> bool:
    host = request.host.split(":", 1)[0].strip("[]").lower()
    if host not in {"127.0.0.1", "localhost", "::1"}:
        return False
    origin = request.headers.get("Origin")
    if not origin:
        return True
    parsed = urlparse(origin)
    return parsed.scheme in {"http", "https"} and parsed.netloc == request.host


def _ok_request() -> bool:
    remote = (request.remote_addr or "").lower()
    return remote in {"127.0.0.1", "::1", "::ffff:127.0.0.1"} and _request_origin_is_local()


def _path_for(home: Path, category: str) -> Path:
    if category not in category_map(home, include_archived=True):
        abort(404)
    return home / "data" / f"{category}.yaml"


def _serialize_record(home: Path, category: str, record: dict[str, Any], index: int) -> dict[str, Any]:
    output = dict(record)
    output.setdefault("record_state", "ready")
    output["_index"] = index
    output["_title"] = _record_title(category, output)
    output["_category_label"] = category_map(home, include_archived=True)[category]["label"]
    return output


def _next_id(records: list[dict[str, Any]], prefix: str) -> str:
    pattern = re.compile(rf"^{re.escape(prefix)}_(\d+)$")
    numbers: list[int] = []
    for record in records:
        match = pattern.fullmatch(str(record.get("id", "")))
        if match:
            numbers.append(int(match.group(1)))
    return f"{prefix}_{max(numbers, default=0) + 1:03d}"


def _schema_for(home: Path, category: str) -> dict[str, Any]:
    return load_yaml(resource_root() / "schemas" / f"{category}.schema.yaml")


def _validate_ready(home: Path, category: str, record: dict[str, Any]) -> dict[str, str]:
    info = category_map(home, include_archived=True)[category]
    fields = field_definitions(home, category)
    required = [field["key"] for field in fields if field.get("required", False)]
    title_field = info.get("title_field", "title")
    if title_field not in required:
        required.append(title_field)
    if info.get("builtin", False):
        schema = _schema_for(home, category)
        record_schema = dict(schema["properties"]["records"]["items"])
        active_keys = {field["key"] for field in fields}
        record_schema["properties"] = {key: value for key, value in record_schema.get("properties", {}).items() if key in active_keys or key == "id"}
    else:
        record_schema = {"type": "object", "properties": {}, "additionalProperties": True}
    record_schema["required"] = required
    for field in fields:
        key, kind = field["key"], field["type"]
        if kind == "select":
            record_schema["properties"][key] = {"type": "string", "enum": field.get("options", [])}
        elif kind in {"list", "multiselect"}:
            items = {"type": "string"}
            if kind == "multiselect":
                items["enum"] = field.get("options", [])
            record_schema["properties"][key] = {"type": "array", "items": items}
        elif kind == "number":
            record_schema["properties"][key] = {"type": "number"}
        elif kind == "bool":
            record_schema["properties"][key] = {"type": "boolean"}
        elif kind == "map":
            record_schema["properties"][key] = {"type": "object", "additionalProperties": {"type": "string"}}
        elif kind in {"text", "textarea", "date", "url"}:
            record_schema["properties"][key] = {"type": "string"}
        elif key not in record_schema["properties"]:
            record_schema["properties"][key] = {"type": "string"}
    errors: dict[str, str] = {}
    field_labels = {field["key"]: field["label"] for field in fields}
    validation_record = dict(record)
    for field in required:
        if field not in validation_record:
            alternate = next((record.get(f"{field}_{language}") for language in ("zh", "en") if record.get(f"{field}_{language}") not in (None, "", [])), None)
            if alternate is not None:
                validation_record[field] = alternate
    for error in Draft202012Validator(record_schema).iter_errors(validation_record):
        key = str(next(iter(error.absolute_path), "_form"))
        if error.validator == "required":
            key = next((field for field in required if field not in validation_record), "_form")
        if error.validator == "required":
            message = f"请填写{field_labels.get(key, '必填信息')}。"
        elif error.validator == "enum":
            message = "请选择有效选项。"
        elif error.validator == "type":
            message = "格式不正确，请检查填写内容。"
        elif error.validator in {"minLength", "minItems"}:
            message = "此项不能为空。"
        else:
            message = "请检查此项填写内容。"
        errors.setdefault(key, message)
    if errors:
        return errors

    allowed_refs = REFERENCE_FIELDS.get(category, {})
    active_field_keys = {field["key"] for field in fields}
    for field, target in allowed_refs.items():
        if field not in active_field_keys:
            continue
        target_id = record.get(field)
        if target_id:
            target_doc = load_yaml(home / "data" / f"{target}.yaml")
            target_ids = {
                item.get("id") for item in target_doc.get("records", [])
                if item.get("record_state", "ready") == "ready"
                and not item.get("archived") and item.get("status") != "archived"
            }
            if target_id not in target_ids:
                errors[field] = "找不到关联的记录。"

    for field, target in REFERENCE_LIST_FIELDS.get(category, {}).items():
        if field not in active_field_keys:
            continue
        target_doc = load_yaml(home / "data" / f"{target}.yaml")
        target_ids = {
            item.get("id") for item in target_doc.get("records", [])
            if item.get("record_state", "ready") == "ready"
            and not item.get("archived") and item.get("status") != "archived"
        }
        if any(item not in target_ids for item in record.get(field, [])):
            errors[field] = "关联的部分记录不存在，请重新选择。"

    date_fields = {field["key"] for field in fields if field["type"] == "date"}
    for field in date_fields:
        if record.get(field) and not validate_date_string(str(record[field])):
            errors[field] = "请使用 YYYY-MM 或 YYYY-MM-DD 格式。"
    url_fields = {field["key"] for field in fields if field["type"] == "url"}
    for field in url_fields:
        value = record.get(field)
        if value:
            parsed = urlparse(str(value))
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                errors[field] = "请输入完整的 http:// 或 https:// 链接。"
    if {"start_date", "end_date"} <= active_field_keys and record.get("start_date") and record.get("end_date"):
        if str(record["end_date"]) < str(record["start_date"]):
            errors["end_date"] = "结束时间不能早于开始时间。"
    if category == "publications" and "status" in active_field_keys and "status" in record and record.get("status") not in {
        "published", "accepted", "under_review", "submitted", "preprint", "manuscript"
    }:
        errors["status"] = "请选择论文的实际状态。"
    return errors


def _field_options(home: Path, category: str, field: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    output = dict(field)
    kind = str(field["type"])
    output["required_for_ready"] = bool(field.get("required", field.get("required_for_ready", False)))
    if kind.startswith("relation:") or kind.startswith("relation_one:"):
        target = kind.split(":", 1)[1]
        output["options"] = [
            {"id": record.get("id"), "label": _record_title(target, record)}
            for record in data.get(target, [])
            if record.get("record_state", "ready") == "ready"
            and not record.get("archived")
            and record.get("status") != "archived"
        ]
    elif kind == "select":
        output["options"] = list(field.get("options", []))
        output["type"] = "select:" + ",".join(output["options"])
    elif kind == "multiselect":
        output["options"] = list(field.get("options", []))
    elif kind.startswith("select:"):
        output["options"] = [
            value.strip() for value in kind.split(":", 1)[1].split(",")
        ]
    return output


def create_app(
    home: Path,
    *,
    static_root: Path | None = None,
    callback_port: int = 52847,
    ai_auth: ChatGPTAuth | None = None,
    ai_provider: ChatGPTProvider | None = None,
) -> Flask:
    home = home.resolve()
    root = static_root or resource_root()
    ui_root = root / "templates"
    static_dir = root / "static"
    app = Flask(
        __name__,
        template_folder=str(ui_root),
        static_folder=str(static_dir),
    )
    app.config["HOME_ROOT"] = home
    app.config["LIBRARY_ID"] = library_id(home)
    auth = ai_auth or ChatGPTAuth()
    provider = ai_provider or ChatGPTProvider(auth)
    app.config["AI_AUTH"] = auth
    app.config["AI_PROVIDER"] = provider
    app.config["AI_BLOCKED"] = None
    app.config["MAX_CONTENT_LENGTH"] = 205 * 1024 * 1024

    @app.before_request
    def enforce_local_only() -> Any:
        if not _ok_request():
            return jsonify({"error": "此平台只允许本机访问。"}), 403
        if request.method in {"POST", "PUT", "PATCH", "DELETE"} and request.endpoint != "health":
            if not request.headers.get("X-Academic-Profile", ""):
                return jsonify({"error": "请求来源检查未通过，请刷新页面后重试。"}), 403
        return None

    @app.get("/")
    def index() -> str:
        return render_template("index.html")

    @app.get("/api/health")
    def health() -> Any:
        return jsonify({"ok": True, "name": "academic-profile", "version": __version__, "library_id": app.config["LIBRARY_ID"]})

    @app.get("/api/config")
    def get_config() -> Any:
        config = registry_for_api(app.config["HOME_ROOT"])
        config["privacy"] = {
            "local_only": True,
            "local_paths": list(PRIVATE_PATHS),
            "github_includes": list(STAGE_PATHS),
        }
        return jsonify(config)

    @app.get("/api/preferences")
    def get_preferences() -> Any:
        home_root: Path = app.config["HOME_ROOT"]
        preferences = load_preferences(home_root)
        valid_sorts: dict[str, dict[str, str]] = {}
        for category_id, setting in preferences["sorts"].items():
            if not isinstance(setting, dict):
                continue
            category = category_map(home_root, include_archived=True).get(category_id)
            if not category or not isinstance(setting.get("sort_by"), str):
                continue
            records = load_yaml(_path_for(home_root, category_id)).get("records", [])
            available = sort_fields(category, records)
            if any(field["key"] == setting["sort_by"] for field in available):
                direction = setting.get("direction", "asc")
                valid_sorts[category_id] = {"sort_by": setting["sort_by"], "direction": direction if direction in {"asc", "desc"} else "asc"}
        if valid_sorts != preferences["sorts"]:
            preferences = save_preferences(home_root, {"sorts": {key: valid_sorts.get(key, {"sort_by": ""}) for key in preferences["sorts"]}})
            preferences["sorts"] = valid_sorts
        return jsonify(preferences)

    @app.patch("/api/preferences")
    def patch_preferences() -> Any:
        home_root: Path = app.config["HOME_ROOT"]
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict) or not payload or set(payload) - {"ai_model", "sorts"}:
            return jsonify({"error": "本机设置格式不正确。"}), 400
        try:
            if "sorts" in payload:
                if not isinstance(payload["sorts"], dict):
                    raise ValueError("分类排序设置格式不正确。")
                clean_sorts: dict[str, dict[str, str]] = {}
                categories = category_map(home_root, include_archived=True)
                for category_id, setting in payload["sorts"].items():
                    if category_id not in categories or not isinstance(setting, dict):
                        raise ValueError("分类或排序设置无效，请刷新后重试。")
                    sort_by = setting.get("sort_by", "")
                    direction = setting.get("direction", "asc")
                    if sort_by == "":
                        clean_sorts[category_id] = {"sort_by": ""}
                        continue
                    if not isinstance(sort_by, str) or direction not in {"asc", "desc"}:
                        raise ValueError("排序方向或字段无效。")
                    records = load_yaml(_path_for(home_root, category_id)).get("records", [])
                    if not any(field["key"] == sort_by for field in sort_fields(categories[category_id], records)):
                        raise ValueError("所选字段没有可排序的数字或日期，请刷新后重试。")
                    clean_sorts[category_id] = {"sort_by": sort_by, "direction": direction}
                payload = {**payload, "sorts": clean_sorts}
            result = save_preferences(home_root, payload)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 422
        return jsonify(result)

    @app.post("/api/categories")
    def create_category() -> Any:
        home_root = app.config["HOME_ROOT"]
        config_path = home_root / "data" / "categories.yaml"
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict) or not isinstance(payload.get("label"), str):
            return jsonify({"error": "请填写分类名称。"}), 400
        label = payload["label"].strip()
        if not label or len(label) > 40:
            return jsonify({"error": "分类名称需为 1 至 40 个字符。"}), 422
        with _path_lock(config_path):
            if payload.get("revision") != registry_revision(home_root):
                return jsonify({"error": "分类配置已在其他窗口修改，请刷新后重试。", "code": "revision_conflict"}), 409
            registry = load_registry(home_root)
            category = make_category(label, len(registry["categories"]))
            registry["categories"].append(category)
            _atomic_write(home_root / "data" / f"{category['id']}.yaml", _yaml_bytes({"records": []}))
            revision = save_registry(home_root, registry)
        return jsonify({"category": category, "revision": revision}), 201

    @app.post("/api/categories/<category_id>")
    def update_category(category_id: str) -> Any:
        home_root = app.config["HOME_ROOT"]
        config_path = home_root / "data" / "categories.yaml"
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return jsonify({"error": "分类修改格式不正确。"}), 400
        with _path_lock(config_path):
            if payload.get("revision") != registry_revision(home_root):
                return jsonify({"error": "分类配置已在其他窗口修改，请刷新后重试。", "code": "revision_conflict"}), 409
            registry = load_registry(home_root)
            category = next((item for item in registry["categories"] if item.get("id") == category_id), None)
            if not category:
                abort(404)
            for key in ("label", "order", "archived"):
                if key in payload:
                    category[key] = payload[key]
            try:
                revision = save_registry(home_root, registry)
            except ValueError as exc:
                return jsonify({"error": str(exc)}), 422
        return jsonify({"category": category, "revision": revision})

    @app.post("/api/categories/<category_id>/fields")
    def add_category_field(category_id: str) -> Any:
        home_root = app.config["HOME_ROOT"]
        config_path = home_root / "data" / "categories.yaml"
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict) or not isinstance(payload.get("label"), str):
            return jsonify({"error": "请填写字段名称。"}), 400
        label = payload["label"].strip()
        if not label or len(label) > 40:
            return jsonify({"error": "字段名称需为 1 至 40 个字符。"}), 422
        for flag in ("required", "advanced"):
            if flag in payload and not isinstance(payload[flag], bool):
                return jsonify({"error": "字段必填与扩展状态格式不正确。"}), 400
        with _path_lock(config_path):
            if payload.get("revision") != registry_revision(home_root):
                return jsonify({"error": "分类配置已在其他窗口修改，请刷新后重试。", "code": "revision_conflict"}), 409
            registry = load_registry(home_root)
            category = next((item for item in registry["categories"] if item.get("id") == category_id), None)
            if not category:
                abort(404)
            records = load_yaml(home_root / "data" / f"{category_id}.yaml").get("records", [])
            required = payload.get("required", False)
            field_key = f"field_{uuid.uuid4().hex[:16]}"
            if required and any(
                record.get("record_state", "ready") == "ready"
                and record.get(field_key) in (None, "", [])
                for record in records
            ):
                return jsonify({"error": "已有整理完成的记录缺少此项，请先补全或改为待完善。"}), 422
            field = {
                "key": field_key,
                "label": label, "type": payload.get("type", "text"),
                "options": payload.get("options", []), "required": required,
                "active": True, "advanced": payload.get("advanced", False),
                "order": max((int(item.get("order", 0)) for item in category["fields"]), default=-1) + 1,
            }
            category["fields"].append(field)
            try:
                revision = save_registry(home_root, registry)
            except ValueError as exc:
                return jsonify({"error": str(exc)}), 422
        return jsonify({"field": field, "revision": revision}), 201

    @app.post("/api/categories/<category_id>/settings")
    def save_category_settings(category_id: str) -> Any:
        home_root = app.config["HOME_ROOT"]
        config_path = home_root / "data" / "categories.yaml"
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"error": "设置格式不正确。"}), 400
        with _path_lock(config_path):
            if payload.get("revision") != registry_revision(home_root):
                return jsonify({"error": "分类配置已在其他窗口修改，请刷新后重试。", "code": "revision_conflict"}), 409
            registry = load_registry(home_root)
            category = next((item for item in registry["categories"] if item["id"] == category_id), None)
            if category is None:
                abort(404)
            with _path_lock(home_root / "data" / f"{category_id}.yaml"):
                records = load_yaml(home_root / "data" / f"{category_id}.yaml").get("records", [])
                try:
                    apply_category_settings(category, payload, records)
                    revision = save_registry(home_root, registry)
                except ValueError as exc:
                    return jsonify({"error": str(exc)}), 422
        return jsonify({"category": category, "revision": revision})

    @app.post("/api/categories/<category_id>/fields/<field_key>")
    def update_category_field(category_id: str, field_key: str) -> Any:
        home_root = app.config["HOME_ROOT"]
        config_path = home_root / "data" / "categories.yaml"
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return jsonify({"error": "字段修改格式不正确。"}), 400
        with _path_lock(config_path):
            if payload.get("revision") != registry_revision(home_root):
                return jsonify({"error": "分类配置已在其他窗口修改，请刷新后重试。", "code": "revision_conflict"}), 409
            registry = load_registry(home_root)
            category = next((item for item in registry["categories"] if item.get("id") == category_id), None)
            if not category:
                abort(404)
            field = next((item for item in category["fields"] if item.get("key") == field_key), None)
            if not field:
                abort(404)
            records = load_yaml(home_root / "data" / f"{category_id}.yaml").get("records", [])
            next_type = payload.get("type", field["type"])
            valid_title_types = {"text", "textarea"} if not category.get("builtin", False) else {"text", "textarea", "select"}
            if field_key == category.get("title_field", "title") and next_type not in valid_title_types:
                return jsonify({"error": "记录名称字段只能使用短文本或长文本类型。"}), 422
            if next_type != field["type"] and any(record.get(field_key) not in (None, "", []) for record in records):
                return jsonify({"error": "该字段已有记录内容，不能直接更改类型。请先新增字段并迁移需要保留的内容。"}), 422
            if payload.get("required") is True and any(record.get("record_state", "ready") == "ready" and record.get(field_key) in (None, "", []) for record in records):
                return jsonify({"error": "已有整理完成的记录缺少此项，请先补全或改为草稿，再设为必填。"}), 422
            if "options" in payload and next_type in {"select", "multiselect"}:
                allowed = set(payload["options"] if isinstance(payload["options"], list) else [])
                def uses_removed_option(record: dict[str, Any]) -> bool:
                    value = record.get(field_key)
                    if value in (None, "", []):
                        return False
                    values = value if isinstance(value, list) else [value]
                    return any(item not in allowed for item in values)
                if any(uses_removed_option(record) for record in records):
                    return jsonify({"error": "已有记录使用了这些选项，不能移除或更名。"}), 422
            for key in ("label", "type", "options", "required", "active", "advanced", "order"):
                if key in payload:
                    field[key] = payload[key]
            try:
                revision = save_registry(home_root, registry)
            except ValueError as exc:
                return jsonify({"error": str(exc)}), 422
        return jsonify({"field": field, "revision": revision})

    @app.get("/auth/callback")
    def chatgpt_callback() -> Any:
        """Finish the SIWC redirect in the system browser without exposing tokens."""
        auth_service: ChatGPTAuth = app.config["AI_AUTH"]
        try:
            auth_service.complete(request.args.to_dict(flat=True))
        except AIServiceError as error:
            message = html.escape(str(error))
            return (
                "<!doctype html><html lang='zh-CN'><meta charset='utf-8'>"
                "<meta name='viewport' content='width=device-width,initial-scale=1'>"
                "<meta http-equiv='refresh' content='8;url=/'>"
                "<title>ChatGPT 授权未完成</title><body style='font:16px system-ui;padding:32px'>"
                "<h1>ChatGPT 授权未完成</h1><p>" + message + "</p>"
                "<p><a href='/'>返回昭濂个人履历库</a></p></body></html>",
                400,
                {"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store"},
            )
        response = redirect("/", code=303)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/ai/status")
    def ai_status() -> Any:
        auth_service: ChatGPTAuth = app.config["AI_AUTH"]
        status = auth_service.status()
        blocked = app.config.get("AI_BLOCKED")
        if blocked:
            status.update(sharing=False, ai_blocked=True, error=blocked["message"], blocked_code=blocked["code"])
        return jsonify(status)

    @app.post("/api/ai/connect")
    def ai_connect() -> Any:
        auth_service: ChatGPTAuth = app.config["AI_AUTH"]
        app.config["AI_BLOCKED"] = None
        callback_uri = f"http://127.0.0.1:{callback_port}/auth/callback"
        return jsonify({"authorization_url": auth_service.begin(callback_uri)})

    @app.post("/api/ai/disconnect")
    def ai_disconnect() -> Any:
        auth_service: ChatGPTAuth = app.config["AI_AUTH"]
        app.config["AI_BLOCKED"] = None
        return jsonify(auth_service.disconnect())

    @app.get("/api/ai/models")
    def ai_models() -> Any:
        blocked = app.config.get("AI_BLOCKED")
        if blocked:
            raise AIServiceError(blocked["message"], blocked["code"], status=403)
        ai_service: ChatGPTProvider = app.config["AI_PROVIDER"]
        return jsonify({"models": ai_service.list_models()})

    @app.get("/api/ai/notes")
    def ai_notes() -> Any:
        return jsonify({"notes": list_ai_notes(app.config["HOME_ROOT"])})

    @app.post("/api/ai/notes")
    def create_ai_note() -> Any:
        uploads: list[tuple[str, bytes]] = []
        if request.mimetype == "multipart/form-data":
            text_value = request.form.get("text", "")
            files = request.files.getlist("files")
            if len(files) > 10:
                return jsonify({"error": "一条素材最多可添加 10 个文件。", "code": "too_many_files"}), 422
            for file in files:
                if not file.filename:
                    continue
                content = file.stream.read(MAX_FILE_BYTES + 1)
                uploads.append((file.filename, content))
        else:
            payload = request.get_json(silent=True) or {}
            if not isinstance(payload, dict):
                return jsonify({"error": "笔记内容格式不正确。", "code": "invalid_note"}), 400
            text_value = payload.get("text", "")
        try:
            note = save_ai_note(app.config["HOME_ROOT"], text_value, uploads)
        except ValueError as exc:
            return jsonify({"error": str(exc), "code": "invalid_note"}), 422
        return jsonify({"note": note}), 201

    @app.get("/api/ai/notes/<note_id>")
    def get_ai_note_route(note_id: str) -> Any:
        try:
            full_note = get_ai_note(app.config["HOME_ROOT"], note_id, include_storage=True)
        except (ValueError, FileNotFoundError):
            return jsonify({"error": "没有找到这条本机笔记。", "code": "note_missing"}), 404
        note = get_ai_note(app.config["HOME_ROOT"], note_id)
        return jsonify({"note": note, "batches": full_note.get("batches", [])})

    @app.post("/api/ai/notes/<note_id>/status")
    def update_ai_note_status(note_id: str) -> Any:
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict) or not isinstance(payload.get("completed"), bool):
            return jsonify({"error": "处理状态不正确。"}), 400
        try:
            note = set_note_completed(app.config["HOME_ROOT"], note_id, payload["completed"])
        except (ValueError, FileNotFoundError):
            return jsonify({"error": "没有找到这条本机笔记。", "code": "note_missing"}), 404
        return jsonify({"note": note})

    @app.post("/api/ai/notes/<note_id>/batches/<batch_id>/candidates/<operation_id>")
    def update_ai_candidate_status(note_id: str, batch_id: str, operation_id: str) -> Any:
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict) or payload.get("status") not in {"pending", "adopted", "discarded"}:
            return jsonify({"error": "候选处理状态不正确。"}), 400
        if payload["status"] == "adopted":
            home_root = app.config["HOME_ROOT"]
            saved = any(
                record.get("_adoption_id") == operation_id
                for category in category_map(home_root, include_archived=True)
                for record in load_yaml(home_root / "data" / f"{category}.yaml").get("records", [])
            )
            if not saved:
                return jsonify({"error": "记录尚未成功入库，草稿已保留，请先保存记录。", "code": "adoption_not_saved"}), 409
        try:
            note = update_candidate(
                app.config["HOME_ROOT"], note_id, batch_id, operation_id,
                payload["status"], payload.get("fields") if isinstance(payload.get("fields"), dict) else None,
                payload.get("category"),
            )
        except (ValueError, FileNotFoundError):
            return jsonify({"error": "没有找到这条待处理的 AI 候选。", "code": "candidate_missing"}), 404
        return jsonify({"note": note})

    @app.get("/api/ai/notes/<note_id>/attachments/<attachment_id>")
    def get_ai_attachment(note_id: str, attachment_id: str) -> Any:
        try:
            note = get_ai_note(app.config["HOME_ROOT"], note_id, include_storage=True)
            attachment = next((item for item in note.get("attachments", []) if item.get("id") == attachment_id), None)
            if not attachment:
                raise FileNotFoundError
            path = attachment_path(app.config["HOME_ROOT"], note_id, attachment)
        except (ValueError, FileNotFoundError):
            return jsonify({"error": "没有找到这份本机附件。", "code": "attachment_missing"}), 404
        return send_file(path, as_attachment=True, download_name=attachment.get("name", "attachment"), mimetype=attachment.get("mime_type", "application/octet-stream"))

    @app.post("/api/ai/proposals")
    def ai_proposals() -> Any:
        home_root: Path = app.config["HOME_ROOT"]
        auth_service: ChatGPTAuth = app.config["AI_AUTH"]
        ai_service: ChatGPTProvider = app.config["AI_PROVIDER"]
        blocked = app.config.get("AI_BLOCKED")
        if blocked:
            raise AIServiceError(blocked["message"], blocked["code"], status=403)
        if not auth_service.status().get("sharing"):
            return jsonify({"error": "请先连接具有 ChatGPT 方案使用权限的账号。", "code": "chatgpt_not_connected"}), 409
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return jsonify({"error": "AI 请求格式不正确。", "code": "invalid_request"}), 400
        note_id = str(payload.get("note_id", "")).strip()
        if not note_id:
            return jsonify({"error": "请先保存要整理的原始笔记。", "code": "note_required"}), 400
        note = get_ai_note(home_root, note_id, include_storage=True)
        models = ai_service.list_models()
        requested_model = str(payload.get("model", "")).strip()
        model = requested_model or (models[0]["slug"] if models else "")
        if not model or model not in {item.get("slug") for item in models}:
            return jsonify({"error": "所选模型当前不可用，请刷新模型列表后重试。", "code": "model_unavailable"}), 409

        if "attachment_ids" in payload:
            attachment_ids = payload.get("attachment_ids")
            if not isinstance(attachment_ids, list) or any(not isinstance(item, str) for item in attachment_ids):
                return jsonify({"error": "附件选择格式不正确。", "code": "invalid_attachments"}), 400
        else:
            attachment_ids = [item.get("id", "") for item in note.get("attachments", [])]
        selected_attachments = [item for item in note.get("attachments", []) if item.get("id") in attachment_ids]
        if len(selected_attachments) != len(set(attachment_ids)):
            return jsonify({"error": "所选附件与这条素材不匹配，请刷新页面后重试。", "code": "invalid_attachments"}), 400

        context_note = note["text"] or "请根据本次选中的附件中的原始事实，整理学术履历候选记录。"
        try:
            context = build_ai_context(home_root, context_note)
        except ValueError as exc:
            return jsonify({"error": str(exc), "code": "context_too_large"}), 422
        try:
            attachment_content = build_attachment_content(home_root, note, attachment_ids)
        except ValueError as exc:
            return jsonify({"error": str(exc), "code": "attachment_limit"}), 422
        categories = [
            {
                "id": category["id"], "label": category["label"],
                "fields": [
                    {"key": field["key"], "label": field["label"], "type": field["type"], "options": field.get("options", [])}
                    for field in field_definitions(home_root, category["id"])
                    if not field["key"].endswith("_en") and "英文" not in field["label"]
                ],
            }
            for category in category_map(home_root).values()
        ]
        instructions = (
            "你是昭濂个人履历库的学术经历整理助手。优先用中文理解和提出候选资料；仅根据用户给出的本次笔记、附件和既有学术记录；"
            "不得编造、推断或补全未提供的事实。把一段笔记拆成零条或多条独立候选记录，"
            "字段只能来自下列分类及字段清单。未知信息省略，不写占位事实。保留论文真实状态。"
            "中文是首选，不得自动翻译或填造未知事实；保留原始论文状态。source_excerpt 如来自文字笔记，必须是其中逐字片段。"
            "如来自附件，在 source_references 中引用本次提供的 attachment_id、页码（适用时）和简短原文摘录。"
            "仅输出 JSON 对象 {\"candidates\":[{\"category\":string,\"fields\":object,"
            "\"source_excerpt\":string,\"source_references\":[{\"attachment_id\":string,\"page\":number,\"excerpt\":string}],\"warnings\":[string]}]}，不要 Markdown。\n"
            "允许的分类与字段：" + json.dumps(categories, ensure_ascii=False)
        )
        input_text = json.dumps({
            "new_note": context["note_text"],
            "academic_profile": context["profile"],
            "context_mode": context["mode"],
            "academic_records": context["records"],
            "academic_record_synopsis": context["synopsis"],
            "selected_attachments": [
                {"attachment_id": item["id"], "filename": item["name"], "mime_type": item["mime_type"]}
                for item in selected_attachments
            ],
        }, ensure_ascii=False)
        request_content = [{"type": "input_text", "text": input_text}, *attachment_content]
        if attachment_content and hasattr(ai_service, "complete_content"):
            response_text = ai_service.complete_content(model, instructions, request_content)
        else:
            response_text = ai_service.complete_text(model, instructions, input_text)
        try:
            candidates = parse_ai_proposals(home_root, response_text, note["text"], selected_attachments)
        except ValueError as exc:
            return jsonify({"error": str(exc), "code": "invalid_ai_response"}), 502
        batch = add_proposal_batch(home_root, note_id, candidates, attachment_ids)
        return jsonify({
            "candidates": batch["candidates"],
            "batch_id": batch["id"],
            "context_mode": context["mode"],
            "records_count": context["record_count"],
            "full_record_count": context["full_record_count"],
            "note_id": note_id,
        })

    @app.get("/api/dashboard")
    def dashboard() -> Any:
        home_root: Path = app.config["HOME_ROOT"]
        data = load_master_data(home_root / "data")
        category_counts: list[dict[str, Any]] = []
        for category in category_map(home_root).values():
            records = data.get(category["id"], [])
            active = [record for record in records if not record.get("archived")]
            category_counts.append({
                "id": category["id"], "label": category["label"],
                "icon": category.get("icon", "类"), "title_field": category.get("title_field", "title"),
                "count": len(active), "drafts": sum(r.get("record_state", "ready") == "draft" for r in active),
            })
        return jsonify({
            "name": data["basics"].get("name_zh") or data["basics"].get("name_en") or "",
            "counts": category_counts,
            "total": sum(item["count"] for item in category_counts),
        })

    @app.get("/api/records/<category>")
    def get_records(category: str) -> Any:
        home_root: Path = app.config["HOME_ROOT"]
        path = _path_for(home_root, category)
        document = load_yaml(path)
        include_archived = request.args.get("archived", "0") == "1"
        query = request.args.get("q", "").strip().casefold()
        category_definition = category_map(home_root, include_archived=True).get(category)
        if category_definition is None:
            abort(404)
        all_records = document.get("records", [])
        available_sort_fields = sort_fields(category_definition, all_records)
        sort_by = request.args.get("sort_by", "")
        direction = request.args.get("sort_direction", "asc")
        if direction not in {"asc", "desc"}:
            return jsonify({"error": "排序方向只能选择升序或降序。"}), 400
        selected_sort = next((item for item in available_sort_fields if item["key"] == sort_by), None)
        if sort_by and selected_sort is None:
            return jsonify({"error": "所选字段没有可排序的数字或日期，请刷新后重试。"}), 400
        title_fields = visible_fields(category_definition)
        title_key = title_fields[0]["key"] if title_fields else ""
        matching = [record for record in all_records if bool(record.get("archived")) == include_archived]
        matching = filter_and_sort_records(
            matching, title_key, query,
            selected_sort.get("type", "") if selected_sort else "", direction, sort_by,
        )
        indices = {id(record): index for index, record in enumerate(all_records)}
        records = []
        for record in matching:
            index = indices[id(record)]
            records.append(_serialize_record(home_root, category, record, index))
        return jsonify({"records": records, "revision": _revision(path), "sort_fields": available_sort_fields})

    @app.get("/api/records/<category>/<record_id>")
    def get_record(category: str, record_id: str) -> Any:
        home_root: Path = app.config["HOME_ROOT"]
        path = _path_for(home_root, category)
        document = load_yaml(path)
        for index, record in enumerate(document.get("records", [])):
            if record.get("id") == record_id:
                result = _serialize_record(home_root, category, record, index)
                result["revision"] = _revision(path)
                data = load_master_data(home_root / "data")
                result["fields"] = [
                    _field_options(home_root, category, field, data)
                    for field in field_definitions(home_root, category)
                    if not field["key"].endswith("_en") and "英文" not in field["label"]
                ]
                return jsonify(result)
        abort(404)

    @app.post("/api/records/<category>")
    def save_record(category: str) -> Any:
        home_root: Path = app.config["HOME_ROOT"]
        path = _path_for(home_root, category)
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return jsonify({"error": "记录内容格式不正确。"}), 400
        info = category_map(home_root, include_archived=True)[category]
        if info.get("archived") and payload.get("id") in (None, ""):
            return jsonify({"error": "此分类已归档，请先恢复分类后再新增记录。", "code": "category_archived"}), 409
        with _path_lock(home_root / "data" / "categories.yaml"), _path_lock(path):
            return _save_record_locked(home_root, category, path, payload)

    @app.post("/api/records/<category>/<record_id>/archive")
    def archive_record(category: str, record_id: str) -> Any:
        return _set_archived(app.config["HOME_ROOT"], category, record_id, True)

    @app.post("/api/records/<category>/<record_id>/restore")
    def restore_record(category: str, record_id: str) -> Any:
        return _set_archived(app.config["HOME_ROOT"], category, record_id, False)

    @app.get("/api/basics")
    def get_basics() -> Any:
        home_root: Path = app.config["HOME_ROOT"]
        path = home_root / "data" / "basics.yaml"
        return jsonify({"basics": load_yaml(path), "contact": load_contact(home_root / "private" / "contact.yaml"), "revision": _revision(path) + ":" + _revision(home_root / "private" / "contact.yaml")})

    @app.post("/api/basics")
    def save_basics() -> Any:
        home_root: Path = app.config["HOME_ROOT"]
        payload = request.get_json(silent=True) or {}
        basic_path = home_root / "data" / "basics.yaml"
        with _path_lock(basic_path):
            return _save_basics_locked(home_root, payload)

    @app.route("/api/cv", defaults={"legacy_path": ""}, methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    @app.route("/api/cv/<path:legacy_path>", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    def removed_cv_endpoints(legacy_path: str) -> Any:
        return jsonify({"error": "简历生成功能已移除；履历记录仍保存在各分类中。", "code": "feature_removed"}), 410

    @app.get("/api/backup/status")
    def get_backup_status() -> Any:
        return jsonify(_backup_status_json(app.config["HOME_ROOT"], refresh=request.args.get("refresh") == "1"))

    @app.route("/api/backup/config", methods=["GET", "PATCH"])
    def backup_config() -> Any:
        home_root = app.config["HOME_ROOT"]
        if request.method == "GET":
            return jsonify({**load_backup_config(home_root), "data_location": str(home_root)})
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or set(payload) != {"repository"}:
            return jsonify({"error": "请填写私有仓库，格式为 用户名/仓库名。"}), 400
        try:
            return jsonify(save_backup_config(home_root, payload["repository"]))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except (OSError, RuntimeError) as exc:
            return jsonify({"error": f"备份设置未保存：{exc}"}), 409

    @app.post("/api/backup")
    def run_backup() -> Any:
        try:
            result = do_backup(app.config["HOME_ROOT"])
            return jsonify(_backup_json(result))
        except (RuntimeError, ValueError, OSError, TimeoutError, subprocess.TimeoutExpired) as exc:
            return jsonify({"error": str(exc), "status": _backup_status_json(app.config["HOME_ROOT"])}), 502

    @app.post("/api/shutdown")
    def shutdown() -> Any:
        root_dir: Path = app.config["HOME_ROOT"]
        marker = root_dir / "private" / "desktop-server.local.json"
        try:
            marker.unlink(missing_ok=True)
        except OSError:
            pass
        threading.Timer(0.4, lambda: os._exit(0)).start()
        return jsonify({"ok": True})

    @app.errorhandler(AcademicProfileError)
    def handle_profile_error(error: AcademicProfileError) -> Any:
        return jsonify({"error": str(error)}), 422

    @app.errorhandler(AIServiceError)
    def handle_ai_service_error(error: AIServiceError) -> Any:
        if error.code in AI_BLOCKING_ERROR_CODES:
            app.config["AI_BLOCKED"] = {"code": error.code, "message": str(error)}
        status = error.status if error.status and 400 <= error.status <= 599 else 502
        payload = {"error": str(error), "code": error.code}
        if error.request_id:
            payload["request_id"] = error.request_id
        return jsonify(payload), status

    @app.errorhandler(413)
    def request_too_large(error: Any) -> Any:
        return jsonify({"error": "本条素材附件总量超过 200 MB，请拆分为多条素材后保存。", "code": "upload_too_large"}), 413

    @app.errorhandler(404)
    def not_found(error: Any) -> Any:
        return jsonify({"error": "没有找到这项内容。"}), 404

    return app


def _backup_json(result: Any) -> dict[str, Any]:
    return {
        "repository": result.repository,
        "is_private": result.is_private,
        "origin_matches": result.origin_matches,
        "pending": result.pending,
        "pending_commits": result.pending_commits,
        "last_successful_backup": result.last_successful_backup,
        "message": result.message,
    }


def _backup_status_json(home: Path, *, refresh: bool = False) -> dict[str, Any]:
    return _backup_json(backup_status(home, refresh=refresh))


def _set_archived(home: Path, category: str, record_id: str, archived: bool) -> Any:
    path = _path_for(home, category)
    payload = request.get_json(silent=True) or {}
    with _path_lock(path):
        revision = _revision(path)
        if payload.get("revision") != revision:
            return jsonify({"error": "资料刚刚在另一个窗口中更新，请刷新后重试。", "code": "revision_conflict"}), 409
        document = load_yaml(path)
        for index, record in enumerate(document.get("records", [])):
            if record.get("id") == record_id:
                record["archived"] = archived
                record["record_state"] = record.get("record_state", "ready")
                _atomic_write(path, _yaml_bytes(document))
                return jsonify({"record": _serialize_record(home, category, record, index), "revision": _revision(path)})
    abort(404)


def _save_record_locked(home: Path, category: str, path: Path, payload: dict[str, Any]) -> Any:
    document = load_yaml(path)
    records = document.setdefault("records", [])
    operation_id = payload.get("operation_id")
    if operation_id is not None and (not isinstance(operation_id, str) or not re.fullmatch(r"[0-9a-f]{32}", operation_id)):
        return jsonify({"error": "采纳操作编号无效。", "code": "invalid_operation"}), 400
    if operation_id:
        adopted_index = next((index for index, item in enumerate(records) if item.get("_adoption_id") == operation_id), None)
        if adopted_index is not None:
            return jsonify({"record": _serialize_record(home, category, records[adopted_index], adopted_index), "revision": _revision(path), "already_saved": True})
        for other_category in category_map(home, include_archived=True):
            if other_category == category:
                continue
            if any(item.get("_adoption_id") == operation_id for item in load_yaml(home / "data" / f"{other_category}.yaml").get("records", [])):
                return jsonify({"error": "此候选已在其他分类入库，请刷新草稿箱，不能重复保存到新分类。", "code": "adoption_category_conflict"}), 409
    current_revision = _revision(path)
    if payload.get("revision") != current_revision:
        return jsonify({"error": "这条资料刚刚在另一个窗口中更新。请刷新列表后重新编辑。", "code": "revision_conflict"}), 409
    raw_id = payload.get("id")
    if raw_id not in (None, "") and not isinstance(raw_id, str):
        return jsonify({"error": "记录编号格式不正确。", "code": "invalid_record_id"}), 400
    record_id = raw_id.strip() if isinstance(raw_id, str) else ""
    existing_index = next(
        (index for index, record in enumerate(records) if record.get("id") == record_id), None
    ) if record_id else None
    if record_id and existing_index is None:
        return jsonify({"error": "这条记录已被其他窗口删除，请刷新列表。", "code": "record_missing"}), 409

    prefix = ID_PREFIXES.get(category, category)
    existing = dict(records[existing_index]) if existing_index is not None else {
        "id": _next_id(records, prefix), "record_state": "draft",
    }
    updated = dict(existing)
    editable_fields = {field["key"] for field in field_definitions(home, category, include_inactive=True)}
    editable_fields |= {"record_state", "archived"}
    values = payload.get("record", {})
    if not isinstance(values, dict):
        return jsonify({"error": "表单内容格式不正确。"}), 400
    for field in editable_fields:
        if field not in values:
            continue
        value = values[field]
        if value in (None, "") or value == []:
            updated.pop(field, None)
        else:
            updated[field] = value
    state = updated.get("record_state", "draft")
    if state not in {"draft", "ready"}:
        return jsonify({"field_errors": {"record_state": "记录只能保存为草稿或完整资料。"}}), 422
    if state == "draft":
        pass
    else:
        field_errors = _validate_ready(home, category, updated)
        if field_errors:
            return jsonify({"field_errors": field_errors}), 422

    updated["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    if operation_id:
        updated["_adoption_id"] = operation_id
    index = existing_index if existing_index is not None else len(records)
    if existing_index is None:
        records.append(updated)
    else:
        records[existing_index] = updated
    if _revision(path) != current_revision:
        return jsonify({"error": "资料在保存时被另一个窗口更新。请刷新后重试。", "code": "revision_conflict"}), 409
    _atomic_write(path, _yaml_bytes(document))
    return jsonify({"record": _serialize_record(home, category, updated, index), "revision": _revision(path)})


def _save_basics_locked(home: Path, payload: dict[str, Any]) -> Any:
    basic_path = home / "data" / "basics.yaml"
    contact_path = home / "private" / "contact.yaml"
    revision = _revision(basic_path) + ":" + _revision(contact_path)
    if payload.get("revision") != revision:
        return jsonify({"error": "个人资料刚刚在另一个窗口中更新，请刷新后再保存。", "code": "revision_conflict"}), 409
    basics = load_yaml(basic_path)
    contact = load_contact(contact_path)
    basics_values = payload.get("basics", {})
    contact_values = payload.get("contact", {})
    if not isinstance(basics_values, dict) or not isinstance(contact_values, dict):
        return jsonify({"error": "个人资料格式不正确。"}), 400
    for key in {"name_en", "name_zh", "headline_en", "headline_zh", "research_interests", "research_interests_en"}:
        if key in basics_values:
            basics[key] = basics_values[key] if basics_values[key] is not None else ""
    for key in {"email", "phone", "github", "website", "location"}:
        if key in contact_values:
            value = contact_values[key]
            if value:
                contact[key] = value
            else:
                contact.pop(key, None)
    try:
        Draft202012Validator(_schema_for(home, "basics")).validate(basics)
    except Exception:
        return jsonify({"field_errors": {"name_en": "个人资料格式不正确。请检查姓名和研究兴趣。"}}), 422
    if _revision(basic_path) + ":" + _revision(contact_path) != revision:
        return jsonify({"error": "个人资料在保存时发生变化，请刷新后重试。", "code": "revision_conflict"}), 409
    _atomic_write(basic_path, _yaml_bytes(basics))
    _atomic_write(contact_path, _yaml_bytes(contact))
    return jsonify({"ok": True, "revision": _revision(basic_path) + ":" + _revision(contact_path)})
