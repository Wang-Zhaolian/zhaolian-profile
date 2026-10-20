from copy import deepcopy
from pathlib import Path

import yaml

from academic_profile.ai_workflow import add_proposal_batch, get_note, list_notes, save_note, update_candidate
from academic_profile.categories import default_registry, load_registry, save_registry
from academic_profile.webapp import create_app
from test_webapp import ROOT, _client, _post


def test_category_settings_are_atomic_and_keep_deleted_values(tmp_path):
    home = tmp_path / "home"
    client = _client(home)
    config = client.get("/api/config").get_json()
    fields = [{"key": "institution", "deleted": True},
              {"key": "semester", "label": "学习阶段", "order": 1, "required": False},
              {"label": "心得", "type": "textarea", "order": 20}]
    revision = client.get("/api/records/coursework").get_json()["revision"]
    record = _post(client, "/api/records/coursework", {"revision": revision, "record": {
        "course_name": "管理学", "institution": "保留的学校", "record_state": "draft",
    }}).get_json()["record"]
    result = _post(client, "/api/categories/coursework/settings", {
        "revision": config["revision"], "label": "课程学习", "fields": fields,
    })
    assert result.status_code == 200
    updated = client.get("/api/config").get_json()
    visible = updated["fields"]["coursework"]
    assert "institution" not in {field["key"] for field in visible}
    assert any(field["label"] == "心得" for field in visible)
    assert any(field["label"] == "学习阶段" and not field["required_for_ready"] for field in visible)
    assert client.get(f"/api/records/coursework/{record['id']}").get_json()["institution"] == "保留的学校"
    old_bytes = (home / "data/categories.yaml").read_bytes()
    failed = _post(client, "/api/categories/coursework/settings", {
        "revision": updated["revision"], "label": "不应保存", "fields": [{"key": "course_name", "deleted": True}],
    })
    assert failed.status_code == 422
    assert (home / "data/categories.yaml").read_bytes() == old_bytes
    assert _post(client, "/api/categories/coursework/settings", {"revision": config["revision"], "label": "过期"}).status_code == 409
    reopened = create_app(home, static_root=ROOT).test_client()
    assert reopened.get("/api/config").get_json()["fields"]["coursework"] == visible


def test_all_field_edits_roll_back_when_one_is_invalid(tmp_path):
    client = _client(tmp_path / "home")
    cfg = client.get("/api/config").get_json()
    revision = client.get("/api/records/coursework").get_json()["revision"]
    _post(client, "/api/records/coursework", {"revision": revision, "record": {"course_name": "管理学", "record_state": "draft"}})
    invalid = _post(client, "/api/categories/coursework/settings", {"revision": cfg["revision"], "fields": [
        {"key": "semester", "label": "不应保存"}, {"key": "course_name", "type": "number"},
    ]})
    assert invalid.status_code == 422
    assert client.get("/api/config").get_json() == cfg


def test_dates_optional_and_new_required_field_protects_ready_records(tmp_path):
    home = tmp_path / "home"
    client = _client(home)
    registry = default_registry()
    for category in registry["categories"]:
        for field in category["fields"]:
            if field["type"] == "date":
                field["required"] = True  # Legacy configuration must also work.
    save_registry(home, registry)
    cfg = client.get("/api/config").get_json()
    assert all(not field["required_for_ready"] for fields in cfg["fields"].values() for field in fields if field["type"] == "date")
    revision = client.get("/api/records/education").get_json()["revision"]
    saved = _post(client, "/api/records/education", {"revision": revision, "record": {
        "institution": "测试大学", "degree": "本科", "major": "管理学", "record_state": "ready",
    }})
    assert saved.status_code == 200, saved.get_json()
    invalid = _post(client, "/api/categories/education/settings", {"revision": cfg["revision"], "fields": [
        {"label": "新增必填", "type": "text", "required": True},
    ]})
    assert invalid.status_code == 422
    assert client.get("/api/config").get_json()["revision"] == cfg["revision"]


