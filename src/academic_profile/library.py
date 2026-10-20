"""Initialize blank libraries without replacing existing user documents."""
from __future__ import annotations

import json
import os
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path

import yaml

from .categories import default_registry


def default_home() -> Path:
    override = os.environ.get("ZHAOLIAN_PROFILE_HOME")
    if override:
        return Path(override).expanduser().resolve()
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share"))
    return base / "ZhaolianProfile"


@contextmanager
def file_lock(path: Path):
    """A nonblocking lock released by the OS even if a process is killed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError("这份资料库正在被另一个操作使用，请稍后重试。") from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix="local-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def library_id(home: Path) -> str:
    path = home / "private" / "library.local.json"
    with file_lock(home / ".runtime" / "identity.lock"):
        if path.exists():
            value = json.loads(path.read_text(encoding="utf-8"))
            return str(uuid.UUID(value["library_id"]))
        identity = str(uuid.uuid4())
        atomic_json(path, {"library_id": identity})
        return identity


def initialize_home(home: Path) -> str:
    home.mkdir(parents=True, exist_ok=True)
    with file_lock(home / ".runtime" / "initialize.lock"):
        data = home / "data"
        if data.exists():
            # A partial or damaged existing library must never become a blank one.
            from .loader import load_master_data
            load_master_data(data)
        else:
            staging = Path(tempfile.mkdtemp(prefix="initial-data-", dir=home))
            try:
                basics = {"version": 1, "name_en": "", "name_zh": "", "headline_en": "",
                          "headline_zh": "", "research_interests": [], "research_interests_en": []}
                registry = default_registry()
                documents = {"basics": basics, "categories": registry}
                documents.update({item["id"]: {"version": 1, "records": []} for item in registry["categories"]})
                for name, document in documents.items():
                    (staging / f"{name}.yaml").write_text(yaml.safe_dump(document, allow_unicode=True, sort_keys=False), encoding="utf-8")
                staging.rename(data)
            finally:
                # Only empty directories or files created by this initialization.
                if staging.exists():
                    for path in staging.iterdir():
                        path.unlink()
                    staging.rmdir()
    return library_id(home)
