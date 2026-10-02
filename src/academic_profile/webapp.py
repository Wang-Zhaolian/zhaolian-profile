"""Loopback-only browser interface backed by the existing YAML records."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml
from flask import Flask, abort, jsonify, render_template, request, send_file
from jsonschema import Draft202012Validator

from .backup import PRIVATE_PATHS, STAGE_PATHS, backup as do_backup, status as backup_status
from .content import build_document_context
from .constants import DATA_CATEGORIES, PROFILE_NAMES, REFERENCE_FIELDS, REFERENCE_LIST_FIELDS
from .dates import validate_date_string
from .errors import AcademicProfileError
from .generator import generate_profile
from .loader import load_contact, load_master_data, load_profile, load_yaml
from .pdf_renderer import render_pdf
from .selection import select_profile
from .ui_fields import CATEGORIES, FIELD_DEFINITIONS, FORM_FIELDS, PROFILE_LABELS
from .validation import validate_repository


ID_PREFIXES = {
    "education": "education", "research": "research", "publications": "paper",
    "projects": "project", "awards": "award", "competitions": "competition",
    "coursework": "course", "skills": "skill", "presentations": "presentation",
    "english": "english", "activities": "activity", "links": "link",
}
TITLE_FIELDS = {item["id"]: item["title_field"] for item in CATEGORIES}
PROFILE_LABELS = dict(PROFILE_LABELS)
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


def _labels() -> dict[str, str]:
    return {item["id"]: item["label"] for item in CATEGORIES}


def _record_title(category: str, record: dict[str, Any]) -> str:
    field = TITLE_FIELDS[category]
    return str(
        record.get(f"{field}_en")
        or record.get(field)
        or record.get(f"{field}_zh")
        or "未命名记录"
    )


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
    if category not in DATA_CATEGORIES:
        abort(404)
    return home / "data" / f"{category}.yaml"


def _serialize_record(category: str, record: dict[str, Any], index: int) -> dict[str, Any]:
    output = dict(record)
    output.setdefault("record_state", "ready")
    output.setdefault("cv_eligible", False)
    output.setdefault("priority", 3)
    output.setdefault("tags", [])
    output["_index"] = index
    output["_title"] = _record_title(category, output)
    output["_category_label"] = _labels()[category]
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
    return load_yaml(home / "schemas" / f"{category}.schema.yaml")


def _validate_ready(home: Path, category: str, record: dict[str, Any]) -> dict[str, str]:
    schema = _schema_for(home, category)
    record_schema = schema["properties"]["records"]["items"]
    errors: dict[str, str] = {}
    field_labels = {field[0]: field[1] for field in FIELD_DEFINITIONS[category]}
    for error in Draft202012Validator(record_schema).iter_errors(record):
        key = str(next(iter(error.absolute_path), "_form"))
        if error.validator == "required":
            missing = next(
                (field for field in record_schema.get("required", []) if field not in record),
                "_form",
            )
            key = missing
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
    for field, target in allowed_refs.items():
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
        target_doc = load_yaml(home / "data" / f"{target}.yaml")
        target_ids = {
            item.get("id") for item in target_doc.get("records", [])
            if item.get("record_state", "ready") == "ready"
            and not item.get("archived") and item.get("status") != "archived"
        }
        if any(item not in target_ids for item in record.get(field, [])):
            errors[field] = "关联的部分记录不存在，请重新选择。"

    for field in ("date", "start_date", "end_date", "expected_graduation", "last_used"):
        if record.get(field) and not validate_date_string(str(record[field])):
            errors[field] = "请使用 YYYY-MM 或 YYYY-MM-DD 格式。"
    for field in ("url", "repository", "demo", "presentation"):
        value = record.get(field)
        if value:
            parsed = urlparse(str(value))
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                errors[field] = "请输入完整的 http:// 或 https:// 链接。"
    if record.get("start_date") and record.get("end_date"):
        if str(record["end_date"]) < str(record["start_date"]):
            errors["end_date"] = "结束时间不能早于开始时间。"
    if category == "publications" and record.get("status") not in {
        "published", "accepted", "under_review", "submitted", "preprint", "manuscript"
    }:
        errors["status"] = "请选择论文的实际状态。"
    return errors


def _field_options(home: Path, category: str, field: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    output = dict(field)
    kind = str(field["type"])
    if kind.startswith("relation:") or kind.startswith("relation_one:"):
        target = kind.split(":", 1)[1]
        output["options"] = [
            {"id": record.get("id"), "label": _record_title(target, record)}
            for record in data.get(target, [])
            if record.get("record_state", "ready") == "ready"
            and not record.get("archived")
            and record.get("status") != "archived"
        ]
    elif kind.startswith("select:"):
        output["options"] = [
            value.strip() for value in kind.split(":", 1)[1].split(",")
        ]
    return output


def create_app(home: Path, *, static_root: Path | None = None) -> Flask:
    home = home.resolve()
    root = static_root or home
    ui_root = root / "templates"
    static_dir = root / "static"
    app = Flask(
        __name__,
        template_folder=str(ui_root),
        static_folder=str(static_dir),
    )
    app.config["HOME_ROOT"] = home

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
        return jsonify({"ok": True, "name": "academic-profile"})

    @app.get("/api/config")
    def get_config() -> Any:
        return jsonify({
            "categories": CATEGORIES,
            "fields": FORM_FIELDS,
            "profiles": PROFILE_LABELS,
            "privacy": {
                "local_only": True,
                "local_paths": list(PRIVATE_PATHS),
                "github_includes": list(STAGE_PATHS),
            },
        })

    @app.get("/api/dashboard")
    def dashboard() -> Any:
        home_root: Path = app.config["HOME_ROOT"]
        data = load_master_data(home_root / "data")
        category_counts: list[dict[str, Any]] = []
        drafts: list[dict[str, Any]] = []
        recent: list[dict[str, Any]] = []
        for category in CATEGORIES:
            records = data[category["id"]]
            active = [record for record in records if not record.get("archived")]
            category_counts.append({
                "id": category["id"], "label": category["label"],
                "count": len(active), "drafts": sum(r.get("record_state", "ready") == "draft" for r in active),
            })
            for record in active:
                if record.get("record_state", "ready") == "draft":
                    drafts.append({
                        "id": record.get("id"), "category": category["id"],
                        "category_label": category["label"], "title": _record_title(category["id"], record),
                    })
                modified = record.get("updated_at") or record.get("start_date") or record.get("date") or ""
                if modified:
                    recent.append({
                        "id": record.get("id"), "category": category["id"],
                        "category_label": category["label"], "title": _record_title(category["id"], record),
                        "updated_at": str(modified),
                    })
        recent.sort(key=lambda item: item["updated_at"], reverse=True)
        pending_validation = [
            str(issue) for issue in validate_repository(
                home_root / "data", home_root / "profiles", home_root / "schemas"
            ) if issue.severity == "error"
        ]
        return jsonify({
            "name": data["basics"].get("name_en") or data["basics"].get("name_zh") or "",
            "counts": category_counts,
            "total": sum(item["count"] for item in category_counts),
            "drafts": drafts,
            "recent": recent[:6],
            "validation_errors": len(pending_validation),
            "backup": _backup_status_json(home_root),
        })

    @app.get("/api/records/<category>")
    def get_records(category: str) -> Any:
        home_root: Path = app.config["HOME_ROOT"]
        path = _path_for(home_root, category)
        document = load_yaml(path)
        include_archived = request.args.get("archived", "0") == "1"
        query = request.args.get("q", "").strip().casefold()
        records = []
        for index, record in enumerate(document.get("records", [])):
            archived = bool(record.get("archived"))
            if bool(archived) != include_archived:
                continue
            title = _record_title(category, record)
            haystack = " ".join(str(value) for value in record.values()).casefold()
            if query and query not in haystack and query not in title.casefold():
                continue
            records.append(_serialize_record(category, record, index))
        return jsonify({"records": records, "revision": _revision(path)})

    @app.get("/api/records/<category>/<record_id>")
    def get_record(category: str, record_id: str) -> Any:
        home_root: Path = app.config["HOME_ROOT"]
        path = _path_for(home_root, category)
        document = load_yaml(path)
        for index, record in enumerate(document.get("records", [])):
            if record.get("id") == record_id:
                result = _serialize_record(category, record, index)
                result["revision"] = _revision(path)
                data = load_master_data(home_root / "data")
                result["fields"] = [
                    _field_options(home_root, category, field, data)
                    for field in FORM_FIELDS[category]
                ]
                return jsonify(result)
        abort(404)

    @app.post("/api/records/<category>")
    def save_record(category: str) -> Any:
        home_root: Path = app.config["HOME_ROOT"]
        path = _path_for(home_root, category)
        payload = request.get_json(silent=True) or {}
        with _path_lock(path):
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

    @app.get("/api/cv/<profile_name>")
    def cv_preview(profile_name: str) -> Any:
        if profile_name not in PROFILE_NAMES:
            abort(404)
        home_root: Path = app.config["HOME_ROOT"]
        data = load_master_data(home_root / "data")
        basics = data["basics"]
        if not (basics.get("name_en") or basics.get("name_zh")):
            return jsonify({"ready": False, "message": "请先在「个人资料」中填写姓名。"}), 200
        try:
            profile = load_profile(home_root / "profiles", profile_name)
            sections = select_profile(data, profile)
            context = build_document_context(
                data, profile, sections,
                load_contact(home_root / "private" / "contact.yaml"),
            )
        except Exception as exc:
            return jsonify({"ready": False, "message": str(exc)}), 422
        item_count = sum(len(section["items"]) for section in sections)
        if item_count == 0:
            return jsonify({"ready": False, "message": "目前没有可用于此版本的完整经历。请在分类中整理记录并勾选“用于简历”；空白简历不会生成。", "profile": profile_name, "label": PROFILE_LABELS[profile_name], "items": 0})
        return jsonify({"ready": True, "profile": profile_name, "label": PROFILE_LABELS.get(profile_name, profile_name), "context": context, "items": item_count})

    @app.post("/api/cv/<profile_name>/export/<format_name>")
    def cv_export(profile_name: str, format_name: str) -> Any:
        if profile_name not in PROFILE_NAMES or format_name not in {"pdf", "docx", "latex"}:
            abort(404)
        home_root: Path = app.config["HOME_ROOT"]
        master_data = load_master_data(home_root / "data")
        basics = master_data["basics"]
        if not (basics.get("name_en") or basics.get("name_zh")):
            return jsonify({"error": "请先在「个人资料」中填写姓名。"}), 422
        profile_config = load_profile(home_root / "profiles", profile_name)
        selected = select_profile(master_data, profile_config)
        if not any(section["items"] for section in selected):
            return jsonify({"error": "目前没有可用于此版本的完整经历。请整理记录并勾选“用于简历”。"}), 422
        output_dir = home_root / "output" / "platform" / profile_name
        if format_name == "pdf":
            context = build_document_context(master_data, profile_config, selected, load_contact(home_root / "private" / "contact.yaml"))
            path = render_pdf(context, output_dir / "cv.pdf")
            return send_file(path, as_attachment=True, download_name=f"academic-cv-{profile_name}.pdf", mimetype="application/pdf")
        generate_profile(
            profile_name,
            data_dir=home_root / "data", profile_dir=home_root / "profiles",
            schema_dir=home_root / "schemas", template_dir=home_root / "templates",
            output_root=home_root / "output" / "platform",
            contact_path=home_root / "private" / "contact.yaml",
            formats=(format_name,),
        )
        path = output_dir / ("cv.docx" if format_name == "docx" else "cv.tex")
        if not path.exists():
            return jsonify({"error": "无法生成所选格式。"}), 500
        mimetype = "application/vnd.openxmlformats-officedocument.wordprocessingml.document" if format_name == "docx" else "application/x-tex"
        return send_file(path, as_attachment=True, download_name=f"academic-cv-{profile_name}.{format_name}", mimetype=mimetype)

    @app.get("/api/backup/status")
    def get_backup_status() -> Any:
        return jsonify(_backup_status_json(app.config["HOME_ROOT"], refresh=request.args.get("refresh") == "1"))

    @app.post("/api/backup")
    def run_backup() -> Any:
        try:
            result = do_backup(app.config["HOME_ROOT"])
            return jsonify(_backup_json(result))
        except (RuntimeError, OSError, TimeoutError, subprocess.TimeoutExpired) as exc:
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

    @app.errorhandler(404)
    def not_found(error: Any) -> Any:
        return jsonify({"error": "没有找到这项内容。"}), 404

    return app


def _backup_json(result: Any) -> dict[str, Any]:
    return {
        "repository": result.repository,
        "is_private": result.is_private,
        "pending": result.pending,
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
                return jsonify({"record": _serialize_record(category, record, index), "revision": _revision(path)})
    abort(404)


def _save_record_locked(home: Path, category: str, path: Path, payload: dict[str, Any]) -> Any:
    current_revision = _revision(path)
    if payload.get("revision") != current_revision:
        return jsonify({"error": "这条资料刚刚在另一个窗口中更新。请刷新列表后重新编辑。", "code": "revision_conflict"}), 409
    document = load_yaml(path)
    records = document.setdefault("records", [])
    record_id = str(payload.get("id", "")).strip()
    existing_index = next(
        (index for index, record in enumerate(records) if record.get("id") == record_id), None
    ) if record_id else None
    if record_id and existing_index is None:
        return jsonify({"error": "这条记录已被其他窗口删除，请刷新列表。", "code": "record_missing"}), 409

    existing = dict(records[existing_index]) if existing_index is not None else {
        "id": _next_id(records, ID_PREFIXES[category]),
        "record_state": "draft", "cv_eligible": False, "priority": 3, "tags": [],
    }
    updated = dict(existing)
    editable_fields = {field[0] for field in FIELD_DEFINITIONS[category]}
    editable_fields |= {"cv_eligible", "priority", "tags", "record_state", "archived"}
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
        updated["cv_eligible"] = False
    else:
        field_errors = _validate_ready(home, category, updated)
        if field_errors:
            return jsonify({"field_errors": field_errors}), 422

    updated["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    index = existing_index if existing_index is not None else len(records)
    if existing_index is None:
        records.append(updated)
    else:
        records[existing_index] = updated
    if _revision(path) != current_revision:
        return jsonify({"error": "资料在保存时被另一个窗口更新。请刷新后重试。", "code": "revision_conflict"}), 409
    _atomic_write(path, _yaml_bytes(document))
    return jsonify({"record": _serialize_record(category, updated, index), "revision": _revision(path)})


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
    for key in {"name_en", "name_zh", "headline_en", "headline_zh", "research_interests"}:
        if key in basics_values:
            basics[key] = basics_values[key] if basics_values[key] is not None else ""
    for key in {"email", "github", "website", "location"}:
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
