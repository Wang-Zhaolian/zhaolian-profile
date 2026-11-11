"""Prepare and verify a private portable library before removing old folders."""
from __future__ import annotations
import argparse
import hashlib
import json
import shutil
import sys
import time
import zipfile
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from academic_profile.library import atomic_json, initialize_home
from academic_profile.loader import load_master_data

SKIP = {'.venv', 'dist', 'build', '.runtime', '.pytest_cache', '.pytest-tmp', '__pycache__', 'tmp', 'third-party-licenses'}


def files_in(folder):
    for path in folder.rglob('*'):
        if any(part in SKIP for part in path.relative_to(folder).parts):
            continue
        if path.is_symlink():
            raise RuntimeError('发现符号链接，先核对其目标后再迁移。')
        if path.is_file():
            yield path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--previous-recovery', type=Path)
    parser.add_argument('--archive', type=Path, required=True)
    args = parser.parse_args()
    source = args.source.resolve()
    archive = args.archive.resolve()
    destination = ROOT / '个人资料'
    if source == ROOT or destination.exists() or archive.exists():
        raise RuntimeError('迁移目标或恢复归档已存在，停止以避免覆盖。')
    load_master_data(source / 'data')
    marker = source / 'private/desktop-server.local.json'
    if marker.exists():
        try:
            port = json.loads(marker.read_text(encoding='utf-8'))['port']
            with urlopen(f'http://127.0.0.1:{int(port)}/api/health', timeout=1) as response:
                if json.load(response).get('name') == 'academic-profile':
                    raise RuntimeError('请先保存并通过界面退出旧程序，再继续迁移。')
        except (OSError, KeyError, ValueError):
            pass
    snapshot = {path.relative_to(source).as_posix(): digest(path)
                for folder in ('data', 'private', 'evidence', 'output') if (source / folder).exists()
                for path in files_in(source / folder)}
    archive.parent.mkdir(parents=True, exist_ok=True)
    roots = [source, ROOT]
    if args.previous_recovery and args.previous_recovery.is_dir():
        roots.append(args.previous_recovery.resolve())
    written = 0
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as output:
        for folder in roots:
            for path in files_in(folder):
                if path.resolve() == archive:
                    continue
                output.write(path, (Path(folder.name) / path.relative_to(folder)).as_posix())
                written += 1
    with zipfile.ZipFile(archive) as output:
        if output.testzip():
            raise RuntimeError('恢复归档校验失败，原目录未删除。')
        for relative, checksum in snapshot.items():
            if hashlib.sha256(output.read(source.name + '/' + relative)).hexdigest() != checksum:
                raise RuntimeError('恢复归档的个人资料校验失败。')
    destination.mkdir()
    for folder in ('data', 'private', 'evidence', 'output'):
        if (source / folder).is_dir():
            shutil.copytree(source / folder, destination / folder, ignore=shutil.ignore_patterns('.runtime', '__pycache__'))
    for relative, checksum in snapshot.items():
        if digest(destination / relative) != checksum or digest(source / relative) != checksum:
            raise RuntimeError('迁移期间原始资料发生变化，停止清理；请核对两个目录。')
    # Runtime markers contain ports/PIDs from the previous computer, not records.
    (destination / 'private/desktop-server.local.json').unlink(missing_ok=True)
    identity = initialize_home(destination)
    atomic_json(ROOT / 'portable-library.json', {'version': 1, 'library': '个人资料', 'library_id': identity})
    atomic_json(destination / 'private/migration-manifest.local.json', {
        'prepared_at': time.strftime('%Y-%m-%d %H:%M:%S'), 'archive': archive.name,
        'verified_files': snapshot, 'library_id': identity})
    totals = {name: len(value) for name, value in load_master_data(destination / 'data').items() if name != 'basics'}
    print(json.dumps({'archive_entries': written, 'archive_bytes': archive.stat().st_size,
        'verified_personal_files': len(snapshot), 'records': sum(totals.values()), 'categories': len(totals)}, ensure_ascii=False))
    print('Portable library prepared and verified. No old source folder was deleted.')


if __name__ == '__main__':
    main()
