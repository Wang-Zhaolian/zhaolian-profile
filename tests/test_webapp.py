from __future__ import annotations

import shutil
from pathlib import Path

import yaml

from academic_profile.categories import default_registry
from academic_profile.webapp import create_app

ROOT = Path(__file__).resolve().parents[1]


def _client(home: Path):
    home.mkdir(parents=True)
    shutil.copytree(ROOT / "schemas", home / "schemas")
    data = home / "data"
    data.mkdir()
    registry = default_registry()
    basics = {
        "version": 1, "name_en": "", "name_zh": "", "headline_en": "", "headline_zh": "",
        "research_interests": [], "research_interests_en": [],
    }
    (data / "basics.yaml").write_text(yaml.safe_dump(basics, allow_unicode=True), encoding="utf-8")
    for category in registry["categories"]:
        (data / f"{category['id']}.yaml").write_text("records: []\n", encoding="utf-8")
    (home / "private").mkdir()
    return create_app(home, static_root=ROOT).test_client()


def _post(client, url: str, payload: dict):
    return client.post(
        url, json=payload, headers={"X-Academic-Profile": "local-ui"},
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
    )


def test_empty_dashboard_null_id_save_and_cv_routes_are_disabled(tmp_path: Path) -> None:
    client = _client(tmp_path / "home")
    from academic_profile import __version__
    assert client.get("/api/health").get_json()["version"] == __version__
    dashboard = client.get("/api/dashboard").get_json()
    assert dashboard["total"] == 0
    assert len(dashboard["counts"]) == 12
    assert all(item["count"] == 0 for item in dashboard["counts"])
    for method, url in (("get", "/api/cv/phd"), ("post", "/api/cv/phd/export/pdf"), ("delete", "/api/cv")):
        response = getattr(client, method)(url, json={} if method != "get" else None,
                                           headers={"X-Academic-Profile": "local-ui"},
                                           environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
        assert response.status_code == 410
        assert response.get_json()["code"] == "feature_removed"

    first = client.get("/api/records/education").get_json()
    saved = _post(client, "/api/records/education", {
        "id": None,
        "revision": first["revision"],
        "record": {"degree": "暂存本科", "record_state": "draft"},
    })
    assert saved.status_code == 200
    record = saved.get_json()["record"]
    assert record["id"] == "education_001"
    assert record["record_state"] == "draft"
    document = yaml.safe_load((tmp_path / "home" / "data" / "education.yaml").read_text(encoding="utf-8"))
    assert document["records"][0]["id"] == record["id"]
    assert "None" not in str(document)

    empty_id = _post(client, "/api/records/education", {
        "id": "", "revision": saved.get_json()["revision"],
        "record": {"degree_zh": "中文草稿", "record_state": "draft"},
    })
    assert empty_id.status_code == 200
    bad_id = _post(client, "/api/records/education", {
        "id": "education_999", "revision": empty_id.get_json()["revision"], "record": {"record_state": "draft"},
    })
    assert bad_id.status_code == 409
    stale = _post(client, "/api/records/education", {
        "revision": saved.get_json()["revision"], "record": {"record_state": "draft"},
    })
    assert stale.status_code == 409


def test_custom_category_fields_revision_validation_and_archive_restore(tmp_path: Path) -> None:
    home = tmp_path / "home"
    client = _client(home)
    config = client.get("/api/config").get_json()
    created = _post(client, "/api/categories", {"label": "志愿经历", "revision": config["revision"]})
    assert created.status_code == 201
    category = created.get_json()["category"]
    category_id = category["id"]

    config = client.get("/api/config").get_json()
    added = _post(client, f"/api/categories/{category_id}/fields", {
        "revision": config["revision"], "label": "服务时数", "type": "number", "required": True,
    })
    assert added.status_code == 201
    field_key = added.get_json()["field"]["key"]

    config = client.get("/api/config").get_json()
    multi = _post(client, f"/api/categories/{category_id}/fields", {
        "revision": config["revision"], "label": "参与主题", "type": "multiselect",
        "options": ["实验", "分析"],
    })
    assert multi.status_code == 201
    multi_key = multi.get_json()["field"]["key"]

    # A stale registry editor must not silently overwrite the current schema.
    stale_rename = _post(client, f"/api/categories/{category_id}", {
        "revision": config["revision"], "label": "旧名称",
    })
    assert stale_rename.status_code == 409

    config = client.get("/api/config").get_json()
    records = client.get(f"/api/records/{category_id}").get_json()
    incomplete = _post(client, f"/api/records/{category_id}", {
        "revision": records["revision"],
        "record": {"title": "校内志愿服务", "record_state": "ready"},
    })
    assert incomplete.status_code == 422
    assert field_key in incomplete.get_json()["field_errors"]

    records = client.get(f"/api/records/{category_id}").get_json()
    created_record = _post(client, f"/api/records/{category_id}", {
        "revision": records["revision"],
        "record": {"title": "校内志愿服务", field_key: 12, multi_key: ["分析"], "record_state": "ready"},
    })
    assert created_record.status_code == 200
    record_id = created_record.get_json()["record"]["id"]

    config = client.get("/api/config").get_json()
    required_add = _post(client, f"/api/categories/{category_id}/fields", {
        "revision": config["revision"], "label": "负责人", "type": "text", "required": True,
    })
    assert required_add.status_code == 422

    config = client.get("/api/config").get_json()
    remove_option = _post(client, f"/api/categories/{category_id}/fields/{multi_key}", {
        "revision": config["revision"], "label": "参与主题", "type": "multiselect",
        "options": ["实验"], "required": False,
    })
    assert remove_option.status_code == 422
    assert "不能移除或更名" in remove_option.get_json()["error"]

    config = client.get("/api/config").get_json()
    field_update = _post(client, f"/api/categories/{category_id}/fields/{field_key}", {
        "revision": config["revision"], "label": "服务时数", "type": "text", "required": True,
    })
    assert field_update.status_code == 422
    assert "不能直接更改类型" in field_update.get_json()["error"]

    config = client.get("/api/config").get_json()
    renamed = _post(client, f"/api/categories/{category_id}", {
        "revision": config["revision"], "label": "公益服务", "order": 0,
    })
    assert renamed.status_code == 200
    assert client.get(f"/api/records/{category_id}/{record_id}").get_json()["_category_label"] == "公益服务"
    reopened = create_app(home, static_root=ROOT).test_client()
    reopened_config = reopened.get("/api/config").get_json()
    assert any(item["id"] == category_id and item["label"] == "公益服务" for item in reopened_config["categories"])
    assert reopened.get(f"/api/records/{category_id}/{record_id}").status_code == 200

    config = client.get("/api/config").get_json()
    archived = _post(client, f"/api/categories/{category_id}", {
        "revision": config["revision"], "archived": True,
    })
    assert archived.status_code == 200
    assert category_id not in {item["id"] for item in client.get("/api/config").get_json()["categories"]}
    assert category_id in {item["id"] for item in client.get("/api/config").get_json()["all_categories"]}

    config = client.get("/api/config").get_json()
    restored = _post(client, f"/api/categories/{category_id}", {
        "revision": config["revision"], "archived": False,
    })
    assert restored.status_code == 200
    assert client.get(f"/api/records/{category_id}/{record_id}").status_code == 200


def test_archive_restore_records_and_local_only_access(tmp_path: Path) -> None:
    client = _client(tmp_path / "home")
    records = client.get("/api/records/awards").get_json()
    created = _post(client, "/api/records/awards", {
        "revision": records["revision"], "record": {"name": "待补充奖项", "record_state": "draft"},
    })
    assert created.status_code == 200
    record_id = created.get_json()["record"]["id"]
    revision = created.get_json()["revision"]
    archived = _post(client, f"/api/records/awards/{record_id}/archive", {"revision": revision})
    assert archived.status_code == 200
    assert len(client.get("/api/records/awards?archived=1").get_json()["records"]) == 1
    restored = _post(client, f"/api/records/awards/{record_id}/restore", {"revision": archived.get_json()["revision"]})
    assert restored.status_code == 200
    assert len(client.get("/api/records/awards?archived=0").get_json()["records"]) == 1
    blocked = client.get("/api/health", headers={"Host": "example.org"})
    assert blocked.status_code == 403


def test_chinese_profile_save_preserves_hidden_english_and_clears_contact(tmp_path: Path) -> None:
    home = tmp_path / "home"
    client = _client(home)
    basics_path = home / "data" / "basics.yaml"
    basics = yaml.safe_load(basics_path.read_text(encoding="utf-8"))
    basics["name_en"] = "Legacy English Name"
    basics_path.write_text(yaml.safe_dump(basics, allow_unicode=True), encoding="utf-8")

    current = client.get("/api/basics").get_json()
    saved = _post(client, "/api/basics", {
        "revision": current["revision"],
        "basics": {"name_zh": "昭濂", "research_interests": ["数字人文"]},
        "contact": {"phone": "+86 138 0000 0000"},
    })
    assert saved.status_code == 200
    assert yaml.safe_load(basics_path.read_text(encoding="utf-8"))["name_en"] == "Legacy English Name"

    current = client.get("/api/basics").get_json()
    cleared = _post(client, "/api/basics", {
        "revision": current["revision"],
        "basics": {"name_zh": "昭濂", "research_interests": ["数字人文"]},
        "contact": {"phone": ""},
    })
    assert cleared.status_code == 200
    assert "phone" not in yaml.safe_load((home / "private" / "contact.yaml").read_text(encoding="utf-8"))

    config = client.get("/api/config").get_json()
    assert all(not field["key"].endswith("_en") for fields in config["fields"].values() for field in fields)


def test_candidate_update_uses_review_revision_and_retries_idempotently(tmp_path: Path) -> None:
    client = _client(tmp_path / "home")
    initial = client.get("/api/records/awards").get_json()
    created = _post(client, "/api/records/awards", {
        "revision": initial["revision"], "record": {"name": "原始名称", "record_state": "draft"},
    })
    record_id = created.get_json()["record"]["id"]

    reviewed = client.get("/api/records/awards").get_json()
    operation_id = "a" * 32
    accepted = _post(client, "/api/records/awards", {
        "id": record_id, "revision": reviewed["revision"], "operation_id": operation_id,
        "record": {"name": "人工确认的新名称", "record_state": "draft"},
    })
    assert accepted.status_code == 200

    retry = _post(client, "/api/records/awards", {
        "id": record_id, "revision": reviewed["revision"], "operation_id": operation_id,
        "record": {"name": "人工确认的新名称", "record_state": "draft"},
    })
    assert retry.status_code == 200
    assert retry.get_json()["already_saved"] is True

    stale_review = client.get("/api/records/awards").get_json()
    concurrent = _post(client, "/api/records/awards", {
        "id": record_id, "revision": stale_review["revision"],
        "record": {"name": "另一个窗口的新名称", "record_state": "draft"},
    })
    assert concurrent.status_code == 200
    conflict = _post(client, "/api/records/awards", {
        "id": record_id, "revision": stale_review["revision"], "operation_id": "b" * 32,
        "record": {"name": "过期候选", "record_state": "draft"},
    })
    assert conflict.status_code == 409
    current = client.get(f"/api/records/awards/{record_id}").get_json()
    assert current["name"] == "另一个窗口的新名称"
