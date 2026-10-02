from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .constants import DATA_CATEGORIES
from .errors import AcademicProfileError
from .generator import generate_profile
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
        description="Validate a master academic record and generate profile-specific CVs.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate", help="Validate YAML, IDs, dates, and references")
    _add_common_paths(validate_parser)

    lint_parser = subparsers.add_parser("lint", help="Run deterministic CV writing checks")
    lint_parser.add_argument("--data-dir", default="data")
    lint_parser.add_argument("--max-bullet-length", type=int, default=220)

    generate_parser = subparsers.add_parser("generate", help="Generate one profile or all profiles")
    generate_parser.add_argument(
        "profile",
        help="Profile YAML name without extension, or 'all'",
    )
    _add_common_paths(generate_parser)
    generate_parser.add_argument("--template-dir", default="templates")
    generate_parser.add_argument("--output-root", default="output")
    generate_parser.add_argument("--contact", default="private/contact.yaml")
    generate_parser.add_argument(
        "--format",
        choices=("all", "latex", "docx", "pdf"),
        default="all",
        help="'all' writes LaTeX and DOCX and builds PDF when a LaTeX engine exists",
    )

    add_parser = subparsers.add_parser("add", help="Interactively append one record")
    add_parser.add_argument("category", choices=DATA_CATEGORIES)
    add_parser.add_argument("--data-dir", default="data")
    return parser


def _legacy_args(argv: list[str]) -> list[str]:
    if "--profile" not in argv:
        return argv
    index = argv.index("--profile")
    try:
        profile = argv[index + 1]
    except IndexError:
        return argv
    return ["generate", profile, *argv[:index], *argv[index + 2 :]]


def main(argv: list[str] | None = None) -> int:
    root = _project_root()
    args = build_parser().parse_args(_legacy_args(list(argv if argv is not None else sys.argv[1:])))
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
            print(f"CV lint completed with {len(issues)} warning(s).")
            return 0

        if args.command == "add":
            record_id = add_record(args.category, _resolve(args.data_dir, root))
            print(f"Added {record_id}. Run 'academic-profile validate' before generation.")
            return 0

        if args.command == "generate":
            formats = ("latex", "docx", "pdf") if args.format == "all" else (args.format,)
            if args.profile == "all":
                profile_names = tuple(
                    path.stem
                    for path in sorted(_resolve(args.profile_dir, root).glob("*.yaml"))
                )
            else:
                profile_names = (args.profile,)
            for profile_name in profile_names:
                result = generate_profile(
                    profile_name,
                    data_dir=_resolve(args.data_dir, root),
                    profile_dir=_resolve(args.profile_dir, root),
                    schema_dir=_resolve(args.schema_dir, root),
                    template_dir=_resolve(args.template_dir, root),
                    output_root=_resolve(args.output_root, root),
                    contact_path=_resolve(args.contact, root),
                    formats=formats,
                )
                print(f"[{profile_name}]")
                for output in result.outputs:
                    print(f"  wrote {output}")
                for message in result.messages:
                    print(f"  {message}")
            return 0
    except (AcademicProfileError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 2
