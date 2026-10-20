"""Collect original third-party notices for the Windows distribution."""
from __future__ import annotations
import importlib.metadata
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    output = ROOT / "docs" / "third-party-licenses"
    output.mkdir(parents=True, exist_ok=True)
    packages = []
    for distribution in sorted(importlib.metadata.distributions(), key=lambda d: d.metadata.get("Name", "").lower()):
        name = distribution.metadata.get("Name", "unknown")
        if name == "academic-profile":
            continue
        folder = output / name
        notices = []
        for file in distribution.files or []:
            lowered = str(file).lower()
            if (".dist-info/" in lowered or name.lower() == "pyinstaller") and any(
                marker in file.name.lower() for marker in ("license", "copying", "notice", "authors", "copyright")):
                source = Path(distribution.locate_file(file))
                if source.is_file():
                    folder.mkdir(exist_ok=True)
                    target = folder / ("__".join(file.parts[-3:]))
                    shutil.copyfile(source, target)
                    notices.append(target.name)
        metadata = distribution.metadata
        packages.append({"name": name, "version": distribution.version,
                         "license": metadata.get("License-Expression") or metadata.get("License"),
                         "homepage": metadata.get_all("Project-URL") or [metadata.get("Home-page")],
                         "notices": notices})
    python_folder = output / "Python"
    python_folder.mkdir(exist_ok=True)
    python_notice = next((p for p in (Path(sys.base_prefix) / "LICENSE.txt", Path(sys.base_prefix) / "LICENSE") if p.is_file()), None)
    if python_notice is None:
        raise RuntimeError("Python runtime license was not found")
    shutil.copyfile(python_notice, python_folder / "LICENSE.txt")
    (output / "DEPENDENCIES.json").write_text(json.dumps(packages, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Collected notices for {len(packages)} packages and Python {sys.version.split()[0]}")


if __name__ == "__main__":
    main()
