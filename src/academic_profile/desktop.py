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
from .library import default_home, file_lock, initialize_home, library_id
from .resources import resource_root

PORT = 52847


def _default_home() -> Path:
    return default_home()


def _server_info(port: int) -> dict:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=0.8) as response:
            if response.status != 200:
                return {}
            payload = json.loads(response.read().decode("utf-8"))
            return payload if isinstance(payload, dict) and payload.get("name") == "academic-profile" else {}
    except (OSError, urllib.error.URLError, ValueError, UnicodeError):
        return {}


def _health(port: int, home: Path) -> bool:
    payload = _server_info(port)
    return payload.get("version") == __version__ and payload.get("library_id") == library_id(home)


def _message(message: str) -> None:
    if os.name == "nt":
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, message, "昭濂个人履历库", 0x10)
    else:
        print(message, file=sys.stderr)


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


def _serve_locked(home: Path, port: int) -> int:
    from waitress import serve

    marker = home / "private" / "desktop-server.local.json"
    marker.parent.mkdir(parents=True, exist_ok=True)
    temp = marker.with_suffix(".tmp")
    temp.write_text(json.dumps({"port": port, "pid": os.getpid(), "version": __version__, "library_id": library_id(home)}), encoding="utf-8")
    os.replace(temp, marker)
    frozen_root = resource_root()
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


def _serve(home: Path, port: int) -> int:
    with file_lock(home / ".runtime" / "server.lock"):
        initialize_home(home)
        return _serve_locked(home, port)


def _desktop(home: Path) -> int:
    initialize_home(home)
    marker = home / "private" / "desktop-server.local.json"
    if marker.exists():
        try:
            port = int(json.loads(marker.read_text(encoding="utf-8"))["port"])
        except (OSError, ValueError, KeyError, TypeError):
            port = PORT
        if _health(port, home):
            webbrowser.open(f"http://127.0.0.1:{port}/", new=1)
            return 0
        info = _server_info(port)
        if info and info.get("version") != __version__:
            _message("这份资料库的旧版程序仍在运行。请先保存旧窗口中的输入，并通过旧版界面的退出按钮关闭程序，然后重新打开新版。")
            return 1

    if _health(PORT, home):
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
        if _health(port, home):
            webbrowser.open(f"http://127.0.0.1:{port}/", new=1)
            return 0
        time.sleep(0.25)
    _message(f"平台启动失败。详细信息保存在：\n{log_path}")
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="昭濂个人履历库")
    parser.add_argument("--serve", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--home", type=Path, default=_default_home(), help=argparse.SUPPRESS)
    parser.add_argument("--port", type=int, default=PORT, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    home = args.home.resolve()
    try:
        if args.serve:
            return _serve(home, args.port)
        return _desktop(home)
    except Exception as exc:
        if args.serve:
            raise
        _message(f"无法打开资料库：{exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
