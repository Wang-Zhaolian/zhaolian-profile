import pytest
from academic_profile.library import default_home, initialize_home
from academic_profile.loader import load_master_data


def test_initialization_is_blank_and_preserves_existing_data(tmp_path):
    home = tmp_path / "独立资料"
    identity = initialize_home(home)
    assert all(not records for name, records in load_master_data(home / "data").items() if name != "basics")
    path = home / "data/coursework.yaml"
    path.write_text("records:\n- id: course_001\n  course_name: 保留的经历\n", encoding="utf-8")
    before = path.read_bytes()
    assert initialize_home(home) == identity
    assert path.read_bytes() == before
    assert not (home / "schemas").exists()


def test_partial_existing_library_is_not_overwritten(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    path = data / "coursework.yaml"
    path.write_text("private existing text", encoding="utf-8")
    with pytest.raises(Exception):
        initialize_home(tmp_path)
    assert path.read_text(encoding="utf-8") == "private existing text"
    assert not (data / "basics.yaml").exists()


def test_default_home_is_outside_install_directory(tmp_path, monkeypatch):
    monkeypatch.delenv("ZHAOLIAN_PROFILE_HOME", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert default_home() == tmp_path / "ZhaolianProfile"
