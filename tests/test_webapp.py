from __future__ import annotations

import shutil
from io import BytesIO
from pathlib import Path

import yaml
from docx import Document

from academic_profile.webapp import create_app

ROOT = Path(__file__).resolve().parents[1]


def _client(home: Path):
    home.mkdir(parents=True)
    for directory in ("data", "schemas", "profiles", "templates"):
        shutil.copytree(ROOT / directory, home / directory)
    (home / "private").mkdir(parents=True)
    return create_app(home, static_root=ROOT).test_client()


def _post(client, url: str, payload: dict):
    return client.post(
        url, json=payload, headers={"X-Academic-Profile": "local-ui"},
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
    )


def _create_education(client, *, state: str, degree: str, revision: str):
    return _post(client, "/api/records/education", {
        "revision": revision,
        "record": {
            "degree": degree,
            "record_state": state,
            "cv_eligible": True,
            "priority": 1,
            "tags": [],
        },
    })


def test_empty_platform_and_incomplete_draft_do_not_block_cv(tmp_path: Path) -> None:
    client = _client(tmp_path / "home")
    dashboard = client.get("/api/dashboard").get_json()
    assert dashboard["total"] == 0
    assert all(item["count"] == 0 for item in dashboard["counts"])
    assert client.get("/api/cv/phd").get_json()["ready"] is False

    first = client.get("/api/records/education").get_json()
    draft = _create_education(client, state="draft", degree="Draft Only", revision=first["revision"])
    assert draft.status_code == 200
    draft_id = draft.get_json()["record"]["id"]

    # Deliberately incomplete drafts are valid, saved locally, and never CV eligible.
    record_doc = yaml.safe_load((tmp_path / "home" / "data" / "education.yaml").read_text(encoding="utf-8"))
    assert record_doc["records"][0]["record_state"] == "draft"
    assert record_doc["records"][0]["cv_eligible"] is False

    incomplete_ready = _post(client, "/api/records/education", {
        "revision": draft.get_json()["revision"],
        "record": {"degree": "BS", "record_state": "ready", "cv_eligible": True, "priority": 1},
    })
    assert incomplete_ready.status_code == 422
    assert "institution" in incomplete_ready.get_json()["field_errors"]

    stale = _create_education(client, state="draft", degree="Conflicting Draft", revision=first["revision"])
    assert stale.status_code == 409

    basics = client.get("/api/basics").get_json()
    saved_basics = _post(client, "/api/basics", {
        "revision": basics["revision"],
        "basics": {"name_en": "Example Student", "research_interests": []},
        "contact": {"email": "student@example.org"},
    })
    assert saved_basics.status_code == 200
    assert yaml.safe_load((tmp_path / "home" / "private" / "contact.yaml").read_text(encoding="utf-8"))["email"] == "student@example.org"
    assert "email" not in (tmp_path / "home" / "data" / "basics.yaml").read_text(encoding="utf-8")

    current = client.get("/api/records/education").get_json()
    ready = _post(client, "/api/records/education", {
        "revision": current["revision"],
        "record": {
            "institution": "示例大学", "degree": "BS", "major": "Computer Science",
            "start_date": "2022-09", "expected_graduation": "2026-06",
            "record_state": "ready", "cv_eligible": True, "priority": 1,
        },
    })
    assert ready.status_code == 200
    assert ready.get_json()["record"]["id"] != draft_id
    preview = client.get("/api/cv/phd").get_json()
    assert preview["ready"] is True
    assert preview["items"] == 1
    assert "Draft Only" not in str(preview["context"])
    assert "示例大学" in str(preview["context"])


def test_all_five_profiles_export_pdf_word_and_latex_from_same_selection(tmp_path: Path) -> None:
    client = _client(tmp_path / "home")
    basics = client.get("/api/basics").get_json()
    assert _post(client, "/api/basics", {
        "revision": basics["revision"], "basics": {"name_en": "Example Student", "research_interests": []}, "contact": {},
    }).status_code == 200
    records = client.get("/api/records/education").get_json()
    complete = _post(client, "/api/records/education", {
        "revision": records["revision"],
        "record": {
            "institution": "示例大学 Example University", "degree": "BS", "major": "Computer Science",
            "start_date": "2022-09", "expected_graduation": "2026-06",
            "cv_bullets": ["负责实验分析与结果核查，确保不同实验设置下的记录一致。" for _ in range(65)],
            "record_state": "ready", "cv_eligible": True, "priority": 1,
        },
    })
    assert complete.status_code == 200

    for profile in ("phd", "ra", "summer_research", "domestic", "internship"):
        preview = client.get(f"/api/cv/{profile}").get_json()
        assert preview["ready"] is True
        assert preview["items"] == 1
        for format_name in ("pdf", "docx", "latex"):
            response = _post(client, f"/api/cv/{profile}/export/{format_name}?lang=en", {})
            assert response.status_code == 200
            data = response.data
            if format_name == "pdf":
                assert data.startswith(b"%PDF")
            elif format_name == "docx":
                document = Document(BytesIO(data))
                text = "\n".join(p.text for p in document.paragraphs)
                assert "Example Student" in text
            else:
                text = data.decode("utf-8")
                assert "Example Student" in text
                assert "BS in Computer Science" in text


def test_chinese_only_profile_can_preview_and_phone_can_be_hidden(tmp_path: Path) -> None:
    client = _client(tmp_path / "home")
    basics = client.get("/api/basics").get_json()
    saved_basics = _post(client, "/api/basics", {
        "revision": basics["revision"],
        "basics": {
            "name_en": "", "name_zh": "测试者", "research_interests": ["计算机视觉"],
            "research_interests_en": [],
        },
        "contact": {"phone": "+86 138 0000 0000"},
    })
    assert saved_basics.status_code == 200
    records = client.get("/api/records/education").get_json()
    ready = _post(client, "/api/records/education", {
        "revision": records["revision"],
        "record": {
            "institution_zh": "示例大学", "degree_zh": "学士", "major_zh": "计算机科学",
            "start_date": "2022-09", "expected_graduation": "2026-06",
            "record_state": "ready", "cv_eligible": True, "priority": 1,
        },
    })
    assert ready.status_code == 200
    preview = client.get("/api/cv/phd").get_json()
    assert preview["ready"] is True
    assert preview["context"]["name"] == "测试者"
    assert preview["context"]["contact"] == [{"label": "电话", "value": "+86 138 0000 0000"}]
    assert "计算机视觉" in str(preview["context"])

    english = client.get("/api/cv/phd?lang=en&include_phone=0").get_json()
    assert english["ready"] is True
    assert any("姓名" in warning for warning in english["context"]["warnings"])
    assert english["context"]["contact"] == []
    exported = _post(client, "/api/cv/phd/export/latex?lang=en&include_phone=0", {})
    assert exported.status_code == 200
    assert "+86 138 0000 0000" not in exported.get_data(as_text=True)


def test_archive_restore_and_local_only_access(tmp_path: Path) -> None:
    client = _client(tmp_path / "home")
    records = client.get("/api/records/awards").get_json()
    created = _post(client, "/api/records/awards", {
        "revision": records["revision"], "record": {"name": "Unfinished award", "record_state": "draft"},
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
