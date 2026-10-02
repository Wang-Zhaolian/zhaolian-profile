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
