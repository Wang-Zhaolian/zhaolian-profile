from __future__ import annotations

from pathlib import Path

from academic_profile.loader import load_master_data, load_profile
from academic_profile.selection import select_profile

ROOT = Path(__file__).resolve().parents[1]


def test_profile_filtering_and_order(example_data_dir: Path) -> None:
    data = load_master_data(example_data_dir)
    profile = load_profile(ROOT / "profiles", "internship")
    sections = select_profile(data, profile)
    ids = [section["id"] for section in sections]
    assert ids[:3] == ["education", "projects", "skills"]
    coursework = next(section for section in sections if section["id"] == "coursework")
    assert [item["id"] for item in coursework["items"]] == ["course_001"]


def test_manual_profile_override(example_data_dir: Path) -> None:
    data = load_master_data(example_data_dir)
    data["awards"][0]["priority"] = 5
    data["awards"][0]["include_for"] = {"phd": True}
    profile = load_profile(ROOT / "profiles", "phd")
    sections = select_profile(data, profile)
    awards = next(section for section in sections if section["id"] == "awards")
    assert awards["items"][0]["id"] == "award_001"


def test_archived_record_never_selected(example_data_dir: Path) -> None:
    data = load_master_data(example_data_dir)
    data["projects"][0]["archived"] = True
    data["projects"][0]["include_for"] = {"internship": True}
    profile = load_profile(ROOT / "profiles", "internship")
    sections = select_profile(data, profile)
    assert "projects" not in [section["id"] for section in sections]
