"""Launch a private loopback web application from the desktop shortcut."""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

from . import __version__
from .webapp import create_app

PORT = 52847


def _default_home() -> Path:
    if getattr(sys, "frozen", False):
        candidate = Path(sys.executable).resolve().parents[2]
    else:
        candidate = Path(__file__).resolve().parents[2]
    for path in (candidate, *candidate.parents):
        if (path / "data").is_dir() and (path / "profiles").is_dir():
            return path
    return candidate


def _health(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=0.8) as response:
            if response.status != 200:
                return False
            payload = json.loads(response.read().decode("utf-8"))
            return payload.get("name") == "academic-profile" and payload.get("version") == __version__
    except (OSError, urllib.error.URLError):
        return False


def _runtime_root(home: Path) -> Path:
    return home / ".runtime"


def _port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        try:
            listener.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _unused_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _serve(home: Path, port: int) -> int:
    from waitress import serve

    marker = home / "private" / "desktop-server.local.json"
    marker.parent.mkdir(parents=True, exist_ok=True)
    temp = marker.with_suffix(".tmp")
    temp.write_text(json.dumps({"port": port, "pid": os.getpid()}), encoding="utf-8")
    os.replace(temp, marker)
    frozen_root = Path(getattr(sys, "_MEIPASS", _default_home()))
    try:
        app = create_app(home, static_root=frozen_root, callback_port=port)
        serve(app, host="127.0.0.1", port=port, threads=6, ident="AcademicProfile")
    finally:
        try:
            current_marker = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            current_marker = {}
        if current_marker.get("pid") == os.getpid():
            marker.unlink(missing_ok=True)
    return 0


def _desktop(home: Path) -> int:
    marker = home / "private" / "desktop-server.local.json"
    if marker.exists():
        try:
            port = int(json.loads(marker.read_text(encoding="utf-8"))["port"])
        except (OSError, ValueError, KeyError, TypeError):
            port = PORT
        if _health(port):
            webbrowser.open(f"http://127.0.0.1:{port}/", new=1)
            return 0

    if _health(PORT):
        webbrowser.open(f"http://127.0.0.1:{PORT}/", new=1)
        return 0

    port = PORT if _port_available(PORT) else _unused_local_port()

    if getattr(sys, "frozen", False):
        command = [sys.executable, "--serve", "--home", str(home), "--port", str(port)]
    else:
        command = [sys.executable, "-m", "academic_profile.desktop", "--serve", "--home", str(home), "--port", str(port)]

    runtime = _runtime_root(home)
    runtime.mkdir(parents=True, exist_ok=True)
    log_path = runtime / "server.log"
    creationflags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)
    with log_path.open("ab") as log_file:
        subprocess.Popen(
            command,
            cwd=home,
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
            close_fds=True,
        )

    for _ in range(80):
        if _health(port):
            webbrowser.open(f"http://127.0.0.1:{port}/", new=1)
            return 0
        time.sleep(0.25)
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            None,
            f"平台启动失败。详细信息保存在：\n{log_path}",
            "昭濂学术档案",
            0x10,
        )
    except Exception:
        pass
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="昭濂学术档案")
    parser.add_argument("--serve", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--home", type=Path, default=_default_home(), help=argparse.SUPPRESS)
    parser.add_argument("--port", type=int, default=PORT, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    home = args.home.resolve()
    if args.serve:
        return _serve(home, args.port)
    return _desktop(home)


if __name__ == "__main__":
    raise SystemExit(main())
