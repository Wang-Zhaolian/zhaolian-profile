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
    monkeypatch.setattr(desktop, "_health", lambda port, home: port == 54321)
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

    def health(port: int, home: Path) -> bool:
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


def test_server_identity_prevents_other_library_reuse(tmp_path, monkeypatch):
    from academic_profile import __version__
    from academic_profile.library import initialize_home
    first, second = tmp_path / "first", tmp_path / "second"
    identity = initialize_home(first)
    initialize_home(second)
    monkeypatch.setattr(desktop, "_server_info", lambda port: {"version": __version__, "library_id": identity})
    assert desktop._health(52847, first)
    assert not desktop._health(52847, second)


def test_old_server_is_left_running_and_user_is_notified(tmp_path, monkeypatch):
    home = tmp_path / "home"
    marker = home / "private/desktop-server.local.json"
    marker.parent.mkdir(parents=True)
    marker.write_text(json.dumps({"port": 54321}), encoding="utf-8")
    monkeypatch.setattr(desktop, "_server_info", lambda port: {"version": "0.2.2"})
    messages = []
    monkeypatch.setattr(desktop, "_message", messages.append)
    monkeypatch.setattr(desktop.subprocess, "Popen", lambda *a, **k: (_ for _ in ()).throw(AssertionError("old server must be left alone")))
    assert desktop._desktop(home) == 1
    assert messages and "先保存" in messages[0]
