from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from academic_profile.backup import _stage_allowed_paths, status


def _git(home: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=home, check=True, capture_output=True,
        text=True, encoding="utf-8", errors="replace",
    )
    return completed.stdout.strip()


def test_backup_allowlist_omits_private_and_evidence_and_checks_staging(tmp_path: Path) -> None:
    home = tmp_path / "repo"
    home.mkdir()
    _git(home, "init", "--initial-branch", "main")
    _git(home, "config", "user.name", "Local Test")
    _git(home, "config", "user.email", "test@example.org")
    (home / "README.md").write_text("app docs\n", encoding="utf-8")
    (home / "static").mkdir()
    (home / "static" / "app.js").write_text("ui bundle\n", encoding="utf-8")
    (home / "data").mkdir()
    (home / "data" / "basics.yaml").write_text("name_en: ''\n", encoding="utf-8")
    (home / "private").mkdir()
    contact = home / "private" / "contact.yaml"
    contact.write_text("email: local@example.org\n", encoding="utf-8")
    (home / "private" / "README.md").write_text("local-only\n", encoding="utf-8")
    (home / "evidence").mkdir()
    (home / "evidence" / "proof.pdf").write_bytes(b"local-only")

    _stage_allowed_paths(home)
    staged = set(_git(home, "diff", "--cached", "--name-only").splitlines())
    assert staged == {"README.md", "data/basics.yaml", "static/app.js"}
    _git(home, "commit", "-m", "fixture")

    contact.write_text("email: changed@example.org\n", encoding="utf-8")
    (home / "private" / "new-local-note.txt").write_text("local-only\n", encoding="utf-8")
    assert status(home).pending is False

    _git(home, "add", "private/contact.yaml")
    with pytest.raises(RuntimeError, match="不在 GitHub 备份清单"):
        _stage_allowed_paths(home)
