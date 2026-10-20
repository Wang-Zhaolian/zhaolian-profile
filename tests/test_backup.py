from __future__ import annotations
import importlib
import json
import subprocess
from pathlib import Path

import pytest
import yaml

from academic_profile.library import initialize_home, library_id
from academic_profile.webapp import create_app

backup = importlib.import_module("academic_profile.backup")


def git(path, *args):
    return subprocess.run(["git", *args], cwd=path, capture_output=True, text=True, encoding="utf-8", check=True).stdout.strip()


@pytest.fixture
def environment(tmp_path, monkeypatch):
    home = tmp_path / "home"
    initialize_home(home)
    remote = tmp_path / "remote.git"
    remote.mkdir()
    git(remote, "init", "--bare", "--initial-branch=main")
    backup.save_config(home, "example/backup")
    monkeypatch.setattr(backup, "_verify_repository", lambda *args: {"private": True})
    def local_git(path, *args):
        return subprocess.run(["git", "-c", f"url.{remote.as_posix()}.insteadOf=https://github.com/example/backup.git", *args],
                              cwd=path, capture_output=True, text=True, encoding="utf-8", errors="replace")
    monkeypatch.setattr(backup, "_git", local_git)
    return home, remote


def test_backup_is_unconfigured_and_no_network_by_default(tmp_path, monkeypatch):
    initialize_home(tmp_path)
    monkeypatch.setattr(backup, "_run", lambda *a, **k: pytest.fail("unexpected external call"))
    assert backup.load_config(tmp_path) == {"repository": ""}
    assert backup.status(tmp_path, refresh=True).repository == "尚未配置"
    with pytest.raises(RuntimeError, match="先保存"):
        backup.backup(tmp_path)


def test_settings_api_and_validation(tmp_path):
    initialize_home(tmp_path)
    client = create_app(tmp_path).test_client()
    headers = {"X-Academic-Profile": "local-ui"}
    for invalid in ("https://github.com/user/repo", "user/../repo", "user/..", None):
        assert client.patch("/api/backup/config", json={"repository": invalid}, headers=headers).status_code == 400
    assert client.patch("/api/backup/config", json={"repository": "demo/private-library"}, headers=headers).status_code == 200
    assert client.get("/api/backup/config").json["repository"] == "demo/private-library"
    assert client.get("/api/preferences").json["ai_model"] is None
    assert client.patch("/api/backup/config", json={"repository": ""}, headers=headers).status_code == 200


def test_successful_backup_contains_only_text_snapshots(environment):
    home, remote = environment
    (home / "private/contact.yaml").write_text("phone: SECRET-PHONE", encoding="utf-8")
    (home / "private/note.txt").write_text("SECRET-NOTE", encoding="utf-8")
    (home / "data/coursework.yaml").write_text(yaml.safe_dump({"records": [{"id": "course_001", "course_name": "示例课程", "evidence": ["C:/secret.pdf"]}]}), encoding="utf-8")
    result = backup.backup(home)
    assert result.last_successful_backup
    paths = git(remote, "ls-tree", "-r", "--name-only", "main").splitlines()
    assert "backup-manifest.json" in paths
    assert len(paths) == 15
    assert all(path.startswith("data/") or path == "backup-manifest.json" for path in paths)
    assert "secret" not in git(remote, "show", "main:data/coursework.yaml").lower()
    assert backup.status(home).pending is False
    head = git(remote, "rev-parse", "main")
    backup.backup(home)
    assert git(remote, "rev-parse", "main") == head
    assert backup.status(home).pending_commits == 0


def test_failed_push_keeps_commit_and_retry_does_not_duplicate(environment, monkeypatch):
    home, remote = environment
    real_git = backup._git
    def failed_push(path, *args):
        if args[0] == "push":
            return subprocess.CompletedProcess(args, 1, "", "offline")
        return real_git(path, *args)
    monkeypatch.setattr(backup, "_git", failed_push)
    with pytest.raises(RuntimeError, match="推送失败"):
        backup.backup(home)
    state = backup.status(home)
    assert state.last_successful_backup is None
    assert state.pending_commits == 1
    monkeypatch.setattr(backup, "_git", real_git)
    backup.backup(home)
    assert git(remote, "rev-list", "--count", "main") == "1"


def test_remote_change_stops_upload(environment, tmp_path):
    home, remote = environment
    backup.backup(home)
    clone = tmp_path / "other"
    git(tmp_path, "clone", str(remote), str(clone))
    git(clone, "config", "user.name", "Test")
    git(clone, "config", "user.email", "test@example.org")
    (clone / "data/basics.yaml").write_text("version: 1\nname_zh: 远端变化\nresearch_interests: []\n", encoding="utf-8")
    git(clone, "add", "data/basics.yaml")
    git(clone, "commit", "-m", "Remote update")
    git(clone, "push")
    original = git(remote, "rev-parse", "main")
    success = backup.status(home).last_successful_backup
    with pytest.raises(RuntimeError, match="远端备份已有不同"):
        backup.backup(home)
    assert git(remote, "rev-parse", "main") == original
    assert backup.status(home).last_successful_backup == success


def test_other_library_or_project_is_not_overwritten(environment, tmp_path):
    home, remote = environment
    backup.backup(home)
    other = tmp_path / "other-home"
    initialize_home(other)
    backup.save_config(other, "example/backup")
    assert library_id(home) != library_id(other)
    head = git(remote, "rev-parse", "main")
    with pytest.raises(RuntimeError, match="不是这份资料库"):
        backup.backup(other)
    assert git(remote, "rev-parse", "main") == head


@pytest.mark.parametrize("private,push,message", [(False, True, "不是私有"), (True, False, "没有此仓库")])
def test_public_repository_and_insufficient_permission_are_rejected(tmp_path, monkeypatch, private, push, message):
    monkeypatch.setattr(backup.shutil, "which", lambda _: "installed")
    monkeypatch.setattr(backup, "_run", lambda *a, **k: subprocess.CompletedProcess([], 0, json.dumps({
        "full_name": "demo/backup", "private": private, "permissions": {"push": push}}), ""))
    with pytest.raises(RuntimeError, match=message):
        backup._verify_repository(tmp_path, "demo/backup")


def test_added_private_file_is_never_pushed(environment):
    home, remote = environment
    backup.backup(home)
    directory, _ = backup._paths(home, "example/backup")
    (directory / "token.txt").write_text("private", encoding="utf-8")
    git(directory, "add", "token.txt")
    with pytest.raises(RuntimeError, match="未获允许"):
        backup.backup(home)
    assert "token.txt" not in git(remote, "ls-tree", "-r", "--name-only", "main")
