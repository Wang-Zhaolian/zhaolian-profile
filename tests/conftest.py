from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


@pytest.fixture
def example_data_dir(tmp_path: Path) -> Path:
    """Create isolated synthetic records; never used by the desktop platform."""
    target = tmp_path / "data"
    import shutil

    shutil.copytree(ROOT / "data", target)
    records = {
        "education": [{
            "id": "education_001", "institution": "Example University", "degree": "BS",
            "major": "Computer Science", "start_date": "2022-09", "expected_graduation": "2026-06",
            "cv_eligible": True, "record_state": "ready", "priority": 1, "tags": [],
        }],
        "research": [{
            "id": "research_001", "title": "Example Research", "institution": "Example University",
            "start_date": "2024-01", "status": "active", "my_contribution": ["Built a reproducible evaluation pipeline"],
            "paper_ids": ["paper_001"], "presentation_ids": ["presentation_001"], "skill_ids": ["skill_001"],
            "cv_bullets": ["Designed a reproducible evaluation pipeline"],
            "cv_eligible": True, "record_state": "ready", "priority": 1, "tags": [],
        }],
        "publications": [{
            "id": "paper_001", "title": "Example Methods for Evaluation", "authors": ["Example Author"],
            "my_author_position": 1, "venue": "Example Workshop", "year": 2025, "status": "under_review",
            "research_id": "research_001", "cv_eligible": True, "record_state": "ready", "priority": 1, "tags": [],
        }],
        "projects": [{
            "id": "project_001", "name": "Robust Evaluation", "type": "Research software",
            "start_date": "2024-02", "status": "completed", "tech_stack": ["Python"],
            "cv_bullets": ["Implemented evaluation tooling"],
            "cv_eligible": True, "record_state": "ready", "priority": 1, "tags": [],
        }],
        "awards": [{
            "id": "award_001", "name": "Example Scholarship", "level": "University",
            "organizer": "Example University", "date": "2024-05", "result": "Recipient",
            "cv_eligible": True, "record_state": "ready", "priority": 1, "tags": [],
        }],
        "competitions": [{
            "id": "competition_001", "name": "Example Challenge", "level": "University",
            "organizer": "Example Organization", "date": "2024-06", "result": "Finalist",
            "project_id": "project_001", "team": True,
            "cv_eligible": True, "record_state": "ready", "priority": 1, "tags": [],
        }],
        "coursework": [{
            "id": "course_001", "course_name": "Example Machine Learning", "institution": "Example University",
            "semester": "2024 Spring", "category": "Machine Learning", "level": "graduate",
            "transcript_visible": True, "skill_ids": ["skill_001"],
            "cv_eligible": True, "record_state": "ready", "priority": 1, "tags": [],
        }],
        "skills": [{
            "id": "skill_001", "category": "Programming", "items": ["Python"],
            "cv_eligible": True, "record_state": "ready", "priority": 1, "tags": [],
        }],
        "presentations": [{
            "id": "presentation_001", "title": "Example Poster", "event": "Example Symposium",
            "date": "2024-07", "research_id": "research_001",
            "cv_eligible": True, "record_state": "ready", "priority": 1, "tags": [],
        }],
        "english": [{
            "id": "english_001", "test": "Example English Test", "score": "100", "date": "2024-08",
            "cv_eligible": True, "record_state": "ready", "priority": 1, "tags": [],
        }],
        "activities": [{
            "id": "activity_001", "name": "Example Society", "organization": "Example University",
            "role": "Member", "start_date": "2023-01", "status": "completed",
            "cv_eligible": True, "record_state": "ready", "priority": 1, "tags": [],
        }],
        "links": [{
            "id": "link_001", "label": "Example Portfolio", "url": "https://example.org/portfolio",
            "cv_eligible": True, "record_state": "ready", "priority": 1, "tags": [],
        }],
    }
    for category, items in records.items():
        path = target / f"{category}.yaml"
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        document["records"] = items
        path.write_text(yaml.safe_dump(document, sort_keys=False, allow_unicode=True), encoding="utf-8")
    basics_path = target / "basics.yaml"
    basics = yaml.safe_load(basics_path.read_text(encoding="utf-8"))
    basics.update({"name_en": "Example Student", "research_interests": ["Example topic"]})
    basics_path.write_text(yaml.safe_dump(basics, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return target
