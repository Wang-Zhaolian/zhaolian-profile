"""Private data backups isolated from the public source working tree."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml

from . import __version__
from .categories import load_registry
from .library import atomic_json, file_lock, library_id
from .loader import load_master_data

STAGE_PATHS = ("data", "backup-manifest.json")
PRIVATE_PATHS = ("private", "evidence", "output", ".runtime", "%LOCALAPPDATA%/AcademicProfile/chatgpt")
_REPOSITORY = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}")
_LOCK = threading.RLock()


@dataclass
class BackupStatus:
    repository: str = "尚未配置"
    is_private: bool | None = None
    origin_matches: bool | None = None
    pending: bool = False
    pending_commits: int = 0
    last_successful_backup: str | None = None
    message: str = ""


def load_config(home: Path) -> dict[str, Any]:
    path = home / "private" / "backup.local.json"
    if not path.exists():
        return {"repository": ""}
    value = json.loads(path.read_text(encoding="utf-8"))
    repository = value.get("repository", "")
    if not isinstance(repository, str) or (repository and not _REPOSITORY.fullmatch(repository)):
        raise ValueError("本机备份配置损坏，请重新设置。")
    return {"repository": repository}


def save_config(home: Path, repository: Any) -> dict[str, Any]:
    if not isinstance(repository, str):
        raise ValueError("仓库格式应为 用户名/仓库名。")
    repository = repository.strip()
    if repository and (not _REPOSITORY.fullmatch(repository) or repository.split("/")[1] in {".", ".."}):
        raise ValueError("请填写 用户名/仓库名，不包含网址、密码或访问令牌。")
    with _LOCK, file_lock(home / ".runtime" / "backup.lock"):
        value = {"repository": repository}
        atomic_json(home / "private" / "backup.local.json", value)
        return value


def _run(directory: Path, args: list[str], *, timeout: int = 90) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GH_PROMPT_DISABLED="1", GCM_INTERACTIVE="never")
    return subprocess.run(args, cwd=directory, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout, check=False, env=env,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _git(directory: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return _run(directory, ["git", "-c", "credential.helper=", "-c", "credential.helper=!gh auth git-credential", *args])


def _diagnostic(result, message: str) -> str:
    detail = " ".join((result.stderr or result.stdout or "").split())
    detail = re.sub(r"(https?://)[^/@\s]+@", r"\1[已隐藏]@", detail)
    detail = re.sub(r"\b(?:gh[pousr]_[A-Za-z0-9_]+|github_pat_[A-Za-z0-9_]+|sk-[A-Za-z0-9_-]+)\b", "[已隐藏]", detail)
    return f"{message}（{detail[:400]}）" if detail else message


def _checked(result, message: str):
    if result.returncode:
        raise RuntimeError(_diagnostic(result, message))
    return result


def _verify_repository(home: Path, repository: str) -> dict:
    if shutil.which("git") is None or shutil.which("gh") is None:
        raise RuntimeError("备份需要安装 Git 和 GitHub CLI，并先在 GitHub CLI 登录；本机录入不受影响。")
    result = _checked(_run(home, ["gh", "api", f"repos/{repository}"], timeout=15), "无法读取仓库，请检查 GitHub CLI 登录状态、仓库名及网络。")
    try:
        value = json.loads(result.stdout)
    except ValueError as exc:
        raise RuntimeError("GitHub 返回的仓库信息无法识别，请稍后重试。") from exc
    if not isinstance(value, dict):
        raise RuntimeError("GitHub 返回的仓库信息无法识别，请稍后重试。")
    if value.get("full_name", "").casefold() != repository.casefold():
        raise RuntimeError("返回的仓库名称与设置不一致，已停止上传。")
    if value.get("private") is not True:
        raise RuntimeError("目标仓库不是私有仓库，已停止上传。请使用单独的私有资料备份仓库。")
    if value.get("permissions", {}).get("push") is not True:
        raise RuntimeError("当前 GitHub 账号没有此仓库的推送权限。")
    return value


def _paths(home: Path, repository: str) -> tuple[Path, Path]:
    key = hashlib.sha256(repository.casefold().encode()).hexdigest()[:20]
    base = home / "private" / "github-backups"
    return base / key, base / f"{key}.local.json"


def _snapshot(home: Path) -> dict[str, bytes]:
    documents = load_master_data(home / "data")
    documents["categories"] = load_registry(home)
    result = {}
    for name, value in documents.items():
        if name not in {"basics", "categories"}:
            value = {"version": 1, "records": [{key: item for key, item in record.items()
                     if key != "evidence" and not key.startswith("_")} for record in value]}
        result[f"data/{name}.yaml"] = yaml.safe_dump(value, allow_unicode=True, sort_keys=False).encode("utf-8")
    result["backup-manifest.json"] = (json.dumps({"format": "zhaolian-profile-backup", "version": 1,
        "library_id": library_id(home), "app_version": __version__}, sort_keys=True, indent=2) + "\n").encode()
    return result


def _digest(snapshot: dict[str, bytes]) -> str:
    digest = hashlib.sha256()
    for name, content in sorted(snapshot.items()):
        digest.update(name.encode() + b"\0" + content + b"\0")
    return digest.hexdigest()


def _read_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _remote_matches(value: str, repository: str) -> bool:
    parsed = urlsplit(value.strip())
    return (parsed.scheme == "https" and parsed.hostname == "github.com" and parsed.username is None
            and parsed.password is None and parsed.path.strip("/").removesuffix(".git").casefold() == repository.casefold())


def status(home: Path, *, refresh: bool = False) -> BackupStatus:
    try:
        repository = load_config(home)["repository"]
    except (OSError, ValueError) as exc:
        return BackupStatus(message=str(exc))
    if not repository:
        return BackupStatus(message="请先填写你自己的私有仓库；未配置时不会上传任何资料。")
    directory, state_path = _paths(home, repository)
    state = _read_state(state_path)
    result = BackupStatus(repository=repository, last_successful_backup=state.get("last_successful_backup"),
                          is_private=state.get("is_private"))
    try:
        result.pending = state.get("digest") != _digest(_snapshot(home))
        if (directory / ".git").is_dir() and shutil.which("git"):
            remote = _git(directory, "config", "--get", "remote.origin.url")
            result.origin_matches = not remote.returncode and _remote_matches(remote.stdout, repository)
            ahead = _git(directory, "rev-list", "--count", "origin/main..HEAD")
            if ahead.returncode == 0:
                result.pending_commits = int(ahead.stdout.strip())
            elif _git(directory, "rev-parse", "--verify", "HEAD").returncode == 0:
                result.pending_commits = int(_git(directory, "rev-list", "--count", "HEAD").stdout.strip())
            result.pending = result.pending or result.pending_commits > 0
        if refresh:
            _verify_repository(home, repository)
            result.is_private = True
            result.message = "已核验私有仓库；点击备份才会提交资料。"
        else:
            result.message = "显示本机状态；推送前会重新核验仓库。"
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        result.is_private = None
        result.message = str(exc)
    return result


def _validate_tree(directory: Path, tree: str, identity: str) -> None:
    paths = _checked(_git(directory, "ls-tree", "-r", "--name-only", tree), "无法检查备份仓库内容。").stdout.splitlines()
    if any(not (name == "backup-manifest.json" or re.fullmatch(r"data/[A-Za-z][A-Za-z0-9_]*\.yaml", name)) for name in paths):
        raise RuntimeError("仓库已有其他项目的文件，已停止上传；请选择空仓库或本资料库的专用备份仓库。")
    manifest = _git(directory, "show", f"{tree}:backup-manifest.json")
    try:
        value = json.loads(manifest.stdout)
    except ValueError:
        value = {}
    if (value.get("format") != "zhaolian-profile-backup" or value.get("version") != 1
            or value.get("library_id") != identity):
        raise RuntimeError("仓库不是这份资料库的备份，已停止上传，未覆盖远端。")


def backup(home: Path) -> BackupStatus:
    with _LOCK, file_lock(home / ".runtime" / "backup.lock"):
        repository = load_config(home)["repository"]
        if not repository:
            raise RuntimeError("请先保存你自己的私有仓库设置。")
        _verify_repository(home, repository)
        snapshot = _snapshot(home)
        identity = json.loads(snapshot["backup-manifest.json"])["library_id"]
        directory, state_path = _paths(home, repository)
        directory.mkdir(parents=True, exist_ok=True)
        if not (directory / ".git").exists():
            _checked(_git(directory, "init", "--initial-branch=main"), "无法创建本机备份目录。")
            _checked(_git(directory, "remote", "add", "origin", f"https://github.com/{repository}.git"), "无法设置备份地址。")
            _checked(_git(directory, "config", "user.name", "Zhaolian Profile Backup"), "无法设置备份身份。")
            _checked(_git(directory, "config", "user.email", "backup@localhost"), "无法设置备份身份。")
        remote = _checked(_git(directory, "config", "--get", "remote.origin.url"), "无法读取备份地址。")
        if not _remote_matches(remote.stdout, repository):
            raise RuntimeError("本机备份目录的远程地址与设置不一致，已停止上传。")
        refs = _checked(_git(directory, "ls-remote", "--heads", "--tags", "origin"), "无法连接备份仓库。")
        has_remote = bool(refs.stdout.strip())
        has_head = _git(directory, "rev-parse", "--verify", "HEAD").returncode == 0
        if has_remote:
            if any(line.split()[1] != "refs/heads/main" for line in refs.stdout.splitlines()):
                raise RuntimeError("备份仓库包含其他分支，请使用空仓库或本资料库的专用备份仓库。")
            _checked(_git(directory, "fetch", "origin", "+refs/heads/main:refs/remotes/origin/main"), "无法读取远端备份。")
            _validate_tree(directory, "origin/main", identity)
            if has_head:
                if _git(directory, "merge-base", "--is-ancestor", "origin/main", "HEAD").returncode:
                    raise RuntimeError("远端备份已有不同的更新，已停止上传；本机资料不受影响。")
            else:
                _checked(_git(directory, "checkout", "-B", "main", "origin/main"), "无法连接现有备份。")
        if has_head:
            _validate_tree(directory, "HEAD", identity)
        data_dir = directory / "data"
        data_dir.mkdir(exist_ok=True)
        for old in data_dir.iterdir():
            if old.relative_to(directory).as_posix() not in snapshot:
                raise RuntimeError("备份目录出现不属于当前资料库的文件，已停止上传。")
        for name, contents in snapshot.items():
            (directory / name).write_bytes(contents)
        _checked(_git(directory, "add", "--", *snapshot), "无法准备履历备份。")
        cached = _checked(_git(directory, "diff", "--cached", "--name-only"), "无法检查待上传文件。")
        if any(name not in snapshot for name in cached.stdout.splitlines()):
            raise RuntimeError("备份暂存区包含未获允许的文件，已停止上传。")
        if cached.stdout.strip():
            _checked(_git(directory, "commit", "-m", "Update personal library backup"), "无法保存备份提交。")
        _verify_repository(home, repository)
        _checked(_git(directory, "push", "-u", "origin", "main"), "备份推送失败，可能存在远端冲突；本机资料仍已保存，可重试。")
        state = {"digest": _digest(snapshot), "last_successful_backup": datetime.now().astimezone().isoformat(timespec="seconds"), "is_private": True}
        atomic_json(state_path, state)
        return BackupStatus(repository=repository, is_private=True, origin_matches=True,
                            last_successful_backup=state["last_successful_backup"], message="已备份到你的私有 GitHub 仓库。")
