"""Build a native .app and a ZIP preserving executable permissions."""
from __future__ import annotations
import hashlib
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from academic_profile import __version__


def main():
    if sys.platform != 'darwin':
        raise SystemExit('A macOS application must be built on macOS.')
    architecture = platform.machine()
    destination = ROOT / 'dist' / f'macos-{architecture}'
    if destination.exists():
        raise SystemExit('The build destination already exists; choose a fresh output folder.')
    subprocess.run([sys.executable, str(ROOT / 'scripts/collect_licenses.py')], check=True, cwd=ROOT)
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
        '--distpath', str(destination), '--workpath', str(ROOT / 'build' / architecture),
        str(ROOT / 'academic-profile.spec')], check=True, cwd=ROOT)
    app = destination / '昭濂个人履历库.app'
    subprocess.run(['codesign', '--verify', '--deep', '--strict', str(app)], check=True)
    archive = destination / f'ZhaolianProfile-{__version__}-macos-{architecture}.zip'
    subprocess.run(['/usr/bin/ditto', '-c', '-k', '--sequesterRsrc', '--keepParent', str(app), str(archive)], check=True)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (destination / 'SHA256SUMS.txt').write_text(f'{digest}  {archive.name}\n', encoding='utf-8')
    print(f'Built {archive}')


if __name__ == '__main__':
    main()
