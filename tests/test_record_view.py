from __future__ import annotations

import yaml

from academic_profile.record_view import _date, _numeric
from academic_profile.webapp import create_app
from test_webapp import ROOT, _client, _post


def test_numeric_and_date_parsing_is_deliberate():
    assert [_numeric(value) for value in ("9", "80", "100", "3.5学分", "89分", "12.5%", "-1,200.5公里")] == [9, 80, 100, 3.5, 89, 12.5, -1200.5]
    assert _numeric("2025-2026学年第1学期") is None
    assert _numeric("课程2") is None
    assert _numeric("3/4") is None
    assert _date("2026") .isoformat() == "2026-01-01"
    assert _date("2026-10") .isoformat() == "2026-10-01"
    assert _date("2026-10-07").isoformat() == "2026-10-07"
    assert _date("2026-13") is None


def test_search_is_title_only_and_numeric_sort_keeps_missing_last(tmp_path):
    home = tmp_path / "home"
    client = _client(home)
    path = home / "data" / "coursework.yaml"
    records = [
        {"id": "course_001", "course_name": "管理学", "institution": "甲校", "grade": "100分", "record_state": "draft"},
        {"id": "course_002", "course_name": "数学分析", "institution": "乙校", "grade": "9", "record_state": "draft"},
        {"id": "course_003", "course_name": "统计学", "institution": "丙校", "grade": "80", "record_state": "draft"},
        {"id": "course_004", "course_name": "经济学", "institution": "目标关键词", "grade": "待补充", "record_state": "draft"},
    ]
    path.write_text(yaml.safe_dump({"records": records}, allow_unicode=True), encoding="utf-8")

    title_match = client.get("/api/records/coursework?q=分析").get_json()["records"]
    assert [item["course_name"] for item in title_match] == ["数学分析"]
    assert client.get("/api/records/coursework?q=关键词").get_json()["records"] == []

    ascending = client.get("/api/records/coursework?sort_by=grade&sort_direction=asc").get_json()
    assert [item["id"] for item in ascending["records"]] == ["course_002", "course_003", "course_001", "course_004"]
    descending = client.get("/api/records/coursework?sort_by=grade&sort_direction=desc").get_json()
    assert [item["id"] for item in descending["records"]] == ["course_001", "course_003", "course_002", "course_004"]
    assert any(item["key"] == "grade" and item["type"] == "number" for item in ascending["sort_fields"])
    assert client.get("/api/records/coursework?sort_by=course_name").status_code == 400
    assert client.get("/api/records/coursework?sort_direction=sideways").status_code == 400


def test_private_preferences_persist_model_and_category_sort(tmp_path):
    home = tmp_path / "home"
    client = _client(home)
    model = _post(client, "/api/preferences", {"ai_model": "gpt-test-model"})
    assert model.status_code == 405  # Preferences are updated with PATCH only.
    saved = client.patch("/api/preferences", json={"ai_model": "gpt-test-model"}, headers={"X-Academic-Profile": "local-ui"}, environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert saved.status_code == 200
    sorted_pref = client.patch("/api/preferences", json={"sorts": {"coursework": {"sort_by": "grade", "direction": "desc"}}}, headers={"X-Academic-Profile": "local-ui"}, environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert sorted_pref.status_code == 422  # No numeric course grades have been entered yet.
    assert client.get("/api/preferences").get_json()["ai_model"] == "gpt-test-model"

    path = home / "data" / "coursework.yaml"
    path.write_text(yaml.safe_dump({"records": [{"id": "course_001", "course_name": "管理学", "grade": "89分", "record_state": "draft"}]}, allow_unicode=True), encoding="utf-8")
    saved_sort = client.patch("/api/preferences", json={"sorts": {"coursework": {"sort_by": "grade", "direction": "desc"}}}, headers={"X-Academic-Profile": "local-ui"}, environ_overrides={"REMOTE_ADDR": "127.0.0.1"})
    assert saved_sort.status_code == 200
    reopened = create_app(home, static_root=ROOT).test_client()
    assert reopened.get("/api/preferences").get_json() == saved_sort.get_json()
    assert (home / "private" / "preferences.local.json").exists()
    assert "private" not in saved_sort.get_json()


def test_config_preview_keys_follow_form_order_and_limit_five(tmp_path):
    client = _client(tmp_path / "home")
    config = client.get("/api/config").get_json()
    coursework = next(item for item in config["categories"] if item["id"] == "coursework")
    ordered = [field["key"] for field in config["fields"]["coursework"]]
    assert coursework["preview_field_keys"] == ordered[:5]
    assert coursework["preview_field_keys"][0] == "course_name"
