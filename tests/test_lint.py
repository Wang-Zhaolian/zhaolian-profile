from pathlib import Path

from academic_profile.linting import lint_repository

ROOT = Path(__file__).resolve().parents[1]


def test_generated_test_records_have_no_rule_warnings(example_data_dir: Path) -> None:
    assert lint_repository(example_data_dir) == []
