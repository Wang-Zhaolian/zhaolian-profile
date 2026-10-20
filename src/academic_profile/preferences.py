"""Private, atomic browser preferences shared by all local app windows."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any


_LOCK = threading.RLock()


def preferences_path(home: Path) -> Path:
    return home / "private" / "preferences.local.json"


def load_preferences(home: Path) -> dict[str, Any]:
    path = preferences_path(home)
    with _LOCK:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {"ai_model": None, "sorts": {}}
    if not isinstance(value, dict):
        return {"ai_model": None, "sorts": {}}
    return {
        "ai_model": value.get("ai_model") if isinstance(value.get("ai_model"), str) else None,
        "sorts": value.get("sorts") if isinstance(value.get("sorts"), dict) else {},
    }


def save_preferences(home: Path, updates: dict[str, Any]) -> dict[str, Any]:
    path = preferences_path(home)
    with _LOCK:
        current = load_preferences(home)
        if "ai_model" in updates:
            model = updates["ai_model"]
            if model is not None and (not isinstance(model, str) or len(model) > 160):
                raise ValueError("模型选择格式不正确。")
            current["ai_model"] = model
        if "sorts" in updates:
            if not isinstance(updates["sorts"], dict):
                raise ValueError("分类排序设置格式不正确。")
            for category, setting in updates["sorts"].items():
                if isinstance(setting, dict) and setting.get("sort_by") == "":
                    current["sorts"].pop(category, None)
                else:
                    current["sorts"][category] = setting
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix="preferences-", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(current, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        except BaseException:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise
        return current