def test_registry_cache_is_isolated_and_invalidates(tmp_path):
    home = tmp_path / "home"
    _client(home)
    save_registry(home, default_registry())
    snapshot = deepcopy(load_registry(home))
    edited = load_registry(home)
    edited["categories"][0]["label"] = "独立修改"
    assert load_registry(home) == snapshot
    save_registry(home, edited)
    assert load_registry(home)["categories"][0]["label"] == "独立修改"


def test_partial_review_stays_and_complete_review_disappears(tmp_path):
    home = tmp_path / "home"
    _client(home)
    note = save_note(home, "课程和奖项")
    batch = add_proposal_batch(home, note["id"], [
        {"category": "coursework", "fields": {"course_name": "课程"}},
        {"category": "awards", "fields": {"name": "奖项"}},
    ], [])
    first, second = [item["operation_id"] for item in batch["candidates"]]
    update_candidate(home, note["id"], batch["id"], first, "adopted")
    assert list_notes(home)[0]["pending_candidates"] == 1
    update_candidate(home, note["id"], batch["id"], second, "pending", {"name": "人工修改"}, "projects")
    stored = get_note(home, note["id"], include_storage=True)["batches"][0]["candidates"][1]
    assert stored["category"] == "projects" and stored["fields"] == {"name": "人工修改"}
    update_candidate(home, note["id"], batch["id"], second, "discarded")
    assert list_notes(home) == []
    # A late retry cannot reopen or duplicate a completed candidate.
    update_candidate(home, note["id"], batch["id"], first, "pending")
    assert list_notes(home) == []
    assert get_note(home, note["id"])["text"] == "课程和奖项"


def test_unselected_attachments_are_not_lost(tmp_path):
    home = tmp_path / "home"
    _client(home)
    note = save_note(home, "分批处理", [("one.txt", b"one"), ("two.txt", b"two")])
    first, second = [item["id"] for item in note["attachments"]]
    batch = add_proposal_batch(home, note["id"], [{"category": "awards", "fields": {"name": "测试"}}], [first])
    update_candidate(home, note["id"], batch["id"], batch["candidates"][0]["operation_id"], "adopted")
    assert len(list_notes(home)) == 1
    remaining = add_proposal_batch(home, note["id"], [{"category": "awards", "fields": {"name": "另一个"}}], [second])
    update_candidate(home, note["id"], remaining["id"], remaining["candidates"][0]["operation_id"], "discarded")
    assert list_notes(home) == []


def test_unsaved_adoption_cannot_remove_draft_and_cross_category_retry_cannot_duplicate(tmp_path):
    home = tmp_path / "home"
    client = _client(home)
    note = save_note(home, "测试")
    batch = add_proposal_batch(home, note["id"], [{"category": "awards", "fields": {"name": "测试"}}], [])
    operation = batch["candidates"][0]["operation_id"]
    url = f"/api/ai/notes/{note['id']}/batches/{batch['id']}/candidates/{operation}"
    assert _post(client, url, {"status": "adopted"}).status_code == 409
    revision = client.get("/api/records/awards").get_json()["revision"]
    assert _post(client, "/api/records/awards", {"revision": revision, "operation_id": operation, "record": {"name": "测试"}}).status_code == 200
    revision = client.get("/api/records/projects").get_json()["revision"]
    assert _post(client, "/api/records/projects", {"revision": revision, "operation_id": operation, "record": {"name": "不能重复"}}).status_code == 409
    assert _post(client, url, {"status": "adopted"}).status_code == 200
    assert client.get("/api/ai/notes").get_json()["notes"] == []


def test_dashboard_does_not_wait_for_backup_network(tmp_path, monkeypatch):
    client = _client(tmp_path / "home")
    monkeypatch.setattr("academic_profile.webapp._backup_status_json", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network status should not run")))
    assert client.get("/api/dashboard").status_code == 200
