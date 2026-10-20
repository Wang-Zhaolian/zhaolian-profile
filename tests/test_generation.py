from __future__ import annotations

import pytest

from academic_profile.cli import build_parser
from academic_profile.errors import GenerationError
from academic_profile.generator import generate_profile


def test_generator_is_explicitly_retired() -> None:
    with pytest.raises(GenerationError, match="简历生成功能已移除"):
        generate_profile("phd")


def test_cli_does_not_expose_generation_command() -> None:
    parser = build_parser()
    choices = parser._subparsers._group_actions[0].choices
    assert "generate" not in choices
