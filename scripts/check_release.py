"""Audit public files and all reachable history; never print private matches."""
from __future__ import annotations
import argparse
import io
import re
import subprocess
import zipfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = {"data", "private", "evidence", "output", ".runtime", ".venv", "dist", "build", "tmp"}
SECRET = re.compile(rb"\b(?:gh[pousr]_[A-Za-z0-9_]{25,}|github_pat_[A-Za-z0-9_]{30,}|sk-(?:proj-)?[A-Za-z0-9_-]{30,})\b")


def git(*args, binary=False):
    result = subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True)
    return result.stdout if binary else result.stdout.decode("utf-8", errors="replace")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--private-source", type=Path)
    parser.add_argument("--archive", type=Path)
    args = parser.parse_args()
    fingerprints = []
    if args.private_source:
        for relative, fields in (("data/basics.yaml", ("name_en", "name_zh")), ("private/contact.yaml", ("email", "phone"))):
            path = args.private_source / relative
            if path.exists():
                document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                for key in fields:
                    value = str(document.get(key) or "").strip()
                    if len(value) >= 3:
                        fingerprints.extend((value.encode("utf-8"), value.encode("utf-16-le")))
    issues = set()
    def inspect(label, contents):
        if SECRET.search(contents) or any(value in contents for value in fingerprints):
            issues.add(f"{label}: possible private content (redacted)")
        if label.lower().endswith((".docx", ".xlsx", ".pptx")):
            try:
                with zipfile.ZipFile(io.BytesIO(contents)) as document:
                    for name in document.namelist():
                        if name.endswith(".xml"):
                            inspect(f"{label}:{name}", document.read(name))
            except zipfile.BadZipFile:
                issues.add(f"{label}: invalid document")
    paths = git("ls-files", "--cached", "--others", "--exclude-standard", "-z", binary=True).decode("utf-8").split("\0")
    for name in set(paths) - {""}:
        if name.split("/")[0] in FORBIDDEN:
            issues.add(f"{name}: runtime data must not be public")
        path = ROOT / name
        if path.is_file():
            inspect(name, path.read_bytes())
    objects = {}
    for commit in git("rev-list", "--all").splitlines():
        for item in git("ls-tree", "-rz", commit, binary=True).split(b"\0"):
            if not item:
                continue
            header, name = item.split(b"\t", 1)
            mode, kind, oid = header.split()
            label = name.decode("utf-8", errors="replace")
            if label.split("/")[0] in FORBIDDEN:
                issues.add(f"history:{label}: runtime data must not be public")
            if kind == b"blob":
                objects[oid] = label
    if objects:
        process = subprocess.run(["git", "cat-file", "--batch"], cwd=ROOT, input=b"\n".join(objects) + b"\n", capture_output=True, check=True)
        output = io.BytesIO(process.stdout)
        for oid in objects:
            header = output.readline().split()
            contents = output.read(int(header[2]))
            output.read(1)
            inspect(f"history:{objects[oid]}", contents)
    if args.archive:
        with zipfile.ZipFile(args.archive) as archive:
            for item in archive.infolist():
                if item.is_dir():
                    continue
                parts = Path(item.filename).parts[1:]
                if any(part in {"private", "data", "evidence", ".git", ".runtime", "__pycache__"} for part in parts):
                    issues.add(f"archive:{item.filename}: runtime data")
                inspect(f"archive:{item.filename}", archive.read(item))
    if issues:
        for issue in sorted(issues):
            print(issue)
        raise SystemExit(1)
    print(f"Release privacy audit passed: {len(set(paths)) - 1} public files; {len(objects)} historical blobs" + ("; archive inspected" if args.archive else ""))


if __name__ == "__main__":
    main()
