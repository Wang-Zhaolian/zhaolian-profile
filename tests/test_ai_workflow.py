from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from academic_profile.ai_workflow import (
    build_context,
    get_note,
    list_notes,
    parse_proposals,
    save_note,
)
from academic_profile.constants import DATA_CATEGORIES


def _empty_home(home: Path) -> Path:
    data_dir = home / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "basics.yaml").write_text(
        yaml.safe_dump({"name_en": "Synthetic Scholar", "research_interests": ["Graph theory"]}), encoding="utf-8"
    )
    for category in DATA_CATEGORIES:
        (data_dir / f"{category}.yaml").write_text("version: 1\nrecords: []\n", encoding="utf-8")
    return home


def _records(home: Path, category: str, records: list[dict]) -> None:
    (home / "data" / f"{category}.yaml").write_text(
        yaml.safe_dump({"version": 1, "records": records}, allow_unicode=True), encoding="utf-8"
    )


def test_raw_notes_live_only_in_private_directory_and_are_addressed_by_id(tmp_path: Path) -> None:
    home = _empty_home(tmp_path / "home")
    raw = "Research paper note; email private@example.org; C:\\Users\\me\\proof.pdf"
    saved = save_note(home, raw)
    assert saved["text"] == raw
    note_file = home / "private" / "ai_notes" / f"{saved['id']}.json"
    assert note_file.exists()
    assert not (home / "data" / "ai_notes").exists()
    assert get_note(home, saved["id"])["text"] == raw
    listed = list_notes(home)
    assert len(listed) == 1
    assert "text" not in listed[0]
    with pytest.raises(ValueError, match="笔记编号无效"):
        get_note(home, "../contact")
    with pytest.raises(ValueError, match="请先输入"):
        save_note(home, " \n")


def test_context_includes_all_structured_records_but_no_private_sources(tmp_path: Path) -> None:
    home = _empty_home(tmp_path / "home")
    _records(home, "research", [{
        "id": "research_001", "title": "Graph Study", "record_state": "draft",
        "description": "Investigated graph methods with private@example.org",
        "raw_details": "Detailed method notes C:\\Users\\me\\proof.pdf",
        "evidence": ["C:\\Users\\me\\certificate.pdf"],
        "paper_ids": ["paper_001"],
    }])
    _records(home, "awards", [{
        "id": "award_001", "name": "Academic Award", "archived": True,
        "evidence": ["https://private.example.org/proof"],
    }])
    (home / "private").mkdir(exist_ok=True)
    (home / "private" / "contact.yaml").write_text("email: hidden-contact@example.org\n", encoding="utf-8")
    save_note(home, "Old note secret phrase")

    context = build_context(home, "Graph Study by private@example.org at C:\\Users\\me\\draft.pdf")
    assert context["mode"] == "full"
    assert context["record_count"] == 2
    assert context["full_record_count"] == 2
    assert {item["record_state"] for item in context["records"]} == {"ready", "draft"}
    serialized = json.dumps(context, ensure_ascii=False)
    assert "Detailed method notes" in serialized
    assert context["profile"] == {"name_en": "Synthetic Scholar", "research_interests": ["Graph theory"]}
    assert "Old note secret phrase" not in serialized
    assert "hidden-contact@example.org" not in serialized
    assert "private@example.org" not in serialized
    assert "C:\\Users\\me" not in serialized
    assert "certificate.pdf" not in serialized
    assert "paper_001" not in serialized
    assert "https://private.example.org/proof" not in serialized


def test_long_context_uses_all_record_synopsis_and_only_fitting_full_records(tmp_path: Path) -> None:
    home = _empty_home(tmp_path / "home")
    _records(home, "research", [
        {"id": f"research_{index:03d}", "title": f"Research {index}", "record_state": "draft",
         "description": "Long descriptive details " + "methodology " * 90}
        for index in range(1, 4)
    ])
    context = build_context(home, "Research 2", max_chars=800)
    assert context["mode"] == "summary"
    assert context["record_count"] == 3
    assert len(context["synopsis"]) == 3
    assert context["full_record_count"] < 3
    assert context["profile"]["name_en"] == "Synthetic Scholar"
    assert all(item["record_state"] == "draft" for item in context["synopsis"])


def test_proposals_allowlist_and_local_duplicate_hints(tmp_path: Path) -> None:
    home = _empty_home(tmp_path / "home")
    _records(home, "awards", [{"id": "award_001", "name": "Excellence Award", "organizer": "University"}])
    note = "I received the Excellence Award from University in 2025-06."
    model_output = {"candidates": [
        {
            "category": "awards",
            "fields": {
                "name": "Excellence Award", "organizer": "University", "date": "2025-06",
                "description": "Won it. Contact private@example.org for details.",
                "evidence": ["C:\\Users\\me\\certificate.pdf"],
                "id": "award_999", "record_state": "ready", "fabricated_key": "fake",
            },
            "source_excerpt": "Excellence Award from University",
            "possible_duplicates": [{"id": "award_999", "score": 1}],
        },
        {
            "category": "publications",
            "fields": {"title": "Paper draft", "status": "published in future"},
            "source_excerpt": "not actually in the note",
        },
        {
            "category": "research",
            "fields": {"title": "Draft inquiry", "raw_details": "Observed initial pattern"},
            "source_excerpt": "",
        },
    ]}
    proposals = parse_proposals(home, "```json\n" + json.dumps(model_output) + "\n```", note)
    assert len(proposals) == 3
    award = proposals[0]
    assert award["fields"]["date"] == "2025-06"
    assert "private@example.org" not in award["fields"]["description"]
    assert not ({"evidence", "id", "record_state", "fabricated_key"} & award["fields"].keys())
    assert award["possible_duplicates"][0]["id"] == "award_001"
    assert award["source_excerpt"] == "Excellence Award from University"
    assert "status" not in proposals[1]["fields"]
    assert proposals[1]["source_excerpt"] == ""
    assert proposals[1]["warnings"]
    assert proposals[2]["fields"]["raw_details"] == "Observed initial pattern"
    with pytest.raises(ValueError, match="有效 JSON"):
        parse_proposals(home, "not JSON", note)
