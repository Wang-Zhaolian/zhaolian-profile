"""Explicit, allowlisted GitHub backup operations for the local interface."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


TARGET_REPOSITORY = "Wang-Zhaolian/academic-profile"
TARGET_REMOTE = f"https://github.com/{TARGET_REPOSITORY}.git"
_CREDENTIAL_URL = re.compile(r"(https?://)[^/@\s]+@", re.IGNORECASE)

STAGE_PATHS = (
    ".gitattributes", ".gitignore", "ADD_RECORD.md", "README.md", "Makefile",
    "pyproject.toml", "uv.lock", "generate.py", "add.py", "start.pyw",
    "academic-profile.spec", "profiles", "schemas", "data", "src",
    "scripts", "static", "templates", "tests",
)
PRIVATE_PATHS = (
    "private/contact.yaml", "%LOCALAPPDATA%/AcademicProfile/chatgpt", "private/ai_notes",
    "evidence", "output", ".venv", "dist",
)


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
    origin_matches: bool | None = None
    pending: bool = False
    pending_commits: int = 0
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


def _safe_diagnostic(result: subprocess.CompletedProcess[str] | None, fallback: str) -> str:
    if result is None:
        return fallback
    detail = (result.stderr or result.stdout or "").strip()
    detail = _CREDENTIAL_URL.sub(r"\1[已隐藏]@", detail)
    detail = " ".join(detail.split())
    if not detail:
        return fallback
    return f"{fallback}（{detail[:500]}）"


def _github_details(home: Path) -> dict[str, Any]:
    result = _run(
        home,
        ["gh", "api", f"repos/{TARGET_REPOSITORY}"],
        timeout=12,
    )
    if result.returncode:
        raise RuntimeError(_safe_diagnostic(result, "无法读取指定的 GitHub 仓库。"))
    try:
        details = json.loads(result.stdout)
    except ValueError:
        raise RuntimeError("GitHub 返回了无法识别的仓库信息。") from None
    if not isinstance(details, dict) or str(details.get("full_name", "")).casefold() != TARGET_REPOSITORY.casefold():
        raise RuntimeError("GitHub 返回的仓库名称与目标仓库不一致，已停止备份。")
    if details.get("private") is not True:
        raise RuntimeError("Wang-Zhaolian/academic-profile 不是 Private 仓库。为保护资料，本次备份已取消。")
    return details


def _origin_matches_target(value: str) -> bool:
    remote = value.strip().replace("\\", "/")
    if remote.startswith("git@github.com:"):
        remote = remote[len("git@github.com:"):]
    else:
        try:
            parsed = urlsplit(remote)
        except ValueError:
            return False
        if parsed.hostname != "github.com":
            return False
        remote = parsed.path
    remote = remote.removesuffix(".git").strip("/")
    return remote.casefold() == TARGET_REPOSITORY.casefold()


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
    remote = _run(home, ["git", "remote", "get-url", "origin"])
    if remote.returncode == 0:
        result.repository = TARGET_REPOSITORY
        result.origin_matches = _origin_matches_target(remote.stdout)
        if not result.origin_matches:
            result.message = "origin 指向的仓库不是 Wang-Zhaolian/academic-profile，已停止备份。"
            result.is_private = None
        if refresh and github_cli_available:
            try:
                details = _github_details(home)
            except subprocess.TimeoutExpired:
                result.is_private = None
                result.message = "连接 GitHub 超时；本机记录不受影响。"
            except RuntimeError as exc:
                result.is_private = None
                result.message = str(exc)
            else:
                result.repository = str(details.get("full_name", TARGET_REPOSITORY))
                result.is_private = True
        elif refresh and not github_cli_available:
            result.message = "没有找到 GitHub CLI。请安装 GitHub CLI 并登录后重试。"
        elif not result.message:
            result.is_private = cached.get("is_private")
            result.message = "显示上次核验结果；点击刷新可重新检查 GitHub。"
    elif github_cli_available:
        result.repository = TARGET_REPOSITORY
        result.origin_matches = None
        result.message = "备份时会核验并连接指定的 Private 仓库。"
    else:
        result.repository = TARGET_REPOSITORY
        result.message = "没有找到 GitHub CLI。请安装 GitHub CLI 并登录后重试。"

    staged = _run(home, ["git", "diff", "--cached", "--name-only"])
    worktree = _run(home, ["git", "diff", "--name-only"])
    untracked = _run(home, ["git", "ls-files", "--others", "--exclude-standard"])
    changed_paths = (
        staged.stdout.splitlines() + worktree.stdout.splitlines() + untracked.stdout.splitlines()
    )
    result.pending = any(_is_allowlisted(path) for path in changed_paths)
    branch = _run(home, ["git", "branch", "--show-current"])
    branch_name = branch.stdout.strip() if branch.returncode == 0 else ""
    if branch_name:
        ahead = _run(home, ["git", "rev-list", "--count", f"refs/remotes/origin/{branch_name}..HEAD"])
        if ahead.returncode == 0 and ahead.stdout.strip().isdigit() and int(ahead.stdout.strip()) > 0:
            result.pending_commits = int(ahead.stdout.strip())
            result.pending = True
        elif ahead.returncode == 128:
            if result.origin_matches is True:
                local_commits = _run(home, ["git", "rev-list", "--count", "HEAD"])
                if local_commits.returncode == 0:
                    result.pending_commits = int(local_commits.stdout.strip() or "0")
                    result.pending = result.pending or result.pending_commits > 0
        elif ahead.returncode:
            result.message = result.message or _safe_diagnostic(ahead, "无法检查尚未推送的本地提交。")
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
        or path.startswith(("private/ai/", "private/ai_notes/"))
        or path in {"private/runtime.local.json", "private/ai_auth.local.json"}
    ]
    if forbidden:
        raise RuntimeError("备份里检测到本机文件，已停止：" + ", ".join(sorted(forbidden)))


def _ensure_private_origin(home: Path) -> str:
    details = _github_details(home)
    remote = _run(home, ["git", "remote", "get-url", "origin"])
    if remote.returncode != 0:
        added = _run(home, ["git", "remote", "add", "origin", TARGET_REMOTE])
        if added.returncode:
            raise RuntimeError(_safe_diagnostic(added, "无法连接指定 GitHub 仓库。"))
        remote = _run(home, ["git", "remote", "get-url", "origin"])
    if remote.returncode:
        raise RuntimeError(_safe_diagnostic(remote, "无法读取 origin 地址。"))
    if not _origin_matches_target(remote.stdout):
        safe_remote = _CREDENTIAL_URL.sub(r"\1[已隐藏]@", remote.stdout.strip())
        raise RuntimeError(
            f"origin 当前指向其他仓库（{safe_remote}）。为避免上传到错误位置，已停止备份。"
        )
    return str(details["full_name"])


def backup(home: Path) -> BackupStatus:
    if shutil.which("git") is None or shutil.which("gh") is None:
        raise RuntimeError("需要安装并登录 GitHub CLI 才能备份。")
    target_repository = _ensure_private_origin(home)
    _stage_allowed_paths(home)

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
        diagnostic = _safe_diagnostic(pushed, "GitHub 未接受此次推送。")
        raise RuntimeError(
            "GitHub 备份失败，本机内容仍已保存。远程可能存在新提交；请先处理同步冲突后重试。\n"
            + diagnostic
        )

    result = BackupStatus()
    result.repository = target_repository
    result.is_private = True
    result.origin_matches = True
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
