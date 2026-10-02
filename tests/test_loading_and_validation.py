from __future__ import annotations

import shutil
from pathlib import Path

import yaml

from academic_profile.loader import load_master_data
from academic_profile.validation import validate_repository

ROOT = Path(__file__).resolve().parents[1]


def _validate(data_dir: Path):
    return validate_repository(data_dir, ROOT / "profiles", ROOT / "schemas")


def test_yaml_parsing_and_synthetic_validation(example_data_dir: Path) -> None:
    data = load_master_data(example_data_dir)
    assert data["education"][0]["id"] == "education_001"
    assert _validate(example_data_dir) == []


def test_empty_master_record_is_valid() -> None:
    assert _validate(ROOT / "data") == []


def test_duplicate_id_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "data"
    shutil.copytree(ROOT / "data", target)
    path = target / "awards.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["records"] = [{"id": "project_001", "record_state": "draft"}]
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    project_path = target / "projects.yaml"
    projects = yaml.safe_load(project_path.read_text(encoding="utf-8"))
    projects["records"] = [{"id": "project_001", "record_state": "draft"}]
    project_path.write_text(yaml.safe_dump(projects, sort_keys=False), encoding="utf-8")
    assert any(issue.code == "duplicate_id" for issue in _validate(target))


def test_publication_status_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "data"
    shutil.copytree(ROOT / "data", target)
    path = target / "publications.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["records"] = [{
        "id": "paper_001", "title": "Fixture", "authors": ["Fixture Author"],
        "my_author_position": 1, "year": 2025, "status": "forthcoming",
        "cv_eligible": True, "priority": 1, "tags": [],
    }]
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    assert any(
        issue.code in {"schema", "publication_status"} for issue in _validate(target)
    )


def test_missing_cross_reference_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "data"
    shutil.copytree(ROOT / "data", target)
    path = target / "publications.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["records"] = [{
        "id": "paper_001", "title": "Fixture", "authors": ["Fixture Author"],
        "my_author_position": 1, "year": 2025, "status": "published",
        "research_id": "research_999", "cv_eligible": True, "priority": 1, "tags": [],
    }]
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    assert any(issue.code == "missing_reference" for issue in _validate(target))


def test_incomplete_draft_is_ignored_but_bad_state_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "data"
    shutil.copytree(ROOT / "data", target)
    path = target / "research.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["records"] = [{"id": "research_001", "record_state": "draft"}]
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    assert _validate(target) == []
    document["records"][0]["record_state"] = "paused"
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    assert any(issue.code == "record_state" for issue in _validate(target))
