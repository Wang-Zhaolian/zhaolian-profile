"""Explicit, allowlisted GitHub backup operations for the local interface."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

STAGE_PATHS = (
    ".gitattributes", ".gitignore", "ADD_RECORD.md", "README.md", "Makefile",
    "pyproject.toml", "uv.lock", "generate.py", "add.py", "start.pyw",
    "academic-profile.spec", "profiles", "schemas", "data", "src",
    "scripts", "static", "templates", "tests",
)
PRIVATE_PATHS = ("private/contact.yaml", "evidence", "output", ".venv", "dist")


def _is_allowlisted(path: str) -> bool:
    normalized = path.replace("\\", "/")
    if normalized.startswith("./"):
        normalized = normalized[2:]
    return any(
        normalized == allowed or normalized.startswith(allowed.rstrip("/") + "/")
        for allowed in STAGE_PATHS
    )


@dataclass
class BackupStatus:
    repository: str = "尚未创建"
    is_private: bool | None = None
    pending: bool = False
    last_successful_backup: str | None = None
    message: str = ""


def _run(home: Path, args: list[str], *, timeout: int = 90) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=home,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _runtime_file(home: Path) -> Path:
    return home / "private" / "runtime.local.json"


def status(home: Path, *, refresh: bool = False) -> BackupStatus:
    result = BackupStatus()
    state_path = _runtime_file(home)
    cached: dict[str, Any] = {}
    if state_path.exists():
        try:
            cached = json.loads(state_path.read_text(encoding="utf-8"))
            result.last_successful_backup = cached.get("last_successful_backup")
        except (OSError, ValueError):
            pass

    github_cli_available = shutil.which("gh") is not None
    if not github_cli_available:
        result.message = "没有找到 GitHub CLI。请安装 GitHub CLI 并登录后重试。"
        result.repository = str(cached.get("repository", result.repository))
        result.is_private = cached.get("is_private")
    remote = _run(home, ["git", "remote", "get-url", "origin"])
    if remote.returncode == 0:
        result.repository = str(cached.get("repository") or remote.stdout.strip())
        result.is_private = cached.get("is_private")
        if refresh and github_cli_available:
            try:
                visibility = _run(home, ["gh", "repo", "view", "--json", "nameWithOwner,visibility"], timeout=8)
            except subprocess.TimeoutExpired:
                visibility = None
                result.message = "连接 GitHub 超时；本机记录不受影响。"
            if visibility and visibility.returncode == 0:
                try:
                    details = json.loads(visibility.stdout)
                    result.repository = details.get("nameWithOwner") or result.repository
                    result.is_private = details.get("visibility") == "PRIVATE"
                except ValueError:
                    result.is_private = None
                    result.message = "暂时无法读取 GitHub 仓库状态。"
            elif visibility:
                result.is_private = None
                result.message = "暂时无法读取 GitHub 仓库状态。"
        elif refresh and not github_cli_available:
            result.message = "没有找到 GitHub CLI。请安装 GitHub CLI 并登录后重试。"
        elif result.is_private is None:
            result.message = "尚未核实远程仓库隐私状态；点击刷新或备份时会重新检查。"
    elif github_cli_available:
        result.message = "点击备份时会创建一个 Private 仓库。"

    staged = _run(home, ["git", "diff", "--cached", "--name-only"])
    worktree = _run(home, ["git", "diff", "--name-only"])
    untracked = _run(home, ["git", "ls-files", "--others", "--exclude-standard"])
    changed_paths = (
        staged.stdout.splitlines() + worktree.stdout.splitlines() + untracked.stdout.splitlines()
    )
    result.pending = any(_is_allowlisted(path) for path in changed_paths)
    if result.is_private is False:
        result.message = "当前远程仓库不是 Private，已停用上传。"
    return result


def _stage_allowed_paths(home: Path) -> None:
    existing = [path for path in STAGE_PATHS if (home / path).exists()]
    if existing:
        result = _run(home, ["git", "add", "--", *existing])
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or "无法准备备份文件。")
    cached = _run(home, ["git", "diff", "--cached", "--name-only"])
    if cached.returncode:
        raise RuntimeError(cached.stderr.strip() or "无法检查备份文件。")
    paths = {line.replace("\\", "/") for line in cached.stdout.splitlines()}
    unapproved = [path for path in paths if not _is_allowlisted(path)]
    if unapproved:
        raise RuntimeError("暂存区里有不在 GitHub 备份清单中的文件，已停止上传：" + ", ".join(sorted(unapproved)))
    forbidden = [
        path for path in paths
        if path.endswith("/contact.yaml") or path == "contact.yaml"
        or path.startswith(("evidence/", "output/", ".venv/", "dist/"))
        or path == "private/runtime.local.json"
    ]
    if forbidden:
        raise RuntimeError("备份里检测到本机文件，已停止：" + ", ".join(sorted(forbidden)))


def _ensure_private_origin(home: Path) -> str:
    remote = _run(home, ["git", "remote", "get-url", "origin"])
    if remote.returncode != 0:
        user = _run(home, ["gh", "api", "user", "--jq", ".login"])
        if user.returncode:
            raise RuntimeError("GitHub 尚未登录。请先登录 GitHub CLI，再重试备份。")
        owner = user.stdout.strip()
        repo = _run(home, ["gh", "repo", "view", f"{owner}/academic-profile", "--json", "visibility,nameWithOwner"])
        if repo.returncode == 0:
            raise RuntimeError(f"GitHub 上已经有 {owner}/academic-profile。请先核对后再配置远程仓库。")
        created = _run(home, ["gh", "repo", "create", "academic-profile", "--private", "--source", str(home), "--remote", "origin"])
        if created.returncode:
            raise RuntimeError(created.stderr.strip() or "无法创建 Private GitHub 仓库。")
        remote = _run(home, ["git", "remote", "get-url", "origin"])
        if remote.returncode:
            raise RuntimeError("Private 仓库已创建，但无法读取 origin 地址。")

    details = _run(home, ["gh", "repo", "view", "--json", "nameWithOwner,visibility"])
    if details.returncode:
        raise RuntimeError("无法核实远程仓库状态。请检查 GitHub 登录和网络后重试。")
    parsed: dict[str, Any] = json.loads(details.stdout)
    if parsed.get("visibility") != "PRIVATE":
        raise RuntimeError("远程仓库不是 Private。为保护个人资料，本次备份已取消。")
    return str(parsed.get("nameWithOwner", remote.stdout.strip()))


def backup(home: Path) -> BackupStatus:
    if shutil.which("git") is None or shutil.which("gh") is None:
        raise RuntimeError("需要安装并登录 GitHub CLI 才能备份。")
    _stage_allowed_paths(home)
    _ensure_private_origin(home)

    staged = _run(home, ["git", "diff", "--cached", "--quiet"])
    head = _run(home, ["git", "rev-parse", "--verify", "HEAD"])
    if staged.returncode == 1:
        stamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")
        committed = _run(home, ["git", "commit", "-m", f"Update academic profile backup {stamp}"])
        if committed.returncode:
            raise RuntimeError(committed.stderr.strip() or "无法创建备份记录。请检查 Git 用户名和邮箱。")
    elif head.returncode != 0:
        raise RuntimeError("没有可以备份的程序或数据文件。")

    branch = _run(home, ["git", "branch", "--show-current"])
    branch_name = branch.stdout.strip() or "main"
    pushed = _run(home, ["git", "push", "-u", "origin", branch_name])
    if pushed.returncode:
        raise RuntimeError(
            "GitHub 备份失败，本机内容仍已保存。远程可能存在新提交；请先处理同步冲突后重试。\n"
            + (pushed.stderr.strip() or pushed.stdout.strip())
        )

    result = BackupStatus()
    result.repository = _ensure_private_origin(home)
    result.is_private = True
    result.pending = False
    result.last_successful_backup = datetime.now().astimezone().isoformat(timespec="seconds")
    result.message = "已备份到 Private GitHub 仓库。"
    state = {
        "last_successful_backup": result.last_successful_backup,
        "repository": result.repository,
        "is_private": True,
    }
    state_path = _runtime_file(home)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix="backup-state-", suffix=".tmp", dir=state_path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(state, ensure_ascii=False, indent=2) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, state_path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return result
