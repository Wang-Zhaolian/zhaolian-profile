from __future__ import annotations

import json
from pathlib import Path

from academic_profile import desktop


def test_repeated_desktop_launch_reuses_healthy_local_server(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    marker = home / "private" / "desktop-server.local.json"
    marker.parent.mkdir(parents=True)
    marker.write_text(json.dumps({"port": 54321, "pid": 100}), encoding="utf-8")
    opened: list[str] = []
    monkeypatch.setattr(desktop, "_health", lambda port: port == 54321)
    monkeypatch.setattr(desktop.webbrowser, "open", lambda url, new=0: opened.append(url) or True)
    monkeypatch.setattr(
        desktop.subprocess, "Popen",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should reuse the running server")),
    )

    assert desktop._desktop(home) == 0
    assert opened == ["http://127.0.0.1:54321/"]


def test_desktop_uses_another_local_port_when_old_version_is_running(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    opened: list[str] = []
    launched: list[list[str]] = []

    def health(port: int) -> bool:
        return bool(launched) and port == 54322

    def popen(command, **kwargs):
        launched.append(command)
        return object()

    monkeypatch.setattr(desktop, "_health", health)
    monkeypatch.setattr(desktop, "_port_available", lambda port: False)
    monkeypatch.setattr(desktop, "_unused_local_port", lambda: 54322)
    monkeypatch.setattr(desktop.webbrowser, "open", lambda url, new=0: opened.append(url) or True)
    monkeypatch.setattr(desktop.subprocess, "Popen", popen)

    assert desktop._desktop(home) == 0
    assert launched[0][-1] == "54322"
    assert opened == ["http://127.0.0.1:54322/"]
