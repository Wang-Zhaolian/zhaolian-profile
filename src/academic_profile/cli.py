from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .constants import DATA_CATEGORIES
from .errors import AcademicProfileError
from .interactive import add_record
from .linting import lint_repository
from .validation import has_errors, validate_repository


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _resolve(path: str, root: Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else root / candidate


def _add_common_paths(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--profile-dir", default="profiles")
    parser.add_argument("--schema-dir", default="schemas")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="academic-profile",
        description="Validate and maintain academic records used by 昭濂个人履历库.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate", help="Validate YAML, IDs, dates, and references")
    _add_common_paths(validate_parser)

    lint_parser = subparsers.add_parser("lint", help="Check stored academic record writing")
    lint_parser.add_argument("--data-dir", default="data")
    lint_parser.add_argument("--max-bullet-length", type=int, default=220)

    add_parser = subparsers.add_parser("add", help="Interactively append one record")
    add_parser.add_argument("category", choices=DATA_CATEGORIES)
    add_parser.add_argument("--data-dir", default="data")
    return parser


def main(argv: list[str] | None = None) -> int:
    root = _project_root()
    args = build_parser().parse_args(list(argv if argv is not None else sys.argv[1:]))
    try:
        if args.command == "validate":
            issues = validate_repository(
                _resolve(args.data_dir, root),
                _resolve(args.profile_dir, root),
                _resolve(args.schema_dir, root),
            )
            for issue in issues:
                print(issue)
            if has_errors(issues):
                print(f"Validation failed with {sum(i.severity == 'error' for i in issues)} error(s).")
                return 1
            print("Validation passed.")
            return 0

        if args.command == "lint":
            issues = lint_repository(
                _resolve(args.data_dir, root), args.max_bullet_length
            )
            for issue in issues:
                print(issue)
            print(f"履历文字检查完成，共 {len(issues)} 项提示。")
            return 0

        if args.command == "add":
            record_id = add_record(args.category, _resolve(args.data_dir, root))
            print(f"已添加记录 {record_id}。")
            return 0
    except (AcademicProfileError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 2
